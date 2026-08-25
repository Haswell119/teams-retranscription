from pathlib import Path

import numpy as np

from hansard.adapters.diarization.consolidation import _agglomerate
from hansard.application.pipeline import _speaker_ceiling
from hansard.domain.meeting import MeetingRequest
from hansard.domain.speakers import Participant, Roster


def unit(*values):
    vector = np.asarray(values, dtype=np.float32)
    return vector / float(np.linalg.norm(vector))


FAR_APART = {
    "a": unit(1.0, 0.0, 0.0),
    "b": unit(0.0, 1.0, 0.0),
    "c": unit(0.0, 0.0, 1.0),
}


def groups(mapping):
    return len(set(mapping.values()))


def test_dissimilar_clusters_survive_when_no_ceiling_applies():
    assert groups(_agglomerate(FAR_APART, 0.70)) == 3


def test_a_generous_ceiling_changes_nothing():
    assert groups(_agglomerate(FAR_APART, 0.70, 8)) == 3


def test_a_tight_ceiling_forces_merging_below_the_similarity_floor():
    assert groups(_agglomerate(FAR_APART, 0.70, 2)) == 2


def test_the_ceiling_merges_the_most_similar_pair_first():
    centroids = {"a": unit(1.0, 0.0), "b": unit(0.99, 0.14), "c": unit(0.0, 1.0)}
    merged = _agglomerate(centroids, 0.999, 2)
    assert merged["a"] == merged["b"]
    assert merged["c"] != merged["a"]


def test_similar_clusters_still_merge_on_similarity_alone():
    centroids = {"a": unit(1.0, 0.0), "b": unit(0.99, 0.14)}
    assert groups(_agglomerate(centroids, 0.70)) == 1


def request_with(**kwargs):
    return MeetingRequest(audio_path=Path("meeting.wav"), title="meeting", **kwargs)


def roster_of(count):
    return Roster(
        participants=tuple(
            Participant(identifier=f"p{index}", display_name=f"Person {index}") for index in range(count)
        )
    )


def test_an_explicit_speaker_count_wins_over_the_roster():
    assert _speaker_ceiling(request_with(speaker_count=3), roster_of(9)) == 3


def test_the_roster_size_becomes_the_ceiling():
    assert _speaker_ceiling(request_with(), roster_of(6)) == 6


def test_expected_participants_are_used_when_no_roster_arrived():
    assert _speaker_ceiling(request_with(expected_participants=("Ada", "Grace")), None) == 2


def test_nothing_known_means_no_ceiling():
    assert _speaker_ceiling(request_with(), None) is None
    assert _speaker_ceiling(request_with(), Roster()) is None
