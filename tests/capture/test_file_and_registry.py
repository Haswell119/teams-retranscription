from __future__ import annotations

import wave

import pytest

from hansard.adapters.capture.file import AudioProbe, FileCapture, NullCapture, probe_audio
from hansard.adapters.capture.registry import available_captures, build_capture, register_capture
from hansard.adapters.capture.teams import TeamsBrowserCapture
from hansard.config import CaptureSettings
from hansard.domain.errors import CaptureError, ConfigurationError
from hansard.domain.meeting import MeetingRequest
from hansard.ports.capture import MeetingCapture


def write_wav(path, seconds=1.0, sample_rate=16_000):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return path


async def test_file_capture_copies_the_source_into_the_workspace(tmp_path):
    source = write_wav(tmp_path / "source.wav", seconds=2.0)
    workspace = tmp_path / "workspace"
    request = MeetingRequest(audio_path=source, expected_participants=("Alice", "Bob"))
    capture = await FileCapture().capture(request, workspace)
    assert capture.audio_path == workspace / f"{request.identifier}.wav"
    assert capture.audio_path.exists()
    assert capture.sample_rate == 16_000
    assert capture.duration == pytest.approx(2.0, abs=0.01)
    assert [participant.display_name for participant in capture.roster.participants] == ["Alice", "Bob"]
    assert capture.roster.observations == ()


async def test_file_capture_can_use_the_source_in_place(tmp_path):
    source = write_wav(tmp_path / "source.wav")
    request = MeetingRequest(audio_path=source)
    capture = await FileCapture(copy_into_workspace=False).capture(request, tmp_path / "workspace")
    assert capture.audio_path == source


async def test_file_capture_requires_an_audio_path(tmp_path):
    request = MeetingRequest(join_url="https://teams.microsoft.com/l/meetup-join/x")
    with pytest.raises(CaptureError, match="audio_path"):
        await FileCapture().capture(request, tmp_path)


async def test_file_capture_accepts_an_injected_probe(tmp_path):
    source = write_wav(tmp_path / "source.wav")
    request = MeetingRequest(audio_path=source)
    engine = FileCapture(probe=lambda _path: AudioProbe(48_000, 90.0))
    capture = await engine.capture(request, tmp_path / "ws")
    assert capture.sample_rate == 48_000
    assert capture.duration == pytest.approx(90.0)


def test_probe_audio_reports_missing_files(tmp_path):
    with pytest.raises(CaptureError, match="not found"):
        probe_audio(tmp_path / "nope.wav")


def test_probe_audio_reads_a_wav(tmp_path):
    probe = probe_audio(write_wav(tmp_path / "source.wav", seconds=0.5))
    assert probe.sample_rate == 16_000
    assert probe.duration_seconds == pytest.approx(0.5, abs=0.01)


async def test_null_capture_writes_readable_silence(tmp_path):
    request = MeetingRequest(join_url="https://teams.microsoft.com/l/meetup-join/x")
    capture = await NullCapture(silence_seconds=0.25).capture(request, tmp_path)
    with wave.open(str(capture.audio_path), "rb") as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnframes() == 4_000
    assert capture.duration == pytest.approx(0.25)


def test_registry_builds_every_declared_engine():
    assert available_captures() == ("browser", "file", "null")
    assert isinstance(build_capture(CaptureSettings(engine="file")), FileCapture)
    assert isinstance(build_capture(CaptureSettings(engine="null")), NullCapture)
    browser = build_capture(CaptureSettings(engine="browser"), sample_rate=48_000)
    assert isinstance(browser, TeamsBrowserCapture)
    assert browser.sample_rate == 48_000


def test_registry_engines_satisfy_the_port():
    for engine in ("browser", "file", "null"):
        assert isinstance(build_capture(CaptureSettings(engine=engine)), MeetingCapture)


def test_registry_rejects_unknown_engines():
    settings = CaptureSettings.model_construct(engine="carrier-pigeon")
    with pytest.raises(ConfigurationError, match="carrier-pigeon"):
        build_capture(settings)


def test_registry_accepts_extra_engines():
    register_capture("stub", lambda _settings, _rate: NullCapture())
    assert "stub" in available_captures()
    assert isinstance(build_capture(CaptureSettings.model_construct(engine="stub")), NullCapture)
