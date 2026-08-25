from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hansard.adapters.asr.biasing import VocabularyBiaser
from hansard.adapters.audio import load_clip
from hansard.application.jobs import JobRecord
from hansard.application.pipeline import TranscriptionPipeline
from hansard.config import Settings
from hansard.domain.meeting import Capture, JobState, MeetingRequest
from hansard.domain.minutes import Minutes
from hansard.domain.speakers import Roster
from hansard.domain.transcript import Transcript
from hansard.ports.capture import MeetingCapture
from hansard.ports.summarization import MinutesWriter
from hansard.rendering.ports import ModelProvenance, RenderContext
from hansard.rendering.registry import minutes_renderer_for, transcript_renderer_for


@dataclass(slots=True)
class MeetingService:
    settings: Settings
    pipeline: TranscriptionPipeline
    capture: MeetingCapture
    minutes_writer: MinutesWriter | None = None
    biaser: VocabularyBiaser | None = None

    async def execute(self, record: JobRecord) -> JobRecord:
        request = record.request
        workspace = self.settings.runtime.workspace / request.identifier
        workspace.mkdir(parents=True, exist_ok=True)
        captured = await self._acquire(request, workspace)
        transcript, roster, stages = await asyncio.to_thread(self._transcribe, captured, request)
        minutes = await asyncio.to_thread(self._compose, transcript, roster, request)
        artifacts = await asyncio.to_thread(
            self._render, transcript, minutes, roster, request, captured, workspace
        )
        return record.advanced(
            JobState.COMPLETED,
            transcript=transcript,
            minutes=minutes,
            roster=roster,
            artifacts=artifacts,
            stage_seconds=stages,
            metrics={
                "audio_seconds": round(captured.duration, 1),
                "word_count": float(transcript.word_count),
                "speaker_count": float(len(transcript.speakers)),
            },
        )

    async def _acquire(self, request: MeetingRequest, workspace: Path) -> Capture:
        if request.audio_path is not None and request.join_url is None:
            moment = datetime.now(UTC)
            return Capture(
                audio_path=request.audio_path,
                roster=Roster(),
                started_at=moment,
                ended_at=moment,
                sample_rate=self.settings.audio.sample_rate,
            )
        return await self.capture.capture(request, workspace)

    def _transcribe(
        self, captured: Capture, request: MeetingRequest
    ) -> tuple[Transcript, Roster, dict[str, float]]:
        clip = load_clip(captured.audio_path, self.settings.audio.sample_rate)
        outcome = self.pipeline.run(clip, request, captured.roster)
        transcript = outcome.transcript
        if self.biaser is not None and request.vocabulary:
            transcript, _ = self.biaser.apply(
                transcript, request.vocabulary, request.language or transcript.language or "en"
            )
        return transcript, captured.roster, outcome.stage_seconds

    def _compose(self, transcript: Transcript, roster: Roster, request: MeetingRequest) -> Minutes | None:
        if self.minutes_writer is None or not self.settings.minutes.enabled:
            return None
        return self.minutes_writer.compose(transcript, roster, request)

    def _render(
        self,
        transcript: Transcript,
        minutes: Minutes | None,
        roster: Roster,
        request: MeetingRequest,
        captured: Capture,
        workspace: Path,
    ) -> tuple[Path, ...]:
        context = RenderContext(
            title=request.title,
            started_at=captured.started_at,
            duration_seconds=captured.duration,
            participants=roster.participants,
            language=request.language or transcript.language or "en",
            provenance=(
                ModelProvenance("recognition", self.settings.asr.engine, self.settings.asr.model_id),
                ModelProvenance(
                    "diarization",
                    self.settings.diarization.engine,
                    self.settings.diarization.embedding_model,
                ),
                ModelProvenance("voice activity", self.settings.vad.engine, ""),
            ),
        )
        written: list[Path] = []
        for name in self.settings.delivery.formats:
            renderer = transcript_renderer_for(name)
            payload = renderer.render_transcript(transcript, context)
            path = workspace / f"transcript{renderer.file_extension}"
            path.write_bytes(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
            written.append(path)
            if minutes is None:
                continue
            try:
                composer = minutes_renderer_for(name)
            except Exception:
                continue
            body = composer.render_minutes(minutes, context)
            target = workspace / f"minutes{composer.file_extension}"
            target.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
            written.append(target)
        return tuple(written)
