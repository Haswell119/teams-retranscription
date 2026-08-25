from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan

_SPEAKER_RECORD = "SPEAKER"
_MISSING = "<NA>"


def parse_rttm(text: str) -> dict[str, Diarization]:
    turns: dict[str, list[SpeakerTurn]] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != _SPEAKER_RECORD or len(fields) < 8:
            continue
        file_identifier = fields[1]
        start = float(fields[3])
        duration = float(fields[4])
        turns.setdefault(file_identifier, []).append(
            SpeakerTurn(span=TimeSpan(start, start + duration), label=fields[7])
        )
    return {
        identifier: Diarization(
            turns=tuple(sorted(items, key=lambda turn: (turn.span.start, turn.span.end, turn.label))),
            labels=tuple(sorted({turn.label for turn in items})),
        )
        for identifier, items in sorted(turns.items())
    }


def load_rttm(path: Path) -> dict[str, Diarization]:
    return parse_rttm(path.read_text(encoding="utf-8"))


def render_rttm(diarizations: Mapping[str, Diarization], channel: str = "1") -> str:
    lines: list[str] = []
    for identifier in sorted(diarizations):
        ordered = sorted(
            diarizations[identifier].turns,
            key=lambda turn: (turn.span.start, turn.span.end, turn.label),
        )
        lines.extend(
            " ".join(
                (
                    _SPEAKER_RECORD,
                    identifier,
                    channel,
                    f"{turn.span.start:.3f}",
                    f"{turn.span.duration:.3f}",
                    _MISSING,
                    _MISSING,
                    turn.label,
                    _MISSING,
                    _MISSING,
                )
            )
            for turn in ordered
        )
    return "\n".join(lines) + ("\n" if lines else "")


def write_rttm(path: Path, diarizations: Mapping[str, Diarization], channel: str = "1") -> None:
    path.write_text(render_rttm(diarizations, channel), encoding="utf-8")
