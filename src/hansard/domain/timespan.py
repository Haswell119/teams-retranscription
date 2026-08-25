from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class TimeSpan:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"TimeSpan end {self.end} precedes start {self.start}")

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2.0

    def shifted(self, offset: float) -> TimeSpan:
        return TimeSpan(self.start + offset, self.end + offset)

    def overlap(self, other: TimeSpan) -> float:
        return max(0.0, min(self.end, other.end) - max(self.start, other.start))

    def intersects(self, other: TimeSpan) -> bool:
        return self.overlap(other) > 0.0

    def contains(self, instant: float) -> bool:
        return self.start <= instant < self.end

    def union(self, other: TimeSpan) -> TimeSpan:
        return TimeSpan(min(self.start, other.start), max(self.end, other.end))

    def clamped(self, lower: float, upper: float) -> TimeSpan:
        return TimeSpan(min(max(self.start, lower), upper), min(max(self.end, lower), upper))


def merge_adjacent(spans: list[TimeSpan], max_gap: float) -> list[TimeSpan]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if span.start - last.end <= max_gap:
            merged[-1] = last.union(span)
        else:
            merged.append(span)
    return merged


def total_duration(spans: list[TimeSpan]) -> float:
    return sum(span.duration for span in merge_adjacent(spans, 0.0))
