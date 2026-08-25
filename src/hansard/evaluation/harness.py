from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from hansard.domain.audio import AudioClip
from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization
from hansard.domain.transcript import Transcript
from hansard.evaluation.datasets import EvaluationSample
from hansard.evaluation.metrics.speaker import (
    DEFAULT_COLLAR,
    concatenated_minimum_permutation_wer,
    diarization_error_rate,
    jaccard_error_rate,
    speaker_count_error,
    word_diarization_counts,
)
from hansard.evaluation.metrics.system import RealTimeFactor, ResourceProbe, ResourceUsage
from hansard.evaluation.metrics.text import ErrorCounts, character_error_counts, word_error_counts
from hansard.evaluation.normalizers import TextNormalizer, normalizer_for
from hansard.ports.asr import RecognitionHints, SpeechRecognizer
from hansard.ports.diarization import DiarizationRequest, Diarizer, SpeakerAttributor


@runtime_checkable
class AudioSource(Protocol):
    def load(self, path: Path) -> AudioClip: ...


@dataclass(frozen=True, slots=True)
class SampleOutcome:
    identifier: str
    language: str
    audio_seconds: float
    processing_seconds: float
    reference_words: int
    wer: float
    cer: float
    cpwer: float | None = None
    wder: float | None = None
    der: float | None = None
    jer: float | None = None
    speaker_count_error: int | None = None

    @property
    def real_time_factor(self) -> float:
        return RealTimeFactor(self.processing_seconds, self.audio_seconds).value


@dataclass(frozen=True, slots=True)
class CorpusMetrics:
    wer: float
    cer: float
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int
    cpwer: float | None = None
    wder: float | None = None
    der: float | None = None
    missed_speech_rate: float | None = None
    false_alarm_rate: float | None = None
    confusion_rate: float | None = None
    jer: float | None = None
    speaker_count_error: float | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    label: str
    engine: str
    generated_at: datetime
    samples: tuple[SampleOutcome, ...]
    corpus: CorpusMetrics
    resources: ResourceUsage
    real_time_factor: RealTimeFactor

    @property
    def metric_values(self) -> dict[str, float]:
        values: dict[str, float] = {
            "wer": self.corpus.wer,
            "cer": self.corpus.cer,
            "rtf": self.real_time_factor.value,
            "peak_rss_mb": self.resources.peak_rss_mb,
            "wall_seconds": self.resources.wall_seconds,
            "cpu_seconds": self.resources.cpu_seconds,
            "audio_seconds": self.real_time_factor.audio_seconds,
            "sample_count": float(len(self.samples)),
        }
        optional: dict[str, float | None] = {
            "cpwer": self.corpus.cpwer,
            "wder": self.corpus.wder,
            "der": self.corpus.der,
            "missed_speech_rate": self.corpus.missed_speech_rate,
            "false_alarm_rate": self.corpus.false_alarm_rate,
            "confusion_rate": self.corpus.confusion_rate,
            "jer": self.corpus.jer,
            "speaker_count_error": self.corpus.speaker_count_error,
            "vram_mb": self.resources.vram_mb,
        }
        values.update({name: value for name, value in optional.items() if value is not None})
        return values


