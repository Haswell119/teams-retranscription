from hansard.adapters.diarization.consolidation import _ranked, contested_fractions
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan


def diarization(*turns):
    resolved = tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in turns)
    return Diarization(turns=resolved, labels=tuple(dict.fromkeys(turn.label for turn in resolved)))


def test_a_turn_nobody_talks_over_is_uncontested():
    contested = contested_fractions(diarization((0.0, 10.0, "A"), (20.0, 30.0, "B")))
    assert contested[TimeSpan(0.0, 10.0)] == 0.0
    assert contested[TimeSpan(20.0, 30.0)] == 0.0


def test_a_turn_half_covered_by_another_speaker_is_half_contested():
    contested = contested_fractions(diarization((0.0, 10.0, "A"), (5.0, 10.0, "B")))
    assert contested[TimeSpan(0.0, 10.0)] == 0.5


def test_a_turn_wholly_inside_another_is_entirely_contested():
    contested = contested_fractions(diarization((0.0, 10.0, "A"), (2.0, 7.0, "B")))
    assert contested[TimeSpan(2.0, 7.0)] == 1.0


def test_the_same_speaker_talking_again_does_not_contest_itself():
    contested = contested_fractions(diarization((0.0, 10.0, "A"), (0.0, 10.0, "A")))
    assert contested[TimeSpan(0.0, 10.0)] == 0.0


def test_two_speakers_covering_the_same_stretch_are_not_counted_twice():
    contested = contested_fractions(diarization((0.0, 10.0, "A"), (0.0, 5.0, "B"), (0.0, 5.0, "C")))
    assert contested[TimeSpan(0.0, 10.0)] == 0.5


def test_a_zero_length_turn_is_uncontested_rather_than_undefined():
    contested = contested_fractions(diarization((4.0, 4.0, "A"), (0.0, 10.0, "B")))
    assert contested[TimeSpan(4.0, 4.0)] == 0.0


def test_the_cleanest_sample_wins_over_the_longest():
    samples = [(TimeSpan(0.0, 30.0), 0.9), (TimeSpan(40.0, 44.0), 0.0)]
    assert [span.start for span, _ in _ranked(samples, True)] == [40.0, 0.0]


def test_length_still_breaks_a_tie_between_equally_clean_samples():
    samples = [(TimeSpan(0.0, 4.0), 0.0), (TimeSpan(10.0, 30.0), 0.0)]
    assert [span.start for span, _ in _ranked(samples, True)] == [10.0, 0.0]


def test_near_equal_contest_is_rounded_so_length_decides():
    samples = [(TimeSpan(0.0, 30.0), 0.101), (TimeSpan(40.0, 44.0), 0.104)]
    assert [span.start for span, _ in _ranked(samples, True)] == [0.0, 40.0]


def test_the_old_behaviour_is_still_reachable():
    samples = [(TimeSpan(0.0, 30.0), 0.9), (TimeSpan(40.0, 44.0), 0.0)]
    assert [span.start for span, _ in _ranked(samples, False)] == [0.0, 40.0]


def test_an_empty_diarization_contests_nothing():
    assert contested_fractions(Diarization()) == {}
