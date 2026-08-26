from __future__ import annotations

import pytest
from conftest import (
    FakeRuntimeFactory,
    FakeScreen,
    StepClock,
    capture_settings,
    fast_timing,
    nosleep,
)

from hansard.adapters.capture.browser import selectors
from hansard.adapters.capture.browser.events import CaptureEvent
from hansard.adapters.capture.browser.session import (
    CHROMIUM_ARGUMENTS,
    IGNORED_DEFAULT_ARGUMENTS,
    MeetingState,
    TeamsBrowserSession,
    is_direct_prejoin_url,
    origin_of,
    rewrite_join_url,
)
from hansard.domain.errors import CaptureError, MeetingAdmissionTimeout, MeetingJoinRefused

CLASSIC_LINK = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=%7B%22Tid%22%3A%22t%22%7D"
DIRECT_LINK = "https://teams.microsoft.com/meet/1234567890?p=abcdef"
LIVE_LINK = "https://teams.live.com/meet/9876543210?p=secret"

JOIN_ON_WEB = selectors.JOIN_ON_WEB[0]
NAME_INPUT = selectors.PREJOIN_DISPLAY_NAME[0]
JOIN_BUTTON = selectors.PREJOIN_JOIN_BUTTON[0]
MIC_TOGGLE = selectors.TOGGLE_MICROPHONE[0]
CAMERA_TOGGLE = selectors.TOGGLE_CAMERA[0]
CONTINUE_BUTTON = selectors.CONTINUE_WITHOUT_MEDIA[0]
HANGUP = selectors.HANGUP_BUTTON[0]
CHAT_BOX = selectors.CHAT_MESSAGE_BOX[0]


def build_session(screens, events=None, **overrides):
    factory = FakeRuntimeFactory(screens)
    settings = capture_settings(**overrides.pop("settings", {}))
    session = TeamsBrowserSession(
        settings=settings,
        factory=factory,
        event_sink=events.append if events is not None else None,
        timing=fast_timing(),
        instrumentation="/* test */",
        clock=StepClock(step=0.25),
        epoch_ms=lambda: 1_700_000_000_000,
        sleep=nosleep,
        **overrides,
    )
    return session, factory


def launcher_screen(**kwargs):
    screen = FakeScreen(present={JOIN_ON_WEB}, **kwargs)

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON, MIC_TOGGLE, CAMERA_TOGGLE)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON, MIC_TOGGLE, CAMERA_TOGGLE)
            current.show(HANGUP)

    screen.on_click = on_click
    screen.attributes = {MIC_TOGGLE: {"aria-checked": "true"}, CAMERA_TOGGLE: {"aria-checked": "true"}}
    return screen


def test_rewrite_join_url_adds_launcher_bypass_parameters():
    rewritten = rewrite_join_url(CLASSIC_LINK)
    assert "msLaunch=false" in rewritten
    assert "type=meetup-join" in rewritten
    assert "directDl=true" in rewritten
    assert "enableMobilePage=true" in rewritten
    assert "suppressPrompt=true" in rewritten
    assert "context=" in rewritten


def test_rewrite_join_url_is_idempotent():
    once = rewrite_join_url(CLASSIC_LINK)
    assert rewrite_join_url(once) == once


def test_rewrite_join_url_leaves_direct_prejoin_links_alone():
    assert rewrite_join_url(DIRECT_LINK) == DIRECT_LINK
    assert rewrite_join_url(LIVE_LINK) == LIVE_LINK
    assert is_direct_prejoin_url(DIRECT_LINK)
    assert not is_direct_prejoin_url(CLASSIC_LINK)


def test_rewrite_join_url_rejects_non_http_schemes():
    with pytest.raises(CaptureError):
        rewrite_join_url("msteams:/l/meetup-join/19:meeting")


def test_origin_of_strips_path():
    assert origin_of(CLASSIC_LINK) == "https://teams.microsoft.com"


def test_chromium_flags_keep_audio_unmuted():
    assert "--mute-audio" in IGNORED_DEFAULT_ARGUMENTS
    assert "--autoplay-policy=no-user-gesture-required" in CHROMIUM_ARGUMENTS
    assert "--headless=new" not in CHROMIUM_ARGUMENTS


