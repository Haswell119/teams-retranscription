from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from hansard.application.jobs import JobRecord, JobStore, now
from hansard.domain.errors import ArtifactNotFoundError
from hansard.domain.meeting import DeliveryChannel, DeliveryTarget, JobState, MeetingRequest
from hansard.observability.logging import get_logger

LOGGER = get_logger(__name__)

JOBS_DIRECTORY: Final[str] = "jobs"
RECORD_SUFFIX: Final[str] = ".json"
MINIMUM_AUDIO_BYTES: Final[int] = 1_024
LISTING_CEILING: Final[int] = 10_000

ABANDONED_REASON: Final[str] = (
    "the worker stopped during the meeting and no recording survived it; "
    "the meeting cannot be rejoined once it has moved on"
)

CAPTURE_STATES: Final[frozenset[JobState]] = frozenset(
    {JobState.PENDING, JobState.JOINING, JobState.CAPTURING}
)
PROCESSING_STATES: Final[frozenset[JobState]] = frozenset(
    {JobState.TRANSCRIBING, JobState.SUMMARIZING, JobState.DELIVERING}
)
ACTIVE_STATES: Final[frozenset[JobState]] = CAPTURE_STATES | PROCESSING_STATES


def _moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def encode_request(request: MeetingRequest) -> dict[str, Any]:
    return {
        "identifier": request.identifier,
        "join_url": request.join_url,
        "audio_path": str(request.audio_path) if request.audio_path else None,
        "title": request.title,
        "language": request.language,
        "expected_participants": list(request.expected_participants),
        "vocabulary": list(request.vocabulary),
        "max_duration_seconds": request.max_duration_seconds,
        "speaker_count": request.speaker_count,
        "starts_at": request.starts_at.isoformat() if request.starts_at else None,
        "delivery": [
            {"channel": target.channel.value, "address": target.address, "formats": list(target.formats)}
            for target in request.delivery
        ],
    }


def decode_request(payload: dict[str, Any]) -> MeetingRequest:
    audio = payload.get("audio_path")
    return MeetingRequest(
        join_url=payload.get("join_url"),
        audio_path=Path(audio) if audio else None,
        title=str(payload.get("title") or "Meeting"),
        language=payload.get("language"),
        expected_participants=tuple(payload.get("expected_participants") or ()),
        vocabulary=tuple(payload.get("vocabulary") or ()),
        max_duration_seconds=int(payload.get("max_duration_seconds") or 4 * 3600),
        speaker_count=payload.get("speaker_count"),
        starts_at=_moment(payload.get("starts_at")),
        delivery=tuple(
            DeliveryTarget(
                channel=DeliveryChannel(item["channel"]),
                address=str(item["address"]),
                formats=tuple(item.get("formats") or ("markdown",)),
            )
            for item in payload.get("delivery") or []
        ),
        identifier=str(payload["identifier"]),
    )


def encode(record: JobRecord) -> dict[str, Any]:
    return {
        "identifier": record.identifier,
        "state": record.state.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "error": record.error,
        "artifacts": [str(path) for path in record.artifacts],
        "metrics": dict(record.metrics),
        "stage_seconds": dict(record.stage_seconds),
        "request": encode_request(record.request),
    }


def decode(payload: dict[str, Any]) -> JobRecord:
    request = decode_request(payload["request"])
    created = _moment(payload.get("created_at")) or now()
    return JobRecord(
        identifier=str(payload.get("identifier") or request.identifier),
        request=request,
        state=JobState(payload["state"]),
        created_at=created,
        updated_at=_moment(payload.get("updated_at")) or created,
        artifacts=tuple(Path(item) for item in payload.get("artifacts") or ()),
        metrics={str(key): float(value) for key, value in (payload.get("metrics") or {}).items()},
        stage_seconds={str(key): float(value) for key, value in (payload.get("stage_seconds") or {}).items()},
        error=payload.get("error"),
    )


@dataclass(slots=True)
class FilesystemJobStore:
    root: Path
    _cache: dict[str, JobRecord] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, identifier: str) -> Path:
        return self.root / f"{identifier}{RECORD_SUFFIX}"

    def _write(self, record: JobRecord) -> None:
        target = self.path_for(record.identifier)
        staging = target.with_suffix(f"{RECORD_SUFFIX}.tmp")
        staging.write_text(json.dumps(encode(record), indent=1, sort_keys=True), encoding="utf-8")
        staging.replace(target)

    def _read(self, path: Path) -> JobRecord | None:
        try:
            return decode(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError) as error:
            LOGGER.warning("job.record_unreadable", record=path.name, error=type(error).__name__)
            return None

    def stored(self) -> tuple[JobRecord, ...]:
        found: dict[str, JobRecord] = {}
        for path in sorted(self.root.glob(f"*{RECORD_SUFFIX}")):
            record = self._read(path)
            if record is not None:
                found[record.identifier] = record
        found.update(self._cache)
        return tuple(sorted(found.values(), key=lambda item: item.created_at, reverse=True))

    async def create(self, request: MeetingRequest) -> JobRecord:
        moment = now()
        record = JobRecord(
            identifier=request.identifier,
            request=request,
            state=JobState.PENDING,
            created_at=moment,
            updated_at=moment,
        )
        return await self.save(record)

    async def get(self, identifier: str) -> JobRecord:
        cached = self._cache.get(identifier)
        if cached is not None:
            return cached
        record = self._read(self.path_for(identifier))
        if record is None:
            raise ArtifactNotFoundError(f"unknown job {identifier}")
        self._cache[identifier] = record
        return record

    async def list(self, limit: int) -> tuple[JobRecord, ...]:
        return self.stored()[:limit]

    async def save(self, record: JobRecord) -> JobRecord:
        self._cache[record.identifier] = record
        self._write(record)
        return record


def captured_audio(workspace_root: Path, identifier: str) -> Path | None:
    candidate = workspace_root / identifier / f"{identifier}.wav"
    try:
        if candidate.is_file() and candidate.stat().st_size > MINIMUM_AUDIO_BYTES:
            return candidate
    except OSError:
        return None
    return None


def resumable(record: JobRecord, workspace_root: Path) -> JobRecord | None:
    if record.state not in ACTIVE_STATES:
        return None
    if record.request.join_url is None:
        return record.advanced(JobState.PENDING, error=None)
    audio = captured_audio(workspace_root, record.identifier)
    if audio is not None:
        return record.advanced(
            JobState.PENDING,
            request=replace(record.request, join_url=None, audio_path=audio),
            error=None,
        )
    if record.state is JobState.PENDING:
        return record.advanced(JobState.PENDING, error=None)
    return None


@dataclass(frozen=True, slots=True)
class Recovery:
    resumed: tuple[JobRecord, ...] = ()
    abandoned: tuple[JobRecord, ...] = ()

    @property
    def considered(self) -> int:
        return len(self.resumed) + len(self.abandoned)


async def recover_jobs(store: JobStore, workspace_root: Path) -> Recovery:
    resumed: list[JobRecord] = []
    abandoned: list[JobRecord] = []
    for record in await store.list(LISTING_CEILING):
        if record.state not in ACTIVE_STATES:
            continue
        candidate = resumable(record, workspace_root)
        if candidate is None:
            abandoned.append(await store.save(record.advanced(JobState.FAILED, error=ABANDONED_REASON)))
            continue
        resumed.append(candidate)
    if resumed or abandoned:
        LOGGER.info("job.recovered", resumed=len(resumed), abandoned=len(abandoned))
    return Recovery(resumed=tuple(resumed), abandoned=tuple(abandoned))
