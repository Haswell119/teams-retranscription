from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

from hansard.domain.errors import CaptureError

PACTL: Final[str] = "pactl"
NULL_SINK_MODULE: Final[str] = "module-null-sink"
REMAP_SOURCE_MODULE: Final[str] = "module-remap-source"


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def message(self) -> str:
        return (self.stderr or self.stdout).strip()


class CommandRunner(Protocol):
    async def run(self, command: Sequence[str], timeout: float | None = None) -> CommandResult: ...


class AsyncCommandRunner:
    async def run(self, command: Sequence[str], timeout: float | None = None) -> CommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            return CommandResult(returncode=127, stderr=f"{command[0]} not found: {error}")
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            return CommandResult(returncode=124, stderr=f"{command[0]} timed out after {timeout}s")
        return CommandResult(
            returncode=process.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )


@dataclass(frozen=True, slots=True)
class PulseSinkPlan:
    sink_name: str = "hansard_sink"
    sink_description: str = "MeetingOut"
    tts_sink_name: str = "hansard_tts"
    virtual_microphone_name: str = "hansard_mic"
    set_defaults: bool = True
    mute_virtual_microphone: bool = True

    @property
    def monitor_source(self) -> str:
        return f"{self.sink_name}.monitor"

    @property
    def tts_monitor_source(self) -> str:
        return f"{self.tts_sink_name}.monitor"


@dataclass(slots=True)
class PulseAudioSink:
    plan: PulseSinkPlan = field(default_factory=PulseSinkPlan)
    runner: CommandRunner = field(default_factory=AsyncCommandRunner)
    binary: str = PACTL
    readiness_timeout_seconds: float = 10.0
    poll_seconds: float = 0.25
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    _owned_modules: list[str] = field(default_factory=list, init=False)
    _started: bool = field(default=False, init=False)

    @property
    def monitor_source(self) -> str:
        return self.plan.monitor_source

    @property
    def owned_modules(self) -> tuple[str, ...]:
        return tuple(self._owned_modules)

    @property
    def started(self) -> bool:
        return self._started

    async def _pactl(self, *arguments: str) -> CommandResult:
        return await self.runner.run([self.binary, *arguments], timeout=15.0)

    async def _require_server(self) -> None:
        result = await self._pactl("info")
        if result.ok:
            return
        if result.returncode == 127:
            raise CaptureError(
                "pactl is not installed; the browser notetaker needs PulseAudio "
                "(the container entrypoint starts pulseaudio before the worker)"
            )
        raise CaptureError(
            "PulseAudio is not reachable; start it (or set PULSE_SERVER) before capturing: "
            f"{result.message[:300]}"
        )

    async def _names(self, kind: str) -> set[str]:
        result = await self._pactl("list", "short", kind)
        if not result.ok:
            raise CaptureError(f"could not list PulseAudio {kind}: {result.message[:300]}")
        names: set[str] = set()
        for line in result.stdout.splitlines():
            columns = line.split("\t")
            if len(columns) >= 2 and columns[1].strip():
                names.add(columns[1].strip())
        return names

    async def _load_module(self, module: str, *arguments: str) -> str | None:
        result = await self._pactl("load-module", module, *arguments)
        if not result.ok:
            raise CaptureError(f"could not load {module}: {result.message[:300]}")
        identifier = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
        if identifier.isdigit():
            self._owned_modules.append(identifier)
            return identifier
        return None

    async def _ensure_null_sink(self, name: str, description: str) -> None:
        if name in await self._names("sinks"):
            return
        await self._load_module(
            NULL_SINK_MODULE,
            f"sink_name={name}",
            f"sink_properties=device.description={description}",
        )

    async def _ensure_virtual_microphone(self) -> None:
        if self.plan.virtual_microphone_name in await self._names("sources"):
            return
        await self._load_module(
            REMAP_SOURCE_MODULE,
            f"master={self.plan.tts_monitor_source}",
            f"source_name={self.plan.virtual_microphone_name}",
        )

    async def _await_source(self, name: str) -> None:
        deadline = self.clock() + self.readiness_timeout_seconds
        while True:
            if name in await self._names("sources"):
                return
            if self.clock() >= deadline:
                raise CaptureError(
                    f"PulseAudio source '{name}' never appeared within "
                    f"{self.readiness_timeout_seconds:g}s; the null sink was not created correctly"
                )
            await self.sleep(self.poll_seconds)

    async def start(self) -> None:
        if self._started:
            return
        await self._require_server()
        await self._ensure_null_sink(self.plan.sink_name, self.plan.sink_description)
        if self.plan.set_defaults:
            await self._pactl("set-default-sink", self.plan.sink_name)
        await self._ensure_null_sink(self.plan.tts_sink_name, "MeetingIn")
        await self._ensure_virtual_microphone()
        if self.plan.set_defaults:
            await self._pactl("set-default-source", self.plan.virtual_microphone_name)
        if self.plan.mute_virtual_microphone:
            await self._pactl("set-source-mute", self.plan.virtual_microphone_name, "1")
        await self._await_source(self.plan.monitor_source)
        self._started = True

    async def stop(self) -> None:
        self._started = False
        modules, self._owned_modules = list(reversed(self._owned_modules)), []
        for identifier in modules:
            await self._pactl("unload-module", identifier)

    async def __aenter__(self) -> PulseAudioSink:
        await self.start()
        return self

    async def __aexit__(self, *exception: object) -> None:
        await self.stop()
