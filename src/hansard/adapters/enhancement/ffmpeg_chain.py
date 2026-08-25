from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

from hansard.domain.audio import AudioClip
from hansard.domain.errors import HansardError


@dataclass(frozen=True, slots=True)
class FfmpegEnhancer:
    high_pass_hz: float = 60.0
    target_lufs: float | None = -23.0
    loudness_range: float = 7.0
    true_peak_db: float = -2.0
    denoise: bool = False
    denoise_strength: float = 12.0

    @property
    def name(self) -> str:
        return "ffmpeg"

    def filter_chain(self) -> str:
        stages: list[str] = []
        if self.high_pass_hz > 0:
            stages.append(f"highpass=f={self.high_pass_hz:g}")
        if self.denoise:
            stages.append(f"afftdn=nr={self.denoise_strength:g}:nf=-25")
        if self.target_lufs is not None:
            stages.append(
                f"loudnorm=I={self.target_lufs:g}:LRA={self.loudness_range:g}:TP={self.true_peak_db:g}"
            )
        return ",".join(stages)

    def enhance(self, clip: AudioClip) -> AudioClip:
        chain = self.filter_chain()
        if not chain or clip.frame_count == 0:
            return clip
        binary = shutil.which("ffmpeg")
        if binary is None:
            raise HansardError("ffmpeg is required by FfmpegEnhancer")
        command = [
            binary, "-hide_banner", "-loglevel", "error",
            "-f", "f32le", "-ac", "1", "-ar", str(clip.sample_rate), "-i", "pipe:0",
            "-af", chain,
            "-f", "f32le", "-ac", "1", "-ar", str(clip.sample_rate), "pipe:1",
        ]
        process = subprocess.run(
            command, input=clip.samples.tobytes(), capture_output=True, check=False
        )
        if process.returncode != 0:
            raise HansardError(f"ffmpeg enhancement failed: {process.stderr.decode(errors='replace')[:400]}")
        enhanced = np.frombuffer(process.stdout, dtype=np.float32).copy()
        return clip.with_samples(enhanced)
