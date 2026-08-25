from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from hansard.domain.audio import AudioClip
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript


@dataclass(frozen=True, slots=True)
class RecognitionHints:
    language: str | None = None
    vocabulary: tuple[str, ...] = ()
    speaker_names: tuple[str, ...] = ()
    segments: tuple[TimeSpan, ...] = ()
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class EngineProfile:
    name: str
    languages: tuple[str, ...]
    emits_word_timestamps: bool
    emits_punctuation: bool
    resident_memory_mb: int
    license_identifier: str
    supports_vocabulary_biasing: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class SpeechRecognizer(Protocol):
    @property
    def profile(self) -> EngineProfile: ...

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript: ...


@runtime_checkable
class LanguageIdentifier(Protocol):
    def identify(self, clip: AudioClip) -> tuple[str, float]: ...
