from hansard.adapters.attribution.naming import RosterSpeakerNamer
from hansard.domain.speakers import (
    ActiveSpeakerObservation,
    Diarization,
    Participant,
    Roster,
    SpeakerTurn,
)
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance


def diarization_of(turns):
    items = tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in turns)
    return Diarization(turns=items, labels=tuple(dict.fromkeys(item.label for item in items)))


def roster_of(observations, participants=()):
    return Roster(
        participants=tuple(
            Participant(identifier=name, display_name=name) for name in participants
        ),
        observations=tuple(
            ActiveSpeakerObservation(TimeSpan(start, end), name) for start, end, name in observations
        ),
    )


def transcript_of(utterances):
    return Transcript(
        utterances=tuple(
            Utterance(TimeSpan(start, end), text, speaker=speaker)
            for start, end, speaker, text in utterances
        )
    )


def test_clusters_take_the_participant_names():
    diarization = diarization_of([(0, 10, "speaker_00"), (12, 20, "speaker_01")])
    roster = roster_of(
        [(0, 10, "Aurélie Fontaine"), (12, 20, "Jean-Luc Mercier")],
        ("Aurélie Fontaine", "Jean-Luc Mercier"),
    )
    names = RosterSpeakerNamer().resolve_names(Transcript(), diarization, roster)
    assert names == {"speaker_00": "Aurélie Fontaine", "speaker_01": "Jean-Luc Mercier"}


def test_a_transcript_can_be_renamed_with_the_result():
    diarization = diarization_of([(0, 10, "speaker_00"), (12, 20, "speaker_01")])
    roster = roster_of([(0, 10, "Aurélie Fontaine"), (12, 20, "Jean-Luc Mercier")])
    transcript = transcript_of(
        [(1, 4, "speaker_00", "bonjour"), (13, 16, "speaker_01", "bonjour à toi")]
    )
    names = RosterSpeakerNamer().resolve_names(transcript, diarization, roster)
    assert transcript.renamed(names).speakers == ("Aurélie Fontaine", "Jean-Luc Mercier")


def test_an_unmatched_cluster_keeps_a_neutral_label():
    diarization = diarization_of([(0, 10, "speaker_00"), (40, 50, "speaker_01")])
    roster = roster_of([(0, 10, "Aurélie Fontaine")])
    names = RosterSpeakerNamer().resolve_names(Transcript(), diarization, roster)
    assert names["speaker_00"] == "Aurélie Fontaine"
    assert names["speaker_01"].startswith("Speaker")


def test_a_thin_margin_refuses_to_guess():
    diarization = diarization_of([(0, 10, "speaker_00")])
    roster = roster_of([(0, 5, "Aurélie Fontaine"), (5, 10, "Jean-Luc Mercier")])
    names = RosterSpeakerNamer().resolve_names(Transcript(), diarization, roster)
    assert names["speaker_00"].startswith("Speaker")


def test_no_observations_yields_neutral_labels():
    diarization = diarization_of([(0, 10, "speaker_00"), (12, 20, "speaker_01")])
    names = RosterSpeakerNamer().resolve_names(Transcript(), diarization, Roster())
    assert sorted(names.values()) == ["Speaker 1", "Speaker 2"]


def test_the_fallback_prefix_is_configurable():
    diarization = diarization_of([(0, 10, "speaker_00")])
    names = RosterSpeakerNamer(fallback_prefix="Participant").resolve_names(
        Transcript(), diarization, Roster()
    )
    assert names["speaker_00"] == "Participant 1"


def test_observation_lag_is_compensated():
    diarization = diarization_of([(0, 10, "speaker_00")])
    roster = roster_of([(1.5, 11.5, "Aurélie Fontaine")])
    named = RosterSpeakerNamer(observation_lag=1.5).resolve_names(
        Transcript(), diarization, roster
    )
    assert named["speaker_00"] == "Aurélie Fontaine"
