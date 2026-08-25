from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.speakers import Diarization, SpeakerTurn
from hansard.domain.timespan import TimeSpan


@dataclass(frozen=True, slots=True)
class SpeechCoverageRefiner:
    maximum_extension: float = 2.5
    minimum_gap: float = 0.15
    inherited_confidence: float = 0.6

    @property
    def name(self) -> str:
        return "speech-coverage"

    def refine(self, diarization: Diarization, speech: tuple[TimeSpan, ...]) -> Diarization:
        if not diarization.turns or not speech:
            return diarization
        covered = sorted(diarization.turns, key=lambda turn: turn.span.start)
        additions: list[SpeakerTurn] = []
        for span in speech:
            for gap in _uncovered(span, covered):
                if gap.duration < self.minimum_gap:
                    continue
                label = _nearest_label(gap, covered, self.maximum_extension)
                if label is not None:
                    additions.append(SpeakerTurn(gap, label, self.inherited_confidence))
        if not additions:
            return diarization
        merged = _merge_same_speaker(sorted(covered + additions, key=lambda turn: turn.span.start))
        labels = tuple(dict.fromkeys(turn.label for turn in merged))
        return Diarization(turns=tuple(merged), labels=labels)


def _uncovered(span: TimeSpan, turns: list[SpeakerTurn]) -> list[TimeSpan]:
    remaining = [span]
    for turn in turns:
        if turn.span.end <= span.start:
            continue
        if turn.span.start >= span.end:
            break
        carved: list[TimeSpan] = []
        for piece in remaining:
            if not piece.intersects(turn.span):
                carved.append(piece)
                continue
            if piece.start < turn.span.start:
                carved.append(TimeSpan(piece.start, turn.span.start))
            if piece.end > turn.span.end:
                carved.append(TimeSpan(turn.span.end, piece.end))
        remaining = carved
        if not remaining:
            break
    return remaining


def _nearest_label(gap: TimeSpan, turns: list[SpeakerTurn], horizon: float) -> str | None:
    best_label: str | None = None
    best_distance = horizon
    for turn in turns:
        distance = max(turn.span.start - gap.end, gap.start - turn.span.end, 0.0)
        if distance < best_distance:
            best_distance = distance
            best_label = turn.label
    return best_label


def _merge_same_speaker(turns: list[SpeakerTurn]) -> list[SpeakerTurn]:
    merged: list[SpeakerTurn] = [turns[0]]
    for turn in turns[1:]:
        previous = merged[-1]
        if turn.label == previous.label and turn.span.start <= previous.span.end + 1e-6:
            merged[-1] = SpeakerTurn(
                TimeSpan(previous.span.start, max(previous.span.end, turn.span.end)),
                previous.label,
                min(previous.confidence, turn.confidence),
            )
        else:
            merged.append(turn)
    return merged
