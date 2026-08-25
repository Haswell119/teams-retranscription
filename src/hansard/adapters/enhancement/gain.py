from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hansard.domain.audio import AudioClip


@dataclass(frozen=True, slots=True)
class PeakNormaliser:
    target_peak: float = 0.89
    noise_floor: float = 1e-5

    @property
    def name(self) -> str:
        return "peak"

    def enhance(self, clip: AudioClip) -> AudioClip:
        peak = clip.peak()
        if peak < self.noise_floor:
            return clip
        return clip.with_samples((clip.samples * (self.target_peak / peak)).astype(np.float32))
