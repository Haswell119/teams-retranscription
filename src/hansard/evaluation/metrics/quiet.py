from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from hansard.domain.speakers import Diarization
from hansard.domain.transcript import Transcript
from hansard.evaluation.metrics.speaker import (
    concatenated_by_speaker,
    concatenated_minimum_permutation_wer,
    scored_regions,
    speaker_mapping,
)
from hansard.evaluation.metrics.text import word_error_counts
from hansard.evaluation.normalizers import TextNormalizer

BUCKET_BOUNDS: tuple[float, ...] = (15.0, 60.0, 300.0)
BUCKET_NAMES: tuple[str, ...] = ("under_15s", "15s_to_60s", "1m_to_5m", "over_5m")


@dataclass(frozen=True, slots=True)
class SpeakerOutcome:
    speaker: str
    speech_seconds: float
    reference_words: int
    matched: str | None
    wer: float
    hits: int
    substitutions: int
    deletions: int
    insertions: int

    @property
    def bucket(self) -> str:
        return bucket_for(self.speech_seconds)

    @property
    def recall(self) -> float:
        return self.hits / self.reference_words if self.reference_words else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "speaker": self.speaker,
            "speech_seconds": round(self.speech_seconds, 1),
            "bucket": self.bucket,
            "reference_words": self.reference_words,
            "matched_cluster": self.matched,
            "found": self.matched is not None,
            "wer_percent": round(self.wer * 100, 2),
            "word_recall_percent": round(self.recall * 100, 2),
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
        }


@dataclass(frozen=True, slots=True)
class BucketOutcome:
    bucket: str
    speakers: int
    found: int
    reference_words: int
    hits: int
    wer: float

    @property
    def speaker_recall(self) -> float:
        return self.found / self.speakers if self.speakers else 0.0

    @property
    def word_recall(self) -> float:
        return self.hits / self.reference_words if self.reference_words else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "bucket": self.bucket,
            "speakers": self.speakers,
            "speakers_found": self.found,
            "speaker_recall_percent": round(self.speaker_recall * 100, 2),
            "reference_words": self.reference_words,
            "word_recall_percent": round(self.word_recall * 100, 2),
            "wer_percent": round(self.wer * 100, 2),
        }


@dataclass(frozen=True, slots=True)
class QuietSpeakerReport:
    speakers: tuple[SpeakerOutcome, ...]
    buckets: tuple[BucketOutcome, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "by_speaker": [item.as_dict() for item in self.speakers],
            "by_duration": [item.as_dict() for item in self.buckets],
        }


def bucket_for(seconds: float) -> str:
    for name, bound in zip(BUCKET_NAMES, BUCKET_BOUNDS, strict=False):
        if seconds < bound:
            return name
    return BUCKET_NAMES[-1]


def speech_seconds(diarization: Diarization) -> dict[str, float]:
    totals: dict[str, float] = {}
    for turn in diarization.turns:
        totals[turn.label] = totals.get(turn.label, 0.0) + turn.span.duration
    return totals


def quiet_speaker_report(
    reference: Transcript,
    hypothesis: Transcript,
    reference_diarization: Diarization,
    hypothesis_diarization: Diarization,
    normalizer: TextNormalizer | None = None,
) -> QuietSpeakerReport:
    durations = speech_seconds(reference_diarization)
    reference_streams = concatenated_by_speaker(reference, normalizer)
    hypothesis_streams = concatenated_by_speaker(hypothesis, normalizer)
    pairing = _pairing(reference, hypothesis, reference_diarization, hypothesis_diarization, normalizer)
    outcomes: list[SpeakerOutcome] = []
    for speaker in sorted(reference_streams):
        stream = reference_streams[speaker]
        matched = pairing.get(speaker)
        counts = word_error_counts(stream, hypothesis_streams.get(matched or "", ""))
        outcomes.append(
            SpeakerOutcome(
                speaker=speaker,
                speech_seconds=durations.get(speaker, 0.0),
                reference_words=counts.reference_units,
                matched=matched,
                wer=counts.rate,
                hits=counts.hits,
                substitutions=counts.substitutions,
                deletions=counts.deletions,
                insertions=counts.insertions,
            )
        )
    return QuietSpeakerReport(speakers=tuple(outcomes), buckets=_buckets(outcomes))


def _pairing(
    reference: Transcript,
    hypothesis: Transcript,
    reference_diarization: Diarization,
    hypothesis_diarization: Diarization,
    normalizer: TextNormalizer | None,
) -> dict[str, str]:
    result = concatenated_minimum_permutation_wer(reference, hypothesis, normalizer)
    paired = {
        speaker: cluster
        for speaker, cluster in result.assignment
        if speaker is not None and cluster is not None
    }
    if paired:
        return paired
    regions = scored_regions(reference_diarization, hypothesis_diarization)
    return dict(speaker_mapping(regions))


def _buckets(outcomes: Sequence[SpeakerOutcome]) -> tuple[BucketOutcome, ...]:
    grouped: dict[str, list[SpeakerOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault(outcome.bucket, []).append(outcome)
    buckets: list[BucketOutcome] = []
    for name in BUCKET_NAMES:
        members = grouped.get(name)
        if not members:
            continue
        words = sum(item.reference_words for item in members)
        hits = sum(item.hits for item in members)
        errors = sum(item.substitutions + item.deletions + item.insertions for item in members)
        buckets.append(
            BucketOutcome(
                bucket=name,
                speakers=len(members),
                found=sum(1 for item in members if item.matched is not None and item.hits > 0),
                reference_words=words,
                hits=hits,
                wer=errors / words if words else 0.0,
            )
        )
    return tuple(buckets)
