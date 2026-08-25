from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from hansard.adapters.capture.browser import selectors
from hansard.adapters.capture.browser.events import (
    CallEndEvent,
    CaptureEvent,
    InstrumentationReadyEvent,
    parse_event,
)
from hansard.config import CaptureSettings
from hansard.domain.errors import CaptureError, MeetingAdmissionTimeout, MeetingJoinRefused

EMIT_BINDING: Final[str] = "__hansardEmit"
SNAPSHOT_EXPRESSION: Final[str] = (
    "() => (typeof window.__hansardSnapshot === 'function' ? window.__hansardSnapshot() : null)"
)
INSTRUMENTATION_PATH: Final[Path] = Path(__file__).with_name("instrumentation.js")

LAUNCHER_PARAMETERS: Final[tuple[tuple[str, str], ...]] = (
    ("msLaunch", "false"),
    ("type", "meetup-join"),
    ("directDl", "true"),
    ("enableMobilePage", "true"),
    ("suppressPrompt", "true"),
)

DIRECT_PREJOIN_PREFIXES: Final[tuple[str, ...]] = ("/meet/", "/v2/", "/dl/launcher/launcher.html")

CHROMIUM_ARGUMENTS: Final[tuple[str, ...]] = (
    "--autoplay-policy=no-user-gesture-required",
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--enable-audio-service-out-of-process",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
)

IGNORED_DEFAULT_ARGUMENTS: Final[tuple[str, ...]] = ("--mute-audio",)

CDP_PERMISSIONS: Final[tuple[str, ...]] = (
    "geolocation",
    "audioCapture",
    "displayCapture",
    "videoCapture",
)

CONTEXT_PERMISSIONS: Final[tuple[str, ...]] = ("microphone", "camera")

UI_LOCALE_VARIABLE: Final[str] = "HANSARD_CAPTURE__UI_LOCALE"
FALLBACK_UI_LOCALE: Final[str] = "en-US"
DEFAULT_UI_LOCALE: Final[str] = os.environ.get(UI_LOCALE_VARIABLE, FALLBACK_UI_LOCALE)


class MeetingState(StrEnum):
    LAUNCHER = "launcher"
    PREJOIN = "prejoin"
    LOBBY = "lobby"
    IN_MEETING = "in_meeting"
    DENIED = "denied"
    REMOVED = "removed"
    ENDED = "ended"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


TEXT_STATES: Final[tuple[tuple[tuple[str, ...], MeetingState], ...]] = (
    (selectors.DENIED_TEXTS, MeetingState.DENIED),
    (selectors.REMOVED_TEXTS, MeetingState.REMOVED),
    (selectors.BLOCKED_TEXTS, MeetingState.BLOCKED),
    (selectors.MEETING_ENDED_TEXTS, MeetingState.ENDED),
    (selectors.LOBBY_TEXTS, MeetingState.LOBBY),
)


class JoinPhase(StrEnum):
    IDLE = "idle"
    LAUNCHING = "launching"
    NAVIGATING = "navigating"
    LAUNCHER_BYPASS = "launcher_bypass"
    PREJOIN = "prejoin"
    ADMISSION = "admission"
    IN_MEETING = "in_meeting"
    LEAVING = "leaving"
    CLOSED = "closed"


class LocatorLike(Protocol):
    @property
    def first(self) -> LocatorLike: ...

    async def count(self) -> int: ...

    async def is_visible(self, timeout: float | None = None) -> bool: ...

    async def get_attribute(self, name: str, timeout: float | None = None) -> str | None: ...

    async def click(self, timeout: float | None = None) -> None: ...

    async def fill(self, value: str, timeout: float | None = None) -> None: ...

    async def press(self, key: str, timeout: float | None = None) -> None: ...


class PageLike(Protocol):
    @property
    def url(self) -> str: ...

    async def goto(self, url: str, timeout: float | None = None) -> Any: ...

    async def inner_text(self, selector: str, timeout: float | None = None) -> str: ...

    async def evaluate(self, expression: str) -> Any: ...

    def locator(self, selector: str) -> LocatorLike: ...


