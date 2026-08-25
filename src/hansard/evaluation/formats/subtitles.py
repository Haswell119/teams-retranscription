from __future__ import annotations

import re
from pathlib import Path

from hansard.domain.speakers import UNKNOWN_SPEAKER
from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Transcript, Utterance

_TIMING = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})\s*-->\s*(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})"
)
_VOICE_TAG = re.compile(r"<v[^>]*?\s+([^>]+?)>", re.IGNORECASE)
_ANY_TAG = re.compile(r"</?[^>]+>")
_NAME_PREFIX = re.compile(r"^([A-ZÀ-ÖØ-Þ][\w.'\u2019-]*(?:\s+[A-ZÀ-ÖØ-Þ0-9][\w.'\u2019-]*){0,3})\s*:\s+(.*)$")
_BLANK_LINE = re.compile(r"\r?\n\s*\r?\n")


def parse_webvtt(text: str, language: str | None = None) -> Transcript:
    return _parse_cues(text, language)


def parse_srt(text: str, language: str | None = None) -> Transcript:
    return _parse_cues(text, language)


def load_subtitles(path: Path, language: str | None = None) -> Transcript:
    return _parse_cues(path.read_text(encoding="utf-8-sig"), language)


def parse_timestamp(value: str) -> float:
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _parse_cues(text: str, language: str | None) -> Transcript:
    utterances: list[Utterance] = []
    for block in _BLANK_LINE.split(text.replace("\ufeff", "")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if _TIMING.search(line)), None)
        if timing_index is None:
            continue
        match = _TIMING.search(lines[timing_index])
        if match is None:
            continue
        payload = lines[timing_index + 1 :]
        if not payload:
            continue
        speaker, content = _speaker_and_text(" ".join(payload))
        if not content:
            continue
        utterances.append(
            Utterance(
                span=TimeSpan(parse_timestamp(match.group("start")), parse_timestamp(match.group("end"))),
                text=content,
                speaker=speaker,
                language=language,
            )
        )
    ordered = tuple(sorted(utterances, key=lambda item: (item.span.start, item.span.end)))
    duration = max((item.span.end for item in ordered), default=0.0)
    return Transcript(utterances=ordered, language=language, audio_duration=duration)


def _speaker_and_text(payload: str) -> tuple[str, str]:
    voice = _VOICE_TAG.search(payload)
    stripped = _ANY_TAG.sub("", payload).strip()
    if voice is not None:
        return voice.group(1).strip(), stripped
    prefixed = _NAME_PREFIX.match(stripped)
    if prefixed is not None:
        return prefixed.group(1).strip(), prefixed.group(2).strip()
    return UNKNOWN_SPEAKER, stripped
