from __future__ import annotations

from math import gcd

import numpy as np

_FILTER_HALF_WIDTH = 24


def _sinc_kernel(up: int, down: int, half_width: int) -> np.ndarray:
    cutoff = 1.0 / max(up, down)
    taps = half_width * max(up, down) * 2 + 1
    positions = (np.arange(taps) - (taps - 1) / 2.0) / up
    kernel = cutoff * np.sinc(cutoff * positions * up) * np.blackman(taps)
    return (kernel / kernel.sum()).astype(np.float32)


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    divisor = gcd(source_rate, target_rate)
    up = target_rate // divisor
    down = source_rate // divisor
    kernel = _sinc_kernel(up, down, _FILTER_HALF_WIDTH)
    upsampled = np.zeros(len(samples) * up, dtype=np.float32)
    upsampled[::up] = samples.astype(np.float32, copy=False)
    filtered = np.convolve(upsampled, kernel, mode="same")
    return np.ascontiguousarray(filtered[::down], dtype=np.float32)
