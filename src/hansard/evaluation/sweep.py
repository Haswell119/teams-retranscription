from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from hansard.adapters.attribution.fusion import WordLevelAttributor
from hansard.adapters.audio import load_clip
from hansard.adapters.diarization.consolidation import EmbeddingClusterConsolidator
from hansard.adapters.diarization.refinement import SpeechCoverageRefiner
from hansard.adapters.diarization.registry import build_diarizer
from hansard.config import Settings
from hansard.domain.audio import AudioClip
from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance, Word
from hansard.evaluation.metrics.quiet import QuietSpeakerReport, quiet_speaker_report
from hansard.evaluation.metrics.speaker import (
    concatenated_minimum_permutation_wer,
    diarization_error_rate,
    jaccard_error_rate,
    word_diarization_error_rate,
)
from hansard.evaluation.normalizers import NORMALIZER_VERSION, normalizer_for
from hansard.factory import Composition
from hansard.ports.diarization import DiarizationRequest

SWEEP_VERSION = "hansard-sweep-1.0.0"

DIARIZER_KEYS: tuple[str, ...] = (
    "embedding_model",
    "segmentation_model",
    "clustering_threshold",
    "min_duration_on",
    "min_duration_off",
    "cluster_consolidation",
)

CONSOLIDATION_KEYS: tuple[str, ...] = (
    "merge_similarity",
    "minimum_speaker_seconds",
    "absorption_similarity",
    "speech_coverage_refinement",
)

SWEEP_KEYS: tuple[str, ...] = DIARIZER_KEYS + CONSOLIDATION_KEYS


@dataclass(frozen=True, slots=True)
class SweepMeeting:
    identifier: str
    audio: Path
    language: str
    reference: Transcript
    reference_diarization: Diarization


@dataclass(frozen=True, slots=True)
class SweepPoint:
    label: str
    overrides: Mapping[str, object] = field(default_factory=dict)

    def applied(self, settings: Settings) -> Settings:
        updated = settings.model_copy(deep=True)
        for key, value in self.overrides.items():
            if key not in SWEEP_KEYS:
                raise ValueError(f"cannot sweep unknown diarization setting {key!r}")
            setattr(updated.diarization, key, value)
        return updated


def cached_transcript(
    meeting: SweepMeeting, settings: Settings, cache: Path
) -> tuple[Transcript, AudioClip, tuple[TimeSpan, ...]]:
    clip = load_clip(meeting.audio)
    path = cache / f"{meeting.identifier}.json"
    if path.exists():
        return _read_transcript(path, meeting.language, clip.duration, clip)
    pipeline = Composition(settings).pipeline()
    pipeline.diarizer = None
    pipeline.consolidator = None
    pipeline.refiner = None
    pipeline.namer = None
    from hansard.domain.meeting import MeetingRequest

    outcome = pipeline.run(
        clip, MeetingRequest(audio_path=meeting.audio, title=meeting.identifier, language=meeting.language)
    )
    _write_transcript(path, outcome.transcript, outcome.speech_spans)
    return outcome.transcript, clip, outcome.speech_spans


def clusters_only(
    clip: AudioClip, settings: Settings, models_dir: Path, speaker_ceiling: int | None = None
) -> tuple[Diarization, float]:
    diarizer = build_diarizer(settings.diarization, models_dir)
    started = time.perf_counter()
    diarization = diarizer.diarize(
        clip,
        DiarizationRequest(
            max_speakers=min(settings.diarization.max_speakers, diarizer.max_supported_speakers),
            min_speakers=settings.diarization.min_speakers,
            known_speaker_count=None,
            speaker_ceiling=speaker_ceiling,
        ),
    )
    return diarization, time.perf_counter() - started


def consolidated(
    diarization: Diarization,
    clip: AudioClip,
    settings: Settings,
    models_dir: Path,
    speaker_ceiling: int | None = None,
) -> Diarization:
    if not settings.diarization.cluster_consolidation or diarization.speaker_count < 2:
        return diarization
    consolidator = EmbeddingClusterConsolidator(
        models_dir=models_dir,
        embedding_model=settings.diarization.embedding_model,
        merge_similarity=settings.diarization.merge_similarity,
        minimum_speaker_seconds=settings.diarization.minimum_speaker_seconds,
        absorption_similarity=settings.diarization.absorption_similarity,
    )
    return consolidator.consolidate(diarization, clip, speaker_ceiling)


