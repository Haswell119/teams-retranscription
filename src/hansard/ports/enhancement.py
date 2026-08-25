from __future__ import annotations

from typing import Protocol, runtime_checkable

from hansard.domain.audio import AudioClip
from hansard.domain.timespan import TimeSpan


@runtime_checkable
class AudioEnhancer(Protocol):
    @property
    def name(self) -> str: ...

    def enhance(self, clip: AudioClip) -> AudioClip: ...


@runtime_checkable
class VoiceActivityDetector(Protocol):
    @property
    def name(self) -> str: ...

    def detect(self, clip: AudioClip) -> tuple[TimeSpan, ...]: ...
