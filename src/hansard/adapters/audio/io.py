from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from hansard.adapters.audio.resample import resample
from hansard.domain.audio import TARGET_SAMPLE_RATE, AudioClip
from hansard.domain.errors import HansardError

_DIRECT_SUFFIXES = {".wav", ".flac", ".ogg", ".opus"}


def _ffmpeg_binary() -> str | None:
    return shutil.which("ffmpeg")


def decode_to_clip(data: bytes, sample_rate: int = TARGET_SAMPLE_RATE) -> AudioClip:
    binary = _ffmpeg_binary()
    if binary is None:
        raise HansardError("ffmpeg is required to decode in-memory audio")
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]
    process = subprocess.run(command, input=data, capture_output=True, check=False)
    if process.returncode != 0:
        raise HansardError(f"ffmpeg decode failed: {process.stderr.decode(errors='replace')[:400]}")
    return AudioClip(np.frombuffer(process.stdout, dtype=np.float32).copy(), sample_rate)


def _load_via_soundfile(path: Path, sample_rate: int) -> AudioClip:
    samples, native_rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = samples.mean(axis=1).astype(np.float32)
    return AudioClip(resample(mono, native_rate, sample_rate), sample_rate)


def _load_via_ffmpeg(path: Path, sample_rate: int) -> AudioClip:
    binary = _ffmpeg_binary()
    if binary is None:
        raise HansardError(f"ffmpeg is required to read {path.suffix} audio")
    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "pipe:1",
    ]
    process = subprocess.run(command, capture_output=True, check=False)
    if process.returncode != 0:
        raise HansardError(f"ffmpeg decode failed: {process.stderr.decode(errors='replace')[:400]}")
    return AudioClip(np.frombuffer(process.stdout, dtype=np.float32).copy(), sample_rate)


def load_clip(path: Path, sample_rate: int = TARGET_SAMPLE_RATE) -> AudioClip:
    if not path.exists():
        raise HansardError(f"audio file not found: {path}")
    if path.suffix.lower() in _DIRECT_SUFFIXES:
        try:
            return _load_via_soundfile(path, sample_rate)
        except (sf.LibsndfileError, RuntimeError):
            return _load_via_ffmpeg(path, sample_rate)
    return _load_via_ffmpeg(path, sample_rate)


def write_clip(clip: AudioClip, path: Path, subtype: str = "PCM_16") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), clip.samples, clip.sample_rate, subtype=subtype)
    return path
