from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from hansard.adapters.asr.registry import build_recognizer
from hansard.adapters.audio import load_clip
from hansard.config import AsrEngine, AsrSettings, Device, Settings
from hansard.domain.audio import AudioClip
from hansard.domain.errors import ConfigurationError
from hansard.domain.timespan import TimeSpan
from hansard.evaluation.ami import discover_meetings
from hansard.evaluation.corpora import SUMM_RE_LANGUAGE, read_meeting, summ_re_split
from hansard.evaluation.metrics.decomposition import Decomposition, decompose
from hansard.evaluation.metrics.system import ResourceProbe
from hansard.evaluation.metrics.text import word_error_rate
from hansard.evaluation.normalizers import NORMALIZER_VERSION, normalizer_for
from hansard.ports.asr import RecognitionHints

SHOOTOUT_VERSION = "hansard-shootout-1.0.0"
DEFAULT_CONTEXT_SECONDS = 0.0

PRESETS: dict[str, EngineSpec] = {}


def register_preset(spec: EngineSpec) -> EngineSpec:
    PRESETS[spec.name] = spec
    return spec


def preset(name: str) -> EngineSpec:
    if name not in PRESETS:
        raise ConfigurationError(f"unknown shootout engine {name!r}, available: {tuple(sorted(PRESETS))}")
    return PRESETS[name]


@dataclass(frozen=True, slots=True)
class ShootoutSegment:
    corpus: str
    meeting: str
    speaker: str
    language: str
    audio: Path
    span: TimeSpan
    reference: str


@dataclass(frozen=True, slots=True)
class EngineSpec:
    name: str
    engine: AsrEngine = "parakeet"
    model_id: str = "nemo-parakeet-tdt-0.6b-v3"
    quantization: str = "none"
    beam_size: int = 1
    language: str | None = None
    device: Device = "cpu"
    batch_size: int = 1

    def settings(self, threads: int) -> AsrSettings:
        return AsrSettings(
            engine=self.engine,
            model_id=self.model_id,
            quantization="int8" if self.quantization == "int8" else "none",
            beam_size=self.beam_size,
            language=self.language,
            device=self.device,
            batch_size=self.batch_size,
            intra_op_threads=threads,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "engine": self.engine,
            "model_id": self.model_id,
            "quantization": self.quantization,
            "beam_size": self.beam_size,
            "language": self.language or "auto",
        }


@dataclass(frozen=True, slots=True)
class LanguageOutcome:
    language: str
    segments: int
    reference_words: int
    hypothesis_words: int
    wer: float
    cer: float
    substitutions: int
    deletions: int
    insertions: int
    decomposition: Decomposition

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "segments": self.segments,
            "reference_words": self.reference_words,
            "hypothesis_words": self.hypothesis_words,
            "wer_percent": round(self.wer * 100, 2),
            "cer_percent": round(self.cer * 100, 2),
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
            "deletion_share_percent": _share(
                self.deletions, self.substitutions + self.deletions + self.insertions
            ),
            "decomposition": self.decomposition.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    spec: EngineSpec
    languages: tuple[LanguageOutcome, ...]
    audio_seconds: float
    elapsed_seconds: float
    peak_memory_mb: float
    empty_segments: int
    failures: int

    @property
    def real_time_factor(self) -> float:
        return self.elapsed_seconds / self.audio_seconds if self.audio_seconds else 0.0

    def outcome_for(self, language: str) -> LanguageOutcome | None:
        return next((item for item in self.languages if item.language == language), None)

    def as_dict(self) -> dict[str, object]:
        return {
            "engine": self.spec.as_dict(),
            "audio_seconds": round(self.audio_seconds, 1),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "real_time_factor": round(self.real_time_factor, 3),
            "peak_memory_mb": round(self.peak_memory_mb, 1),
            "empty_segments": self.empty_segments,
            "failures": self.failures,
            "by_language": [item.as_dict() for item in self.languages],
        }


@dataclass(slots=True)
class _Tally:
    references: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    raw_references: list[str] = field(default_factory=list)


def summ_re_segments(
    root: Path,
    minimum_seconds: float = 0.4,
    split: str | None = None,
    meetings: Sequence[str] | None = None,
) -> tuple[ShootoutSegment, ...]:
    if not root.is_dir():
        return ()
    segments: list[ShootoutSegment] = []
    for directory in sorted(item for item in root.iterdir() if item.is_dir()):
        if meetings is not None and directory.name not in meetings:
            continue
        if split is not None and summ_re_split(directory.name) != split:
            continue
        meeting = read_meeting(directory)
        if meeting.mixed_audio is None:
            continue
        for track in meeting.tracks:
            for utterance in track.utterances:
                if utterance.span.duration < minimum_seconds:
                    continue
                segments.append(
                    ShootoutSegment(
                        corpus="summ-re",
                        meeting=meeting.identifier,
                        speaker=track.speaker,
                        language=SUMM_RE_LANGUAGE,
                        audio=meeting.mixed_audio,
                        span=utterance.span,
                        reference=utterance.text,
                    )
                )
    return tuple(segments)


