from hansard.adapters.diarization.refinement import SpeechCoverageRefiner
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan


def test_turns_extend_over_detected_speech():
    diarization = Diarization(
        turns=(SpeakerTurn(TimeSpan(0, 2), "A"), SpeakerTurn(TimeSpan(5, 7), "B")), labels=("A", "B")
    )
    refined = SpeechCoverageRefiner().refine(diarization, (TimeSpan(0, 3.0), TimeSpan(4.5, 7.5)))
    spans = [(turn.span.start, turn.span.end, turn.label) for turn in refined.turns]
    assert spans == [(0.0, 3.0, "A"), (4.5, 7.5, "B")]


def test_gaps_beyond_the_horizon_are_left_alone():
    diarization = Diarization(turns=(SpeakerTurn(TimeSpan(0, 2), "A"),), labels=("A",))
    refined = SpeechCoverageRefiner(maximum_extension=0.5).refine(diarization, (TimeSpan(10, 12),))
    assert refined.turns == diarization.turns


def test_tiny_gaps_are_ignored():
    diarization = Diarization(turns=(SpeakerTurn(TimeSpan(0, 2), "A"),), labels=("A",))
    refined = SpeechCoverageRefiner(minimum_gap=1.0).refine(diarization, (TimeSpan(0, 2.2),))
    assert refined.turns == diarization.turns


def test_empty_inputs_are_safe():
    assert SpeechCoverageRefiner().refine(Diarization(), (TimeSpan(0, 1),)) == Diarization()
