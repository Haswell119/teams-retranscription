from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from hansard.domain.minutes import Minutes
from hansard.domain.speakers import Roster
from hansard.domain.transcript import Transcript


class JobState(StrEnum):
    PENDING = "pending"
    JOINING = "joining"
    CAPTURING = "capturing"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryChannel(StrEnum):
    TEAMS_CHAT = "teams_chat"
    EMAIL = "email"
    WEBHOOK = "webhook"
    FILESYSTEM = "filesystem"


@dataclass(frozen=True, slots=True)
class DeliveryTarget:
    channel: DeliveryChannel
    address: str
    formats: tuple[str, ...] = ("markdown",)


@dataclass(frozen=True, slots=True)
class MeetingRequest:
    join_url: str | None = None
    audio_path: Path | None = None
    title: str = "Meeting"
    language: str | None = None
    expected_participants: tuple[str, ...] = ()
    vocabulary: tuple[str, ...] = ()
    max_duration_seconds: int = 4 * 3600
    delivery: tuple[DeliveryTarget, ...] = ()
    identifier: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if not self.join_url and not self.audio_path:
            raise ValueError("MeetingRequest requires either join_url or audio_path")


@dataclass(frozen=True, slots=True)
class Capture:
    audio_path: Path
    roster: Roster
    started_at: datetime
    ended_at: datetime
    sample_rate: int

    @property
    def duration(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


@dataclass(frozen=True, slots=True)
class MeetingRecord:
    request: MeetingRequest
    state: JobState
    transcript: Transcript | None = None
    minutes: Minutes | None = None
    roster: Roster = field(default_factory=Roster)
    artifacts: tuple[Path, ...] = ()
    error: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
