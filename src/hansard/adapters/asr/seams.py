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
        end = span.end
        if index > 0:
            previous = ordered[index - 1]
            if previous.end > span.start:
                start = max(start, (span.start + previous.end) / 2.0)
        if index + 1 < len(ordered):
            following = ordered[index + 1]
            if span.end > following.start:
                end = min(end, (following.start + span.end) / 2.0)
        regions.append(TimeSpan(start, max(start, end)))
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
