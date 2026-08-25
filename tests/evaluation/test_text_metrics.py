import pytest

from hansard.evaluation.metrics.text import (
    aligned_word_pairs,
    character_error_rate,
    word_error_counts,
    word_error_rate,
)
from hansard.evaluation.normalizers import FrenchNormalizer


def test_single_substitution():
    result = word_error_rate("the cat sat on the mat", "the cat sat on a mat")
    assert result.substitutions == 1
    assert result.deletions == 0
    assert result.insertions == 0
    assert result.hits == 5
    assert result.reference_words == 6
    assert result.wer == pytest.approx(1 / 6)


def test_corpus_level_aggregation():
    result = word_error_rate(["a b c", "d e"], ["a x c", "d e f"])
    assert (result.substitutions, result.deletions, result.insertions) == (1, 0, 1)
    assert result.reference_words == 5
    assert result.wer == pytest.approx(0.4)


def test_deletions_and_insertions():
    counts = word_error_counts("one two three four", "one three four five")
    assert (counts.deletions, counts.insertions, counts.substitutions) == (1, 1, 0)
    assert counts.rate == pytest.approx(0.5)


def test_empty_reference_counts_hypothesis_as_insertions():
    result = word_error_rate("", "hello there")
    assert result.insertions == 2
    assert result.reference_words == 0
    assert result.wer == pytest.approx(2.0)


def test_character_error_rate_is_hand_checkable():
    assert character_error_rate("abc", "axc") == pytest.approx(1 / 3)
    assert character_error_rate("abc", "abc") == pytest.approx(0.0)


def test_normalizer_removes_spurious_errors():
    result = word_error_rate(
        "M. Dupont a 21 ans.",
        "Monsieur Dupont a vingt et un ans",
        FrenchNormalizer(),
    )
    assert result.wer == pytest.approx(0.0)


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="count mismatch"):
        word_error_rate(["a", "b"], ["a"])


def test_aligned_word_pairs_reports_equal_positions():
    assert aligned_word_pairs("a b c d", "a x c d") == ((0, 0), (2, 2), (3, 3))
