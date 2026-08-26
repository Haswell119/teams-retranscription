from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from hansard.domain.speakers import UNKNOWN_SPEAKER, Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance
from hansard.evaluation.corpora import (
    SUMM_RE_LANGUAGE,
    SUMM_RE_SOURCE,
    SummReMeeting,
    download_summ_re,
    meeting_diarization,
    meeting_transcript,
    prepare_summ_re,
    read_meeting,
)
from hansard.evaluation.formats.rttm import load_rttm, parse_rttm, render_rttm, write_rttm
from hansard.evaluation.formats.subtitles import load_subtitles, parse_srt, parse_webvtt

__all__ = [
    "EvaluationSample",
    "download_summ_re",
    "load_manifest",
    "load_meetings",
    "load_reference_json",
    "load_rttm",
    "load_subtitles",
    "parse_rttm",
    "parse_srt",
    "parse_webvtt",
    "prepare_summ_re",
    "render_rttm",
    "sample_from_record",
    "sample_from_subtitles",
    "summ_re_sample",
    "write_rttm",
]

DEFAULT_LANGUAGE = "en"
REFERENCE_JSON_SUFFIX = ".ref.json"
_UTTERANCE_KEYS = ("utterances", "segments")
_DURATION_KEYS = ("seconds", "duration")


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    identifier: str
    reference: Transcript
    language: str
    source: str
    audio_path: Path | None = None
    reference_diarization: Diarization | None = None
    audio_seconds: float = 0.0

    @property
    def reference_text(self) -> str:
        return self.reference.text


def load_manifest(path: Path) -> tuple[EvaluationSample, ...]:
    samples: list[EvaluationSample] = []
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{index + 1} manifest lines must be JSON objects")
            samples.append(sample_from_record(record, source=path.stem, index=index))
    return tuple(samples)


def sample_from_record(record: Mapping[str, object], source: str, index: int) -> EvaluationSample:
    audio_path = Path(str(record["audio"])) if record.get("audio") else None
    language = str(record.get("language") or DEFAULT_LANGUAGE)
    identifier = str(record.get("id") or (audio_path.stem if audio_path else f"{source}-{index:05d}"))
    segments = _segments(record)
    if segments:
        utterances = tuple(_utterance(segment, language) for segment in segments)
        diarization = _diarization(utterances)
    else:
        duration = _duration(record)
        utterances = (
            Utterance(
                span=TimeSpan(0.0, duration),
                text=str(record.get("text") or ""),
                speaker=str(record.get("speaker") or UNKNOWN_SPEAKER),
                language=language,
            ),
        )
        diarization = None
    duration = _duration(record) or max((item.span.end for item in utterances), default=0.0)
    return EvaluationSample(
        identifier=identifier,
        reference=Transcript(utterances=utterances, language=language, audio_duration=duration),
        language=language,
        source=str(record.get("source") or source),
        audio_path=audio_path,
        reference_diarization=diarization,
        audio_seconds=duration,
    )


def load_reference_json(
    path: Path,
    language: str = DEFAULT_LANGUAGE,
    source: str = "synthetic",
) -> EvaluationSample:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"{path} must contain a JSON object")
    identifier = path.name.removesuffix(REFERENCE_JSON_SUFFIX).removesuffix(".json")
    enriched = {"id": identifier, "language": record.get("language") or language, **record}
    sample = sample_from_record(enriched, source=source, index=0)
    companion = path.with_name(f"{identifier}.rttm")
    if not companion.exists():
        return sample
    return replace(sample, reference_diarization=load_rttm(companion).get(identifier))


def load_meetings(
    directory: Path,
    language: str = DEFAULT_LANGUAGE,
    source: str = "synthetic",
) -> tuple[EvaluationSample, ...]:
    return tuple(
        load_reference_json(path, language, source)
        for path in sorted(directory.glob(f"*{REFERENCE_JSON_SUFFIX}"))
    )


def summ_re_sample(meeting: SummReMeeting) -> EvaluationSample:
    transcript = meeting_transcript(meeting)
    return EvaluationSample(
        identifier=meeting.identifier,
        reference=transcript,
        language=SUMM_RE_LANGUAGE,
        source=SUMM_RE_SOURCE,
        audio_path=meeting.mixed_audio,
        reference_diarization=meeting_diarization(meeting),
        audio_seconds=meeting.duration,
    )


def summ_re_samples(root: Path) -> tuple[EvaluationSample, ...]:
    return tuple(
        summ_re_sample(read_meeting(directory)) for directory in sorted(root.iterdir()) if directory.is_dir()
    )


def sample_from_subtitles(
    path: Path,
    language: str,
    source: str = "subtitles",
    audio_path: Path | None = None,
) -> EvaluationSample:
    transcript = load_subtitles(path, language)
    return EvaluationSample(
        identifier=path.stem,
        reference=transcript,
        language=language,
        source=source,
        audio_path=audio_path,
        reference_diarization=_diarization(transcript.utterances),
        audio_seconds=transcript.audio_duration,
    )


def _segments(record: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    for key in _UTTERANCE_KEYS:
        value = record.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    return []


def _utterance(segment: Mapping[str, object], language: str) -> Utterance:
    start = _as_float(segment.get("start"))
    end = _as_float(segment.get("end")) or start
    return Utterance(
        span=TimeSpan(start, max(start, end)),
        text=str(segment.get("text") or ""),
        speaker=str(segment.get("speaker") or UNKNOWN_SPEAKER),
        language=str(segment.get("language") or language),
    )


def _duration(record: Mapping[str, object]) -> float:
    for key in _DURATION_KEYS:
        value = _as_float(record.get(key))
        if value:
            return value
    return 0.0


def _as_float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        return float(value)
    return 0.0


def _diarization(utterances: Sequence[Utterance]) -> Diarization | None:
    labelled = [item for item in utterances if item.speaker != UNKNOWN_SPEAKER and item.span.duration > 0.0]
    if not labelled:
        return None
    return Diarization(
        turns=tuple(SpeakerTurn(span=item.span, label=item.speaker) for item in labelled),
        labels=tuple(sorted({item.speaker for item in labelled})),
    )
