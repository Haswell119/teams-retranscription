from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from hansard.domain.audio import AudioClip
from hansard.domain.errors import RecognitionError
from hansard.domain.language import MIXED, merge_tags, normalise_tag
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word
from hansard.ports.asr import EngineProfile, RecognitionHints

CTRANSLATE2_WEIGHTS = "model.bin"
ENGLISH_ONLY_MARKER = ".en"
INSTALL_HINT = "pip install 'hansard[asr-whisper]'"

WHISPER_LANGUAGES: tuple[str, ...] = (
    "af",
    "am",
    "ar",
    "as",
    "az",
    "ba",
    "be",
    "bg",
    "bn",
    "bo",
    "br",
    "bs",
    "ca",
    "cs",
    "cy",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fo",
    "fr",
    "gl",
    "gu",
    "ha",
    "haw",
    "he",
    "hi",
    "hr",
    "ht",
    "hu",
    "hy",
    "id",
    "is",
    "it",
    "ja",
    "jw",
    "ka",
    "kk",
    "km",
    "kn",
    "ko",
    "la",
    "lb",
    "ln",
    "lo",
    "lt",
    "lv",
    "mg",
    "mi",
    "mk",
    "ml",
    "mn",
    "mr",
    "ms",
    "mt",
    "my",
    "ne",
    "nl",
    "nn",
    "no",
    "oc",
    "pa",
    "pl",
    "ps",
    "pt",
    "ro",
    "ru",
    "sa",
    "sd",
    "si",
    "sk",
    "sl",
    "sn",
    "so",
    "sq",
    "sr",
    "su",
    "sv",
    "sw",
    "ta",
    "te",
    "tg",
    "th",
    "tk",
    "tl",
    "tr",
    "tt",
    "uk",
    "ur",
    "uz",
    "vi",
    "yi",
    "yo",
    "yue",
    "zh",
)

_RESIDENT_MEMORY_MB: dict[str, int] = {
    "tiny": 250,
    "base": 320,
    "small": 650,
    "distil": 1200,
    "turbo": 1500,
    "medium": 1700,
    "large": 3300,
}

_DEFAULT_RESIDENT_MEMORY_MB = 1500
_COMPACT_COMPUTE_TYPES = frozenset({"int8", "int8_float16", "int8_float32", "int8_bfloat16"})


class WhisperSegmentLike(Protocol):
    start: float
    end: float
    text: str
    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float


class WhisperModelLike(Protocol):
    def transcribe(self, audio: Any, **options: Any) -> tuple[Iterable[Any], Any]: ...


@dataclass(frozen=True, slots=True)
class WhisperModelRequest:
    source: str
    device: str
    compute_type: str
    download_root: str | None
    local_files_only: bool


WhisperModelLoader = Callable[[WhisperModelRequest], WhisperModelLike]


def load_faster_whisper_model(request: WhisperModelRequest) -> WhisperModelLike:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RecognitionError(f"faster-whisper is not installed; {INSTALL_HINT}") from error
    try:
        model: WhisperModelLike = WhisperModel(
            request.source,
            device=request.device,
            compute_type=request.compute_type,
            download_root=request.download_root,
            local_files_only=request.local_files_only,
        )
    except Exception as error:
        raise RecognitionError(f"failed to load Whisper model {request.source}: {error}") from error
    return model


def local_model_directory(models_dir: Path, model_id: str) -> Path | None:
    candidates = (
        models_dir / model_id.replace("/", "__"),
        models_dir / model_id,
        models_dir / "whisper" / model_id.replace("/", "__"),
    )
    for candidate in candidates:
        if (candidate / CTRANSLATE2_WEIGHTS).is_file():
            return candidate
    return None


def confidence_from_log_probability(average_log_probability: float) -> float:
    return min(1.0, max(0.0, math.exp(average_log_probability)))


