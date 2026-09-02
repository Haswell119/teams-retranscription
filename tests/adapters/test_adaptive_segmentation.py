from hansard.adapters.enhancement.segmentation import (
    SegmentationPolicy,
    ceiling_for,
    plan_segments,
    speech_ratio,
)
from hansard.domain.timespan import TimeSpan


def spans(*pairs):
    return tuple(TimeSpan(start, end) for start, end in pairs)


def continuous(count, span_seconds, gap_seconds):
    step = span_seconds + gap_seconds
    return tuple(TimeSpan(index * step, index * step + span_seconds) for index in range(count))


def test_speech_ratio_is_covered_time_over_duration():
    assert speech_ratio(spans((0.0, 5.0), (10.0, 15.0)), 20.0) == 0.5


def test_speech_ratio_of_nothing_is_zero():
    assert speech_ratio((), 20.0) == 0.0
    assert speech_ratio(spans((0.0, 5.0)), 0.0) == 0.0


def test_speech_ratio_never_exceeds_one():
    assert speech_ratio(spans((0.0, 30.0), (0.0, 30.0)), 20.0) == 1.0


def test_a_room_with_real_pauses_keeps_the_long_ceiling():
    policy = SegmentationPolicy(max_seconds=120.0)
    sparse = continuous(10, span_seconds=14.0, gap_seconds=6.0)
    assert ceiling_for(sparse, policy, 200.0) == 120.0


def test_speech_with_almost_no_silence_gets_the_short_ceiling():
    policy = SegmentationPolicy(max_seconds=120.0)
    dense = continuous(10, span_seconds=19.0, gap_seconds=1.0)
    assert ceiling_for(dense, policy, 200.0) == 15.0


def test_the_threshold_is_where_it_says_it_is():
    policy = SegmentationPolicy(max_seconds=120.0, dense_speech_ratio=0.85)
    assert ceiling_for(spans((0.0, 84.0)), policy, 100.0) == 120.0
    assert ceiling_for(spans((0.0, 86.0)), policy, 100.0) == 15.0


def test_a_dense_ceiling_at_or_above_the_normal_one_is_ignored():
    policy = SegmentationPolicy(max_seconds=120.0, dense_max_seconds=120.0)
    assert ceiling_for(spans((0.0, 99.0)), policy, 100.0) == 120.0


def test_the_adaptation_can_be_turned_off():
    policy = SegmentationPolicy(max_seconds=120.0, dense_max_seconds=0.0)
    assert ceiling_for(spans((0.0, 99.0)), policy, 100.0) == 120.0


def test_dense_audio_is_cut_into_more_segments_than_sparse_audio():
    policy = SegmentationPolicy(max_seconds=120.0)
    dense = plan_segments(continuous(10, 19.0, 1.0), policy, 200.0)
    sparse = plan_segments(continuous(10, 14.0, 6.0), policy, 200.0)
    assert len(dense) > len(sparse)
    assert max(item.duration for item in dense) <= 15.0 + 2 * policy.padding_seconds


def test_no_speech_still_covers_the_whole_recording():
    policy = SegmentationPolicy(max_seconds=120.0)
    planned = plan_segments((), policy, 300.0)
    assert planned
    assert planned[0].start == 0.0
    assert max(item.duration for item in planned) <= 120.0


def test_a_single_long_dense_span_is_split_at_the_short_ceiling():
    policy = SegmentationPolicy(max_seconds=120.0)
    planned = plan_segments(spans((0.0, 100.0)), policy, 100.0)
    assert len(planned) > 1
    assert max(item.duration for item in planned) <= 15.0 + 2 * policy.padding_seconds


def test_a_single_long_sparse_span_keeps_the_long_ceiling():
    policy = SegmentationPolicy(max_seconds=120.0)
    planned = plan_segments(spans((0.0, 60.0)), policy, 200.0)
    assert len(planned) == 1
