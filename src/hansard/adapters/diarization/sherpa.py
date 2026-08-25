from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hansard.domain.audio import AudioClip
from hansard.domain.errors import DiarizationError
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.ports.diarization import DiarizationRequest

SEGMENTATION_FILENAME = "sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx"
EMBEDDING_FILENAME = "nemo_en_titanet_small.onnx"


@dataclass(slots=True)
class SherpaDiarizer:
    models_dir: Path
    segmentation_model: str = SEGMENTATION_FILENAME
    embedding_model: str = EMBEDDING_FILENAME
    num_threads: int = 4
    provider: str = "cpu"
    clustering_threshold: float = 0.99
    min_duration_on: float = 0.25
    min_duration_off: float = 0.40
    window_shift_ratio: float = 0.1
    minimum_speaker_seconds: float = 3.0
    _engine: Any | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return "sherpa-onnx"

    @property
    def max_supported_speakers(self) -> int:
        return 32

    def _resolve(self, filename: str) -> Path:
        path = self.models_dir / filename
        if not path.exists():
            raise DiarizationError(f"diarization model missing: {path}")
        return path

    def _build(self, request: DiarizationRequest) -> Any:
        import sherpa_onnx

        segmentation = sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(self._resolve(self.segmentation_model)),
                window_shift_ratio=self.window_shift_ratio,
            ),
            num_threads=self.num_threads,
            provider=self.provider,
        )
        embedding = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(self._resolve(self.embedding_model)),
            num_threads=self.num_threads,
            provider=self.provider,
        )
        clustering = sherpa_onnx.FastClusteringConfig(
            num_clusters=_bounded_cluster_count(request),
            threshold=self.clustering_threshold,
        )
        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=segmentation,
            embedding=embedding,
            clustering=clustering,
            min_duration_on=self.min_duration_on,
            min_duration_off=self.min_duration_off,
        )
        if not config.validate():
            raise DiarizationError("invalid sherpa-onnx diarization configuration")
        return sherpa_onnx.OfflineSpeakerDiarization(config)

    def diarize(self, clip: AudioClip, request: DiarizationRequest) -> Diarization:
        if clip.frame_count == 0:
            return Diarization()
        engine = self._build(request)
        if clip.sample_rate != engine.sample_rate:
            raise DiarizationError(
                f"diarizer expects {engine.sample_rate} Hz, received {clip.sample_rate} Hz"
            )
        outcome = engine.process(clip.samples).sort_by_start_time()
        turns = tuple(
            SpeakerTurn(
                span=TimeSpan(float(segment.start), float(segment.end)).shifted(clip.offset),
                label=f"speaker_{segment.speaker:02d}",
            )
            for segment in outcome
            if segment.end > segment.start
        )
        turns = _absorb_marginal_speakers(turns, self.minimum_speaker_seconds)
        labels = tuple(dict.fromkeys(turn.label for turn in turns))
        return Diarization(turns=turns, labels=labels)


def _bounded_cluster_count(request: DiarizationRequest) -> int:
    known = request.known_speaker_count
    if not known:
        return -1
    return max(request.min_speakers, min(known, request.max_speakers))


def _absorb_marginal_speakers(
    turns: tuple[SpeakerTurn, ...], minimum_seconds: float
) -> tuple[SpeakerTurn, ...]:
    if len(turns) < 2 or minimum_seconds <= 0.0:
        return turns
    totals: dict[str, float] = {}
    for turn in turns:
        totals[turn.label] = totals.get(turn.label, 0.0) + turn.span.duration
    marginal = {label for label, total in totals.items() if total < minimum_seconds}
    if not marginal or len(marginal) == len(totals):
        return turns
    ordered = sorted(turns, key=lambda turn: turn.span.start)
    absorbed: list[SpeakerTurn] = []
    for position, turn in enumerate(ordered):
        if turn.label not in marginal:
            absorbed.append(turn)
            continue
        neighbour = _nearest_stable_label(ordered, position, marginal)
        absorbed.append(SpeakerTurn(turn.span, neighbour or turn.label, turn.confidence * 0.5))
    return tuple(absorbed)


def _nearest_stable_label(ordered: list[SpeakerTurn], position: int, marginal: set[str]) -> str | None:
    offset = 1
    while position - offset >= 0 or position + offset < len(ordered):
        for index in (position - offset, position + offset):
            if 0 <= index < len(ordered) and ordered[index].label not in marginal:
                return ordered[index].label
        offset += 1
    return None
