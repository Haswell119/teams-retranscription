from hansard.adapters.asr.onnx_engine import _batches
from hansard.domain.timespan import TimeSpan


def spans_of(durations):
    cursor = 0.0
    built = []
    for duration in durations:
        built.append(TimeSpan(cursor, cursor + duration))
        cursor += duration
    return built


def test_a_batch_never_exceeds_the_count_limit():
    batches = _batches(spans_of([1.0] * 9), size=4, seconds=10_000.0)
    assert [len(batch) for batch in batches] == [4, 4, 1]


def test_a_batch_never_exceeds_the_time_budget():
    batches = _batches(spans_of([100.0] * 6), size=8, seconds=240.0)
    assert all(sum(span.duration for span in batch) <= 240.0 for batch in batches)


def test_a_single_oversized_segment_still_forms_a_batch():
    batches = _batches(spans_of([600.0]), size=4, seconds=240.0)
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_every_segment_is_emitted_exactly_once():
    original = spans_of([30.0, 90.0, 120.0, 15.0, 200.0])
    emitted = [span for batch in _batches(original, size=4, seconds=240.0) for span in batch]
    assert emitted == original


def test_a_disabled_budget_falls_back_to_the_count_limit():
    batches = _batches(spans_of([500.0] * 5), size=2, seconds=0.0)
    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_no_segments_yields_no_batches():
    assert _batches([], size=4, seconds=240.0) == []


def test_a_batch_budget_accounts_for_padding_to_the_longest_segment():
    batches = _batches(spans_of([120.0, 1.5, 2.0, 3.0]), size=4, seconds=240.0)
    for batch in batches:
        longest = max(span.duration for span in batch)
        assert len(batch) * longest <= 240.0


def test_a_long_segment_does_not_drag_short_ones_into_its_padding():
    batches = _batches(spans_of([120.0, 1.5, 1.5, 1.5]), size=4, seconds=240.0)
    assert [len(batch) for batch in batches] == [2, 2]


def test_uniform_short_segments_still_fill_the_count_limit():
    batches = _batches(spans_of([30.0] * 8), size=4, seconds=240.0)
    assert [len(batch) for batch in batches] == [4, 4]