def diarize_once(
    clip: AudioClip, settings: Settings, models_dir: Path, speaker_ceiling: int | None = None
) -> tuple[Diarization, float]:
    diarization, elapsed = clusters_only(clip, settings, models_dir, speaker_ceiling)
    return consolidated(diarization, clip, settings, models_dir, speaker_ceiling), elapsed


def diarizer_signature(settings: Settings) -> tuple[object, ...]:
    return tuple(getattr(settings.diarization, key) for key in DIARIZER_KEYS)


def score_point(
    meeting: SweepMeeting,
    transcript: Transcript,
    diarization: Diarization,
    speech: Sequence[TimeSpan] = (),
    refine: bool = True,
) -> dict[str, object]:
    resolved = diarization
    if refine and speech and diarization.turns:
        resolved = SpeechCoverageRefiner().refine(diarization, tuple(speech))
    attributed = WordLevelAttributor().attribute(transcript, resolved)
    normalizer = normalizer_for(meeting.language)
    strict = diarization_error_rate(meeting.reference_diarization, resolved, collar=0.0)
    quiet = quiet_speaker_report(
        meeting.reference, attributed, meeting.reference_diarization, resolved, normalizer
    )
    return {
        "meeting": meeting.identifier,
        "detected_speakers": resolved.speaker_count,
        "reference_speakers": len({turn.label for turn in meeting.reference_diarization.turns}),
        "cpwer_percent": _percent(
            concatenated_minimum_permutation_wer(meeting.reference, attributed, normalizer).wer
        ),
        "wder_percent": _percent(word_diarization_error_rate(meeting.reference, attributed, normalizer)),
        "der_percent": _percent(strict.der),
        "der_missed_percent": _percent(strict.missed_rate),
        "der_false_alarm_percent": _percent(strict.false_alarm_rate),
        "der_confusion_percent": _percent(strict.confusion_rate),
        "jer_percent": _percent(jaccard_error_rate(meeting.reference_diarization, resolved).jer),
        "quiet_speaker_recall_percent": _quiet_recall(quiet),
        "speakers": quiet.as_dict(),
    }


def run_sweep(
    meetings: Sequence[SweepMeeting],
    points: Sequence[SweepPoint],
    settings: Settings,
    cache: Path,
) -> dict[str, object]:
    cache.mkdir(parents=True, exist_ok=True)
    models_dir = settings.runtime.models_dir
    prepared: list[tuple[SweepMeeting, Transcript, AudioClip, tuple[TimeSpan, ...]]] = []
    for meeting in meetings:
        transcript, clip, speech = cached_transcript(meeting, settings, cache)
        prepared.append((meeting, transcript, clip, speech))
    rows: list[dict[str, object]] = []
    clusters: dict[tuple[object, ...], dict[str, Diarization]] = {}
    for point in points:
        applied = point.applied(settings)
        signature = diarizer_signature(applied)
        cached = clusters.setdefault(signature, {})
        scored: list[dict[str, object]] = []
        elapsed = 0.0
        for meeting, transcript, clip, speech in prepared:
            raw = cached.get(meeting.identifier)
            if raw is None:
                raw, seconds = clusters_only(clip, applied, models_dir)
                cached[meeting.identifier] = raw
                elapsed += seconds
            diarization = consolidated(raw, clip, applied, models_dir)
            scored.append(
                score_point(
                    meeting,
                    transcript,
                    diarization,
                    speech,
                    applied.diarization.speech_coverage_refinement,
                )
            )
        rows.append(
            {
                "point": point.label,
                "overrides": dict(point.overrides),
                "diarization_seconds": round(elapsed, 1),
                "macro": _macro(scored),
                "meetings": scored,
            }
        )
    return {
        "benchmark": "diarization-sweep",
        "sweep_version": SWEEP_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "meetings": [meeting.identifier for meeting in meetings],
        "transcript_cache": str(cache),
        "rows": rows,
    }


