from __future__ import annotations

import resource
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

KILOBYTES_PER_MEGABYTE = 1024.0
_STATUS_PATH = Path("/proc/self/status")
_HIGH_WATER_MARK = "VmHWM:"


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    wall_seconds: float
    cpu_seconds: float
    peak_rss_mb: float
    vram_mb: float | None = None


@dataclass(frozen=True, slots=True)
class RealTimeFactor:
    processing_seconds: float
    audio_seconds: float

    @property
    def value(self) -> float:
        return self.processing_seconds / self.audio_seconds if self.audio_seconds > 0.0 else 0.0

    @property
    def speedup(self) -> float:
        return self.audio_seconds / self.processing_seconds if self.processing_seconds > 0.0 else 0.0


class ResourceProbe:
    def __init__(self) -> None:
        self._wall_start = 0.0
        self._cpu_start = 0.0
        self._usage: ResourceUsage | None = None

    def __enter__(self) -> ResourceProbe:
        self._wall_start = time.perf_counter()
        self._cpu_start = _cpu_seconds()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._usage = ResourceUsage(
            wall_seconds=time.perf_counter() - self._wall_start,
            cpu_seconds=_cpu_seconds() - self._cpu_start,
            peak_rss_mb=peak_resident_memory_mb(),
            vram_mb=nvidia_memory_mb(),
        )

    @property
    def usage(self) -> ResourceUsage:
        if self._usage is None:
            raise RuntimeError("ResourceProbe.usage is only available after the context exits")
        return self._usage


def peak_resident_memory_mb() -> float:
    kilobytes = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    high_water_mark = _read_high_water_mark_kb()
    if high_water_mark is not None:
        kilobytes = max(kilobytes, high_water_mark)
    return kilobytes / KILOBYTES_PER_MEGABYTE


def nvidia_memory_mb() -> float | None:
    try:
        import pynvml
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        used_bytes = float(pynvml.nvmlDeviceGetMemoryInfo(handle).used)
        pynvml.nvmlShutdown()
    except Exception:
        return None
    return used_bytes / (1024.0 * 1024.0)


def _cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def _read_high_water_mark_kb() -> float | None:
    try:
        content = _STATUS_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        if line.startswith(_HIGH_WATER_MARK):
            return float(line.split()[1])
    return None
