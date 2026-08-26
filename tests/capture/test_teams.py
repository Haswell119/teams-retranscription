from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    VOLUMEDETECT_LOUD,
    VOLUMEDETECT_SILENT,
    FakeLauncher,
    FakePactl,
    FakeProcess,
    ProbeRunner,
    StepClock,
    capture_settings,
    nosleep,
)

from hansard.adapters.capture.audio.pulse import PulseAudioSink, PulseSinkPlan
from hansard.adapters.capture.audio.recorder import FfmpegRecorder, RecorderSettings
from hansard.adapters.capture.browser.events import CaptureEvent, TimelineSettings
from hansard.adapters.capture.browser.session import JoinOutcome, MeetingState
from hansard.adapters.capture.teams import StopReason, TeamsBrowserCapture
from hansard.domain.errors import CaptureError, MeetingJoinRefused
from hansard.domain.meeting import MeetingRequest

ORIGIN = datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)
ORIGIN_MS = int(ORIGIN.timestamp() * 1000)
JOIN_URL = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"


class DatetimeClock:
    def __init__(self, start: datetime = ORIGIN, step_seconds: float = 1.0) -> None:
        self.value = start
        self.step = timedelta(seconds=step_seconds)

    def __call__(self) -> datetime:
        current = self.value
        self.value = self.value + self.step
        return current


class FakeSession:
    def __init__(
        self,
        sink: Callable[[CaptureEvent], None],
        *,
        states: Sequence[MeetingState] = (),
        join_events: Sequence[Mapping[str, Any]] = (),
        tick_events: Sequence[Mapping[str, Any]] = (),
        join_error: Exception | None = None,
        can_announce: bool = True,
        can_open_roster: bool = True,
    ) -> None:
        self.sink = sink
        self.states = list(states)
        self.join_events = list(join_events)
        self.tick_events = list(tick_events)
        self.join_error = join_error
        self.can_announce = can_announce
        self.can_open_roster = can_open_roster
        self.roster_opened = 0
        self.announced: list[str] = []
        self.joined: list[str] = []
        self.left = False
        self.closed = False
        self.call_end = None

    def _emit(self, payload: Mapping[str, Any]) -> None:
        from hansard.adapters.capture.browser.events import parse_event

        event = parse_event(payload)
        if event is not None:
            self.sink(event)

    async def join(self, join_url: str) -> JoinOutcome:
        self.joined.append(join_url)
        if self.join_error is not None:
            raise self.join_error
        for payload in self.join_events:
            self._emit(payload)
        return JoinOutcome(
            state=MeetingState.IN_MEETING,
            url=join_url,
            attempts=1,
            admitted_epoch_ms=ORIGIN_MS,
            waited_in_lobby=False,
        )

    async def announce(self, message: str) -> bool:
        self.announced.append(message)
        return self.can_announce

    async def open_roster(self) -> bool:
        self.roster_opened += 1
        return self.can_open_roster

    async def detect_state(self) -> MeetingState:
        if self.tick_events:
            self._emit(self.tick_events.pop(0))
        if self.states:
            return self.states.pop(0)
        return MeetingState.IN_MEETING

    async def leave(self) -> None:
        self.left = True

    async def aclose(self) -> None:
        self.closed = True


