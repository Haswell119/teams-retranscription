from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from hansard.domain.audio import AudioClip
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan

_NEIGHBOURHOOD = 64


@dataclass(slots=True)
class EmbeddingClusterConsolidator:
    models_dir: Path
    embedding_model: str = "nemo_en_titanet_small.onnx"
    num_threads: int = 4
    provider: str = "cpu"
    merge_similarity: float = 0.60
    samples_per_cluster: int = 8
    minimum_segment_seconds: float = 1.2
    clean_embedding_samples: bool = True
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
        contested = contested_fractions(diarization)
        by_label: dict[str, list[tuple[TimeSpan, float]]] = {label: [] for label in labels}
        for turn in diarization.turns:
            if turn.span.duration >= self.minimum_segment_seconds:
                by_label[turn.label].append((turn.span, contested.get(turn.span, 0.0)))
        extractor = self._load()
        centroids: dict[str, np.ndarray] = {}
        for label, samples in by_label.items():
            chosen = [span for span, _ in _ranked(samples, self.clean_embedding_samples)][
                : self.samples_per_cluster
            ]
            centroid = self._centroid(extractor, clip, chosen)
            if centroid is not None:
                centroids[label] = centroid
        if len(centroids) < 2:
            return diarization
        merged = _agglomerate(centroids, self.merge_similarity, ceiling)
        if len(set(merged.values())) == len(centroids):
            return diarization
        turns = tuple(
            SpeakerTurn(turn.span, merged.get(turn.label, turn.label), turn.confidence)
            for turn in diarization.turns
        )
        return Diarization(turns=turns, labels=tuple(dict.fromkeys(turn.label for turn in turns)))


def contested_fractions(diarization: Diarization) -> dict[TimeSpan, float]:
    turns = sorted(diarization.turns, key=lambda turn: turn.span.start)
    contested: dict[TimeSpan, float] = {}
    for index, turn in enumerate(turns):
        if turn.span.duration <= 0.0:
            contested[turn.span] = 0.0
            continue
        covered = 0.0
        cursor = turn.span.start
        for other in turns[max(0, index - _NEIGHBOURHOOD) : index + _NEIGHBOURHOOD]:
            if other.label == turn.label or other.span.end <= cursor:
                continue
            if other.span.start >= turn.span.end:
                break
            start = max(other.span.start, cursor)
            end = min(other.span.end, turn.span.end)
            if end > start:
                covered += end - start
                cursor = end
        contested[turn.span] = min(1.0, covered / turn.span.duration)
    return contested


def _ranked(samples: list[tuple[TimeSpan, float]], prefer_clean: bool) -> list[tuple[TimeSpan, float]]:
    if not prefer_clean:
        return sorted(samples, key=lambda item: -item[0].duration)
    return sorted(samples, key=lambda item: (round(item[1], 2), -item[0].duration))


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
