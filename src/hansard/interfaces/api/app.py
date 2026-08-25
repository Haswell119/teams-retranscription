from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from hansard import __version__
from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.adapters.capture.registry import build_capture
from hansard.adapters.delivery.dispatcher import dispatcher_from_settings
from hansard.adapters.summarization.registry import build_minutes_writer
from hansard.application.jobs import InMemoryJobStore, JobQueue, JobRecord
from hansard.application.meeting_service import MeetingService, artifact_key
from hansard.config import Settings, load_settings
from hansard.domain.errors import ArtifactNotFound, ConfigurationError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget, MeetingRequest
from hansard.factory import Composition
from hansard.interfaces.api.schemas import (
    HealthReport,
    JobDetail,
    JobSummary,
    MeetingSubmission,
    SpeakerShare,
)
from hansard.observability import metrics
from hansard.observability.logging import configure_logging, get_logger
from hansard.ports.delivery import Payload
from hansard.ports.storage import ArtifactStore

LOGGER = get_logger(__name__)
METRICS_PATH = "/metrics"
QUEUE_STREAM = "meetings"
QUEUE_GROUP = "api"


@dataclass(slots=True)
class Runtime:
    settings: Settings
    store: InMemoryJobStore
    queue: JobQueue
    artifacts: ArtifactStore


def _build_runtime(settings: Settings) -> Runtime:
    composition = Composition(settings)
    minutes_writer = None
    if settings.minutes.enabled:
        try:
            minutes_writer = build_minutes_writer(settings.minutes)
        except (ConfigurationError, ImportError):
            minutes_writer = None
    artifacts = composition.artifact_store()
    service = MeetingService(
        settings=settings,
        pipeline=composition.pipeline(),
        capture=build_capture(settings.capture, settings.audio.sample_rate),
        minutes_writer=minutes_writer,
        biaser=VocabularyBiaser(),
        artifact_store=artifacts,
    )
    dispatcher = dispatcher_from_settings(settings.delivery)

    async def handler(record: JobRecord) -> JobRecord:
        completed = await service.execute(record)
        targets = service.delivery_targets(completed.request)
        if targets and completed.artifacts:
            await dispatcher.deliver(targets, _payload(completed))
        return completed

    store = InMemoryJobStore()
    queue = JobQueue(store=store, handler=handler, concurrency=settings.runtime.max_concurrent_meetings)
    return Runtime(settings=settings, store=store, queue=queue, artifacts=artifacts)


def _payload(record: JobRecord) -> Payload:
    body = ""
    for artifact in record.artifacts:
        if artifact.suffix == ".md" and artifact.stem == "minutes":
            body = artifact.read_text(encoding="utf-8")
            break
    if not body and record.artifacts:
        body = record.artifacts[0].read_text(encoding="utf-8", errors="replace")
    return Payload(subject=record.request.title, body=body, body_format="markdown")


async def _restored(runtime: Runtime, identifier: str, name: str) -> bytes:
    key = artifact_key(identifier, name)
    try:
        with TemporaryDirectory() as directory:
            restored = await runtime.artifacts.get(key, Path(directory) / name)
            return restored.read_bytes()
    except Exception as error:
        raise HTTPException(404, f"unknown artifact {name}") from error


def _summary(record: JobRecord) -> JobSummary:
    return JobSummary(
        identifier=record.identifier,
        state=record.state,
        title=record.request.title,
        language=record.request.language,
        created_at=record.created_at,
        updated_at=record.updated_at,
        error=record.error,
    )