class ContextLike(Protocol):
    async def add_init_script(self, script: str) -> None: ...

    async def expose_binding(self, name: str, callback: Callable[..., Any]) -> None: ...

    async def grant_permissions(self, permissions: Sequence[str], origin: str | None = None) -> None: ...


class CdpSessionLike(Protocol):
    async def send(self, method: str, params: Mapping[str, Any]) -> Any: ...


class BrowserRuntime(Protocol):
    @property
    def context(self) -> ContextLike: ...

    @property
    def page(self) -> PageLike: ...

    async def cdp(self) -> CdpSessionLike | None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BrowserOptions:
    headless: bool = False
    executable_path: Path | None = None
    window_width: int = 1280
    window_height: int = 720
    locale: str = DEFAULT_UI_LOCALE
    extra_arguments: tuple[str, ...] = ()

    def chromium_arguments(self) -> tuple[str, ...]:
        window = f"--window-size={self.window_width},{self.window_height}"
        return (*CHROMIUM_ARGUMENTS, window, f"--lang={self.locale}", *self.extra_arguments)


class BrowserRuntimeFactory(Protocol):
    async def start(self, options: BrowserOptions) -> BrowserRuntime: ...


@dataclass(frozen=True, slots=True)
class JoinOutcome:
    state: MeetingState
    url: str
    attempts: int
    admitted_epoch_ms: int
    waited_in_lobby: bool = False


@dataclass(slots=True)
class SessionTiming:
    poll_seconds: float = 0.5
    url_stability_seconds: float = 10.0
    element_timeout_ms: float = 5_000.0
    navigation_timeout_ms: float = 60_000.0
    prejoin_settle_seconds: float = 1.0


class _RestartJoinError(Exception):
    pass


@dataclass(slots=True)
class _Deadline:
    clock: Callable[[], float]
    seconds: float
    started: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.started = self.clock()

    @property
    def remaining(self) -> float:
        return self.seconds - (self.clock() - self.started)

    @property
    def expired(self) -> bool:
        return self.remaining <= 0.0


def is_direct_prejoin_url(url: str) -> bool:
    parsed = urlsplit(url)
    return any(parsed.path.startswith(prefix) for prefix in ("/meet/",)) and "meetup-join" not in url


def rewrite_join_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise CaptureError(
            f"unsupported meeting link scheme '{parsed.scheme or 'none'}'; "
            "provide the https Teams meeting link"
        )
    if not parsed.netloc:
        raise CaptureError(f"meeting link has no host: {url}")
    if is_direct_prejoin_url(url):
        return url
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(dict(LAUNCHER_PARAMETERS))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def load_instrumentation(path: Path | None = None) -> str:
    source = path or INSTRUMENTATION_PATH
    return source.read_text(encoding="utf-8")


