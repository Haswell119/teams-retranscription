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

    def consolidate(self, diarization: Diarization, clip: AudioClip) -> Diarization:
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
        merged = _agglomerate(centroids, self.merge_similarity)
        if len(set(merged.values())) == len(centroids):
            return diarization
        turns = tuple(
            SpeakerTurn(turn.span, merged.get(turn.label, turn.label), turn.confidence)
            for turn in diarization.turns
        )
        return Diarization(turns=turns, labels=tuple(dict.fromkeys(turn.label for turn in turns)))


def _agglomerate(centroids: dict[str, np.ndarray], threshold: float) -> dict[str, str]:
    labels = list(centroids)
    parent = {label: label for label in labels}

    def root(label: str) -> str:
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    pairs: list[tuple[float, str, str]] = []
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            similarity = float(np.dot(centroids[left], centroids[right]))
            if similarity >= threshold:
                pairs.append((similarity, left, right))
    for _, left, right in sorted(pairs, reverse=True):
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)
    return {label: root(label) for label in labels}
