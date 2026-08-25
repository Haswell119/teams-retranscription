from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from hansard.domain.meeting import JobState


class DeliveryRequest(BaseModel):
    channel: Literal["teams_chat", "email", "webhook", "filesystem"]
    address: str
    formats: tuple[str, ...] = ("markdown",)


class MeetingSubmission(BaseModel):
    join_url: str | None = None
    audio_path: str | None = None
    title: str = "Meeting"
    language: str | None = Field(default=None, description="fr, en, or null to detect")
    expected_participants: tuple[str, ...] = ()
    vocabulary: tuple[str, ...] = ()
    max_duration_seconds: int = 4 * 3600
    speaker_count: int | None = None
    starts_at: datetime | None = None
    delivery: tuple[DeliveryRequest, ...] = ()


class JobSummary(BaseModel):
    identifier: str
    state: JobState
    title: str
    language: str | None = None
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class SpeakerShare(BaseModel):
    speaker: str
    seconds: float
    share: float


class JobDetail(JobSummary):
    audio_seconds: float | None = None
    word_count: int | None = None
    speaker_count: int | None = None
    real_time_factor: float | None = None
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    speaking_time: tuple[SpeakerShare, ...] = ()
    artifacts: tuple[str, ...] = ()


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    telemetry: Literal["disabled"] = "disabled"
    checks: dict[str, str]
