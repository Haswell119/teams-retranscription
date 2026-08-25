from __future__ import annotations

from typing import Any

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
from hansard.adapters.capture.browser.session import (
    DEFAULT_UI_LOCALE,
    FALLBACK_UI_LOCALE,
    BrowserOptions,
    MeetingState,
    PlaywrightRuntimeFactory,
    TeamsBrowserSession,
)
from hansard.adapters.capture.teams import DEFAULT_ANNOUNCEMENTS, announcement_for, language_key
from hansard.domain.errors import CaptureError, MeetingJoinRefused

FRENCH_JOIN_ON_WEB = 'button:has-text("Rejoindre la réunion à partir de ce navigateur")'
FRENCH_NAME_INPUT = 'input[placeholder="Tapez votre nom"]'
FRENCH_JOIN_BUTTON = 'button:has-text("Rejoindre maintenant")'
FRENCH_CONTINUE = 'button:has-text("Poursuivre sans audio ni vidéo")'
FRENCH_CHAT_BOX = '[aria-label="Écrivez un message"]'
HANGUP = selectors.HANGUP_BUTTON[0]

FRENCH_LOBBY = "Quelqu\u2019un vous laissera bientôt entrer dans la réunion."
FRENCH_DENIED = "Désolé, mais vous avez été refusé pour cette réunion"
FRENCH_REMOVED = "Vous avez été supprimé de cette réunion"
FRENCH_ENDED = "La réunion est terminée"


def build_session(screen: FakeScreen, **overrides: Any):
    factory = FakeRuntimeFactory([screen])
    session = TeamsBrowserSession(
        settings=capture_settings(**overrides.pop("settings", {})),
        factory=factory,
        timing=fast_timing(),
        instrumentation="/* test */",
        clock=StepClock(step=0.25),
        epoch_ms=lambda: 1_700_000_000_000,
        sleep=nosleep,
        **overrides,
    )
    return session, factory


def french_screen() -> FakeScreen:
    screen = FakeScreen(present={FRENCH_JOIN_ON_WEB})

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == FRENCH_JOIN_ON_WEB:
            current.hide(FRENCH_JOIN_ON_WEB)
            current.show(FRENCH_NAME_INPUT, FRENCH_JOIN_BUTTON)
        elif selector == FRENCH_JOIN_BUTTON:
            current.hide(FRENCH_NAME_INPUT, FRENCH_JOIN_BUTTON)
            current.show(HANGUP)

    screen.on_click = on_click
    return screen


def test_normalise_text_folds_apostrophes_case_and_french_spacing():
    assert selectors.normalise_text("Quelqu\u2019un vous\u00a0laissera BIENTÔT entrer") == (
        "quelqu'un vous laissera bientôt entrer"
    )
    assert selectors.normalise_text("  La réunion\u202fest terminée  ") == "la réunion est terminée"


def test_matches_any_is_language_and_typography_agnostic():
    assert selectors.matches_any(FRENCH_LOBBY, selectors.LOBBY_TEXTS)
    assert selectors.matches_any("Someone will let you in shortly", selectors.LOBBY_TEXTS)
    assert selectors.matches_any("You\u2019ve been removed from this meeting", selectors.REMOVED_TEXTS)
    assert selectors.matches_any(FRENCH_REMOVED, selectors.REMOVED_TEXTS)
    assert selectors.matches_any("MEETING ENDED", selectors.MEETING_ENDED_TEXTS)
    assert selectors.matches_any("rien à signaler", selectors.DENIED_TEXTS) is None


def test_every_text_state_list_carries_english_and_french_candidates():
    for texts in (
        selectors.LOBBY_TEXTS,
        selectors.DENIED_TEXTS,
        selectors.REMOVED_TEXTS,
        selectors.MEETING_ENDED_TEXTS,
        selectors.BLOCKED_TEXTS,
    ):
        assert any("é" in text or "ê" in text or "è" in text for text in texts)


def test_every_clickable_group_starts_with_a_locale_independent_selector():
    for group in (
        selectors.PREJOIN_DISPLAY_NAME,
        selectors.PREJOIN_JOIN_BUTTON,
        selectors.TOGGLE_MICROPHONE,
        selectors.TOGGLE_CAMERA,
        selectors.JOIN_ON_WEB,
        selectors.HANGUP_BUTTON,
        selectors.ROSTER_PANEL,
        selectors.ROSTER_PARTICIPANT_ROW,
    ):
        assert "data-tid" in group[0] or group[0].startswith("button#")


async def test_join_works_against_a_french_teams_ui():
    screen = french_screen()
    session, _ = build_session(screen)
    outcome = await session.join("https://teams.microsoft.com/l/meetup-join/19%3ameeting/0")
    assert outcome.state is MeetingState.IN_MEETING
    assert screen.fills == [(FRENCH_NAME_INPUT, "Hansard Notetaker")]


