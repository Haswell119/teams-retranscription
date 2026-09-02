import numpy as np

from hansard.adapters.diarization.consolidation import _absorb_quiet_clusters


def unit(*values):
    vector = np.asarray(values, dtype=np.float32)
    return vector / float(np.linalg.norm(vector))


def test_nothing_is_absorbed_without_a_floor():
    assignment = {"a": "a", "b": "b"}
    centroids = {"a": unit(1.0, 0.0), "b": unit(1.0, 0.05)}
    speaking = {"a": 400.0, "b": 4.0}
    assert _absorb_quiet_clusters(assignment, centroids, speaking, 0.0, 0.55) == assignment


def test_a_quiet_cluster_that_sounds_like_a_loud_one_is_absorbed():
    assignment = {"a": "a", "b": "b"}
    centroids = {"a": unit(1.0, 0.0), "b": unit(1.0, 0.05)}
    speaking = {"a": 400.0, "b": 4.0}
    absorbed = _absorb_quiet_clusters(assignment, centroids, speaking, 10.0, 0.55)
    assert absorbed["b"] == "a"


def test_a_quiet_cluster_that_sounds_like_nobody_survives():
    assignment = {"a": "a", "b": "b"}
    centroids = {"a": unit(1.0, 0.0), "b": unit(0.0, 1.0)}
    speaking = {"a": 400.0, "b": 4.0}
    absorbed = _absorb_quiet_clusters(assignment, centroids, speaking, 10.0, 0.55)
    assert absorbed["b"] == "b"


def test_a_twelve_second_speaker_is_not_lost_merely_for_being_brief():
    assignment = {"loud": "loud", "brief": "brief"}
    centroids = {"loud": unit(1.0, 0.0, 0.0), "brief": unit(0.2, 1.0, 0.0)}
    speaking = {"loud": 380.0, "brief": 12.0}
    absorbed = _absorb_quiet_clusters(assignment, centroids, speaking, 15.0, 0.55)
    assert len(set(absorbed.values())) == 2


def test_absorption_follows_the_current_grouping_not_the_raw_labels():
    assignment = {"a": "a", "b": "a", "c": "c"}
    centroids = {"a": unit(1.0, 0.0), "b": unit(1.0, 0.02), "c": unit(1.0, 0.05)}
    speaking = {"a": 200.0, "b": 200.0, "c": 3.0}
    absorbed = _absorb_quiet_clusters(assignment, centroids, speaking, 10.0, 0.55)
    assert absorbed["c"] == "a"
    assert absorbed["a"] == "a"
    assert absorbed["b"] == "a"


def test_every_cluster_being_quiet_leaves_them_all_alone():
    assignment = {"a": "a", "b": "b"}
    centroids = {"a": unit(1.0, 0.0), "b": unit(1.0, 0.01)}
    speaking = {"a": 3.0, "b": 4.0}
    assert _absorb_quiet_clusters(assignment, centroids, speaking, 10.0, 0.55) == assignment


def test_a_cluster_without_a_centroid_is_left_where_it_is():
    assignment = {"a": "a", "b": "b"}
    centroids = {"a": unit(1.0, 0.0)}
    speaking = {"a": 400.0, "b": 2.0}
    assert _absorb_quiet_clusters(assignment, centroids, speaking, 10.0, 0.55)["b"] == "b"