def _detail(record: JobRecord) -> JobDetail:
    transcript = record.transcript
    shares: tuple[SpeakerShare, ...] = ()
    if transcript is not None and transcript.speech_duration > 0:
        totals: dict[str, float] = {}
        for utterance in transcript.utterances:
            totals[utterance.speaker] = totals.get(utterance.speaker, 0.0) + utterance.span.duration
        total = sum(totals.values()) or 1.0
        shares = tuple(
            SpeakerShare(speaker=name, seconds=round(seconds, 1), share=round(seconds / total, 4))
            for name, seconds in sorted(totals.items(), key=lambda item: -item[1])
        )
    elapsed = sum(record.stage_seconds.values())
    audio_seconds = record.metrics.get("audio_seconds")
    return JobDetail(
        **_summary(record).model_dump(),
        audio_seconds=audio_seconds,
        word_count=transcript.word_count if transcript else None,
        speaker_count=len(transcript.speakers) if transcript else None,
        real_time_factor=round(elapsed / audio_seconds, 4) if audio_seconds else None,
        stage_seconds=record.stage_seconds,
        speaking_time=shares,
        artifacts=tuple(path.name for path in record.artifacts),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    configure_logging(resolved.runtime)
    runtime = _build_runtime(resolved)
    metrics.set_build_info(
        version=__version__,
        component="api",
        asr_engine=resolved.asr.engine,
        asr_model=resolved.asr.model_id,
        compute=resolved.asr.quantization,
        language=resolved.asr.language,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await runtime.queue.start()
        yield
        await runtime.queue.stop()

    application = FastAPI(
        title="Hansard",
        version=__version__,
        summary="Sovereign meeting transcription. No data leaves this host.",
        root_path=resolved.api.root_path,
        lifespan=lifespan,
    )
    if resolved.api.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.api.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    def authorise(request: Request) -> None:
        expected = resolved.api.api_key
        if expected is None:
            return
        provided = request.headers.get("x-api-key")
        if provided != expected.get_secret_value():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-API-Key")

    meetings = APIRouter(prefix="/v1/meetings", dependencies=[Depends(authorise)])

    @application.get("/healthz", response_model=HealthReport)
    async def healthz() -> HealthReport:
        checks = {
            "ffmpeg": "ok" if shutil.which("ffmpeg") else "missing",
            "models": "ok" if resolved.runtime.models_dir.is_dir() else "missing",
            "queue": f"{runtime.queue.pending} pending",
        }
        degraded = any(value == "missing" for value in checks.values())
        return HealthReport(status="degraded" if degraded else "ok", version=__version__, checks=checks)

    if resolved.api.metrics_enabled and metrics.backend_available():

        @application.get(METRICS_PATH)
        async def prometheus_metrics() -> Response:
            payload, content_type = metrics.render_latest()
            return Response(content=payload, media_type=content_type)

    @application.get("/readyz")
    async def readyz() -> Response:
        ready = resolved.runtime.models_dir.is_dir() and shutil.which("ffmpeg") is not None
        return Response(status_code=200 if ready else 503)

    @meetings.post("", response_model=JobSummary, status_code=202)
    async def submit(submission: MeetingSubmission) -> JobSummary:
        if not submission.join_url and not submission.audio_path:
            raise HTTPException(422, "either join_url or audio_path is required")
        request = MeetingRequest(
            join_url=submission.join_url,
            audio_path=Path(submission.audio_path) if submission.audio_path else None,
            title=submission.title,
            language=submission.language,
            expected_participants=submission.expected_participants,
            vocabulary=submission.vocabulary,
            max_duration_seconds=submission.max_duration_seconds,
            speaker_count=submission.speaker_count,
            delivery=tuple(
                DeliveryTarget(
                    channel=DeliveryChannel(item.channel), address=item.address, formats=item.formats
                )
                for item in submission.delivery
            ),
        )
        summary = _summary(await runtime.queue.submit(request))
        metrics.record_meeting_scheduled()
        metrics.record_queue_depth(QUEUE_STREAM, QUEUE_GROUP, runtime.queue.pending)
        LOGGER.info("meeting.submitted", meeting=summary.identifier, language=request.language or "auto")
        return summary

    @meetings.get("", response_model=list[JobSummary])
    async def index(limit: int = 50) -> list[JobSummary]:
        return [_summary(record) for record in await runtime.store.list(limit)]

    @meetings.get("/{identifier}", response_model=JobDetail)
    async def show(identifier: str) -> JobDetail:
        try:
            return _detail(await runtime.store.get(identifier))
        except ArtifactNotFound as error:
            raise HTTPException(404, str(error)) from error

    @meetings.get("/{identifier}/artifacts/{name}")
    async def artifact(identifier: str, name: str) -> Response:
        try:
            record = await runtime.store.get(identifier)
        except ArtifactNotFound as error:
            raise HTTPException(404, str(error)) from error
        for path in record.artifacts:
            if path.name != name:
                continue
            content = path.read_bytes() if path.is_file() else await _restored(runtime, identifier, name)
            return Response(
                content=content,
                media_type="application/octet-stream",
                headers={"content-disposition": f'attachment; filename="{name}"'},
            )
        raise HTTPException(404, f"unknown artifact {name}")

    application.include_router(meetings)
    return application
