from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
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
    DEFAULT_TIME_COLLAR,
    concatenated_minimum_permutation_wer,
    diarization_error_rate,
    jaccard_error_rate,
    speaker_count_error,
    time_constrained_cpwer,
    word_diarization_counts,
)
from hansard.evaluation.metrics.system import RealTimeFactor, ResourceProbe, ResourceUsage
from hansard.evaluation.metrics.text import ErrorCounts, character_error_counts, word_error_counts
from hansard.evaluation.normalizers import NORMALIZER_VERSION, TextNormalizer, normalizer_for
from hansard.ports.asr import RecognitionHints, SpeechRecognizer
from hansard.ports.diarization import DiarizationRequest, Diarizer, SpeakerAttributor

ALL_DATASETS = "all"
ALL_LANGUAGES = "all"


@runtime_checkable
class AudioSource(Protocol):
    def load(self, path: Path) -> AudioClip: ...


@dataclass(frozen=True, slots=True)
class SampleOutcome:
    identifier: str
    dataset: str
    language: str
    audio_seconds: float
    processing_seconds: float
    reference_words: int
    wer: float
    cer: float
    cpwer: float | None = None
    tcpwer: float | None = None
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
    tcpwer: float | None = None
    wder: float | None = None
    der: float | None = None
    missed_speech_rate: float | None = None
    false_alarm_rate: float | None = None
    confusion_rate: float | None = None
    jer: float | None = None
    speaker_count_error: float | None = None


