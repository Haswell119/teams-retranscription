from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.audio import AudioClip
from hansard.domain.transcript import Transcript, Utterance
from hansard.ports.asr import EngineProfile, RecognitionHints


@dataclass(frozen=True, slots=True)
class NullRecognizer:
    placeholder: str = ""

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name="null",
            languages=("any",),
            emits_word_timestamps=False,
            emits_punctuation=False,
            resident_memory_mb=0,
            license_identifier="apache-2.0",
        )

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        spans = hints.segments or (clip.span,)
        return Transcript(
            utterances=tuple(Utterance(span=span, text=self.placeholder) for span in spans),
            language=hints.language,
            audio_duration=clip.duration,
        )
