from __future__ import annotations

from dataclasses import dataclass

from hansard.domain.timespan import TimeSpan


@dataclass(frozen=True, slots=True)
class SegmentationPolicy:
    max_seconds: float = 30.0
    min_seconds: float = 0.15
    merge_gap_seconds: float = 0.4
    padding_seconds: float = 0.2
    split_overlap_seconds: float = 2.0


def _split_long(span: TimeSpan, policy: SegmentationPolicy) -> list[TimeSpan]:
    if span.duration <= policy.max_seconds:
        return [span]
    overlap = min(policy.split_overlap_seconds, policy.max_seconds / 3.0)
    stride = policy.max_seconds - overlap
    parts: list[TimeSpan] = []
    cursor = span.start
    while cursor < span.end:
        finish = min(cursor + policy.max_seconds, span.end)
        parts.append(TimeSpan(cursor, finish))
        if finish >= span.end:
            break
        cursor += stride
    return parts


def plan_segments(
    speech: tuple[TimeSpan, ...],
    policy: SegmentationPolicy,
    total_duration: float,
) -> tuple[TimeSpan, ...]:
    if not speech:
        if total_duration <= 0.0:
            return ()
        return tuple(_split_long(TimeSpan(0.0, total_duration), policy))
    grouped: list[TimeSpan] = [speech[0]]
    for span in speech[1:]:
        current = grouped[-1]
        gap = span.start - current.end
        if gap <= policy.merge_gap_seconds and (span.end - current.start) <= policy.max_seconds:
            grouped[-1] = TimeSpan(current.start, span.end)
        else:
            grouped.append(span)
    planned: list[TimeSpan] = []
    for span in grouped:
        padded = TimeSpan(
            max(0.0, span.start - policy.padding_seconds),
            min(total_duration, span.end + policy.padding_seconds),
        )
        if span.duration < policy.min_seconds:
            continue
        planned.extend(_split_long(padded, policy))
    return tuple(planned)
