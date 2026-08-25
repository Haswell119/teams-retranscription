from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from hansard.adapters.capture.audio.pulse import AsyncCommandRunner, CommandRunner
from hansard.domain.errors import CaptureError

FFMPEG: Final[str] = "ffmpeg"
WAV_HEADER_BYTES: Final[int] = 44
VOLUME_PATTERN: Final[re.Pattern[str]] = re.compile(r"(mean_volume|max_volume):\s*(-?\d+(?:\.\d+)?)\s*dB")

SILENCE_DIAGNOSTIC: Final[str] = (
    "the capture contains no audible audio. Usual causes, in order of likelihood: "
    "Playwright launched Chromium with its default --mute-audio (pass ignore_default_args); "
    "the browser is not routed to the PulseAudio null sink (check set-default-sink); "
    "the meeting was never joined or nobody spoke; "
    "the tab was never granted audio permission for the meeting origin"
)


class ProcessHandle(Protocol):
    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class ProcessLauncher(Protocol):
    async def spawn(self, command: Sequence[str]) -> ProcessHandle: ...


class AsyncProcessLauncher:
    async def spawn(self, command: Sequence[str]) -> ProcessHandle:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise CaptureError(f"{command[0]} is not installed: {error}") from error
        return process


@dataclass(frozen=True, slots=True)
class RecorderSettings:
    sample_rate: int = 16_000
    channels: int = 1
    stall_grace_seconds: float = 20.0
    silence_floor_dbfs: float = -60.0
    stop_timeout_seconds: float = 10.0
    minimum_bytes: int = WAV_HEADER_BYTES + 1_000


@dataclass(frozen=True, slots=True)
class SilenceReport:
    mean_dbfs: float | None
    max_dbfs: float | None
    floor_dbfs: float

    @property
    def measured(self) -> bool:
        return self.max_dbfs is not None

    @property
    def is_silent(self) -> bool:
        if self.max_dbfs is None:
            return False
        return self.max_dbfs <= self.floor_dbfs


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


@dataclass(slots=True)
class FfmpegRecorder:
    source: str
    settings: RecorderSettings = field(default_factory=RecorderSettings)
    launcher: ProcessLauncher = field(default_factory=AsyncProcessLauncher)
    runner: CommandRunner = field(default_factory=AsyncCommandRunner)
    binary: str = FFMPEG
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    size_of: Callable[[Path], int] = _file_size
    _process: ProcessHandle | None = field(default=None, init=False)
    _output: Path | None = field(default=None, init=False)
    _last_size: int = field(default=0, init=False)
    _last_growth_at: float = field(default=0.0, init=False)
    _started_at: float = field(default=0.0, init=False)

    @property
    def output_path(self) -> Path | None:
        return self._output

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def command(self, output: Path) -> tuple[str, ...]:
        return (
            self.binary,
            "-y",
            "-loglevel",
            "warning",
            "-f",
            "pulse",
            "-i",
            self.source,
            "-ac",
            str(self.settings.channels),
            "-ar",
            str(self.settings.sample_rate),
            "-af",
            "aresample=async=1:first_pts=0",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output),
        )

    def probe_command(self, target: Path) -> tuple[str, ...]:
        return (
            self.binary,
            "-hide_banner",
            "-nostats",
            "-i",
            str(target),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        )

    async def start(self, output: Path) -> None:
        if self.running:
            raise CaptureError("the ffmpeg recorder is already running")
        output.parent.mkdir(parents=True, exist_ok=True)
        self._process = await self.launcher.spawn(self.command(output))
        self._output = output
        self._started_at = self.clock()
        self._last_growth_at = self._started_at
        self._last_size = 0

    async def ensure_progressing(self) -> None:
        process = self._process
        output = self._output
        if process is None or output is None:
            raise CaptureError("the ffmpeg recorder was never started")
        if process.returncode is not None:
            raise CaptureError(
                f"ffmpeg exited early with code {process.returncode}; "
                f"the PulseAudio source '{self.source}' is probably gone"
            )
        size = self.size_of(output)
        now = self.clock()
        if size > self._last_size:
            self._last_size = size
            self._last_growth_at = now
            return
        if now - self._last_growth_at > self.settings.stall_grace_seconds:
            raise CaptureError(
                f"ffmpeg stopped writing to {output} for "
                f"{self.settings.stall_grace_seconds:g}s; the PulseAudio monitor "
                f"'{self.source}' produced no data"
            )

    async def stop(self) -> Path:
        process, self._process = self._process, None
        output = self._output
        if process is None or output is None:
            raise CaptureError("the ffmpeg recorder was never started")
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=self.settings.stop_timeout_seconds)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self.size_of(output) < self.settings.minimum_bytes:
            raise CaptureError(
                f"ffmpeg produced no usable audio at {output} "
                f"({self.size_of(output)} bytes); {SILENCE_DIAGNOSTIC}"
            )
        return output

    async def silence_report(self, target: Path) -> SilenceReport:
        result = await self.runner.run(self.probe_command(target), timeout=120.0)
        readings = {name: float(value) for name, value in VOLUME_PATTERN.findall(result.stderr)}
        return SilenceReport(
            mean_dbfs=readings.get("mean_volume"),
            max_dbfs=readings.get("max_volume"),
            floor_dbfs=self.settings.silence_floor_dbfs,
        )

    async def assert_not_silent(self, target: Path) -> SilenceReport:
        report = await self.silence_report(target)
        if report.is_silent:
            raise CaptureError(
                f"{SILENCE_DIAGNOSTIC} (peak {report.max_dbfs:g} dBFS, mean {report.mean_dbfs} dBFS, "
                f"floor {report.floor_dbfs:g} dBFS)"
            )
        return report
