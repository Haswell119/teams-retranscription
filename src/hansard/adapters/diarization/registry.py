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


def _provider(device: str) -> str:
    if device == "cuda":
        return "cuda"
    if device == "auto":
        try:
            import onnxruntime

            if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                return "cuda"
        except ImportError:
            return "cpu"
    return "cpu"


def _build_sherpa(settings: DiarizationSettings, models_dir: Path) -> Diarizer:
    from hansard.adapters.diarization.sherpa import SherpaDiarizer

    return SherpaDiarizer(
        models_dir=models_dir,
        segmentation_model=settings.segmentation_model,
        embedding_model=settings.embedding_model,
        clustering_threshold=settings.clustering_threshold,
        minimum_speaker_seconds=settings.minimum_speaker_seconds,
        provider=_provider(settings.device),
    )


def _build_null(_settings: DiarizationSettings, _models_dir: Path) -> Diarizer:
    from hansard.adapters.diarization.null_diarizer import NullDiarizer

    return NullDiarizer()


register_diarizer("sherpa", _build_sherpa)
register_diarizer("spectral", _build_sherpa)
register_diarizer("sortformer", _build_sherpa)
register_diarizer("pyannote", _build_sherpa)
register_diarizer("null", _build_null)
