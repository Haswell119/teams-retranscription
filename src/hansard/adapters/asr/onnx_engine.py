from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hansard.adapters.asr.tokens import TokenStream, tokens_to_words, words_to_text
from hansard.domain.audio import AudioClip
from hansard.domain.errors import RecognitionError
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.ports.asr import EngineProfile, RecognitionHints

_KNOWN_PROFILES: dict[str, tuple[tuple[str, ...], int, str]] = {
    "nemo-parakeet-tdt-0.6b-v3": (
        (
            "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hr", "hu", "it", "lt",
            "lv", "mt", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "uk",
        ),
        1500,
        "cc-by-4.0",
    ),
    "nemo-parakeet-tdt-0.6b-v2": (("en",), 1500, "cc-by-4.0"),
    "nemo-canary-1b-v2": (("en", "fr", "de", "es"), 2600, "cc-by-4.0"),
    "whisper-base": (("multilingual",), 400, "mit"),
}


@dataclass(slots=True)
class OnnxRecognizer:
    model_id: str = "nemo-parakeet-tdt-0.6b-v3"
    quantization: str | None = "int8"
    model_path: Path | None = None
    providers: tuple[str, ...] = ("CPUExecutionProvider",)
    intra_op_threads: int = 0
    inter_op_threads: int = 0
    batch_size: int = 4
    language: str | None = None
    _model: Any | None = field(default=None, init=False, repr=False)

    @property
    def profile(self) -> EngineProfile:
        languages, memory, licence = _KNOWN_PROFILES.get(
            self.model_id, (("multilingual",), 2000, "unknown")
        )
        return EngineProfile(
            name=f"onnx:{self.model_id}",
            languages=languages,
            emits_word_timestamps=True,
            emits_punctuation=True,
            resident_memory_mb=memory if self.quantization == "int8" else int(memory * 2.2),
            license_identifier=licence,
            supports_vocabulary_biasing=False,
            metadata={"quantization": self.quantization or "none"},
        )

    def _session_options(self) -> Any:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        if self.intra_op_threads > 0:
            options.intra_op_num_threads = self.intra_op_threads
        if self.inter_op_threads > 0:
            options.inter_op_num_threads = self.inter_op_threads
        options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        return options

    def _load(self) -> Any:
        if self._model is None:
            import onnx_asr

            try:
                model = onnx_asr.load_model(
                    self.model_id,
                    str(self.model_path) if self.model_path else None,
                    quantization=self.quantization,
                    providers=list(self.providers),
                    sess_options=self._session_options(),
                )
            except Exception as error:
                raise RecognitionError(f"failed to load ONNX ASR model {self.model_id}: {error}") from error
            self._model = model.with_timestamps()
        return self._model

    def warm_up(self) -> None:
        model = self._load()
        model.recognize(np.zeros(16_000, dtype=np.float32), sample_rate=16_000)

    def _decode_batch(
        self, model: Any, waveforms: list[np.ndarray], spans: list[TimeSpan], language: str | None
    ) -> list[Utterance]:
        options: dict[str, Any] = {"sample_rate": 16_000}
        if language:
            options["language"] = language
        try:
            results = model.recognize(waveforms, **options)
        except TypeError:
            results = model.recognize(waveforms, sample_rate=16_000)
        except Exception as error:
            raise RecognitionError(f"ONNX ASR decoding failed: {error}") from error
        if not isinstance(results, list):
            results = [results]
        utterances: list[Utterance] = []
        for result, span in zip(results, spans, strict=False):
            stream = TokenStream(
                tokens=tuple(result.tokens or ()),
                timestamps=tuple(result.timestamps or ()),
                logprobs=tuple(result.logprobs or ()),
            )
            words = tokens_to_words(stream, span)
            text = result.text.strip() or words_to_text(words)
            if not text:
                continue
            confidence = (
                float(np.mean([word.confidence for word in words])) if words else 1.0
            )
            utterances.append(
                Utterance(
                    span=span,
                    text=text,
                    language=language,
                    confidence=confidence,
                    words=words,
                )
            )
        return utterances

    def transcribe(self, clip: AudioClip, hints: RecognitionHints) -> Transcript:
        model = self._load()
        language = hints.language or self.language
        spans = list(hints.segments) or [clip.span]
        utterances: list[Utterance] = []
        for start in range(0, len(spans), max(1, self.batch_size)):
            chunk = spans[start : start + max(1, self.batch_size)]
            waveforms = [clip.extract(span).samples for span in chunk]
            usable = [(wave, span) for wave, span in zip(waveforms, chunk, strict=True) if wave.size]
            if not usable:
                continue
            utterances.extend(
                self._decode_batch(model, [wave for wave, _ in usable], [span for _, span in usable], language)
            )
        utterances.sort(key=lambda utterance: utterance.span.start)
        return Transcript(
            utterances=tuple(utterances),
            language=language,
            audio_duration=clip.duration,
        )
