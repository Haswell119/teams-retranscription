from itertools import pairwise

from hansard.adapters.asr.seams import authoritative_regions, trim_to_regions
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Utterance, Word


def utterance(span, words):
    items = tuple(Word(text, TimeSpan(start, end)) for text, start, end in words)
    return Utterance(span, " ".join(item.text for item in items), words=items)


def test_the_earlier_segment_owns_the_whole_overlap():
    regions = authoritative_regions([TimeSpan(0, 10), TimeSpan(8, 18)])
    assert regions[0] == TimeSpan(0, 10)
    assert regions[1] == TimeSpan(10, 18)


def test_the_later_segment_gets_context_before_its_region_begins():
    regions = authoritative_regions([TimeSpan(0, 6), TimeSpan(4, 10), TimeSpan(8, 14)])
    assert [region.start for region in regions] == [0, 6, 10]
    assert [region.end for region in regions] == [6, 10, 14]


def test_regions_tile_the_timeline_without_gaps_or_double_cover():
    spans = [TimeSpan(0, 6), TimeSpan(4, 10), TimeSpan(8, 14)]
    regions = authoritative_regions(spans)
    for earlier, later in pairwise(regions):
        assert earlier.end == later.start


def test_a_span_swallowed_by_its_predecessor_yields_an_empty_region():
    regions = authoritative_regions([TimeSpan(0, 20), TimeSpan(5, 15)])
    assert regions[1].duration == 0.0


def test_non_overlapping_spans_are_untouched():
    spans = [TimeSpan(0, 5), TimeSpan(6, 10)]
    assert authoritative_regions(spans) == spans


def test_duplicated_words_are_emitted_once_and_kept_by_the_earlier_segment():
    first = utterance(TimeSpan(0, 10), [("alpha", 1, 2), ("beta", 8.5, 9.0)])
    second = utterance(TimeSpan(8, 18), [("beta", 8.5, 9.0), ("gamma", 12, 13)])
    trimmed = trim_to_regions([first, second], [first.span, second.span])
    assert [item.text for item in trimmed] == ["alpha beta", "gamma"]


def test_a_word_only_the_earlier_segment_heard_survives():
    first = utterance(TimeSpan(0, 10), [("alpha", 1, 2), ("beta", 9.4, 9.8)])
    second = utterance(TimeSpan(8, 18), [("gamma", 12, 13)])
    trimmed = trim_to_regions([first, second], [first.span, second.span])
    assert [item.text for item in trimmed] == ["alpha beta", "gamma"]


def test_a_single_segment_is_returned_unchanged():
    only = utterance(TimeSpan(0, 5), [("alpha", 1, 2)])
    assert trim_to_regions([only], [only.span]) == [only]


def test_a_segment_emptied_by_trimming_is_dropped():
    first = utterance(TimeSpan(0, 10), [("alpha", 1, 2), ("beta", 8.6, 8.9)])
    second = utterance(TimeSpan(8, 18), [("beta", 8.6, 8.9)])
    trimmed = trim_to_regions([first, second], [first.span, second.span])
    assert len(trimmed) == 1