def ami_segments(
    audio_root: Path, annotations: Path, minimum_seconds: float = 0.4
) -> tuple[ShootoutSegment, ...]:
    if not audio_root.is_dir() or not annotations.is_dir():
        return ()
    segments: list[ShootoutSegment] = []
    for meeting in discover_meetings(audio_root, annotations):
        for utterance in meeting.reference.utterances:
            if utterance.span.duration < minimum_seconds or not utterance.text.strip():
                continue
            segments.append(
                ShootoutSegment(
                    corpus="ami",
                    meeting=meeting.identifier,
                    speaker=utterance.speaker,
                    language="en",
                    audio=meeting.audio_path,
                    span=utterance.span,
                    reference=utterance.text,
                )
            )
    return tuple(segments)


def budgeted(
    segments: Sequence[ShootoutSegment], seconds: float, seed_meetings: Sequence[str] | None = None
) -> tuple[ShootoutSegment, ...]:
    if seconds <= 0:
        return tuple(segments)
    by_meeting: dict[str, list[ShootoutSegment]] = {}
    for segment in sorted(segments, key=lambda item: (item.meeting, item.span.start)):
        by_meeting.setdefault(segment.meeting, []).append(segment)
    order = list(seed_meetings) if seed_meetings else sorted(by_meeting)
    order = [name for name in order if name in by_meeting]
    chosen: list[ShootoutSegment] = []
    budget = 0.0
    index = 0
    while order and budget < seconds:
        name = order[index % len(order)]
        queue = by_meeting[name]
        if not queue:
            order.remove(name)
            continue
        segment = queue.pop(0)
        chosen.append(segment)
        budget += segment.span.duration
        index += 1
    return tuple(sorted(chosen, key=lambda item: (item.meeting, item.span.start)))


def transcribe_segments(
    spec: EngineSpec,
    segments: Sequence[ShootoutSegment],
    models_dir: Path,
    threads: int = 0,
    context_seconds: float = DEFAULT_CONTEXT_SECONDS,
) -> tuple[tuple[ShootoutSegment, ...], tuple[str, ...], float, float, int]:
    recognizer = build_recognizer(spec.settings(threads), models_dir)
    ordered: list[ShootoutSegment] = []
    hypotheses: list[str] = []
    failures = 0
    with ResourceProbe() as probe:
        for audio, group in _grouped(segments):
            clip = load_clip(audio)
            for segment in group:
                ordered.append(segment)
                hints = RecognitionHints(
                    language=spec.language,
                    segments=(_padded(segment.span, clip, context_seconds),),
                )
                try:
                    transcript = recognizer.transcribe(clip, hints)
                except Exception:
                    failures += 1
                    hypotheses.append("")
                    continue
                hypotheses.append(transcript.text.strip())
            del clip
    usage = probe.usage
    return tuple(ordered), tuple(hypotheses), usage.wall_seconds, usage.peak_rss_mb, failures


def score_engine(
    spec: EngineSpec,
    segments: Sequence[ShootoutSegment],
    hypotheses: Sequence[str],
    elapsed: float,
    peak_memory_mb: float,
    failures: int,
    glossary: Iterable[str] = (),
) -> EngineOutcome:
    tallies: dict[str, _Tally] = {}
    for segment, hypothesis in zip(segments, hypotheses, strict=True):
        tally = tallies.setdefault(segment.language, _Tally())
        tally.references.append(segment.reference)
        tally.hypotheses.append(hypothesis)
        tally.raw_references.append(segment.reference)
    outcomes: list[LanguageOutcome] = []
    terms = tuple(glossary)
    for language, tally in sorted(tallies.items()):
        normalizer = normalizer_for(language)
        result = word_error_rate(tally.references, tally.hypotheses, normalizer)
        total = Decomposition(categories=())
        hypothesis_words = 0
        for reference, hypothesis, raw in zip(
            tally.references, tally.hypotheses, tally.raw_references, strict=True
        ):
            clean_reference = normalizer.normalize(reference)
            clean_hypothesis = normalizer.normalize(hypothesis)
            hypothesis_words += len(clean_hypothesis.split())
            total = total + decompose(clean_reference, clean_hypothesis, language, raw, terms)
        outcomes.append(
            LanguageOutcome(
                language=language,
                segments=len(tally.references),
                reference_words=result.reference_words,
                hypothesis_words=hypothesis_words,
                wer=result.wer,
                cer=result.cer,
                substitutions=result.substitutions,
                deletions=result.deletions,
                insertions=result.insertions,
                decomposition=total,
            )
        )
    return EngineOutcome(
        spec=spec,
        languages=tuple(outcomes),
        audio_seconds=sum(segment.span.duration for segment in segments),
        elapsed_seconds=elapsed,
        peak_memory_mb=peak_memory_mb,
        empty_segments=sum(1 for item in hypotheses if not item.strip()),
        failures=failures,
    )