@dataclass(slots=True)
class WhisperRecognizer:
    model_id: str = "large-v3-turbo"
    device: str = "cpu"
    compute_type: str = "int8"
    models_dir: Path = Path("/var/lib/hansard/models")
    beam_size: int = 1
    language: str | None = None
    allow_downloads: bool = True
    vad_filter: bool = True
    no_speech_threshold: float = 0.6
    compression_ratio_threshold: float = 2.4
    log_probability_threshold: float = -1.0
    loader: WhisperModelLoader = load_faster_whisper_model
    _model: WhisperModelLike | None = field(default=None, init=False, repr=False)

    @property
    def profile(self) -> EngineProfile:
        return EngineProfile(
            name=f"whisper:{self.model_id}",
            languages=self._languages(),
            emits_word_timestamps=True,
            emits_punctuation=True,
            resident_memory_mb=self._resident_memory_mb(),
            license_identifier="mit",
            supports_vocabulary_biasing=True,
            metadata={
                "compute_type": self.compute_type,
                "device": self.device,
                "vad_filter": str(self.vad_filter).lower(),
                "word_timestamps": "approximate",
            },
        )

    def warm_up(self) -> None:
        model = self._load()
        self._recognise(model, np.zeros(16_000, dtype=np.float32), self.language, RecognitionHints())

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        model = self._load()
        requested = _decoder_language(hints.language or self.language)
        spans = list(hints.segments) or [clip.span]
        utterances: list[Utterance] = []
        observed: list[str] = []
        for span in spans:
            piece = clip.extract(span)
            if piece.frame_count == 0:
                continue
            samples = np.ascontiguousarray(piece.samples, dtype=np.float32)
            segments, info = self._recognise(model, samples, requested, hints)
            spoken = requested or _detected_language(info)
            if spoken:
                observed.append(spoken)
            utterances.extend(self._utterances(segments, piece.span, spoken))
        utterances.sort(key=lambda utterance: utterance.span.start)
        return Transcript(
            utterances=tuple(utterances),
            language=merge_tags(observed),
            audio_duration=clip.duration,
        )

    def _languages(self) -> tuple[str, ...]:
        return ("en",) if ENGLISH_ONLY_MARKER in self.model_id.lower() else WHISPER_LANGUAGES

    def _resident_memory_mb(self) -> int:
        identifier = self.model_id.lower()
        baseline = next(
            (memory for name, memory in _RESIDENT_MEMORY_MB.items() if name in identifier),
            _DEFAULT_RESIDENT_MEMORY_MB,
        )
        return baseline if self.compute_type in _COMPACT_COMPUTE_TYPES else int(baseline * 2.2)

    def _load(self) -> WhisperModelLike:
        if self._model is None:
            self._model = self.loader(self._model_request())
        return self._model

    def _model_request(self) -> WhisperModelRequest:
        local = local_model_directory(self.models_dir, self.model_id)
        if local is not None:
            return WhisperModelRequest(
                source=str(local),
                device=self.device,
                compute_type=self.compute_type,
                download_root=str(self.models_dir),
                local_files_only=True,
            )
        if not self.allow_downloads:
            raise RecognitionError(
                f"no CTranslate2 Whisper model for '{self.model_id}' under {self.models_dir} "
                "and downloads are disabled"
            )
        return WhisperModelRequest(
            source=self.model_id,
            device=self.device,
            compute_type=self.compute_type,
            download_root=str(self.models_dir),
            local_files_only=False,
        )

    def _decoding_options(self, language: str | None, hints: RecognitionHints) -> dict[str, Any]:
        options: dict[str, Any] = {
            "beam_size": max(1, self.beam_size),
            "word_timestamps": True,
            "vad_filter": self.vad_filter,
            "condition_on_previous_text": False,
            "no_speech_threshold": self.no_speech_threshold,
            "compression_ratio_threshold": self.compression_ratio_threshold,
            "log_prob_threshold": self.log_probability_threshold,
        }
        if language:
            options["language"] = language
        if hints.prompt:
            options["initial_prompt"] = hints.prompt
        if hints.vocabulary:
            options["hotwords"] = " ".join(hints.vocabulary)
        return options

    def _recognise(
        self,
        model: WhisperModelLike,
        samples: np.ndarray,
        language: str | None,
        hints: RecognitionHints,
    ) -> tuple[list[Any], Any]:
        try:
            emitted, info = model.transcribe(samples, **self._decoding_options(language, hints))
            return list(emitted), info
        except Exception as error:
            raise RecognitionError(f"Whisper decoding failed: {error}") from error

    def _is_hallucination(self, segment: WhisperSegmentLike) -> bool:
        silent = segment.no_speech_prob > self.no_speech_threshold
        unlikely = segment.avg_logprob < self.log_probability_threshold
        repetitive = segment.compression_ratio > self.compression_ratio_threshold
        return repetitive or (silent and unlikely)

    def _utterances(self, segments: Sequence[Any], span: TimeSpan, language: str | None) -> list[Utterance]:
        utterances: list[Utterance] = []
        for segment in segments:
            text = str(segment.text).strip()
            if not text or self._is_hallucination(segment):
                continue
            utterances.append(
                Utterance(
                    span=_bounded(float(segment.start), float(segment.end), span),
                    text=text,
                    language=language,
                    confidence=confidence_from_log_probability(float(segment.avg_logprob)),
                    words=_words(getattr(segment, "words", None) or (), span),
                )
            )
        return utterances


def _words(emitted: Iterable[Any], span: TimeSpan) -> tuple[Word, ...]:
    words: list[Word] = []
    for item in emitted:
        text = str(item.word).strip()
        if not text:
            continue
        words.append(
            Word(
                text=text,
                span=_bounded(float(item.start), float(item.end), span),
                confidence=min(1.0, max(0.0, float(item.probability))),
            )
        )
    return tuple(words)


def _bounded(start: float, end: float, span: TimeSpan) -> TimeSpan:
    shifted = TimeSpan(span.start + start, span.start + max(end, start))
    return shifted.clamped(span.start, span.end)


def _decoder_language(tag: str | None) -> str | None:
    resolved = normalise_tag(tag)
    return None if resolved == MIXED else resolved


def _detected_language(info: Any) -> str | None:
    language = getattr(info, "language", None)
    return str(language) if language else None
