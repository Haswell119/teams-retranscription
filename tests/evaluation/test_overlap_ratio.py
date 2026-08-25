from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.evaluation.metrics.speaker import overlap_ratio


def diarization(*items):
    turns = tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in items)
    return Diarization(turns=turns, labels=tuple(dict.fromkeys(turn.label for turn in turns)))


def test_a_meeting_where_nobody_talks_over_anybody_has_no_overlap():
    assert overlap_ratio(diarization((0.0, 10.0, "a"), (10.0, 20.0, "b"))) == 0.0


def test_an_empty_diarization_has_no_overlap():
    assert overlap_ratio(Diarization()) == 0.0


def test_two_speakers_talking_at_once_throughout_gives_half():
    assert overlap_ratio(diarization((0.0, 10.0, "a"), (0.0, 10.0, "b"))) == 0.5


def test_partial_overlap_is_measured_against_total_speaking_time():
    assert overlap_ratio(diarization((0.0, 10.0, "a"), (8.0, 18.0, "b"))) == 0.1


def test_three_way_overlap_counts_every_simultaneous_voice():
    ratio = overlap_ratio(diarization((0.0, 6.0, "a"), (0.0, 6.0, "b"), (0.0, 6.0, "c")))
    assert round(ratio, 6) == round(2 / 3, 6)


def test_a_turn_nested_inside_another_is_entirely_overlap():
    assert overlap_ratio(diarization((0.0, 20.0, "a"), (5.0, 10.0, "b"))) == 0.2
