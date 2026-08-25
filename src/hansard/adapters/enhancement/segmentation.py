from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.timespan import TimeSpan


@dataclass(frozen=True, slots=True)
class SegmentationPolicy:
    max_seconds: float = 30.0
    min_seconds: float = 1.0
    merge_gap_seconds: float = 0.4
    padding_seconds: float = 0.2


def _split_long(span: TimeSpan, max_seconds: float) -> list[TimeSpan]:
    if span.duration <= max_seconds:
        return [span]
    parts = int(span.duration // max_seconds) + 1
    step = span.duration / parts
    return [TimeSpan(span.start + index * step, span.start + (index + 1) * step) for index in range(parts)]


def plan_segments(
    speech: tuple[TimeSpan, ...],
    policy: SegmentationPolicy,
    total_duration: float,
) -> tuple[TimeSpan, ...]:
    if not speech:
        return tuple(_split_long(TimeSpan(0.0, total_duration), policy.max_seconds)) if total_duration else ()
    grouped: list[TimeSpan] = [speech[0]]
    for span in speech[1:]:
        current = grouped[-1]
        gap = span.start - current.end
        if gap <= policy.merge_gap_seconds and (span.end - current.start) <= policy.max_seconds:
            grouped[-1] = TimeSpan(current.start, span.end)
        else:
            grouped.append(span)
    expanded: list[TimeSpan] = []
    for span in grouped:
        expanded.extend(_split_long(span, policy.max_seconds))
    padded = [
        TimeSpan(
            max(0.0, span.start - policy.padding_seconds),
            min(total_duration, span.end + policy.padding_seconds),
        )
        for span in expanded
    ]
    return tuple(span for span in padded if span.duration >= policy.min_seconds)
