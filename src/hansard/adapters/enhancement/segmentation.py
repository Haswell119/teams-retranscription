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
    dense_max_seconds: float = 15.0
    dense_speech_ratio: float = 0.85


def speech_ratio(speech: tuple[TimeSpan, ...], total_duration: float) -> float:
    if total_duration <= 0.0:
        return 0.0
    return min(1.0, sum(span.duration for span in speech) / total_duration)


def ceiling_for(speech: tuple[TimeSpan, ...], policy: SegmentationPolicy, total_duration: float) -> float:
    if policy.dense_max_seconds <= 0.0 or policy.dense_max_seconds >= policy.max_seconds:
        return policy.max_seconds
    dense = speech_ratio(speech, total_duration) >= policy.dense_speech_ratio
    return policy.dense_max_seconds if dense else policy.max_seconds


def _split_long(span: TimeSpan, policy: SegmentationPolicy, ceiling: float) -> list[TimeSpan]:
    if span.duration <= ceiling:
        return [span]
    overlap = min(policy.split_overlap_seconds, ceiling / 3.0)
    stride = ceiling - overlap
    parts: list[TimeSpan] = []
    cursor = span.start
    while cursor < span.end:
        finish = min(cursor + ceiling, span.end)
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
        return tuple(_split_long(TimeSpan(0.0, total_duration), policy, policy.max_seconds))
    ceiling = ceiling_for(speech, policy, total_duration)
    grouped: list[TimeSpan] = [speech[0]]
    for span in speech[1:]:
        current = grouped[-1]
        gap = span.start - current.end
        if gap <= policy.merge_gap_seconds and (span.end - current.start) <= ceiling:
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
        planned.extend(_split_long(padded, policy, ceiling))
    return tuple(planned)
