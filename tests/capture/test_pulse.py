from __future__ import annotations

import pytest
from conftest import FakePactl, StepClock, nosleep

from hansard.adapters.capture.audio.pulse import PulseAudioSink, PulseSinkPlan
from hansard.domain.errors import CaptureError


def build_sink(pactl: FakePactl, **overrides) -> PulseAudioSink:
    return PulseAudioSink(
        plan=PulseSinkPlan(sink_name="hansard_sink"),
        runner=pactl,
        clock=overrides.pop("clock", StepClock(step=0.1)),
        sleep=nosleep,
        readiness_timeout_seconds=overrides.pop("readiness_timeout_seconds", 2.0),
        poll_seconds=0.0,
        **overrides,
    )


async def test_start_creates_the_null_sink_virtual_microphone_and_defaults():
    pactl = FakePactl()
    sink = build_sink(pactl)
    await sink.start()
    assert sink.started
    assert sink.monitor_source == "hansard_sink.monitor"
    assert pactl.loaded_modules() == ["module-null-sink", "module-null-sink", "module-remap-source"]
    assert ("pactl", "set-default-sink", "hansard_sink") in pactl.calls
    assert ("pactl", "set-default-source", "hansard_mic") in pactl.calls
    assert ("pactl", "set-source-mute", "hansard_mic", "1") in pactl.calls
    assert len(sink.owned_modules) == 3


async def test_start_is_idempotent_for_pre_existing_devices():
    pactl = FakePactl(
        sinks={"hansard_sink", "hansard_tts"},
        sources={"hansard_sink.monitor", "hansard_tts.monitor", "hansard_mic"},
    )
    sink = build_sink(pactl)
    await sink.start()
    assert pactl.loaded_modules() == []
    assert sink.owned_modules == ()


async def test_second_start_does_nothing():
    pactl = FakePactl()
    sink = build_sink(pactl)
    await sink.start()
    calls = len(pactl.calls)
    await sink.start()
    assert len(pactl.calls) == calls


async def test_stop_unloads_only_the_modules_it_created_in_reverse_order():
    pactl = FakePactl()
    sink = build_sink(pactl)
    await sink.start()
    created = list(sink.owned_modules)
    await sink.stop()
    assert pactl.unloaded == list(reversed(created))
    assert sink.owned_modules == ()
    assert not sink.started


async def test_stop_after_an_idempotent_start_unloads_nothing():
    pactl = FakePactl(
        sinks={"hansard_sink", "hansard_tts"},
        sources={"hansard_sink.monitor", "hansard_tts.monitor", "hansard_mic"},
    )
    sink = build_sink(pactl)
    await sink.start()
    await sink.stop()
    assert pactl.unloaded == []


async def test_missing_pactl_is_reported_clearly():
    sink = build_sink(FakePactl(installed=False))
    with pytest.raises(CaptureError, match="pactl is not installed"):
        await sink.start()


async def test_unreachable_pulse_server_is_reported_clearly():
    sink = build_sink(FakePactl(server_ok=False))
    with pytest.raises(CaptureError, match="PULSE_SERVER"):
        await sink.start()


async def test_monitor_source_that_never_appears_times_out():
    pactl = FakePactl(monitor_ready=False)
    sink = build_sink(pactl, clock=StepClock(step=1.0), readiness_timeout_seconds=2.0)
    with pytest.raises(CaptureError, match="never appeared"):
        await sink.start()


async def test_context_manager_starts_and_stops():
    pactl = FakePactl()
    async with build_sink(pactl) as sink:
        assert sink.started
    assert pactl.unloaded


async def test_a_stray_playback_stream_is_moved_onto_the_capture_sink():
    pactl = FakePactl(
        sinks={"hansard_sink", "hansard_tts"},
        sources={"hansard_sink.monitor", "hansard_tts.monitor", "hansard_mic"},
        sink_inputs={"7": "9"},
    )
    sink = build_sink(pactl)
    await sink.start()
    report = await sink.route_playback_to_capture()
    assert report.moved == ("7",)
    assert report.playback_streams == 1
    assert report.changed
    assert pactl.sink_inputs["7"] == pactl.sink_index("hansard_sink")
    assert pactl.unmuted_inputs == ["7"]


async def test_a_stream_already_on_the_capture_sink_is_left_alone():
    pactl = FakePactl(
        sinks={"hansard_sink", "hansard_tts"},
        sources={"hansard_sink.monitor", "hansard_tts.monitor", "hansard_mic"},
    )
    sink = build_sink(pactl)
    await sink.start()
    pactl.sink_inputs = {"3": pactl.sink_index("hansard_sink")}
    report = await sink.route_playback_to_capture()
    assert report.moved == ()
    assert not report.changed
    assert "move-sink-input" not in {call[1] for call in pactl.calls}


async def test_a_muted_capture_sink_is_unmuted_because_its_monitor_records_the_mute():
    pactl = FakePactl(
        sinks={"hansard_sink", "hansard_tts"},
        sources={"hansard_sink.monitor", "hansard_tts.monitor", "hansard_mic"},
        sink_muted=True,
    )
    sink = build_sink(pactl)
    await sink.start()
    report = await sink.route_playback_to_capture()
    assert report.sink_unmuted
    assert report.changed
    assert not pactl.sink_muted


async def test_routing_without_a_capture_sink_reports_nothing_rather_than_failing():
    pactl = FakePactl(sinks=set(), sources=set())
    sink = build_sink(pactl)
    report = await sink.route_playback_to_capture()
    assert report.playback_streams == 0
    assert not report.changed
