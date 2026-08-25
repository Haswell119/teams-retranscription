from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    VOLUMEDETECT_LOUD,
    VOLUMEDETECT_SILENT,
    FakeLauncher,
    FakeProcess,
    ProbeRunner,
    StepClock,
    nosleep,
)

from hansard.adapters.capture.audio.recorder import FfmpegRecorder, RecorderSettings
from hansard.domain.errors import CaptureError


def build_recorder(tmp_path: Path, **overrides) -> tuple[FfmpegRecorder, FakeLauncher, ProbeRunner]:
    launcher = overrides.pop("launcher", FakeLauncher())
    runner = overrides.pop("runner", ProbeRunner())
    sizes = overrides.pop("sizes", [1_000_000])
    recorder = FfmpegRecorder(
        source="hansard_sink.monitor",
        settings=overrides.pop("settings", RecorderSettings()),
        launcher=launcher,
        runner=runner,
        clock=overrides.pop("clock", StepClock(step=1.0)),
        sleep=nosleep,
        size_of=overrides.pop("size_of", lambda _path: sizes[-1] if sizes else 0),
        **overrides,
    )
    return recorder, launcher, runner


def test_command_captures_the_monitor_at_the_configured_rate(tmp_path):
    recorder, _, _ = build_recorder(tmp_path)
    command = recorder.command(tmp_path / "out.wav")
    assert command[0] == "ffmpeg"
    assert "-f" in command and "pulse" in command
    assert "hansard_sink.monitor" in command
    assert "16000" in command
    assert "pcm_s16le" in command
    assert "aresample=async=1:first_pts=0" in command


async def test_start_then_stop_returns_the_written_file(tmp_path):
    recorder, launcher, _ = build_recorder(tmp_path)
    output = tmp_path / "meeting.wav"
    await recorder.start(output)
    assert recorder.running
    assert launcher.commands[0][-1] == str(output)
    assert await recorder.stop() == output
    assert launcher.process.terminated
    assert not recorder.running


async def test_start_twice_is_refused(tmp_path):
    recorder, _, _ = build_recorder(tmp_path)
    await recorder.start(tmp_path / "meeting.wav")
    with pytest.raises(CaptureError, match="already running"):
        await recorder.start(tmp_path / "meeting.wav")


async def test_stop_without_start_is_refused(tmp_path):
    recorder, _, _ = build_recorder(tmp_path)
    with pytest.raises(CaptureError, match="never started"):
        await recorder.stop()


async def test_stop_rejects_a_file_that_never_grew(tmp_path):
    recorder, _, _ = build_recorder(tmp_path, size_of=lambda _path: 44)
    await recorder.start(tmp_path / "meeting.wav")
    with pytest.raises(CaptureError, match="no usable audio"):
        await recorder.stop()


async def test_ensure_progressing_detects_a_dead_ffmpeg(tmp_path):
    launcher = FakeLauncher(FakeProcess())
    recorder, _, _ = build_recorder(tmp_path, launcher=launcher)
    await recorder.start(tmp_path / "meeting.wav")
    launcher.process.set_returncode(1)
    with pytest.raises(CaptureError, match="ffmpeg exited early"):
        await recorder.ensure_progressing()


async def test_ensure_progressing_accepts_a_growing_file(tmp_path):
    growth = iter([1_000, 2_000, 3_000])
    recorder, _, _ = build_recorder(tmp_path, size_of=lambda _path: next(growth))
    await recorder.start(tmp_path / "meeting.wav")
    await recorder.ensure_progressing()
    await recorder.ensure_progressing()


async def test_ensure_progressing_detects_a_stalled_capture(tmp_path):
    recorder, _, _ = build_recorder(
        tmp_path,
        settings=RecorderSettings(stall_grace_seconds=1.0),
        clock=StepClock(step=2.0),
        size_of=lambda _path: 4_096,
    )
    await recorder.start(tmp_path / "meeting.wav")
    await recorder.ensure_progressing()
    with pytest.raises(CaptureError, match="stopped writing"):
        await recorder.ensure_progressing()


async def test_silence_report_parses_volumedetect(tmp_path):
    recorder, _, runner = build_recorder(tmp_path, runner=ProbeRunner(VOLUMEDETECT_LOUD))
    report = await recorder.silence_report(tmp_path / "meeting.wav")
    assert report.mean_dbfs == pytest.approx(-26.4)
    assert report.max_dbfs == pytest.approx(-3.1)
    assert report.measured
    assert not report.is_silent
    assert "volumedetect" in " ".join(runner.commands[0])


async def test_assert_not_silent_raises_a_loud_diagnostic(tmp_path):
    recorder, _, _ = build_recorder(tmp_path, runner=ProbeRunner(VOLUMEDETECT_SILENT))
    with pytest.raises(CaptureError, match="mute-audio"):
        await recorder.assert_not_silent(tmp_path / "meeting.wav")


async def test_assert_not_silent_passes_on_audible_audio(tmp_path):
    recorder, _, _ = build_recorder(tmp_path, runner=ProbeRunner(VOLUMEDETECT_LOUD))
    report = await recorder.assert_not_silent(tmp_path / "meeting.wav")
    assert report.max_dbfs == pytest.approx(-3.1)


async def test_unmeasurable_audio_is_not_declared_silent(tmp_path):
    recorder, _, _ = build_recorder(tmp_path, runner=ProbeRunner("no readings here"))
    report = await recorder.assert_not_silent(tmp_path / "meeting.wav")
    assert not report.measured
    assert not report.is_silent
