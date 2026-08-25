from hansard.adapters.diarization.sherpa import _absorb_marginal_speakers, _absorption_floor
from hansard.domain.speakers import SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.ports.diarization import DiarizationRequest


def turns(*items):
    return tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in items)


def labels_of(collection):
    return [turn.label for turn in collection]


def test_a_speaker_below_the_floor_is_folded_into_its_nearest_stable_neighbour():
    absorbed = _absorb_marginal_speakers(
        turns((0.0, 30.0, "a"), (30.0, 32.0, "b"), (32.0, 60.0, "a")), 10.0
    )
    assert labels_of(absorbed) == ["a", "a", "a"]


def test_speakers_above_the_floor_are_left_alone():
    original = turns((0.0, 30.0, "a"), (30.0, 70.0, "b"), (70.0, 100.0, "a"))
    assert _absorb_marginal_speakers(original, 10.0) == original


def test_a_floor_of_zero_disables_absorption():
    original = turns((0.0, 30.0, "a"), (30.0, 31.0, "b"))
    assert _absorb_marginal_speakers(original, 0.0) == original


def test_absorption_never_erases_every_speaker():
    original = turns((0.0, 1.0, "a"), (2.0, 3.0, "b"))
    assert _absorb_marginal_speakers(original, 10.0) == original


def test_total_speaking_time_decides_not_the_length_of_any_single_turn():
    absorbed = _absorb_marginal_speakers(
        turns((0.0, 30.0, "a"), (30.0, 36.0, "b"), (36.0, 60.0, "a"), (60.0, 66.0, "b")), 10.0
    )
    assert labels_of(absorbed) == ["a", "b", "a", "b"]


def test_a_known_roster_disables_absorption_so_the_count_cannot_fall_below_it():
    assert _absorption_floor(DiarizationRequest(known_speaker_count=4), 10.0) == 0.0
    assert _absorption_floor(DiarizationRequest(), 10.0) == 10.0