@dataclass(slots=True)
class _Totals:
    words: ErrorCounts = field(default_factory=ErrorCounts)
    characters: ErrorCounts = field(default_factory=ErrorCounts)
    concatenated: ErrorCounts = field(default_factory=ErrorCounts)
    concatenated_samples: int = 0
    wrong_speaker_words: int = 0
    aligned_words: int = 0
    missed_speech: float = 0.0
    false_alarm: float = 0.0
    confusion: float = 0.0
    reference_speech: float = 0.0
    diarized_samples: int = 0
    jaccard_scores: list[float] = field(default_factory=list)
    speaker_count_errors: list[int] = field(default_factory=list)
    audio_seconds: float = 0.0
    processing_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class BenchmarkRunner:
    recognizer: SpeechRecognizer
    audio_source: AudioSource
    diarizer: Diarizer | None = None
    attributor: SpeakerAttributor | None = None
    normalizer_factory: Callable[[str | None], TextNormalizer] = normalizer_for
    collar: float = DEFAULT_COLLAR
    skip_overlap: bool = False
    diarization_request: DiarizationRequest = field(default_factory=DiarizationRequest)

    def run(self, samples: Sequence[EvaluationSample], label: str = "hansard") -> BenchmarkReport:
        totals = _Totals()
        outcomes: list[SampleOutcome] = []
        with ResourceProbe() as probe:
            for sample in samples:
                outcomes.append(self._evaluate(sample, totals))
        return BenchmarkReport(
            label=label,
            engine=self.recognizer.profile.name,
            generated_at=datetime.now(UTC),
            samples=tuple(outcomes),
            corpus=_corpus_metrics(totals),
            resources=probe.usage,
            real_time_factor=RealTimeFactor(totals.processing_seconds, totals.audio_seconds),
        )

    def _evaluate(self, sample: EvaluationSample, totals: _Totals) -> SampleOutcome:
        clip = self._load(sample)
        normalizer = self.normalizer_factory(sample.language)
        started = time.perf_counter()
        hypothesis = self.recognizer.transcribe(clip, self._hints(sample))
        diarization = self._diarize(clip)
        if diarization is not None and self.attributor is not None:
            hypothesis = self.attributor.attribute(hypothesis, diarization)
        processing_seconds = time.perf_counter() - started

        words = word_error_counts(
            normalizer.normalize(sample.reference.text),
            normalizer.normalize(hypothesis.text),
        )
        characters = character_error_counts(
            normalizer.normalize(sample.reference.text),
            normalizer.normalize(hypothesis.text),
        )
        totals.words = totals.words + words
        totals.characters = totals.characters + characters
        totals.audio_seconds += sample.audio_seconds or clip.duration
        totals.processing_seconds += processing_seconds

        cpwer = self._concatenated(sample.reference, hypothesis, normalizer, totals)
        wder = self._word_diarization(sample.reference, hypothesis, normalizer, totals)
        der, jer, count_error = self._diarization_metrics(sample.reference_diarization, diarization, totals)
        return SampleOutcome(
            identifier=sample.identifier,
            language=sample.language,
            audio_seconds=sample.audio_seconds or clip.duration,
            processing_seconds=processing_seconds,
            reference_words=words.reference_units,
            wer=words.rate,
            cer=characters.rate,
            cpwer=cpwer,
            wder=wder,
            der=der,
            jer=jer,
            speaker_count_error=count_error,
        )

    def _load(self, sample: EvaluationSample) -> AudioClip:
        if sample.audio_path is None:
            raise ValueError(f"sample {sample.identifier} has no audio path to benchmark")
        return self.audio_source.load(sample.audio_path)

    def _hints(self, sample: EvaluationSample) -> RecognitionHints:
        return RecognitionHints(
            language=sample.language,
            speaker_names=tuple(
                speaker for speaker in sample.reference.speakers if speaker != UNKNOWN_SPEAKER
            ),
        )

    def _diarize(self, clip: AudioClip) -> Diarization | None:
        if self.diarizer is None:
            return None
        return self.diarizer.diarize(clip, self.diarization_request)

    def _concatenated(
        self,
        reference: Transcript,
        hypothesis: Transcript,
        normalizer: TextNormalizer,
        totals: _Totals,
    ) -> float | None:
        if not _is_multi_speaker(reference) and not _is_multi_speaker(hypothesis):
            return None
        result = concatenated_minimum_permutation_wer(reference, hypothesis, normalizer)
        totals.concatenated = totals.concatenated + ErrorCounts(
            substitutions=result.substitutions,
            deletions=result.deletions,
            insertions=result.insertions,
            hits=result.hits,
            reference_units=result.reference_words,
        )
        totals.concatenated_samples += 1
        return result.wer

    def _word_diarization(
        self,
        reference: Transcript,
        hypothesis: Transcript,
        normalizer: TextNormalizer,
        totals: _Totals,
    ) -> float | None:
        if not _is_multi_speaker(reference):
            return None
        wrong, aligned = word_diarization_counts(reference, hypothesis, normalizer)
        totals.wrong_speaker_words += wrong
        totals.aligned_words += aligned
        return wrong / aligned if aligned else 0.0

    def _diarization_metrics(
        self,
        reference: Diarization | None,
        hypothesis: Diarization | None,
        totals: _Totals,
    ) -> tuple[float | None, float | None, int | None]:
        if reference is None or hypothesis is None:
            return None, None, None
        der = diarization_error_rate(reference, hypothesis, self.collar, self.skip_overlap)
        jer = jaccard_error_rate(reference, hypothesis, self.collar, self.skip_overlap)
        totals.missed_speech += der.missed_speech
        totals.false_alarm += der.false_alarm
        totals.confusion += der.confusion
        totals.reference_speech += der.total_reference_speech
        totals.diarized_samples += 1
        totals.jaccard_scores.extend(score for _, score in jer.per_speaker)
        count_error = speaker_count_error(reference, hypothesis)
        totals.speaker_count_errors.append(count_error)
        return der.der, jer.jer, count_error


def _corpus_metrics(totals: _Totals) -> CorpusMetrics:
    diarized = totals.reference_speech > 0.0
    errors = totals.missed_speech + totals.false_alarm + totals.confusion
    return CorpusMetrics(
        wer=totals.words.rate,
        cer=totals.characters.rate,
        substitutions=totals.words.substitutions,
        deletions=totals.words.deletions,
        insertions=totals.words.insertions,
        reference_words=totals.words.reference_units,
        cpwer=totals.concatenated.rate if totals.concatenated_samples else None,
        wder=totals.wrong_speaker_words / totals.aligned_words if totals.aligned_words else None,
        der=errors / totals.reference_speech if diarized else None,
        missed_speech_rate=totals.missed_speech / totals.reference_speech if diarized else None,
        false_alarm_rate=totals.false_alarm / totals.reference_speech if diarized else None,
        confusion_rate=totals.confusion / totals.reference_speech if diarized else None,
        jer=sum(totals.jaccard_scores) / len(totals.jaccard_scores) if totals.jaccard_scores else None,
        speaker_count_error=(
            sum(abs(value) for value in totals.speaker_count_errors) / len(totals.speaker_count_errors)
            if totals.speaker_count_errors
            else None
        ),
    )


def _is_multi_speaker(transcript: Transcript) -> bool:
    return len({speaker for speaker in transcript.speakers if speaker != UNKNOWN_SPEAKER}) > 1
