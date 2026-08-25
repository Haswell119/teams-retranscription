from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript
from hansard.evaluation.metrics.assignment import maximum_gain_assignment, minimum_cost_assignment
from hansard.evaluation.metrics.text import ErrorCounts, aligned_word_pairs, word_error_counts
from hansard.evaluation.normalizers import TextNormalizer

DEFAULT_COLLAR = 0.25
DEFAULT_TIME_COLLAR = 5.0
MAX_ALIGNMENT_CELLS = 20_000_000


@dataclass(frozen=True, slots=True)
class TimedToken:
    text: str
    speaker: str
    span: TimeSpan


@dataclass(frozen=True, slots=True)
class ScoredRegion:
    span: TimeSpan
    reference: frozenset[str]
    hypothesis: frozenset[str]


@dataclass(frozen=True, slots=True)
class DerResult:
    der: float
    missed_speech: float
    false_alarm: float
    confusion: float
    total_reference_speech: float
    mapping: tuple[tuple[str, str], ...]

    @property
    def missed_rate(self) -> float:
        return self.missed_speech / self.total_reference_speech if self.total_reference_speech else 0.0

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarm / self.total_reference_speech if self.total_reference_speech else 0.0

    @property
    def confusion_rate(self) -> float:
        return self.confusion / self.total_reference_speech if self.total_reference_speech else 0.0


@dataclass(frozen=True, slots=True)
class JerResult:
    jer: float
    per_speaker: tuple[tuple[str, float], ...]
    mapping: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CpWerResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    hits: int
    reference_words: int
    assignment: tuple[tuple[str | None, str | None], ...]
    missed_speakers: int
    false_alarm_speakers: int


def scored_regions(
    reference: Diarization,
    hypothesis: Diarization,
    collar: float = 0.0,
    skip_overlap: bool = False,
) -> tuple[ScoredRegion, ...]:
    excluded = _collar_intervals(reference, collar)
    boundaries = _boundaries(reference, hypothesis, excluded)
    regions: list[ScoredRegion] = []
    for start, end in pairwise(boundaries):
        if end <= start:
            continue
        instant = (start + end) / 2.0
        if any(interval.contains(instant) for interval in excluded):
            continue
        reference_labels = _labels_at(reference, instant)
        hypothesis_labels = _labels_at(hypothesis, instant)
        if not reference_labels and not hypothesis_labels:
            continue
        if skip_overlap and len(reference_labels) > 1:
            continue
        regions.append(ScoredRegion(TimeSpan(start, end), reference_labels, hypothesis_labels))
    return tuple(regions)


def speaker_mapping(regions: tuple[ScoredRegion, ...]) -> tuple[tuple[str, str], ...]:
    reference_labels = sorted({label for region in regions for label in region.reference})
    hypothesis_labels = sorted({label for region in regions for label in region.hypothesis})
    gains = [
        [_shared_duration(regions, reference, hypothesis) for hypothesis in hypothesis_labels]
        for reference in reference_labels
    ]
    return tuple(
        (reference_labels[row], hypothesis_labels[column])
        for row, column in maximum_gain_assignment(gains)
        if gains[row][column] > 0.0
    )


def diarization_error_rate(
    reference: Diarization,
    hypothesis: Diarization,
    collar: float = DEFAULT_COLLAR,
    skip_overlap: bool = False,
) -> DerResult:
    regions = scored_regions(reference, hypothesis, collar, skip_overlap)
    mapping = speaker_mapping(regions)
    mapped = dict(mapping)
    missed = 0.0
    false_alarm = 0.0
    confusion = 0.0
    total = 0.0
    for region in regions:
        duration = region.span.duration
        reference_count = len(region.reference)
        hypothesis_count = len(region.hypothesis)
        correct = sum(1 for label in region.reference if mapped.get(label) in region.hypothesis)
        missed += max(0, reference_count - hypothesis_count) * duration
        false_alarm += max(0, hypothesis_count - reference_count) * duration
        confusion += (min(reference_count, hypothesis_count) - correct) * duration
        total += reference_count * duration
    errors = missed + false_alarm + confusion
    return DerResult(
        der=_ratio(errors, total),
        missed_speech=missed,
        false_alarm=false_alarm,
        confusion=confusion,
        total_reference_speech=total,
        mapping=mapping,
    )


