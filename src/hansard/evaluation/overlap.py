from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

from hansard.domain.errors import ConfigurationError
from hansard.domain.speakers import Diarization

POWERSET_CLASSES: tuple[tuple[int, ...], ...] = (
    (),
    (0,),
    (1,),
    (2,),
    (0, 1),
    (0, 2),
    (1, 2),
)
WINDOW_SAMPLES = 160_000
FRAME_SHIFT_SAMPLES = 270
SAMPLE_RATE = 16_000


@dataclass(frozen=True, slots=True)
class OverlapAgreement:
    meeting: str
    frames: int
    reference_overlap_percent: float
    predicted_overlap_percent: float
    recall_percent: float
    precision_percent: float

    def as_row(self) -> dict[str, object]:
        return {
            "meeting": self.meeting,
            "frames": self.frames,
            "reference_overlap_percent": round(self.reference_overlap_percent, 2),
            "predicted_overlap_percent": round(self.predicted_overlap_percent, 2),
            "recall_percent": round(self.recall_percent, 2),
            "precision_percent": round(self.precision_percent, 2),
        }


def load_segmenter(model: Path) -> ort.InferenceSession:
    if not model.exists():
        raise ConfigurationError(f"segmentation model missing: {model}")
    return ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])


def speaker_counts(session: ort.InferenceSession, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sizes = np.array([len(members) for members in POWERSET_CLASSES], dtype=np.int64)
    centres: list[np.ndarray] = []
    counts: list[np.ndarray] = []
    for start in range(0, max(len(samples), 1), WINDOW_SAMPLES):
        window = samples[start : start + WINDOW_SAMPLES]
        if len(window) < WINDOW_SAMPLES:
            window = np.pad(window, (0, WINDOW_SAMPLES - len(window)))
        logits = session.run(None, {"x": window[None, None, :].astype(np.float32)})[0][0]
        chosen = sizes[logits.argmax(axis=-1)]
        offsets = np.arange(len(chosen)) * FRAME_SHIFT_SAMPLES + FRAME_SHIFT_SAMPLES / 2.0
        centres.append((start + offsets) / SAMPLE_RATE)
        counts.append(chosen)
    if not centres:
        return np.empty(0), np.empty(0, dtype=np.int64)
    return np.concatenate(centres), np.concatenate(counts)


def reference_counts(diarization: Diarization, moments: np.ndarray) -> np.ndarray:
    starts = np.array(sorted(turn.span.start for turn in diarization.turns))
    ends = np.array(sorted(turn.span.end for turn in diarization.turns))
    if starts.size == 0:
        return np.zeros(len(moments), dtype=np.int64)
    began = np.array([bisect_right(starts, moment) for moment in moments])
    finished = np.array([bisect_right(ends, moment) for moment in moments])
    counted: np.ndarray = (began - finished).astype(np.int64)
    return counted


def agreement(meeting: str, predicted: np.ndarray, reference: np.ndarray) -> OverlapAgreement:
    total = len(predicted)
    if total == 0:
        return OverlapAgreement(meeting, 0, 0.0, 0.0, 0.0, 0.0)
    hypothesis = predicted >= 2
    truth = reference >= 2
    hits = int(np.count_nonzero(hypothesis & truth))
    return OverlapAgreement(
        meeting=meeting,
        frames=total,
        reference_overlap_percent=100.0 * int(np.count_nonzero(truth)) / total,
        predicted_overlap_percent=100.0 * int(np.count_nonzero(hypothesis)) / total,
        recall_percent=100.0 * hits / max(int(np.count_nonzero(truth)), 1),
        precision_percent=100.0 * hits / max(int(np.count_nonzero(hypothesis)), 1),
    )
