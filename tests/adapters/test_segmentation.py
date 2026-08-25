from itertools import pairwise

from hansard.adapters.enhancement.segmentation import SegmentationPolicy, plan_segments
from hansard.domain.timespan import TimeSpan


def test_short_utterances_survive():
    speech = (TimeSpan(1.0, 1.3), TimeSpan(5.0, 5.4))
    segments = plan_segments(speech, SegmentationPolicy(), 10.0)
    assert len(segments) == 2


def test_segments_below_the_floor_are_dropped():
    speech = (TimeSpan(1.0, 1.05),)
    assert plan_segments(speech, SegmentationPolicy(min_seconds=0.15), 10.0) == ()


def test_close_spans_are_merged():
    speech = (TimeSpan(0.0, 2.0), TimeSpan(2.2, 4.0))
    segments = plan_segments(speech, SegmentationPolicy(merge_gap_seconds=0.5), 10.0)
    assert len(segments) == 1


def test_distant_spans_stay_separate():
    speech = (TimeSpan(0.0, 2.0), TimeSpan(8.0, 9.0))
    assert len(plan_segments(speech, SegmentationPolicy(merge_gap_seconds=0.5), 10.0)) == 2


def test_long_spans_split_with_overlap():
    speech = (TimeSpan(0.0, 70.0),)
    segments = plan_segments(
        speech, SegmentationPolicy(max_seconds=30.0, split_overlap_seconds=2.0, padding_seconds=0.0), 70.0
    )
    assert len(segments) >= 3
    for earlier, later in pairwise(segments):
        assert later.start < earlier.end


def test_splits_cover_the_whole_span():
    speech = (TimeSpan(0.0, 70.0),)
    segments = plan_segments(speech, SegmentationPolicy(max_seconds=30.0, padding_seconds=0.0), 70.0)
    assert segments[0].start == 0.0
    assert segments[-1].end == 70.0


def test_padding_is_clamped_to_the_recording():
    speech = (TimeSpan(0.0, 1.0),)
    segments = plan_segments(speech, SegmentationPolicy(padding_seconds=5.0), 2.0)
    assert segments[0].start == 0.0
    assert segments[0].end == 2.0


def test_no_speech_falls_back_to_the_whole_recording():
    segments = plan_segments((), SegmentationPolicy(max_seconds=30.0), 45.0)
    assert segments[0].start == 0.0
    assert sum(segment.duration for segment in segments) >= 45.0


def test_empty_recording_yields_nothing():
    assert plan_segments((), SegmentationPolicy(), 0.0) == ()