def jaccard_error_rate(
    reference: Diarization,
    hypothesis: Diarization,
    collar: float = 0.0,
    skip_overlap: bool = False,
) -> JerResult:
    regions = scored_regions(reference, hypothesis, collar, skip_overlap)
    mapping = speaker_mapping(regions)
    mapped = dict(mapping)
    reference_labels = sorted({label for region in regions for label in region.reference})
    per_speaker: list[tuple[str, float]] = []
    for label in reference_labels:
        counterpart = mapped.get(label)
        reference_time = sum(region.span.duration for region in regions if label in region.reference)
        hypothesis_time = (
            sum(region.span.duration for region in regions if counterpart in region.hypothesis)
            if counterpart is not None
            else 0.0
        )
        intersection = _shared_duration(regions, label, counterpart) if counterpart is not None else 0.0
        union = reference_time + hypothesis_time - intersection
        per_speaker.append((label, 1.0 - intersection / union if union > 0.0 else 0.0))
    scores = [score for _, score in per_speaker]
    return JerResult(
        jer=sum(scores) / len(scores) if scores else 0.0,
        per_speaker=tuple(per_speaker),
        mapping=mapping,
    )


def speaker_tokens(
    transcript: Transcript,
    normalizer: TextNormalizer | None = None,
) -> tuple[tuple[str, str], ...]:
    tokens: list[tuple[str, str]] = []
    for utterance in sorted(transcript.utterances, key=lambda item: item.span.start):
        if utterance.words:
            for word in utterance.words:
                speaker = word.speaker if word.speaker != UNKNOWN_SPEAKER else utterance.speaker
                tokens.extend((token, speaker) for token in _tokenize(word.text, normalizer))
            continue
        tokens.extend((token, utterance.speaker) for token in _tokenize(utterance.text, normalizer))
    return tuple(tokens)


def concatenated_by_speaker(
    transcript: Transcript,
    normalizer: TextNormalizer | None = None,
) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for token, speaker in speaker_tokens(transcript, normalizer):
        grouped.setdefault(speaker, []).append(token)
    return {speaker: " ".join(tokens) for speaker, tokens in grouped.items()}


def word_diarization_counts(
    reference: Transcript,
    hypothesis: Transcript,
    normalizer: TextNormalizer | None = None,
) -> tuple[int, int]:
    reference_tokens = speaker_tokens(reference, normalizer)
    hypothesis_tokens = speaker_tokens(hypothesis, normalizer)
    pairs = aligned_word_pairs(
        " ".join(token for token, _ in reference_tokens),
        " ".join(token for token, _ in hypothesis_tokens),
    )
    if not pairs:
        return 0, 0
    reference_labels = sorted({speaker for _, speaker in reference_tokens})
    hypothesis_labels = sorted({speaker for _, speaker in hypothesis_tokens})
    agreement = [[0.0 for _ in hypothesis_labels] for _ in reference_labels]
    for reference_index, hypothesis_index in pairs:
        row = reference_labels.index(reference_tokens[reference_index][1])
        column = hypothesis_labels.index(hypothesis_tokens[hypothesis_index][1])
        agreement[row][column] += 1.0
    correct = sum(agreement[row][column] for row, column in maximum_gain_assignment(agreement))
    return len(pairs) - round(correct), len(pairs)


def word_diarization_error_rate(
    reference: Transcript,
    hypothesis: Transcript,
    normalizer: TextNormalizer | None = None,
) -> float:
    wrong, aligned = word_diarization_counts(reference, hypothesis, normalizer)
    return wrong / aligned if aligned else 0.0


def concatenated_minimum_permutation_wer(
    reference: Transcript,
    hypothesis: Transcript,
    normalizer: TextNormalizer | None = None,
) -> CpWerResult:
    reference_streams = concatenated_by_speaker(reference, normalizer)
    hypothesis_streams = concatenated_by_speaker(hypothesis, normalizer)
    reference_labels = sorted(reference_streams)
    hypothesis_labels = sorted(hypothesis_streams)
    size = max(len(reference_labels), len(hypothesis_labels))
    if size == 0:
        return CpWerResult(0.0, 0, 0, 0, 0, 0, (), 0, 0)
    counts = [
        [
            word_error_counts(
                _stream(reference_streams, reference_labels, row),
                _stream(hypothesis_streams, hypothesis_labels, column),
            )
            for column in range(size)
        ]
        for row in range(size)
    ]
    return _assemble_permutation_result(counts, reference_labels, hypothesis_labels)


