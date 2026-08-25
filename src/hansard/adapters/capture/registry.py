from __future__ import annotations

from collections.abc import Callable

from hansard.config import CaptureSettings
from hansard.domain.audio import TARGET_SAMPLE_RATE
from hansard.domain.errors import ConfigurationError
from hansard.ports.capture import MeetingCapture

CaptureFactory = Callable[[CaptureSettings, int], MeetingCapture]

_FACTORIES: dict[str, CaptureFactory] = {}


def register_capture(name: str, factory: CaptureFactory) -> None:
    _FACTORIES[name] = factory


def available_captures() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def build_capture(settings: CaptureSettings, sample_rate: int = TARGET_SAMPLE_RATE) -> MeetingCapture:
    factory = _FACTORIES.get(settings.engine)
    if factory is None:
        raise ConfigurationError(
            f"unknown capture engine '{settings.engine}', available: {available_captures()}"
        )
    return factory(settings, sample_rate)


def _build_browser(settings: CaptureSettings, sample_rate: int) -> MeetingCapture:
    from hansard.adapters.capture.teams import TeamsBrowserCapture

    return TeamsBrowserCapture(settings=settings, sample_rate=sample_rate)


def _build_file(_settings: CaptureSettings, _sample_rate: int) -> MeetingCapture:
    from hansard.adapters.capture.file import FileCapture

    return FileCapture()


def _build_null(_settings: CaptureSettings, sample_rate: int) -> MeetingCapture:
    from hansard.adapters.capture.file import NullCapture

    return NullCapture(sample_rate=sample_rate)


register_capture("browser", _build_browser)
register_capture("file", _build_file)
register_capture("null", _build_null)
