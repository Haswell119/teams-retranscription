from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hansard.config import AsrSettings
from hansard.domain.errors import ConfigurationError
from hansard.ports.asr import SpeechRecognizer

RecognizerFactory = Callable[[AsrSettings, Path], SpeechRecognizer]

_FACTORIES: dict[str, RecognizerFactory] = {}


def register_recognizer(name: str, factory: RecognizerFactory) -> None:
    _FACTORIES[name] = factory


def available_recognizers() -> tuple[str, ...]:
    return tuple(sorted(_FACTORIES))


def build_recognizer(settings: AsrSettings, models_dir: Path) -> SpeechRecognizer:
    factory = _FACTORIES.get(settings.engine)
    if factory is None:
        raise ConfigurationError(
            f"unknown ASR engine '{settings.engine}', available: {available_recognizers()}"
        )
    return factory(settings, models_dir)


def _providers(device: str) -> tuple[str, ...]:
    if device == "cuda":
        return ("CUDAExecutionProvider", "CPUExecutionProvider")
    if device == "auto":
        try:
            import onnxruntime

            if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                return ("CUDAExecutionProvider", "CPUExecutionProvider")
        except ImportError:
            return ("CPUExecutionProvider",)
    return ("CPUExecutionProvider",)


def _local_model_path(models_dir: Path, model_id: str) -> Path | None:
    candidate = models_dir / model_id.replace("/", "__")
    return candidate if candidate.is_dir() else None


def _build_onnx(settings: AsrSettings, models_dir: Path) -> SpeechRecognizer:
    from hansard.adapters.asr.onnx_engine import OnnxRecognizer

    return OnnxRecognizer(
        model_id=settings.model_id,
        quantization=None if settings.quantization == "none" else settings.quantization,
        model_path=_local_model_path(models_dir, settings.model_id),
        providers=_providers(settings.device),
        intra_op_threads=settings.intra_op_threads,
        inter_op_threads=settings.inter_op_threads,
        batch_size=settings.batch_size,
        batch_seconds=settings.batch_seconds,
        memory_profile=settings.memory_profile,
        language=settings.language,
    )


def _build_whisper(settings: AsrSettings, models_dir: Path) -> SpeechRecognizer:
    from hansard.adapters.asr.whisper_engine import WhisperRecognizer

    recognizer: SpeechRecognizer = WhisperRecognizer(
        model_id=settings.model_id,
        device="cuda" if settings.device == "cuda" else "cpu",
        compute_type="int8" if settings.quantization == "int8" else "float32",
        models_dir=models_dir,
        beam_size=settings.beam_size,
        language=settings.language,
    )
    return recognizer


def _build_null(_settings: AsrSettings, _models_dir: Path) -> SpeechRecognizer:
    from hansard.adapters.asr.null_engine import NullRecognizer

    return NullRecognizer()


register_recognizer("parakeet", _build_onnx)
register_recognizer("qwen3", _build_onnx)
register_recognizer("whisper", _build_whisper)
register_recognizer("null", _build_null)