def timed_speaker_tokens(
    transcript: Transcript,
    normalizer: TextNormalizer | None = None,
) -> tuple[TimedToken, ...]:
    tokens: list[TimedToken] = []
    for utterance in sorted(transcript.utterances, key=lambda item: item.span.start):
        if utterance.words:
            for word in utterance.words:
                speaker = word.speaker if word.speaker != UNKNOWN_SPEAKER else utterance.speaker
                tokens.extend(
                    TimedToken(token, speaker, word.span) for token in _tokenize(word.text, normalizer)
                )
            continue
        parts = _tokenize(utterance.text, normalizer)
        tokens.extend(
            TimedToken(token, utterance.speaker, _slice(utterance.span, index, len(parts)))
            for index, token in enumerate(parts)
        )
    return tuple(sorted(tokens, key=lambda token: (token.span.start, token.span.end)))


def timed_streams(
    transcript: Transcript,
    normalizer: TextNormalizer | None = None,
) -> dict[str, tuple[TimedToken, ...]]:
    grouped: dict[str, list[TimedToken]] = {}
    for token in timed_speaker_tokens(transcript, normalizer):
        grouped.setdefault(token.speaker, []).append(token)
    return {speaker: tuple(tokens) for speaker, tokens in grouped.items()}


def time_constrained_cpwer(
    reference: Transcript,
    hypothesis: Transcript,
    normalizer: TextNormalizer | None = None,
    collar: float = DEFAULT_TIME_COLLAR,
) -> CpWerResult:
    reference_streams = timed_streams(reference, normalizer)
    hypothesis_streams = timed_streams(hypothesis, normalizer)
    reference_labels = sorted(reference_streams)
    hypothesis_labels = sorted(hypothesis_streams)
    size = max(len(reference_labels), len(hypothesis_labels))
    if size == 0:
        return CpWerResult(0.0, 0, 0, 0, 0, 0, (), 0, 0)
    counts = [
        [
            time_constrained_counts(
                _timed_stream(reference_streams, reference_labels, row),
                _timed_stream(hypothesis_streams, hypothesis_labels, column),
                collar,
            )
            for column in range(size)
        ]
        for row in range(size)
    ]
    return _assemble_permutation_result(counts, reference_labels, hypothesis_labels)


def time_constrained_counts(
    reference: tuple[TimedToken, ...],
    hypothesis: tuple[TimedToken, ...],
    collar: float,
) -> ErrorCounts:
    if not reference:
        return ErrorCounts(insertions=len(hypothesis))
    if not hypothesis:
        return ErrorCounts(deletions=len(reference), reference_units=len(reference))
    if len(reference) * len(hypothesis) > MAX_ALIGNMENT_CELLS:
        raise ValueError(
            f"time constrained alignment needs {len(reference)}x{len(hypothesis)} cells, "
            f"above the {MAX_ALIGNMENT_CELLS} limit; split the meeting into shorter sessions"
        )
    windows = _collar_windows(reference, hypothesis, collar)
    previous = [_State(index, 0, 0, index, 0) for index in range(len(hypothesis) + 1)]
    for row, reference_token in enumerate(reference, start=1):
        current = [_State(row, 0, row, 0, 0)]
        low, high = windows[row - 1]
        for column, hypothesis_token in enumerate(hypothesis, start=1):
            deletion = previous[column].deleted()
            insertion = current[column - 1].inserted()
            best = deletion if deletion.cost <= insertion.cost else insertion
            if low <= column - 1 <= high:
                diagonal = previous[column - 1].advanced(reference_token.text == hypothesis_token.text)
                if diagonal.cost <= best.cost:
                    best = diagonal
            current.append(best)
        previous = current
    final = previous[len(hypothesis)]
    return ErrorCounts(
        substitutions=final.substitutions,
        deletions=final.deletions,
        insertions=final.insertions,
        hits=final.hits,
        reference_units=final.substitutions + final.deletions + final.hits,
    )


def cross_check_with_meeteval(
    reference: Transcript,
    hypothesis: Transcript,
    normalizer: TextNormalizer | None = None,
) -> float | None:
    try:
        from meeteval.wer import cp_word_error_rate
    except ImportError:
        return None
    reference_streams = concatenated_by_speaker(reference, normalizer)
    hypothesis_streams = concatenated_by_speaker(hypothesis, normalizer)
    if not reference_streams or not hypothesis_streams:
        return None
    return float(cp_word_error_rate(reference_streams, hypothesis_streams).error_rate)


def speaker_count_error(reference: Diarization, hypothesis: Diarization) -> int:
    return hypothesis.speaker_count - reference.speaker_count