def build_capture(volumedetect: str = VOLUMEDETECT_LOUD, **session_kwargs):
    pactl = session_kwargs.pop("pactl", None) or FakePactl()
    pulse = PulseAudioSink(
        plan=PulseSinkPlan(sink_name="hansard_sink"),
        runner=pactl,
        clock=StepClock(step=0.1),
        sleep=nosleep,
        poll_seconds=0.0,
    )
    launcher = session_kwargs.pop("launcher", None) or FakeLauncher()
    recorder = session_kwargs.pop("recorder", None) or FfmpegRecorder(
        source=pulse.monitor_source,
        launcher=launcher,
        runner=ProbeRunner(volumedetect),
        clock=StepClock(step=1.0),
        sleep=nosleep,
        size_of=lambda _path: 1_000_000,
    )
    sessions: list[FakeSession] = []

    def build_session(sink: Callable[[CaptureEvent], None]) -> FakeSession:
        session = FakeSession(sink, **session_kwargs)
        sessions.append(session)
        return session

    settings = session_kwargs.pop("settings", None) or capture_settings(
        max_duration_seconds=5, silence_timeout_seconds=600, alone_timeout_seconds=600
    )
    capture = TeamsBrowserCapture(
        settings=settings,
        sample_rate=16_000,
        session_builder=build_session,
        recorder_builder=lambda _source: recorder,
        pulse=pulse,
        timeline_settings=TimelineSettings(metadata_lag_seconds=0.0, min_slice_seconds=0.0),
        now=DatetimeClock(),
        sleep=nosleep,
    )
    return capture, sessions, pactl, launcher


def roster_event(offset_ms: int = 0):
    return {
        "kind": "roster",
        "at_epoch_ms": ORIGIN_MS + offset_ms,
        "call_id": "chain-1",
        "participants": [
            {
                "id": "a",
                "display_name": "Alice",
                "state": "active",
                "meeting_role": "organizer",
                "audio_sources": [11],
            }
        ],
    }


def csrc_event(offset_ms: int, *sources: int):
    return {"kind": "csrc", "at_epoch_ms": ORIGIN_MS + offset_ms, "sources": list(sources)}


async def test_capture_records_announces_and_returns_a_roster(tmp_path):
    capture, sessions, pactl, launcher = build_capture(
        join_events=[roster_event(), csrc_event(500, 11)],
        tick_events=[csrc_event(2_000)],
    )
    request = MeetingRequest(join_url=JOIN_URL, title="Comité")
    result = await capture.capture(request, tmp_path / "workspace")
    session = sessions[0]
    assert session.joined == [JOIN_URL]
    assert session.announced == [capture.settings.announcement_text]
    assert session.left and session.closed
    assert result.audio_path == tmp_path / "workspace" / f"{request.identifier}.wav"
    assert result.sample_rate == 16_000
    assert [participant.display_name for participant in result.roster.participants] == ["Alice"]
    assert result.roster.observations
    assert launcher.commands and launcher.process.terminated
    assert "load-module" in [call[1] for call in pactl.calls]
    assert pactl.unloaded
    diagnostics = capture.last_diagnostics
    assert diagnostics is not None
    assert diagnostics.stop_reason is StopReason.MAX_DURATION
    assert diagnostics.announced
    assert diagnostics.silence is not None and not diagnostics.silence.is_silent