async def test_french_denial_text_raises_join_refused():
    screen = french_screen()

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == FRENCH_JOIN_ON_WEB:
            current.hide(FRENCH_JOIN_ON_WEB)
            current.show(FRENCH_JOIN_BUTTON)
        elif selector == FRENCH_JOIN_BUTTON:
            current.hide(FRENCH_JOIN_BUTTON)
            current.text = FRENCH_DENIED

    screen.on_click = on_click
    session, _ = build_session(screen)
    with pytest.raises(MeetingJoinRefused):
        await session.join("https://teams.microsoft.com/l/meetup-join/19%3ameeting/0")


async def test_french_meeting_ended_text_raises_capture_error():
    screen = french_screen()

    def on_click(current: FakeScreen, selector: str) -> None:
        if selector == FRENCH_JOIN_ON_WEB:
            current.hide(FRENCH_JOIN_ON_WEB)
            current.show(FRENCH_JOIN_BUTTON)
        elif selector == FRENCH_JOIN_BUTTON:
            current.hide(FRENCH_JOIN_BUTTON)
            current.text = FRENCH_ENDED

    screen.on_click = on_click
    session, _ = build_session(screen)
    with pytest.raises(CaptureError, match="ended"):
        await session.join("https://teams.microsoft.com/l/meetup-join/19%3ameeting/0")


async def test_french_lobby_text_is_recognised_as_waiting():
    screen = FakeScreen(text=FRENCH_LOBBY)
    session, _ = build_session(screen)
    await session._start_runtime("https://teams.microsoft.com/l/meetup-join/19%3ameeting/0")
    assert await session.detect_state() is MeetingState.LOBBY


async def test_announcement_is_typed_into_the_french_chat_box():
    screen = french_screen()
    session, _ = build_session(screen)
    await session.join("https://teams.microsoft.com/l/meetup-join/19%3ameeting/0")
    screen.show(FRENCH_CHAT_BOX)
    assert await session.announce("Cette réunion est transcrite")
    assert screen.fills[-1] == (FRENCH_CHAT_BOX, "Cette réunion est transcrite")


def test_browser_options_pin_the_ui_language():
    assert DEFAULT_UI_LOCALE == FALLBACK_UI_LOCALE
    assert "--lang=en-US" in BrowserOptions().chromium_arguments()
    assert "--lang=fr-FR" in BrowserOptions(locale="fr-FR").chromium_arguments()


def test_language_key_normalises_locale_tags():
    assert language_key("fr-FR") == "fr"
    assert language_key("fr_CA") == "fr"
    assert language_key("en-US") == "en"
    assert language_key(None) == "en"


def test_announcement_defaults_follow_the_meeting_language():
    settings = capture_settings()
    assert announcement_for(settings, "en-GB") == DEFAULT_ANNOUNCEMENTS["en"]
    assert announcement_for(settings, "fr-FR") == DEFAULT_ANNOUNCEMENTS["fr"]
    assert "réunion" in announcement_for(settings, "fr")
    assert announcement_for(settings, "de-DE") == DEFAULT_ANNOUNCEMENTS["en"]


def test_a_configured_announcement_always_wins():
    settings = capture_settings(announcement_text="Avis personnalisé de l'organisation")
    assert announcement_for(settings, "fr") == "Avis personnalisé de l'organisation"
    assert announcement_for(settings, "en") == "Avis personnalisé de l'organisation"


class FakePlaywrightPage:
    pass


class FakePlaywrightContext:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.page = FakePlaywrightPage()
        self.cdp_sessions: list[object] = []
        self.closed = False

    async def new_page(self) -> FakePlaywrightPage:
        return self.page

    async def new_cdp_session(self, page: object) -> object:
        self.cdp_sessions.append(page)
        return object()

    async def close(self) -> None:
        self.closed = True


class FakePlaywrightBrowser:
    def __init__(self) -> None:
        self.context: FakePlaywrightContext | None = None
        self.closed = False

    async def new_context(self, **kwargs: Any) -> FakePlaywrightContext:
        self.context = FakePlaywrightContext(**kwargs)
        return self.context

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self) -> None:
        self.browser = FakePlaywrightBrowser()
        self.launch_kwargs: dict[str, Any] = {}

    async def launch(self, **kwargs: Any) -> FakePlaywrightBrowser:
        self.launch_kwargs = kwargs
        return self.browser


class FakeDriver:
    def __init__(self) -> None:
        self.chromium = FakeChromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


async def test_playwright_factory_forces_the_locale_and_keeps_audio_unmuted():
    driver = FakeDriver()

    async def starter() -> FakeDriver:
        return driver

    factory = PlaywrightRuntimeFactory(starter=starter)
    runtime = await factory.start(BrowserOptions(locale="fr-FR", headless=False))
    assert driver.chromium.launch_kwargs["ignore_default_args"] == ["--mute-audio"]
    assert "--lang=fr-FR" in driver.chromium.launch_kwargs["args"]
    assert driver.chromium.launch_kwargs["headless"] is False
    context = driver.chromium.browser.context
    assert context is not None
    assert context.kwargs["locale"] == "fr-FR"
    assert await runtime.cdp() is not None
    await runtime.aclose()
    assert context.closed
    assert driver.chromium.browser.closed
    assert driver.stopped
