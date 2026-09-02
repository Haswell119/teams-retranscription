from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hansard.domain.audio import AudioClip
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan


@dataclass(slots=True)
class EmbeddingClusterConsolidator:
    models_dir: Path
    embedding_model: str = "nemo_en_titanet_small.onnx"
    num_threads: int = 4
    provider: str = "cpu"
    merge_similarity: float = 0.60
    samples_per_cluster: int = 8
    minimum_segment_seconds: float = 1.2
    minimum_speaker_seconds: float = 0.0
    absorption_similarity: float = 0.55
    _extractor: Any | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return "embedding-consolidation"

    def _load(self) -> Any:
        if self._extractor is None:
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(self.models_dir / self.embedding_model),
                num_threads=self.num_threads,
                provider=self.provider,
            )
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        return self._extractor

    def _centroid(self, extractor: Any, clip: AudioClip, spans: list[TimeSpan]) -> np.ndarray | None:
        vectors: list[np.ndarray] = []
        for span in spans:
            samples = clip.extract(span).samples
            if samples.size < clip.sample_rate:
                continue
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=clip.sample_rate, waveform=samples)
            stream.input_finished()
            if not extractor.is_ready(stream):
                continue
            vector = np.asarray(extractor.compute(stream), dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vectors.append(vector / norm)
        if not vectors:
            return None
        mean = np.mean(np.stack(vectors), axis=0)
        norm = float(np.linalg.norm(mean))
        return mean / norm if norm > 0 else None

    def consolidate(
        self, diarization: Diarization, clip: AudioClip, ceiling: int | None = None
    ) -> Diarization:
        labels = list(diarization.labels or dict.fromkeys(turn.label for turn in diarization.turns))
        if len(labels) < 2:
            return diarization
        by_label: dict[str, list[TimeSpan]] = {label: [] for label in labels}
        for turn in diarization.turns:
            if turn.span.duration >= self.minimum_segment_seconds:
                by_label[turn.label].append(turn.span)
        extractor = self._load()
        centroids: dict[str, np.ndarray] = {}
        for label, spans in by_label.items():
            chosen = sorted(spans, key=lambda span: -span.duration)[: self.samples_per_cluster]
            centroid = self._centroid(extractor, clip, chosen)
            if centroid is not None:
                centroids[label] = centroid
        if len(centroids) < 2:
            return diarization
        merged = _agglomerate(centroids, self.merge_similarity, ceiling)
        rescued = _absorb_quiet_clusters(
            merged,
            centroids,
            diarization.speaking_time(),
            self.minimum_speaker_seconds,
            self.absorption_similarity,
        )
        if len(set(rescued.values())) == len(centroids):
            return diarization
        turns = tuple(
            SpeakerTurn(turn.span, rescued.get(turn.label, turn.label), turn.confidence)
            for turn in diarization.turns
        )
        return Diarization(turns=turns, labels=tuple(dict.fromkeys(turn.label for turn in turns)))


def _agglomerate(
    centroids: dict[str, np.ndarray], threshold: float, ceiling: int | None = None
) -> dict[str, str]:
    labels = list(centroids)
    parent = {label: label for label in labels}
    groups = len(labels)

    def root(label: str) -> str:
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    pairs: list[tuple[float, str, str]] = []
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            pairs.append((float(np.dot(centroids[left], centroids[right])), left, right))
    for similarity, left, right in sorted(pairs, reverse=True):
        left_root, right_root = root(left), root(right)
        if left_root == right_root:
            continue
        if similarity < threshold and (ceiling is None or groups <= ceiling):
            continue
        parent[max(left_root, right_root)] = min(left_root, right_root)
        groups -= 1
    return {label: root(label) for label in labels}


def _absorb_quiet_clusters(
    assignment: dict[str, str],
    centroids: dict[str, np.ndarray],
    speaking: dict[str, float],
    minimum_seconds: float,
    similarity: float,
) -> dict[str, str]:
    if minimum_seconds <= 0.0:
        return assignment
    totals: dict[str, float] = {}
    for label, group in assignment.items():
        totals[group] = totals.get(group, 0.0) + speaking.get(label, 0.0)
    quiet = {group for group, total in totals.items() if total < minimum_seconds}
    loud = [group for group in totals if group not in quiet]
    if not quiet or not loud:
        return assignment
    absorbed = dict(assignment)
    for group in sorted(quiet):
        members = [label for label, target in assignment.items() if target == group]
        centre = _mean_direction([centroids[label] for label in members if label in centroids])
        if centre is None:
            continue
        best, score = _closest(centre, loud, assignment, centroids)
        if best is None or score < similarity:
            continue
        for label in members:
            absorbed[label] = best
    return absorbed


def _closest(
    centre: np.ndarray,
    candidates: list[str],
    assignment: dict[str, str],
    centroids: dict[str, np.ndarray],
) -> tuple[str | None, float]:
    best: str | None = None
    score = -1.0
    for group in candidates:
        members = [centroids[label] for label, target in assignment.items() if target == group]
        other = _mean_direction(members)
        if other is None:
            continue
        similarity = float(np.dot(centre, other))
        if similarity > score:
            best, score = group, similarity
    return best, score


def _mean_direction(vectors: list[np.ndarray]) -> np.ndarray | None:
    if not vectors:
        return None
    mean = np.mean(np.stack(vectors), axis=0)
    norm = float(np.linalg.norm(mean))
    return mean / norm if norm > 0 else None