async def test_announcement_can_be_switched_off(tmp_path):
    capture, sessions, _, _ = build_capture(
        settings=capture_settings(announce_recording=False, max_duration_seconds=3)
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert sessions[0].announced == []
    assert capture.last_diagnostics is not None
    assert not capture.last_diagnostics.announced


async def test_silence_timeout_stops_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        settings=capture_settings(
            max_duration_seconds=3_600, silence_timeout_seconds=3, alone_timeout_seconds=3_600
        )
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.SILENCE_TIMEOUT


async def test_alone_timeout_stops_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        join_events=[roster_event(), csrc_event(0, 11)],
        settings=capture_settings(
            max_duration_seconds=3_600, silence_timeout_seconds=3_600, alone_timeout_seconds=3
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.ALONE_TIMEOUT


async def test_the_roster_panel_is_opened_so_the_alone_timeout_can_arm(tmp_path):
    capture, sessions, _, _ = build_capture()
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert sessions[0].roster_opened == 1


async def test_a_roster_panel_that_will_not_open_does_not_stop_the_capture(tmp_path):
    capture, sessions, _, _ = build_capture(can_open_roster=False)
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert sessions[0].roster_opened == 1
    assert capture.last_diagnostics is not None


async def test_a_page_that_stops_looking_like_a_meeting_stops_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        states=[MeetingState.IN_MEETING, MeetingState.UNKNOWN, MeetingState.UNKNOWN],
        settings=capture_settings(
            max_duration_seconds=3_600,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
            state_timeout_seconds=1,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.STATE_LOST


async def test_a_momentary_unknown_state_does_not_stop_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        states=[MeetingState.IN_MEETING, MeetingState.UNKNOWN, MeetingState.IN_MEETING],
        settings=capture_settings(
            max_duration_seconds=4,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
            state_timeout_seconds=3,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.MAX_DURATION


async def test_the_lost_state_guard_can_be_switched_off(tmp_path):
    capture, _, _, _ = build_capture(
        states=[MeetingState.UNKNOWN],
        settings=capture_settings(
            max_duration_seconds=3,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
            state_timeout_seconds=0,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.MAX_DURATION


async def test_meeting_end_state_stops_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        states=[MeetingState.IN_MEETING, MeetingState.ENDED],
        settings=capture_settings(max_duration_seconds=3_600),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.MEETING_ENDED


async def test_removal_stops_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        states=[MeetingState.REMOVED],
        settings=capture_settings(max_duration_seconds=3_600),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.REMOVED


async def test_call_end_event_stops_the_capture(tmp_path):
    capture, _, _, _ = build_capture(
        tick_events=[{"kind": "call_end", "at_epoch_ms": ORIGIN_MS, "code": 5000, "sub_code": 5000}],
        settings=capture_settings(max_duration_seconds=3_600),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.MEETING_ENDED


async def test_join_refusal_propagates_and_releases_the_devices(tmp_path):
    capture, sessions, pactl, launcher = build_capture(
        join_error=MeetingJoinRefused("anonymous join is disabled by tenant policy")
    )
    with pytest.raises(MeetingJoinRefused):
        await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert sessions[0].closed
    assert pactl.unloaded
    assert launcher.process.terminated


async def test_a_silent_recording_fails_loudly(tmp_path):
    capture, _, _, _ = build_capture(
        volumedetect=VOLUMEDETECT_SILENT, settings=capture_settings(max_duration_seconds=2)
    )
    with pytest.raises(CaptureError, match="no audible audio"):
        await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)


async def test_capture_requires_a_join_url(tmp_path):
    capture, _, _, _ = build_capture()
    request = MeetingRequest(audio_path=tmp_path / "existing.wav")
    with pytest.raises(CaptureError, match="join_url"):
        await capture.capture(request, tmp_path)


def test_the_bot_never_appears_in_its_own_roster():
    capture, _, _, _ = build_capture()
    reducer = capture._reducer()
    assert capture.settings.display_name in reducer.settings.ignore_display_names


async def test_announcement_follows_the_meeting_language(tmp_path):
    from hansard.adapters.capture.teams import DEFAULT_ANNOUNCEMENTS

    capture, sessions, _, _ = build_capture(settings=capture_settings(max_duration_seconds=3))
    await capture.capture(MeetingRequest(join_url=JOIN_URL, language="fr-FR"), tmp_path)
    assert sessions[0].announced == [DEFAULT_ANNOUNCEMENTS["fr"]]


async def test_announcement_falls_back_to_the_forced_ui_locale(tmp_path):
    from hansard.adapters.capture.teams import DEFAULT_ANNOUNCEMENTS

    capture, sessions, _, _ = build_capture(settings=capture_settings(max_duration_seconds=3))
    capture.ui_locale = "fr-FR"
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert sessions[0].announced == [DEFAULT_ANNOUNCEMENTS["fr"]]


def pcm(sample: int, count: int = 16_000) -> bytes:
    return int(sample).to_bytes(2, "little", signed=True) * count


def build_recorder(pactl: FakePactl, *, tail: bytes, launcher=None, **overrides) -> FfmpegRecorder:
    sizes = iter(range(1_000_000, 100_000_000, 1_000))
    runner = ProbeRunner(VOLUMEDETECT_LOUD)

    def stitch(command: Sequence[str]) -> None:
        if "concat" in command:
            Path(command[-1]).write_bytes(b"\0" * 200_000)

    runner.on_run = stitch
    return FfmpegRecorder(
        source="hansard_sink.monitor",
        launcher=launcher or FakeLauncher(),
        runner=runner,
        clock=StepClock(step=1.0),
        sleep=nosleep,
        size_of=lambda _path: next(sizes),
        read_tail=lambda _path, _count: tail,
        **overrides,
    )


async def test_the_browser_playback_stream_is_claimed_as_soon_as_the_bot_is_admitted(tmp_path):
    pactl = FakePactl(sink_inputs={"5": "99"})
    capture, _, _, _ = build_capture(pactl=pactl)
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert pactl.sink_inputs["5"] == pactl.sink_index("hansard_sink")


async def test_a_capture_that_records_silence_has_its_routing_repaired_during_the_meeting(tmp_path):
    pactl = FakePactl()
    capture, _, _, _ = build_capture(
        pactl=pactl,
        recorder=build_recorder(pactl, tail=pcm(0)),
        settings=capture_settings(
            max_duration_seconds=6,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
            audio_probe_seconds=1.0,
            audio_repair_after_seconds=0,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    diagnostics = capture.last_diagnostics
    assert diagnostics is not None
    assert diagnostics.audio_repairs >= 1
    assert diagnostics.last_level is not None and diagnostics.last_level.is_silent


async def test_audible_audio_is_not_repaired_and_is_reported(tmp_path):
    pactl = FakePactl()
    capture, _, _, _ = build_capture(
        pactl=pactl,
        recorder=build_recorder(pactl, tail=pcm(12_000)),
        settings=capture_settings(
            max_duration_seconds=6,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
            audio_probe_seconds=1.0,
            audio_repair_after_seconds=0,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    diagnostics = capture.last_diagnostics
    assert diagnostics is not None
    assert diagnostics.audio_repairs == 0
    assert diagnostics.last_level is not None and diagnostics.last_level.is_audible


async def test_a_meeting_that_is_still_audible_is_not_left_for_silence(tmp_path):
    pactl = FakePactl()
    capture, _, _, _ = build_capture(
        pactl=pactl,
        recorder=build_recorder(pactl, tail=pcm(12_000)),
        settings=capture_settings(
            max_duration_seconds=6,
            silence_timeout_seconds=2,
            alone_timeout_seconds=3_600,
            audio_probe_seconds=1.0,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.MAX_DURATION


async def test_a_recorder_that_dies_mid_meeting_is_restarted_instead_of_losing_the_capture(tmp_path):
    pactl = FakePactl()
    launcher = FakeLauncher(processes=[FakeProcess(returncode=1), FakeProcess()])
    capture, _, _, _ = build_capture(
        pactl=pactl,
        recorder=build_recorder(pactl, tail=pcm(12_000), launcher=launcher),
        settings=capture_settings(
            max_duration_seconds=4,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
        ),
    )
    await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    diagnostics = capture.last_diagnostics
    assert diagnostics is not None
    assert diagnostics.stop_reason is StopReason.MAX_DURATION
    assert diagnostics.recorder_restarts == 1
    assert len(launcher.commands) == 2


async def test_a_recorder_that_cannot_be_restarted_stops_the_capture_and_keeps_the_audio(tmp_path):
    pactl = FakePactl()
    launcher = FakeLauncher(processes=[FakeProcess(returncode=1)])
    capture, sessions, _, _ = build_capture(
        pactl=pactl,
        recorder=build_recorder(
            pactl,
            tail=pcm(12_000),
            launcher=launcher,
            settings=RecorderSettings(max_restarts=0),
        ),
        settings=capture_settings(
            max_duration_seconds=3_600,
            silence_timeout_seconds=3_600,
            alone_timeout_seconds=3_600,
        ),
    )
    result = await capture.capture(MeetingRequest(join_url=JOIN_URL), tmp_path)
    assert capture.last_diagnostics is not None
    assert capture.last_diagnostics.stop_reason is StopReason.RECORDER_FAILED
    assert result.audio_path.name.endswith(".wav")
    assert sessions[0].left
