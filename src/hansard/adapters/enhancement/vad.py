from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hansard.domain.audio import AudioClip
from hansard.domain.timespan import TimeSpan, merge_adjacent

_ENERGY_EPSILON = 1e-10


@dataclass(slots=True)
class SileroVoiceActivityDetector:
    threshold: float = 0.5
    min_speech_seconds: float = 0.25
    min_silence_seconds: float = 0.35
    speech_pad_seconds: float = 0.15
    model_path: str | None = None
    _detector: Any | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return "silero"

    def _load(self) -> Any:
        if self._detector is None:
            import onnx_asr

            self._detector = onnx_asr.load_vad("silero", self.model_path)
        return self._detector

    def detect(self, clip: AudioClip) -> tuple[TimeSpan, ...]:
        if clip.frame_count == 0:
            return ()
        detector = self._load()
        segments = detector.segment(
            [clip.samples],
            sample_rate=clip.sample_rate,
            threshold=self.threshold,
            min_speech_duration=self.min_speech_seconds,
            min_silence_duration=self.min_silence_seconds,
            speech_pad=self.speech_pad_seconds,
        )
        spans = [
            TimeSpan(float(segment.start), float(segment.end)).shifted(clip.offset)
            for batch in segments
            for segment in batch
        ]
        return tuple(merge_adjacent(spans, 0.0))


@dataclass(frozen=True, slots=True)
class EnergyVoiceActivityDetector:
    frame_seconds: float = 0.03
    percentile: float = 35.0
    margin_db: float = 9.0
    min_speech_seconds: float = 0.25
    min_silence_seconds: float = 0.35
    speech_pad_seconds: float = 0.15

    @property
    def name(self) -> str:
        return "energy"

    def detect(self, clip: AudioClip) -> tuple[TimeSpan, ...]:
        frame = max(1, int(self.frame_seconds * clip.sample_rate))
        usable = clip.frame_count - (clip.frame_count % frame)
        if usable < frame:
            return ()
        frames = clip.samples[:usable].reshape(-1, frame)
        energy_db = 10.0 * np.log10(np.mean(np.square(frames), axis=1) + _ENERGY_EPSILON)
        floor = float(np.percentile(energy_db, self.percentile))
        active = energy_db > floor + self.margin_db
        spans: list[TimeSpan] = []
        start: int | None = None
        for index, is_active in enumerate(active):
            if is_active and start is None:
                start = index
            elif not is_active and start is not None:
                spans.append(TimeSpan(start * self.frame_seconds, index * self.frame_seconds))
                start = None
        if start is not None:
            spans.append(TimeSpan(start * self.frame_seconds, len(active) * self.frame_seconds))
        merged = merge_adjacent(spans, self.min_silence_seconds)
        padded = [
            TimeSpan(
                max(0.0, span.start - self.speech_pad_seconds),
                min(clip.duration, span.end + self.speech_pad_seconds),
            ).shifted(clip.offset)
            for span in merged
            if span.duration >= self.min_speech_seconds
        ]
        return tuple(merge_adjacent(padded, 0.0))
