from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from hansard.domain.timespan import TimeSpan

TARGET_SAMPLE_RATE = 16_000


@dataclass(frozen=True, slots=True)
class AudioClip:
    samples: np.ndarray
    sample_rate: int
    offset: float = 0.0

    def __post_init__(self) -> None:
        if self.samples.ndim != 1:
            raise ValueError(f"AudioClip expects mono samples, got shape {self.samples.shape}")
        if self.sample_rate <= 0:
            raise ValueError(f"AudioClip sample_rate must be positive, got {self.sample_rate}")

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    @property
    def span(self) -> TimeSpan:
        return TimeSpan(self.offset, self.offset + self.duration)

    @property
    def frame_count(self) -> int:
        return len(self.samples)

    def extract(self, span: TimeSpan) -> AudioClip:
        local = TimeSpan(span.start - self.offset, span.end - self.offset).clamped(0.0, self.duration)
        first = round(local.start * self.sample_rate)
        last = round(local.end * self.sample_rate)
        return replace(self, samples=self.samples[first:last], offset=self.offset + local.start)

    def with_samples(self, samples: np.ndarray) -> AudioClip:
        return replace(self, samples=samples)

    def peak(self) -> float:
        return float(np.max(np.abs(self.samples))) if self.samples.size else 0.0

    def rms(self) -> float:
        return float(np.sqrt(np.mean(np.square(self.samples)))) if self.samples.size else 0.0


def concatenate(clips: list[AudioClip]) -> AudioClip:
    if not clips:
        raise ValueError("concatenate requires at least one clip")
    rates = {clip.sample_rate for clip in clips}
    if len(rates) != 1:
        raise ValueError(f"cannot concatenate clips with mixed sample rates: {sorted(rates)}")
    return AudioClip(
        samples=np.concatenate([clip.samples for clip in clips]),
        sample_rate=clips[0].sample_rate,
        offset=clips[0].offset,
    )
