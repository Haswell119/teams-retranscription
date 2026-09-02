from __future__ import annotations

import struct
from pathlib import Path

import pytest

from hansard.adapters.audio.io import load_clip
from hansard.domain.errors import HansardError

FORMAT_CHUNK = struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)


def wav(path: Path, samples: int, *, declared: int | None = None) -> Path:
    payload = b"".join(struct.pack("<h", (index % 400) * 60) for index in range(samples))
    size = len(payload) if declared is None else declared
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + size)
        + b"WAVEfmt "
        + FORMAT_CHUNK
        + b"data"
        + struct.pack("<I", size)
    )
    path.write_bytes(header + payload)
    return path


def test_a_complete_recording_reads_normally(tmp_path):
    clip = load_clip(wav(tmp_path / "meeting.wav", 16_000), 16_000)
    assert clip.samples.size == 16_000
    assert clip.duration == pytest.approx(1.0)


def test_a_recording_whose_header_was_never_finalised_is_still_read(tmp_path):
    target = wav(tmp_path / "killed.wav", 16_000, declared=0)
    clip = load_clip(target, 16_000)
    assert clip.samples.size == 16_000


def test_a_genuinely_empty_recording_stays_empty(tmp_path):
    clip = load_clip(wav(tmp_path / "nothing.wav", 0), 16_000)
    assert clip.samples.size == 0


def test_a_missing_recording_says_so(tmp_path):
    with pytest.raises(HansardError, match="audio file not found"):
        load_clip(tmp_path / "absent.wav", 16_000)
