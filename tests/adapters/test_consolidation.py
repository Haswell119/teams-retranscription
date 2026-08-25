import numpy as np

from hansard.adapters.diarization.consolidation import _agglomerate


def unit(values):
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_similar_centroids_merge():
    centroids = {"a": unit([1.0, 0.0]), "b": unit([0.98, 0.2]), "c": unit([0.0, 1.0])}
    mapping = _agglomerate(centroids, threshold=0.9)
    assert mapping["a"] == mapping["b"]
    assert mapping["c"] != mapping["a"]


def test_a_high_threshold_merges_nothing():
    centroids = {"a": unit([1.0, 0.0]), "b": unit([0.9, 0.4])}
    mapping = _agglomerate(centroids, threshold=0.99)
    assert mapping["a"] != mapping["b"]


def test_merging_is_transitive():
    centroids = {"a": unit([1.0, 0.0]), "b": unit([0.99, 0.1]), "c": unit([0.98, 0.2])}
    mapping = _agglomerate(centroids, threshold=0.95)
    assert len(set(mapping.values())) == 1


def test_labels_are_preserved_when_distinct():
    centroids = {"a": unit([1.0, 0.0]), "b": unit([0.0, 1.0]), "c": unit([0.0, -1.0])}
    mapping = _agglomerate(centroids, threshold=0.5)
    assert len(set(mapping.values())) == 3