async def test_join_walks_launcher_prejoin_and_meeting():
    screen = launcher_screen()
    session, factory = build_session([screen])
    outcome = await session.join(CLASSIC_LINK)
    assert outcome.state is MeetingState.IN_MEETING
    assert outcome.attempts == 1
    assert not outcome.waited_in_lobby
    context = factory.latest.context
    assert context.init_scripts == ["/* test */"]
    assert "__hansardEmit" in context.bindings
    assert context.permissions == [(("microphone", "camera"), "https://teams.microsoft.com")]
    method, params = factory.latest.cdp_session.calls[0]
    assert method == "Browser.grantPermissions"
    assert params["permissions"] == ["geolocation", "audioCapture", "displayCapture", "videoCapture"]
    assert screen.fills == [(NAME_INPUT, "Hansard Notetaker")]
    assert MIC_TOGGLE in screen.clicks
    assert CAMERA_TOGGLE in screen.clicks
    assert screen.navigations[0].startswith("https://teams.microsoft.com/l/meetup-join/")


async def test_join_leaves_already_muted_devices_alone():
    screen = launcher_screen()
    screen.attributes = {MIC_TOGGLE: {"aria-checked": "false"}, CAMERA_TOGGLE: {"aria-checked": "false"}}
    session, _ = build_session([screen])
    await session.join(CLASSIC_LINK)
    assert MIC_TOGGLE not in screen.clicks
    assert CAMERA_TOGGLE not in screen.clicks


async def test_join_handles_continue_without_audio_or_video_dialog():
    screen = launcher_screen()
    continued = {"clicked": False}

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON)
        elif selector == CONTINUE_BUTTON:
            current.hide(CONTINUE_BUTTON)
            continued["clicked"] = True
        elif selector == JOIN_BUTTON and not continued["clicked"]:
            current.show(CONTINUE_BUTTON)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON)
            current.show(HANGUP)

    screen.on_click = on_click
    session, _ = build_session([screen])
    outcome = await session.join(CLASSIC_LINK)
    assert outcome.state is MeetingState.IN_MEETING
    assert screen.clicks.count(JOIN_BUTTON) == 2
    assert CONTINUE_BUTTON in screen.clicks


async def test_join_waits_in_lobby_then_gets_admitted():
    screen = launcher_screen()

    def on_poll(current: FakeScreen) -> None:
        if current.polls >= 3:
            current.text = ""
            current.show(HANGUP)

    screen.on_poll = on_poll

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON)
            current.text = "Someone will let you in shortly"

    screen.on_click = on_click
    session, _ = build_session([screen])
    outcome = await session.join(CLASSIC_LINK)
    assert outcome.state is MeetingState.IN_MEETING
    assert outcome.waited_in_lobby


async def test_lobby_timeout_raises_admission_timeout():
    screen = launcher_screen()

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON)
            current.text = "Someone will let you in shortly"

    screen.on_click = on_click
    session, _ = build_session([screen], settings={"lobby_timeout_seconds": 1})
    with pytest.raises(MeetingAdmissionTimeout, match="lobby"):
        await session.join(CLASSIC_LINK)


async def test_denial_text_raises_join_refused():
    screen = launcher_screen()

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON)
            current.text = "Sorry, but you were denied access to this meeting"

    screen.on_click = on_click
    session, _ = build_session([screen])
    with pytest.raises(MeetingJoinRefused):
        await session.join(CLASSIC_LINK)


@pytest.mark.parametrize("sub_code", [5723, 5854])
async def test_conversation_end_sub_codes_raise_join_refused(sub_code):
    screen = launcher_screen()
    events: list[CaptureEvent] = []
    session, factory = build_session([screen], events=events)

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON)
            current.text = "Someone will let you in shortly"
            factory.latest.emit(
                {
                    "kind": "call_end",
                    "at_epoch_ms": 1,
                    "code": 5000,
                    "sub_code": sub_code,
                    "reason": "conversationEnd",
                }
            )

    screen.on_click = on_click
    with pytest.raises(MeetingJoinRefused) as failure:
        await session.join(CLASSIC_LINK)
    assert str(sub_code) in str(failure.value)
    assert events


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("You\u2019ve been removed from this meeting", "removed"),
        ("Meeting ended", "ended"),
    ],
)
async def test_terminal_meeting_texts_raise_capture_error(text, message):
    screen = launcher_screen()

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == JOIN_ON_WEB:
            current.hide(JOIN_ON_WEB)
            current.show(NAME_INPUT, JOIN_BUTTON)
        elif selector == JOIN_BUTTON:
            current.hide(NAME_INPUT, JOIN_BUTTON)
            current.text = text

    screen.on_click = on_click
    session, _ = build_session([screen])
    with pytest.raises(CaptureError, match=message):
        await session.join(CLASSIC_LINK)