def _quiet_recall(report: QuietSpeakerReport) -> float:
    buckets = report.buckets
    quiet = [item for item in buckets if item.bucket in ("under_15s", "15s_to_60s")]
    speakers = sum(item.speakers for item in quiet)
    found = sum(item.found for item in quiet)
    return round(found / speakers * 100, 2) if speakers else 100.0


def _macro(rows: Sequence[Mapping[str, object]]) -> dict[str, float]:
    metrics = (
        "cpwer_percent",
        "wder_percent",
        "der_percent",
        "der_missed_percent",
        "der_false_alarm_percent",
        "der_confusion_percent",
        "jer_percent",
        "quiet_speaker_recall_percent",
    )
    if not rows:
        return {}
    macro = {key: round(sum(_number(row, key) for row in rows) / len(rows), 2) for key in metrics}
    macro["speaker_count_error"] = round(
        sum(abs(_number(row, "detected_speakers") - _number(row, "reference_speakers")) for row in rows)
        / len(rows),
        2,
    )
    return macro


def _number(row: Mapping[str, object], key: str) -> float:
    value = row.get(key)
    return float(value) if isinstance(value, int | float) else 0.0


def _percent(value: float) -> float:
    return round(value * 100, 2)


def _speech_spans(transcript: Transcript) -> tuple[TimeSpan, ...]:
    return tuple(utterance.span for utterance in transcript.utterances)


def _write_transcript(path: Path, transcript: Transcript, speech: Sequence[TimeSpan] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "language": transcript.language,
        "audio_duration": transcript.audio_duration,
        "speech_spans": [[span.start, span.end] for span in speech],
        "utterances": [
            {
                "start": utterance.span.start,
                "end": utterance.span.end,
                "text": utterance.text,
                "language": utterance.language,
                "confidence": utterance.confidence,
                "words": [
                    {
                        "text": word.text,
                        "start": word.span.start,
                        "end": word.span.end,
                        "confidence": word.confidence,
                    }
                    for word in utterance.words
                ],
            }
            for utterance in transcript.utterances
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_transcript(
    path: Path, language: str, duration: float, clip: AudioClip
) -> tuple[Transcript, AudioClip, tuple[TimeSpan, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    utterances = tuple(
        Utterance(
            span=TimeSpan(float(item["start"]), float(item["end"])),
            text=str(item["text"]),
            language=item.get("language") or language,
            confidence=float(item.get("confidence", 1.0)),
            words=tuple(
                Word(
                    text=str(word["text"]),
                    span=TimeSpan(float(word["start"]), float(word["end"])),
                    confidence=float(word.get("confidence", 1.0)),
                )
                for word in item.get("words", ())
            ),
        )
        for item in payload.get("utterances", ())
    )
    transcript = Transcript(
        utterances=utterances,
        language=payload.get("language") or language,
        audio_duration=float(payload.get("audio_duration") or duration),
    )
    recorded = payload.get("speech_spans")
    speech = (
        tuple(TimeSpan(float(pair[0]), float(pair[1])) for pair in recorded)
        if recorded
        else _speech_spans(transcript)
    )
    return transcript, clip, speech


def grid(
    name: str, values: Sequence[object], base: Mapping[str, object] | None = None
) -> tuple[SweepPoint, ...]:
    shared = dict(base or {})
    return tuple(SweepPoint(label=f"{name}={value}", overrides={**shared, name: value}) for value in values)


def named_diarization(turns: Sequence[tuple[float, float, str]]) -> Diarization:
    resolved = tuple(SpeakerTurn(TimeSpan(start, end), label) for start, end, label in turns)
    return Diarization(turns=resolved, labels=tuple(dict.fromkeys(turn.label for turn in resolved)))


def rebuilt(settings: Settings, **overrides: object) -> Settings:
    return SweepPoint(label="ad-hoc", overrides=overrides).applied(settings)


def without_consolidation(point: SweepPoint) -> SweepPoint:
    return replace(point, overrides={**point.overrides, "cluster_consolidation": False})