def run_shootout(
    specs: Sequence[EngineSpec],
    segments: Sequence[ShootoutSegment],
    models_dir: Path,
    threads: int = 0,
    glossary: Iterable[str] = (),
    transcripts_dir: Path | None = None,
    context_seconds: float = DEFAULT_CONTEXT_SECONDS,
) -> tuple[EngineOutcome, ...]:
    if not segments:
        raise ConfigurationError("no shootout segments were selected")
    outcomes: list[EngineOutcome] = []
    for spec in specs:
        ordered, hypotheses, elapsed, memory, failures = transcribe_segments(
            spec, segments, models_dir, threads, context_seconds
        )
        if transcripts_dir is not None:
            _write_transcripts(transcripts_dir / f"{spec.name}.jsonl", ordered, hypotheses)
        outcomes.append(score_engine(spec, ordered, hypotheses, elapsed, memory, failures, glossary))
    return tuple(outcomes)


def shootout_payload(
    outcomes: Sequence[EngineOutcome],
    segments: Sequence[ShootoutSegment],
    corpus: str,
    settings: Settings | None = None,
) -> dict[str, object]:
    resolved = settings or Settings()
    return {
        "benchmark": "asr-shootout",
        "shootout_version": SHOOTOUT_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "corpus": corpus,
        "boundaries": "reference utterances",
        "segments": len(segments),
        "meetings": sorted({segment.meeting for segment in segments}),
        "audio_seconds": round(sum(segment.span.duration for segment in segments), 1),
        "threads": resolved.asr.intra_op_threads,
        "engines": [outcome.as_dict() for outcome in outcomes],
    }


def _padded(span: TimeSpan, clip: AudioClip, seconds: float) -> TimeSpan:
    if seconds <= 0.0:
        return span
    return TimeSpan(max(0.0, span.start - seconds), min(clip.duration, span.end + seconds))


def _grouped(segments: Sequence[ShootoutSegment]) -> list[tuple[Path, list[ShootoutSegment]]]:
    grouped: dict[Path, list[ShootoutSegment]] = {}
    for segment in segments:
        grouped.setdefault(segment.audio, []).append(segment)
    return [(audio, grouped[audio]) for audio in grouped]


def _write_transcripts(path: Path, segments: Sequence[ShootoutSegment], hypotheses: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for segment, hypothesis in zip(segments, hypotheses, strict=True):
            handle.write(
                json.dumps(
                    {
                        "meeting": segment.meeting,
                        "speaker": segment.speaker,
                        "start": round(segment.span.start, 3),
                        "end": round(segment.span.end, 3),
                        "language": segment.language,
                        "reference": segment.reference,
                        "hypothesis": hypothesis,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _share(part: int, whole: int) -> float:
    return round(part / whole * 100, 2) if whole else 0.0


def with_language(spec: EngineSpec, language: str | None) -> EngineSpec:
    return replace(spec, language=language)


register_preset(EngineSpec(name="parakeet-fp32"))
register_preset(EngineSpec(name="parakeet-fp32-fr", language="fr"))
register_preset(EngineSpec(name="parakeet-fp32-en", language="en"))
register_preset(EngineSpec(name="parakeet-int8", quantization="int8"))
register_preset(
    EngineSpec(name="whisper-large-v3", engine="whisper", model_id="large-v3", quantization="int8")
)
register_preset(
    EngineSpec(name="whisper-large-v3-fp32", engine="whisper", model_id="large-v3", quantization="none")
)
register_preset(
    EngineSpec(
        name="whisper-large-v3-fr",
        engine="whisper",
        model_id="large-v3",
        quantization="int8",
        language="fr",
    )
)
register_preset(
    EngineSpec(
        name="whisper-large-v3-beam5",
        engine="whisper",
        model_id="large-v3",
        quantization="int8",
        beam_size=5,
    )
)
register_preset(
    EngineSpec(
        name="whisper-large-v3-turbo", engine="whisper", model_id="large-v3-turbo", quantization="int8"
    )
)
register_preset(EngineSpec(name="whisper-medium", engine="whisper", model_id="medium", quantization="int8"))