@dataclass(frozen=True, slots=True)
class _State:
    cost: int
    substitutions: int
    deletions: int
    insertions: int
    hits: int

    def deleted(self) -> _State:
        return _State(self.cost + 1, self.substitutions, self.deletions + 1, self.insertions, self.hits)

    def inserted(self) -> _State:
        return _State(self.cost + 1, self.substitutions, self.deletions, self.insertions + 1, self.hits)

    def advanced(self, identical: bool) -> _State:
        if identical:
            return _State(self.cost, self.substitutions, self.deletions, self.insertions, self.hits + 1)
        return _State(self.cost + 1, self.substitutions + 1, self.deletions, self.insertions, self.hits)


def _assemble_permutation_result(
    counts: list[list[ErrorCounts]],
    reference_labels: list[str],
    hypothesis_labels: list[str],
) -> CpWerResult:
    costs = [[float(cell.errors) for cell in row] for row in counts]
    total = ErrorCounts()
    assignment: list[tuple[str | None, str | None]] = []
    missed_speakers = 0
    false_alarm_speakers = 0
    for row, column in minimum_cost_assignment(costs):
        reference_label = _label_at(reference_labels, row)
        hypothesis_label = _label_at(hypothesis_labels, column)
        assignment.append((reference_label, hypothesis_label))
        total = total + counts[row][column]
        if reference_label is None:
            false_alarm_speakers += 1
        if hypothesis_label is None:
            missed_speakers += 1
    return CpWerResult(
        wer=total.rate,
        substitutions=total.substitutions,
        deletions=total.deletions,
        insertions=total.insertions,
        hits=total.hits,
        reference_words=total.reference_units,
        assignment=tuple(sorted(assignment, key=_assignment_sort_key)),
        missed_speakers=missed_speakers,
        false_alarm_speakers=false_alarm_speakers,
    )


def _collar_windows(
    reference: tuple[TimedToken, ...],
    hypothesis: tuple[TimedToken, ...],
    collar: float,
) -> tuple[tuple[int, int], ...]:
    windows: list[tuple[int, int]] = []
    for token in reference:
        low = 0
        while low < len(hypothesis) and hypothesis[low].span.end < token.span.start - collar:
            low += 1
        high = low - 1
        while high + 1 < len(hypothesis) and hypothesis[high + 1].span.start <= token.span.end + collar:
            high += 1
        windows.append((low, high))
    return tuple(windows)


def _slice(span: TimeSpan, index: int, count: int) -> TimeSpan:
    if count <= 1 or span.duration <= 0.0:
        return span
    width = span.duration / count
    return TimeSpan(span.start + index * width, span.start + (index + 1) * width)


def _timed_stream(
    streams: dict[str, tuple[TimedToken, ...]],
    labels: list[str],
    index: int,
) -> tuple[TimedToken, ...]:
    label = _label_at(labels, index)
    return streams[label] if label is not None else ()


def _tokenize(text: str, normalizer: TextNormalizer | None) -> list[str]:
    return (normalizer.normalize(text) if normalizer is not None else text).split()


def _labels_at(diarization: Diarization, instant: float) -> frozenset[str]:
    return frozenset(turn.label for turn in diarization.turns if turn.span.contains(instant))


def _collar_intervals(reference: Diarization, collar: float) -> tuple[TimeSpan, ...]:
    if collar <= 0.0:
        return ()
    return tuple(
        TimeSpan(boundary - collar, boundary + collar)
        for turn in reference.turns
        for boundary in (turn.span.start, turn.span.end)
    )


def _boundaries(
    reference: Diarization,
    hypothesis: Diarization,
    excluded: tuple[TimeSpan, ...],
) -> tuple[float, ...]:
    instants = {
        value
        for turns in (reference.turns, hypothesis.turns)
        for turn in turns
        for value in (turn.span.start, turn.span.end)
    }
    instants.update(value for interval in excluded for value in (interval.start, interval.end))
    return tuple(sorted(instants))


def _shared_duration(regions: tuple[ScoredRegion, ...], reference: str, hypothesis: str) -> float:
    return sum(
        region.span.duration
        for region in regions
        if reference in region.reference and hypothesis in region.hypothesis
    )


def _ratio(numerator: float, denominator: float) -> float:
    if denominator > 0.0:
        return numerator / denominator
    return 0.0 if numerator == 0.0 else 1.0


def _stream(streams: dict[str, str], labels: list[str], index: int) -> str:
    label = _label_at(labels, index)
    return streams[label] if label is not None else ""


def _label_at(labels: list[str], index: int) -> str | None:
    return labels[index] if index < len(labels) else None


def _assignment_sort_key(pair: tuple[str | None, str | None]) -> tuple[int, str, str]:
    reference, hypothesis = pair
    return (0 if reference is not None else 1, reference or "", hypothesis or "")
