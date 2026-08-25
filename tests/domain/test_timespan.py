import pytest

from hansard.domain.timespan import TimeSpan, merge_adjacent, total_duration


def test_duration_and_midpoint():
    span = TimeSpan(2.0, 5.0)
    assert span.duration == 3.0
    assert span.midpoint == 3.5


def test_rejects_inverted_span():
    with pytest.raises(ValueError, match="precedes start"):
        TimeSpan(4.0, 1.0)


def test_overlap_and_intersection():
    assert TimeSpan(0, 10).overlap(TimeSpan(5, 15)) == 5
    assert TimeSpan(0, 10).overlap(TimeSpan(10, 15)) == 0
    assert not TimeSpan(0, 10).intersects(TimeSpan(10, 15))


def test_contains_is_half_open():
    span = TimeSpan(1.0, 2.0)
    assert span.contains(1.0)
    assert not span.contains(2.0)


def test_clamped_keeps_bounds():
    assert TimeSpan(-3, 20).clamped(0, 10) == TimeSpan(0, 10)


def test_merge_adjacent_respects_gap():
    spans = [TimeSpan(0, 1), TimeSpan(1.2, 2), TimeSpan(5, 6)]
    assert merge_adjacent(spans, 0.5) == [TimeSpan(0, 2), TimeSpan(5, 6)]
    assert merge_adjacent(spans, 0.1) == spans


def test_total_duration_deduplicates_overlap():
    assert total_duration([TimeSpan(0, 5), TimeSpan(3, 8)]) == 8
