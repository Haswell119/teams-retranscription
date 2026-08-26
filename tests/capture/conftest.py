from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hansard.adapters.capture.audio.pulse import CommandResult
from hansard.adapters.capture.browser.session import BrowserOptions, SessionTiming
from hansard.config import CaptureSettings


class StepClock:
    def __init__(self, step: float = 0.25) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


async def nosleep(_seconds: float) -> None:
    return None


@dataclass
class FakeScreen:
    url: str = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"
    text: str = ""
    present: set[str] = field(default_factory=set)
    hidden: set[str] = field(default_factory=set)
    attributes: dict[str, dict[str, str]] = field(default_factory=dict)
    clicks: list[str] = field(default_factory=list)
    fills: list[tuple[str, str]] = field(default_factory=list)
    presses: list[tuple[str, str]] = field(default_factory=list)
    navigations: list[str] = field(default_factory=list)
    polls: int = 0
    redirect_to: str | None = None
    on_click: Callable[[FakeScreen, str], None] | None = None
    on_poll: Callable[[FakeScreen], None] | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)

    def click(self, selector: str) -> None:
        self.clicks.append(selector)
        if self.on_click is not None:
            self.on_click(self, selector)

    def poll(self) -> None:
        self.polls += 1
        if self.on_poll is not None:
            self.on_poll(self)

    def show(self, *selectors: str) -> None:
        self.present.update(selectors)

    def hide(self, *selectors: str) -> None:
        self.present.difference_update(selectors)


class FakeLocator:
    def __init__(self, screen: FakeScreen, selector: str) -> None:
        self._screen = screen
        self._selectors = [part.strip() for part in selector.split(", ") if part.strip()]

    @property
    def first(self) -> FakeLocator:
        return self

    def _matched(self) -> str | None:
        mounted = self._screen.present | self._screen.hidden
        for candidate in self._selectors:
            if candidate in mounted:
                return candidate
        return None

    def _shown(self) -> str | None:
        for candidate in self._selectors:
            if candidate in self._screen.present:
                return candidate
        return None

    async def count(self) -> int:
        mounted = self._screen.present | self._screen.hidden
        return sum(1 for candidate in self._selectors if candidate in mounted)

    async def is_visible(self, timeout: float | None = None) -> bool:
        return self._shown() is not None

    async def get_attribute(self, name: str, timeout: float | None = None) -> str | None:
        matched = self._matched()
        if matched is None:
            return None
        return self._screen.attributes.get(matched, {}).get(name)

    async def click(self, timeout: float | None = None) -> None:
        matched = self._matched()
        if matched is None:
            raise RuntimeError("nothing to click")
        self._screen.click(matched)

    async def fill(self, value: str, timeout: float | None = None) -> None:
        matched = self._matched()
        if matched is None:
            raise RuntimeError("nothing to fill")
        self._screen.fills.append((matched, value))

    async def press(self, key: str, timeout: float | None = None) -> None:
        matched = self._matched()
        if matched is None:
            raise RuntimeError("nothing to press")
        self._screen.presses.append((matched, key))


class FakePage:
    def __init__(self, screen: FakeScreen) -> None:
        self.screen = screen

    @property
    def url(self) -> str:
        return self.screen.url

    async def goto(self, url: str, timeout: float | None = None) -> None:
        self.screen.navigations.append(url)
        self.screen.url = self.screen.redirect_to or url

    async def inner_text(self, selector: str, timeout: float | None = None) -> str:
        self.screen.poll()
        return self.screen.text

    async def evaluate(self, expression: str) -> Any:
        return self.screen.snapshot

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.screen, selector)


class FakeCdpSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def send(self, method: str, params: Mapping[str, Any]) -> None:
        self.calls.append((method, params))


class FakeContext:
    def __init__(self) -> None:
        self.init_scripts: list[str] = []
        self.bindings: dict[str, Callable[..., Any]] = {}
        self.permissions: list[tuple[tuple[str, ...], str | None]] = []

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    async def expose_binding(self, name: str, callback: Callable[..., Any]) -> None:
        self.bindings[name] = callback

    async def grant_permissions(self, permissions: Sequence[str], origin: str | None = None) -> None:
        self.permissions.append((tuple(permissions), origin))


class FakeRuntime:
    def __init__(self, screen: FakeScreen) -> None:
        self.screen = screen
        self._context = FakeContext()
        self._page = FakePage(screen)
        self.cdp_session = FakeCdpSession()
        self.closed = False

    @property
    def context(self) -> FakeContext:
        return self._context

    @property
    def page(self) -> FakePage:
        return self._page

    async def cdp(self) -> FakeCdpSession:
        return self.cdp_session

    async def aclose(self) -> None:
        self.closed = True

    def emit(self, payload: Mapping[str, Any]) -> None:
        binding = self._context.bindings.get("__hansardEmit")
        if binding is not None:
            binding({"page": "fake"}, payload)


class FakeRuntimeFactory:
    def __init__(self, screens: Sequence[FakeScreen]) -> None:
        self._screens = list(screens)
        self.runtimes: list[FakeRuntime] = []
        self.options: list[BrowserOptions] = []

    async def start(self, options: BrowserOptions) -> FakeRuntime:
        self.options.append(options)
        screen = self._screens[min(len(self.runtimes), len(self._screens) - 1)]
        runtime = FakeRuntime(screen)
        self.runtimes.append(runtime)
        return runtime

    @property
    def latest(self) -> FakeRuntime:
        return self.runtimes[-1]


