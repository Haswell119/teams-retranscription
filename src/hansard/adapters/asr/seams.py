from __future__ import annotations

from dataclasses import replace

from hansard.domain.timespan import TimeSpan
from hansard.domain.transcript import Utterance, Word


def authoritative_regions(spans: list[TimeSpan]) -> list[TimeSpan]:
    if len(spans) < 2:
        return list(spans)
    ordered = sorted(spans, key=lambda span: span.start)
    regions: list[TimeSpan] = []
    for index, span in enumerate(ordered):
        start = span.start
        if index > 0:
            start = max(start, ordered[index - 1].end)
        regions.append(TimeSpan(start, max(start, span.end)))
    return regions


def trim_to_regions(utterances: list[Utterance], spans: list[TimeSpan]) -> list[Utterance]:
    if len(spans) < 2 or len(utterances) != len(spans):
        return utterances
    regions = authoritative_regions(spans)
    trimmed: list[Utterance] = []
    for utterance, region in zip(utterances, regions, strict=True):
        if not utterance.words:
            trimmed.append(utterance)
            continue
        kept = tuple(word for word in utterance.words if _belongs(word, region))
        if not kept:
            continue
        trimmed.append(
            replace(
                utterance,
                span=TimeSpan(kept[0].span.start, kept[-1].span.end),
                text=" ".join(word.text for word in kept),
                words=kept,
            )
        )
    return trimmed


def _belongs(word: Word, region: TimeSpan) -> bool:
    return region.contains(word.span.midpoint) or region.overlap(word.span) > 0.5 * word.span.duration


def _key(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


def _keys(utterance: Utterance) -> tuple[str, ...]:
    if utterance.words:
        return tuple(_key(word.text) for word in utterance.words)
    return tuple(_key(piece) for piece in utterance.text.split())


def _repeat_length(tail: tuple[str, ...], head: tuple[str, ...], limit: int) -> int:
    for length in range(min(limit, len(tail), len(head)), 0, -1):
        if tail[-length:] == head[:length] and all(tail[-length:]):
            return length
    return 0


def _without_tail(utterance: Utterance, count: int) -> Utterance | None:
    if utterance.words:
        kept = utterance.words[:-count]
        if not kept:
            return None
        return replace(
            utterance,
            span=TimeSpan(kept[0].span.start, kept[-1].span.end),
            text=" ".join(word.text for word in kept),
            words=kept,
        )
    pieces = utterance.text.split()[:-count]
    if not pieces:
        return None
    return replace(utterance, text=" ".join(pieces))


def drop_seam_repeats(
    utterances: list[Utterance],
    max_repeat_words: int = 8,
    max_gap_seconds: float = 1.0,
) -> list[Utterance]:
    if len(utterances) < 2 or max_repeat_words < 1:
        return utterances
    resolved: list[Utterance | None] = list(utterances)
    for index in range(len(resolved) - 1):
        earlier, later = resolved[index], utterances[index + 1]
        if earlier is None:
            continue
        if later.span.start - earlier.span.end > max_gap_seconds:
            continue
        repeated = _repeat_length(_keys(earlier), _keys(later), max_repeat_words)
        if repeated:
            resolved[index] = _without_tail(earlier, repeated)
    return [utterance for utterance in resolved if utterance is not None]
