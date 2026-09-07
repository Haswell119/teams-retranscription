import numpy as np

from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.evaluation.overlap import (
    POWERSET_CLASSES,
    agreement,
    reference_counts,
)


def diarization(*turns):
    resolved = tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in turns)
    return Diarization(turns=resolved, labels=tuple(dict.fromkeys(turn.label for turn in resolved)))


def test_the_powerset_carries_every_pair_of_three_speakers():
    assert len(POWERSET_CLASSES) == 7
    assert sum(1 for members in POWERSET_CLASSES if len(members) == 2) == 3
    assert max(len(members) for members in POWERSET_CLASSES) == 2


def test_nobody_speaking_counts_as_nobody():
    counts = reference_counts(diarization((10.0, 20.0, "A")), np.array([0.0, 5.0, 25.0]))
    assert list(counts) == [0, 0, 0]


def test_one_speaker_counts_as_one_and_two_as_two():
    reference = diarization((0.0, 10.0, "A"), (4.0, 8.0, "B"))
    counts = reference_counts(reference, np.array([1.0, 5.0, 9.0]))
    assert list(counts) == [1, 2, 1]


def test_three_at_once_is_counted_as_three():
    reference = diarization((0.0, 10.0, "A"), (0.0, 10.0, "B"), (0.0, 10.0, "C"))
    assert list(reference_counts(reference, np.array([5.0]))) == [3]


def test_a_perfect_mask_scores_full_recall_and_precision():
    predicted = np.array([1, 2, 2, 0])
    truth = np.array([1, 2, 2, 0])
    result = agreement("m", predicted, truth)
    assert result.recall_percent == 100.0
    assert result.precision_percent == 100.0
    assert result.reference_overlap_percent == 50.0


def test_a_mask_that_never_fires_scores_no_recall_without_dividing_by_zero():
    result = agreement("m", np.array([1, 1, 1, 1]), np.array([2, 2, 1, 1]))
    assert result.recall_percent == 0.0
    assert result.precision_percent == 0.0


def test_over_prediction_costs_precision_and_not_recall():
    result = agreement("m", np.array([2, 2, 2, 2]), np.array([2, 2, 0, 0]))
    assert result.recall_percent == 100.0
    assert result.precision_percent == 50.0


def test_an_empty_recording_reports_nothing_rather_than_failing():
    result = agreement("m", np.empty(0), np.empty(0))
    assert result.frames == 0
    assert result.recall_percent == 0.0