class ScriptedRunner:
    def __init__(self, responses: Mapping[str, CommandResult] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, ...]] = []
        self.default = CommandResult(returncode=0)

    def key(self, command: Sequence[str]) -> str:
        return " ".join(command[1:3]) if len(command) > 2 else " ".join(command[1:])

    async def run(self, command: Sequence[str], timeout: float | None = None) -> CommandResult:
        self.calls.append(tuple(command))
        for prefix, result in self.responses.items():
            if " ".join(command).startswith(prefix) or " ".join(command[1:]).startswith(prefix):
                return result
        return self.default


def fast_timing() -> SessionTiming:
    return SessionTiming(
        poll_seconds=0.01,
        url_stability_seconds=0.02,
        element_timeout_ms=1.0,
        navigation_timeout_ms=1.0,
        prejoin_settle_seconds=0.0,
    )


def capture_settings(**overrides: Any) -> CaptureSettings:
    defaults: dict[str, Any] = {
        "display_name": "Hansard Notetaker",
        "join_timeout_seconds": 5,
        "lobby_timeout_seconds": 5,
        "silence_timeout_seconds": 600,
        "alone_timeout_seconds": 120,
        "max_duration_seconds": 3600,
        "roster_poll_seconds": 0.01,
    }
    defaults.update(overrides)
    return CaptureSettings(**defaults)


class FakePactl:
    def __init__(self, sinks=(), sources=(), server_ok=True, installed=True, monitor_ready=True):
        self.sinks = set(sinks)
        self.sources = set(sources)
        self.server_ok = server_ok
        self.installed = installed
        self.monitor_ready = monitor_ready
        self.calls: list[tuple[str, ...]] = []
        self.unloaded: list[str] = []
        self._next_module = 100

    def loaded_modules(self) -> list[str]:
        return [call[2] for call in self.calls if call[1] == "load-module"]

    @staticmethod
    def _value(arguments: Sequence[str], key: str) -> str | None:
        for argument in arguments:
            if argument.startswith(f"{key}="):
                return argument.split("=", 1)[1]
        return None

    def _table(self, names: set[str]) -> str:
        return "".join(
            f"{index}\t{name}\tmodule-null-sink\ts16le 1ch 16000Hz\tIDLE\n"
            for index, name in enumerate(sorted(names), start=1)
        )

    async def run(self, command: Sequence[str], timeout: float | None = None) -> CommandResult:
        self.calls.append(tuple(command))
        if not self.installed:
            return CommandResult(returncode=127, stderr="pactl: command not found")
        arguments = list(command[1:])
        verb = arguments[0]
        if verb == "info":
            if not self.server_ok:
                return CommandResult(1, stderr="Connection refused")
            return CommandResult(0, stdout="Server Name: pulseaudio\n")
        if verb == "list":
            names = self.sinks if arguments[2] == "sinks" else self.sources
            return CommandResult(0, stdout=self._table(names))
        if verb == "load-module":
            module = arguments[1]
            if module == "module-null-sink":
                name = self._value(arguments, "sink_name") or ""
                self.sinks.add(name)
                if self.monitor_ready:
                    self.sources.add(f"{name}.monitor")
            if module == "module-remap-source":
                self.sources.add(self._value(arguments, "source_name") or "")
            identifier = self._next_module
            self._next_module += 1
            return CommandResult(0, stdout=f"{identifier}\n")
        if verb == "unload-module":
            self.unloaded.append(arguments[1])
        return CommandResult(0)


class FakeProcess:
    def __init__(self, returncode: int | None = None) -> None:
        self._returncode = returncode
        self.terminated = False
        self.killed = False

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def set_returncode(self, value: int) -> None:
        self._returncode = value

    async def wait(self) -> int:
        if self._returncode is None:
            self._returncode = 0
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = 0

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9


class FakeLauncher:
    def __init__(self, process: FakeProcess | None = None) -> None:
        self.process = process or FakeProcess()
        self.commands: list[tuple[str, ...]] = []

    async def spawn(self, command: Sequence[str]) -> FakeProcess:
        self.commands.append(tuple(command))
        return self.process


class ProbeRunner:
    def __init__(self, stderr: str = "") -> None:
        self.stderr = stderr
        self.commands: list[tuple[str, ...]] = []

    async def run(self, command: Sequence[str], timeout: float | None = None) -> CommandResult:
        self.commands.append(tuple(command))
        return CommandResult(returncode=0, stderr=self.stderr)


VOLUMEDETECT_LOUD = (
    "[Parsed_volumedetect_0 @ 0x1] mean_volume: -26.4 dB\n[Parsed_volumedetect_0 @ 0x1] max_volume: -3.1 dB\n"
)

VOLUMEDETECT_SILENT = (
    "[Parsed_volumedetect_0 @ 0x1] mean_volume: -91.0 dB\n"
    "[Parsed_volumedetect_0 @ 0x1] max_volume: -91.0 dB\n"
)