class TeamsBrowserSession:
    def __init__(
        self,
        *,
        settings: CaptureSettings,
        factory: BrowserRuntimeFactory,
        event_sink: Callable[[CaptureEvent], None] | None = None,
        options: BrowserOptions | None = None,
        timing: SessionTiming | None = None,
        instrumentation: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        epoch_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_join_attempts: int = 2,
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._event_sink = event_sink
        self._options = options or BrowserOptions(headless=settings.headless)
        self._timing = timing or SessionTiming()
        self._instrumentation = instrumentation if instrumentation is not None else load_instrumentation()
        self._clock = clock
        self._epoch_ms = epoch_ms
        self._sleep = sleep
        self._max_join_attempts = max(1, max_join_attempts)
        self._runtime: BrowserRuntime | None = None
        self._phase = JoinPhase.IDLE
        self._call_end: CallEndEvent | None = None
        self._instrumentation_ready = False

    @property
    def phase(self) -> JoinPhase:
        return self._phase

    @property
    def call_end(self) -> CallEndEvent | None:
        return self._call_end

    @property
    def instrumentation_ready(self) -> bool:
        return self._instrumentation_ready

    @property
    def page(self) -> PageLike:
        if self._runtime is None:
            raise CaptureError("browser session is not started")
        return self._runtime.page

    async def join(self, join_url: str) -> JoinOutcome:
        attempts = 0
        while True:
            attempts += 1
            try:
                return await self._attempt_join(join_url, attempts)
            except _RestartJoinError:
                await self.aclose()
                if attempts >= self._max_join_attempts:
                    raise CaptureError(
                        "Teams kept redirecting to the light experience; "
                        f"gave up after {attempts} join attempts"
                    ) from None

    async def _attempt_join(self, join_url: str, attempt: int) -> JoinOutcome:
        deadline = _Deadline(self._clock, float(self._settings.join_timeout_seconds))
        await self._start_runtime(join_url)
        self._phase = JoinPhase.NAVIGATING
        target = rewrite_join_url(join_url)
        await self._navigate(target, deadline)
        await self._wait_url_stable(deadline)
        settled = rewrite_join_url(self.page.url)
        if settled != self.page.url:
            await self._navigate(settled, deadline)
            await self._wait_url_stable(deadline)
        self._phase = JoinPhase.LAUNCHER_BYPASS
        await self._bypass_launcher(deadline)
        self._phase = JoinPhase.PREJOIN
        await self._complete_prejoin(deadline)
        self._phase = JoinPhase.ADMISSION
        outcome = await self._wait_for_admission(attempt)
        self._phase = JoinPhase.IN_MEETING
        return outcome

    async def _start_runtime(self, join_url: str) -> None:
        if self._runtime is not None:
            return
        self._phase = JoinPhase.LAUNCHING
        runtime = await self._factory.start(self._options)
        self._runtime = runtime
        await runtime.context.expose_binding(EMIT_BINDING, self._handle_binding)
        await runtime.context.add_init_script(self._instrumentation)
        await self._grant_permissions(origin_of(join_url))

    async def _grant_permissions(self, origin: str) -> None:
        runtime = self._runtime
        if runtime is None:
            return
        try:
            await runtime.context.grant_permissions(list(CONTEXT_PERMISSIONS), origin=origin)
        except Exception as error:
            raise CaptureError(
                f"could not grant microphone/camera permission for {origin}: {error}"
            ) from error
        session = await runtime.cdp()
        if session is None:
            return
        await session.send(
            "Browser.grantPermissions",
            {"origin": origin, "permissions": list(CDP_PERMISSIONS)},
        )

    def _handle_binding(self, _source: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            return
        event = parse_event(payload)
        if event is None:
            return
        if isinstance(event, InstrumentationReadyEvent):
            self._instrumentation_ready = True
        if isinstance(event, CallEndEvent):
            self._call_end = event
        if self._event_sink is not None:
            self._event_sink(event)

    async def _navigate(self, url: str, deadline: _Deadline) -> None:
        if deadline.expired:
            raise MeetingAdmissionTimeout(f"join timed out before navigating to {url}")
        try:
            budget = min(self._timing.navigation_timeout_ms, deadline.remaining * 1000)
            await self.page.goto(url, timeout=budget)
        except Exception as error:
            raise CaptureError(f"could not open the meeting link: {error}") from error

    async def _wait_url_stable(self, deadline: _Deadline) -> None:
        stable_for = 0.0
        previous = self.page.url
        while stable_for < self._timing.url_stability_seconds:
            if selectors.LIGHT_EXPERIENCE_MARKER in self.page.url:
                raise _RestartJoinError
            if deadline.expired:
                raise MeetingAdmissionTimeout("timed out waiting for the Teams URL to settle")
            await self._sleep(self._timing.poll_seconds)
            current = self.page.url
            stable_for = stable_for + self._timing.poll_seconds if current == previous else 0.0
            previous = current

    def _locator(self, selector_group: Sequence[str]) -> LocatorLike:
        return self.page.locator(", ".join(selector_group))

    async def _present(self, selector_group: Sequence[str]) -> LocatorLike | None:
        locator = self._locator(selector_group)
        try:
            if await locator.count() > 0:
                return locator.first
        except Exception:
            return None
        return None

    async def _click(self, selector_group: Sequence[str], timeout_ms: float | None = None) -> bool:
        locator = await self._present(selector_group)
        if locator is None:
            return False
        try:
            await locator.click(timeout=timeout_ms or self._timing.element_timeout_ms)
        except Exception:
            return False
        return True

    async def _bypass_launcher(self, deadline: _Deadline) -> None:
        while not deadline.expired:
            if await self._present(selectors.PREJOIN_JOIN_BUTTON) is not None:
                return
            if await self._click(selectors.JOIN_ON_WEB):
                await self._sleep(self._timing.prejoin_settle_seconds)
                return
            state = await self.detect_state()
            if state in {MeetingState.PREJOIN, MeetingState.LOBBY, MeetingState.IN_MEETING}:
                return
            self._raise_for_terminal_state(state)
            await self._sleep(self._timing.poll_seconds)
        raise MeetingAdmissionTimeout("timed out waiting for the Teams launcher or pre-join screen")

    async def _fill_display_name(self) -> None:
        locator = await self._present(selectors.PREJOIN_DISPLAY_NAME)
        if locator is None:
            return
        try:
            await locator.fill(self._settings.display_name, timeout=self._timing.element_timeout_ms)
        except Exception:
            return

    async def _disable_device(self, selector_group: Sequence[str]) -> None:
        locator = await self._present(selector_group)
        if locator is None:
            return
        try:
            checked = await locator.get_attribute("aria-checked")
            if checked == "true":
                await locator.click(timeout=self._timing.element_timeout_ms)
        except Exception:
            return

    async def _complete_prejoin(self, deadline: _Deadline) -> None:
        while not deadline.expired:
            state = await self.detect_state()
            if state in {MeetingState.IN_MEETING, MeetingState.LOBBY}:
                return
            self._raise_for_terminal_state(state)
            if await self._present(selectors.PREJOIN_JOIN_BUTTON) is None:
                await self._sleep(self._timing.poll_seconds)
                continue
            await self._fill_display_name()
            await self._disable_device(selectors.TOGGLE_MICROPHONE)
            await self._disable_device(selectors.TOGGLE_CAMERA)
            await self._click(selectors.PREJOIN_JOIN_BUTTON)
            await self._sleep(self._timing.prejoin_settle_seconds)
            if await self._click(selectors.CONTINUE_WITHOUT_MEDIA):
                await self._sleep(self._timing.prejoin_settle_seconds)
                await self._click(selectors.PREJOIN_JOIN_BUTTON)
                await self._sleep(self._timing.prejoin_settle_seconds)
            if await self._present(selectors.PREJOIN_JOIN_BUTTON) is None:
                return
        raise MeetingAdmissionTimeout("timed out on the Teams pre-join screen")

    async def _wait_for_admission(self, attempt: int) -> JoinOutcome:
        deadline = _Deadline(self._clock, float(self._settings.lobby_timeout_seconds))
        waited = False
        while True:
            self._raise_for_call_end()
            state = await self.detect_state()
            if state is MeetingState.IN_MEETING:
                return JoinOutcome(
                    state=state,
                    url=self.page.url,
                    attempts=attempt,
                    admitted_epoch_ms=self._epoch_ms(),
                    waited_in_lobby=waited,
                )
            self._raise_for_terminal_state(state)
            if state is MeetingState.LOBBY:
                waited = True
            if deadline.expired:
                raise MeetingAdmissionTimeout(
                    "nobody admitted the notetaker from the lobby within "
                    f"{self._settings.lobby_timeout_seconds}s; "
                    "an organiser must admit it or the tenant must allow bot access"
                )
            await self._sleep(self._timing.poll_seconds)

    def _raise_for_call_end(self) -> None:
        event = self._call_end
        if event is None:
            return
        if event.is_refusal:
            raise MeetingJoinRefused(f"Teams refused the join: {event.explanation}")
        if event.is_termination:
            raise CaptureError(f"the call ended before the notetaker was admitted: {event.explanation}")

    def _raise_for_terminal_state(self, state: MeetingState) -> None:
        if state is MeetingState.DENIED:
            raise MeetingJoinRefused("a meeting participant denied the notetaker's request to join")
        if state is MeetingState.BLOCKED:
            raise MeetingJoinRefused("tenant policy blocked the notetaker from joining this meeting")
        if state is MeetingState.REMOVED:
            raise CaptureError("the notetaker was removed from the meeting")
        if state is MeetingState.ENDED:
            raise CaptureError("the meeting ended before the notetaker was admitted")

    async def _body_text(self) -> str:
        try:
            return await self.page.inner_text("body", timeout=self._timing.element_timeout_ms)
        except Exception:
            return ""

    async def _hangup_visible(self) -> bool:
        locator = await self._present(selectors.HANGUP_BUTTON)
        if locator is None:
            return False
        try:
            disabled = await locator.get_attribute("aria-disabled")
        except Exception:
            disabled = None
        return disabled != "true"

    async def detect_state(self) -> MeetingState:
        if await self._hangup_visible():
            return MeetingState.IN_MEETING
        text = await self._body_text()
        for texts, state in TEXT_STATES:
            if selectors.matches_any(text, texts) is not None:
                return state
        if await self._present(selectors.PREJOIN_JOIN_BUTTON) is not None:
            return MeetingState.PREJOIN
        if await self._present(selectors.JOIN_ON_WEB) is not None:
            return MeetingState.LAUNCHER
        return MeetingState.UNKNOWN

    async def announce(self, message: str) -> bool:
        if not message.strip():
            return False
        box = await self._present(selectors.CHAT_MESSAGE_BOX)
        if box is None:
            await self._click(selectors.CHAT_PANEL_TOGGLE)
            await self._sleep(self._timing.prejoin_settle_seconds)
            box = await self._present(selectors.CHAT_MESSAGE_BOX)
        if box is None:
            return False
        try:
            await box.fill(message, timeout=self._timing.element_timeout_ms)
            await box.press("Enter", timeout=self._timing.element_timeout_ms)
        except Exception:
            return False
        return True

    async def instrumentation_snapshot(self) -> Mapping[str, Any] | None:
        if self._runtime is None:
            return None
        try:
            result = await self.page.evaluate(SNAPSHOT_EXPRESSION)
        except Exception:
            return None
        return result if isinstance(result, Mapping) else None

    async def leave(self) -> None:
        if self._runtime is None:
            return
        self._phase = JoinPhase.LEAVING
        await self._click(selectors.HANGUP_BUTTON)
        await self._sleep(self._timing.prejoin_settle_seconds)

    async def aclose(self) -> None:
        runtime, self._runtime = self._runtime, None
        self._phase = JoinPhase.CLOSED
        if runtime is None:
            return
        try:
            await runtime.aclose()
        except Exception:
            return


class PlaywrightRuntime:
    def __init__(self, driver: Any, browser: Any, context: Any, page: Any) -> None:
        self._driver = driver
        self._browser = browser
        self._context = context
        self._page = page

    @property
    def context(self) -> ContextLike:
        return cast(ContextLike, self._context)

    @property
    def page(self) -> PageLike:
        return cast(PageLike, self._page)

    async def cdp(self) -> CdpSessionLike | None:
        try:
            session = await self._context.new_cdp_session(self._page)
        except Exception:
            return None
        return cast(CdpSessionLike, session)

    async def aclose(self) -> None:
        for closer in (self._context, self._browser, self._driver):
            close = getattr(closer, "close", None) or getattr(closer, "stop", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                continue


class PlaywrightRuntimeFactory:
    def __init__(self, starter: Callable[[], Any] | None = None) -> None:
        self._starter = starter

    async def start(self, options: BrowserOptions) -> BrowserRuntime:
        driver = await self._driver()
        browser = await driver.chromium.launch(
            headless=options.headless,
            args=list(options.chromium_arguments()),
            ignore_default_args=list(IGNORED_DEFAULT_ARGUMENTS),
            executable_path=str(options.executable_path) if options.executable_path else None,
        )
        context = await browser.new_context(
            viewport={"width": options.window_width, "height": options.window_height},
            locale=options.locale,
            permissions=[],
        )
        page = await context.new_page()
        return PlaywrightRuntime(driver, browser, context, page)

    async def _driver(self) -> Any:
        if self._starter is not None:
            return await self._starter()
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise CaptureError(
                "playwright is not installed; install the 'capture' extra to run the browser notetaker"
            ) from error
        return await async_playwright().start()
