from __future__ import annotations

import asyncio
import math
import re
import sys
import time
from array import array
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


FULL_SCALE: Final[float] = 32_768.0
SILENT_DBFS: Final[float] = -120.0


@dataclass(frozen=True, slots=True)
class RecorderSettings:
    sample_rate: int = 16_000
    channels: int = 1
    stall_grace_seconds: float = 20.0
    silence_floor_dbfs: float = -60.0
    stop_timeout_seconds: float = 10.0
    minimum_bytes: int = WAV_HEADER_BYTES + 1_000
    max_restarts: int = 3

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * 2


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


@dataclass(frozen=True, slots=True)
class LevelReading:
    peak_dbfs: float | None
    mean_dbfs: float | None
    seconds: float
    floor_dbfs: float

    @property
    def measured(self) -> bool:
        return self.peak_dbfs is not None

    @property
    def is_silent(self) -> bool:
        if self.peak_dbfs is None:
            return False
        return self.peak_dbfs <= self.floor_dbfs

    @property
    def is_audible(self) -> bool:
        return self.measured and not self.is_silent


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_tail(path: Path, byte_count: int) -> bytes:
    size = _file_size(path)
    if size <= WAV_HEADER_BYTES:
        return b""
    start = max(WAV_HEADER_BYTES, size - byte_count)
    start -= (start - WAV_HEADER_BYTES) % 2
    try:
        with path.open("rb") as handle:
            handle.seek(start)
            payload = handle.read(size - start)
    except OSError:
        return b""
    return payload[: len(payload) - len(payload) % 2]


def _dbfs(amplitude: float) -> float:
    if amplitude <= 0.0:
        return SILENT_DBFS
    return max(SILENT_DBFS, 20.0 * math.log10(amplitude / FULL_SCALE))


def measure_pcm(payload: bytes, sample_rate: int, channels: int, floor_dbfs: float) -> LevelReading:
    if len(payload) < 2:
        return LevelReading(peak_dbfs=None, mean_dbfs=None, seconds=0.0, floor_dbfs=floor_dbfs)
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max(max(samples), -min(samples))
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    frames = len(samples) / max(channels, 1)
    return LevelReading(
        peak_dbfs=_dbfs(float(peak)),
        mean_dbfs=_dbfs(rms),
        seconds=frames / float(sample_rate or 1),
        floor_dbfs=floor_dbfs,
    )


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
    read_tail: Callable[[Path, int], bytes] = _read_tail
    _process: ProcessHandle | None = field(default=None, init=False)
    _output: Path | None = field(default=None, init=False)
    _destination: Path | None = field(default=None, init=False)
    _segments: list[Path] = field(default_factory=list, init=False)
    _restarts: int = field(default=0, init=False)
    _join_error: str | None = field(default=None, init=False)
    _last_size: int = field(default=0, init=False)
    _last_growth_at: float = field(default=0.0, init=False)
    _started_at: float = field(default=0.0, init=False)

    @property
    def output_path(self) -> Path | None:
        return self._destination

    @property
    def segments(self) -> tuple[Path, ...]:
        return tuple(self._segments)

    @property
    def restarts(self) -> int:
        return self._restarts

    @property
    def join_error(self) -> str | None:
        return self._join_error

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

    def concat_command(self, manifest: Path, output: Path) -> tuple[str, ...]:
        return (
            self.binary,
            "-y",
            "-loglevel",
            "warning",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-c",
            "copy",
            str(output),
        )

    async def start(self, output: Path) -> None:
        if self.running:
            raise CaptureError("the ffmpeg recorder is already running")
        output.parent.mkdir(parents=True, exist_ok=True)
        self._destination = output
        self._segments = [output]
        self._restarts = 0
        self._join_error = None
        await self._spawn(output)

    async def _spawn(self, segment: Path) -> None:
        self._process = await self.launcher.spawn(self.command(segment))
        self._output = segment
        self._started_at = self.clock()
        self._last_growth_at = self._started_at
        self._last_size = 0

    def _next_segment(self) -> Path:
        destination = self._destination
        if destination is None:
            raise CaptureError("the ffmpeg recorder was never started")
        return destination.with_name(f"{destination.stem}.part{len(self._segments)}{destination.suffix}")

    async def restart(self) -> bool:
        if self._destination is None:
            raise CaptureError("the ffmpeg recorder was never started")
        if self._restarts >= self.settings.max_restarts:
            return False
        await self._halt()
        segment = self._next_segment()
        self._segments.append(segment)
        self._restarts += 1
        await self._spawn(segment)
        return True

    async def _halt(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.settings.stop_timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()

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

    async def tail_level(self, seconds: float) -> LevelReading:
        segment = self._output
        floor = self.settings.silence_floor_dbfs
        if segment is None:
            return LevelReading(peak_dbfs=None, mean_dbfs=None, seconds=0.0, floor_dbfs=floor)
        window = max(seconds, 0.0) * self.settings.bytes_per_second
        payload = self.read_tail(segment, int(window))
        return measure_pcm(payload, self.settings.sample_rate, self.settings.channels, floor)

    async def stop(self) -> Path:
        destination = self._destination
        if destination is None or self._output is None:
            raise CaptureError("the ffmpeg recorder was never started")
        await self._halt()
        output = await self._join_segments(destination)
        if self.size_of(output) < self.settings.minimum_bytes:
            raise CaptureError(
                f"ffmpeg produced no usable audio at {output} "
                f"({self.size_of(output)} bytes); {SILENCE_DIAGNOSTIC}"
            )
        return output

    async def _join_segments(self, destination: Path) -> Path:
        parts = [part for part in self._segments if self.size_of(part) > WAV_HEADER_BYTES]
        if len(parts) < 2:
            return destination
        manifest = destination.with_name(f"{destination.stem}.segments.txt")
        joined = destination.with_name(f"{destination.stem}.joined{destination.suffix}")
        manifest.write_text("".join(f"file '{part.resolve()}'\n" for part in parts), encoding="utf-8")
        result = await self.runner.run(self.concat_command(manifest, joined), timeout=600.0)
        manifest.unlink(missing_ok=True)
        if not result.ok or not joined.exists() or self.size_of(joined) < self.settings.minimum_bytes:
            joined.unlink(missing_ok=True)
            self._join_error = (
                f"could not stitch {len(parts)} capture segments together "
                f"({result.message[:200] or 'the concatenated file was empty'}); "
                f"keeping only the first {self.size_of(destination)} bytes"
            )
            return destination
        joined.replace(destination)
        for part in parts[1:]:
            part.unlink(missing_ok=True)
        return destination

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
