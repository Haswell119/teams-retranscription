from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from hansard.domain.audio import AudioClip
from hansard.domain.speakers import Diarization, Roster
from hansard.domain.transcript import Transcript


@dataclass(frozen=True, slots=True)
class DiarizationRequest:
    max_speakers: int = 8
    min_speakers: int = 1
    known_speaker_count: int | None = None


@runtime_checkable
class Diarizer(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def max_supported_speakers(self) -> int: ...

    def diarize(self, clip: AudioClip, request: DiarizationRequest) -> Diarization: ...


@runtime_checkable
class SpeakerAttributor(Protocol):
    def attribute(self, transcript: Transcript, diarization: Diarization) -> Transcript: ...


@runtime_checkable
class SpeakerNamer(Protocol):
    def resolve_names(
        self,
        transcript: Transcript,
        diarization: Diarization,
        roster: Roster,
    ) -> dict[str, str]: ...
