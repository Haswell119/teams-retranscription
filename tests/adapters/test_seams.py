from hansard.adapters.asr.seams import authoritative_regions, trim_to_regions
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Utterance, Word


def utterance(span, words):
    items = tuple(Word(text, TimeSpan(start, end)) for text, start, end in words)
    return Utterance(span, " ".join(item.text for item in items), words=items)


def test_regions_split_overlap_at_the_midpoint():
    regions = authoritative_regions([TimeSpan(0, 10), TimeSpan(8, 18)])
    assert regions[0].end == 9.0
    assert regions[1].start == 9.0


def test_non_overlapping_spans_are_untouched():
    spans = [TimeSpan(0, 5), TimeSpan(6, 10)]
    assert authoritative_regions(spans) == spans


def test_duplicated_words_are_emitted_once():
    first = utterance(TimeSpan(0, 10), [("alpha", 1, 2), ("beta", 8.5, 9.0)])
    second = utterance(TimeSpan(8, 18), [("beta", 8.5, 9.0), ("gamma", 12, 13)])
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
