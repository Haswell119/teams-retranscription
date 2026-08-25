from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hansard.config import DiarizationSettings
from hansard.domain.errors import ConfigurationError
from hansard.ports.diarization import Diarizer

DiarizerFactory = Callable[[DiarizationSettings, Path], Diarizer]

_FACTORIES: dict[str, DiarizerFactory] = {}


def register_diarizer(name: str, factory: DiarizerFactory) -> None:
    _FACTORIES[name] = factory


def available_diarizers() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def build_diarizer(settings: DiarizationSettings, models_dir: Path) -> Diarizer:
    factory = _FACTORIES.get(settings.engine)
    if factory is None:
        raise ConfigurationError(
            f"unknown diarization engine '{settings.engine}', available: {available_diarizers()}"
        )
    return factory(settings, models_dir)


def _build_sherpa(settings: DiarizationSettings, models_dir: Path) -> Diarizer:
    from hansard.adapters.diarization.sherpa import SherpaDiarizer

    return SherpaDiarizer(
        models_dir=models_dir,
        provider="cuda" if settings.device == "cuda" else "cpu",
    )


def _build_null(settings: DiarizationSettings, models_dir: Path) -> Diarizer:
    from hansard.adapters.diarization.null_diarizer import NullDiarizer

    return NullDiarizer()


register_diarizer("spectral", _build_sherpa)
register_diarizer("sherpa", _build_sherpa)
register_diarizer("null", _build_null)
