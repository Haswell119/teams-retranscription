from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.audio import AudioClip
from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization, SpeakerTurn
from hansard.ports.diarization import DiarizationRequest


@dataclass(frozen=True, slots=True)
class NullDiarizer:
    label: str = UNKNOWN_SPEAKER

    @property
    def name(self) -> str:
        return "null"

    @property
    def max_supported_speakers(self) -> int:
        return 1

    def diarize(self, clip: AudioClip, request: DiarizationRequest) -> Diarization:
        if clip.frame_count == 0:
            return Diarization()
        turn = SpeakerTurn(span=clip.span, label=self.label)
        return Diarization(turns=(turn,), labels=(self.label,))