async def test_light_experience_redirect_restarts_the_browser():
    broken = launcher_screen()
    broken.redirect_to = "https://teams.microsoft.com/v2/?lightExperience=false"
    healthy = launcher_screen()
    session, factory = build_session([broken, healthy])
    outcome = await session.join(CLASSIC_LINK)
    assert outcome.attempts == 2
    assert factory.runtimes[0].closed
    assert outcome.state is MeetingState.IN_MEETING


async def test_light_experience_redirect_gives_up_after_max_attempts():
    broken = launcher_screen()
    broken.redirect_to = "https://teams.microsoft.com/v2/?lightExperience=false"
    session, factory = build_session([broken], max_join_attempts=2)
    with pytest.raises(CaptureError, match="light experience"):
        await session.join(CLASSIC_LINK)
    assert len(factory.runtimes) == 2


async def test_announce_types_into_the_meeting_chat():
    screen = launcher_screen()
    session, _ = build_session([screen])
    await session.join(CLASSIC_LINK)
    screen.show(CHAT_BOX)
    assert await session.announce("recording notice")
    assert screen.fills[-1] == (CHAT_BOX, "recording notice")
    assert screen.presses[-1] == (CHAT_BOX, "Enter")


async def test_announce_is_a_no_op_without_a_chat_box():
    screen = launcher_screen()
    session, _ = build_session([screen])
    await session.join(CLASSIC_LINK)
    assert not await session.announce("recording notice")


async def test_leave_clicks_hangup_and_close_releases_the_runtime():
    screen = launcher_screen()
    session, factory = build_session([screen])
    await session.join(CLASSIC_LINK)
    await session.leave()
    assert screen.clicks[-1] == HANGUP
    await session.aclose()
    assert factory.latest.closed


async def test_detect_state_reports_launcher_and_prejoin():
    screen = FakeScreen(present={JOIN_ON_WEB})
    session, _ = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert await session.detect_state() is MeetingState.LAUNCHER
    screen.hide(JOIN_ON_WEB)
    screen.show(JOIN_BUTTON)
    assert await session.detect_state() is MeetingState.PREJOIN
    screen.hide(JOIN_BUTTON)
    assert await session.detect_state() is MeetingState.UNKNOWN


async def test_instrumentation_ready_flag_is_set_from_the_binding():
    screen = launcher_screen()
    session, factory = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert not session.instrumentation_ready
    factory.latest.emit({"kind": "ready", "at_epoch_ms": 5, "href": "https://teams.microsoft.com"})
    assert session.instrumentation_ready


async def test_a_hangup_button_left_mounted_but_hidden_no_longer_reads_as_in_meeting():
    screen = FakeScreen(present={HANGUP})
    session, _ = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert await session.detect_state() is MeetingState.IN_MEETING
    screen.present.discard(HANGUP)
    screen.hidden.add(HANGUP)
    screen.text = "La réunion est terminée"
    assert await session.detect_state() is MeetingState.ENDED


async def test_a_disabled_hangup_button_still_does_not_read_as_in_meeting():
    screen = FakeScreen(present={HANGUP}, attributes={HANGUP: {"aria-disabled": "true"}})
    session, _ = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert await session.detect_state() is MeetingState.UNKNOWN


async def test_opening_the_roster_clicks_the_toggle_and_confirms_the_panel():
    toggle = selectors.ROSTER_PANEL_TOGGLE[0]
    panel = selectors.ROSTER_PANEL[0]
    screen = FakeScreen(present={HANGUP, toggle})

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == toggle:
            current.show(panel)

    screen.on_click = on_click
    session, _ = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert await session.open_roster()
    assert toggle in screen.clicks


async def test_an_already_open_roster_is_left_alone():
    panel = selectors.ROSTER_PANEL[0]
    screen = FakeScreen(present={HANGUP, panel})
    session, _ = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert await session.open_roster()
    assert not screen.clicks


async def test_a_missing_roster_toggle_is_reported_rather_than_raised():
    screen = FakeScreen(present={HANGUP})
    session, _ = build_session([screen])
    await session._start_runtime(CLASSIC_LINK)
    assert not await session.open_roster()