@dataclass(frozen=True, slots=True)
class CorpusSlice:
    dataset: str
    language: str
    sample_count: int
    audio_seconds: float
    processing_seconds: float
    corpus: CorpusMetrics

    @property
    def real_time_factor(self) -> RealTimeFactor:
        return RealTimeFactor(self.processing_seconds, self.audio_seconds)

    @property
    def metric_values(self) -> dict[str, float]:
        return corpus_metric_values(
            self.corpus,
            self.real_time_factor,
            self.sample_count,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    label: str
    engine: str
    generated_at: datetime
    samples: tuple[SampleOutcome, ...]
    corpus: CorpusMetrics
    resources: ResourceUsage
    real_time_factor: RealTimeFactor
    dataset_slices: tuple[CorpusSlice, ...] = ()
    language_slices: tuple[CorpusSlice, ...] = ()
    normalizer_version: str = NORMALIZER_VERSION

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(slice_.language for slice_ in self.language_slices)

    @property
    def metric_values(self) -> dict[str, float]:
        values = corpus_metric_values(self.corpus, self.real_time_factor, len(self.samples))
        values["peak_rss_mb"] = self.resources.peak_rss_mb
        values["wall_seconds"] = self.resources.wall_seconds
        values["cpu_seconds"] = self.resources.cpu_seconds
        if self.resources.vram_mb is not None:
            values["vram_mb"] = self.resources.vram_mb
        return values

    def metric_values_for(self, language: str | None) -> dict[str, float] | None:
        if language is None or language == ALL_LANGUAGES:
            return self.metric_values
        for slice_ in self.language_slices:
            if slice_.language == language:
                return slice_.metric_values
        return None


def corpus_metric_values(
    corpus: CorpusMetrics,
    real_time_factor: RealTimeFactor,
    sample_count: int,
) -> dict[str, float]:
    values: dict[str, float] = {
        "wer": corpus.wer,
        "cer": corpus.cer,
        "rtf": real_time_factor.value,
        "audio_seconds": real_time_factor.audio_seconds,
        "sample_count": float(sample_count),
    }
    optional: dict[str, float | None] = {
        "cpwer": corpus.cpwer,
        "tcpwer": corpus.tcpwer,
        "wder": corpus.wder,
        "der": corpus.der,
        "missed_speech_rate": corpus.missed_speech_rate,
        "false_alarm_rate": corpus.false_alarm_rate,
        "confusion_rate": corpus.confusion_rate,
        "jer": corpus.jer,
        "speaker_count_error": corpus.speaker_count_error,
    }
    values.update({name: value for name, value in optional.items() if value is not None})
    return values


@dataclass(slots=True)
class _Totals:
    words: ErrorCounts = field(default_factory=ErrorCounts)
    characters: ErrorCounts = field(default_factory=ErrorCounts)
    concatenated: ErrorCounts = field(default_factory=ErrorCounts)
    concatenated_samples: int = 0
    time_constrained: ErrorCounts = field(default_factory=ErrorCounts)
    time_constrained_samples: int = 0
    wrong_speaker_words: int = 0
    aligned_words: int = 0
    missed_speech: float = 0.0
    false_alarm: float = 0.0
    confusion: float = 0.0
    reference_speech: float = 0.0
    jaccard_scores: list[float] = field(default_factory=list)
    speaker_count_errors: list[int] = field(default_factory=list)
    audio_seconds: float = 0.0
    processing_seconds: float = 0.0
    sample_count: int = 0


@dataclass(frozen=True, slots=True)
class BenchmarkRunner:
    recognizer: SpeechRecognizer
    audio_source: AudioSource
    diarizer: Diarizer | None = None
    attributor: SpeakerAttributor | None = None
    normalizer_factory: Callable[[str | None], TextNormalizer] = normalizer_for
    collar: float = DEFAULT_COLLAR
    time_collar: float = DEFAULT_TIME_COLLAR
    skip_overlap: bool = False
    diarization_request: DiarizationRequest = field(default_factory=DiarizationRequest)

    def run(self, samples: Sequence[EvaluationSample], label: str = "hansard") -> BenchmarkReport:
        groups: dict[tuple[str, str], _Totals] = {}
        outcomes: list[SampleOutcome] = []
        with ResourceProbe() as probe:
            for sample in samples:
                totals = groups.setdefault((sample.source, sample.language), _Totals())
                outcomes.append(self._evaluate(sample, totals))
        overall = _merge(groups.values())
        return BenchmarkReport(
            label=label,
            engine=self.recognizer.profile.name,
            generated_at=datetime.now(UTC),
            samples=tuple(outcomes),
            corpus=_corpus_metrics(overall),
            resources=probe.usage,
            real_time_factor=RealTimeFactor(overall.processing_seconds, overall.audio_seconds),
            dataset_slices=_dataset_slices(groups),
            language_slices=_language_slices(groups),
            normalizer_version=NORMALIZER_VERSION,
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

        reference_text = normalizer.normalize(sample.reference.text)
        hypothesis_text = normalizer.normalize(hypothesis.text)
        words = word_error_counts(reference_text, hypothesis_text)
        characters = character_error_counts(reference_text, hypothesis_text)
        audio_seconds = sample.audio_seconds or clip.duration
        totals.words = totals.words + words
        totals.characters = totals.characters + characters
        totals.audio_seconds += audio_seconds
        totals.processing_seconds += processing_seconds
        totals.sample_count += 1

        cpwer, tcpwer = self._permutation_metrics(sample.reference, hypothesis, normalizer, totals)
        wder = self._word_diarization(sample.reference, hypothesis, normalizer, totals)
        der, jer, count_error = self._diarization_metrics(sample.reference_diarization, diarization, totals)
        return SampleOutcome(
            identifier=sample.identifier,
            dataset=sample.source,
            language=sample.language,
            audio_seconds=audio_seconds,
            processing_seconds=processing_seconds,
            reference_words=words.reference_units,
            wer=words.rate,
            cer=characters.rate,
            cpwer=cpwer,
            tcpwer=tcpwer,
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

    def _permutation_metrics(
        self,
        reference: Transcript,
        hypothesis: Transcript,
        normalizer: TextNormalizer,
        totals: _Totals,
    ) -> tuple[float | None, float | None]:
        if not _is_multi_speaker(reference) and not _is_multi_speaker(hypothesis):
            return None, None
        concatenated = concatenated_minimum_permutation_wer(reference, hypothesis, normalizer)
        constrained = time_constrained_cpwer(reference, hypothesis, normalizer, self.time_collar)
        totals.concatenated = totals.concatenated + _as_counts(
            concatenated.substitutions,
            concatenated.deletions,
            concatenated.insertions,
            concatenated.hits,
            concatenated.reference_words,
        )
        totals.concatenated_samples += 1
        totals.time_constrained = totals.time_constrained + _as_counts(
            constrained.substitutions,
            constrained.deletions,
            constrained.insertions,
            constrained.hits,
            constrained.reference_words,
        )
        totals.time_constrained_samples += 1
        return concatenated.wer, constrained.wer

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
        totals.jaccard_scores.extend(score for _, score in jer.per_speaker)
        count_error = speaker_count_error(reference, hypothesis)
        totals.speaker_count_errors.append(count_error)
        return der.der, jer.jer, count_error


def _as_counts(
    substitutions: int,
    deletions: int,
    insertions: int,
    hits: int,
    reference_words: int,
) -> ErrorCounts:
    return ErrorCounts(
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        hits=hits,
        reference_units=reference_words,
    )


def _merge(items: Iterable[_Totals]) -> _Totals:
    merged = _Totals()
    for item in items:
        merged.words = merged.words + item.words
        merged.characters = merged.characters + item.characters
        merged.concatenated = merged.concatenated + item.concatenated
        merged.concatenated_samples += item.concatenated_samples
        merged.time_constrained = merged.time_constrained + item.time_constrained
        merged.time_constrained_samples += item.time_constrained_samples
        merged.wrong_speaker_words += item.wrong_speaker_words
        merged.aligned_words += item.aligned_words
        merged.missed_speech += item.missed_speech
        merged.false_alarm += item.false_alarm
        merged.confusion += item.confusion
        merged.reference_speech += item.reference_speech
        merged.jaccard_scores.extend(item.jaccard_scores)
        merged.speaker_count_errors.extend(item.speaker_count_errors)
        merged.audio_seconds += item.audio_seconds
        merged.processing_seconds += item.processing_seconds
        merged.sample_count += item.sample_count
    return merged


def _dataset_slices(groups: dict[tuple[str, str], _Totals]) -> tuple[CorpusSlice, ...]:
    return tuple(_slice(dataset, language, totals) for (dataset, language), totals in sorted(groups.items()))


def _language_slices(groups: dict[tuple[str, str], _Totals]) -> tuple[CorpusSlice, ...]:
    languages = sorted({language for _, language in groups})
    return tuple(
        _slice(
            ALL_DATASETS,
            language,
            _merge(totals for (_, key), totals in groups.items() if key == language),
        )
        for language in languages
    )


def _slice(dataset: str, language: str, totals: _Totals) -> CorpusSlice:
    return CorpusSlice(
        dataset=dataset,
        language=language,
        sample_count=totals.sample_count,
        audio_seconds=totals.audio_seconds,
        processing_seconds=totals.processing_seconds,
        corpus=_corpus_metrics(totals),
    )


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
        tcpwer=totals.time_constrained.rate if totals.time_constrained_samples else None,
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
