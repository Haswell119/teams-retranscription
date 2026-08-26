from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from hansard.domain.timespan import TimeSpan

MINIMUM_PROBE_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class DriftGuardPolicy:
    probe_seconds: float = 4.0
    probe_count: int = 8
    ladder: tuple[float, ...] = (15.0, 8.0, 4.0)
    minimum_audio_seconds: float = 45.0
    recovery_share: float = 0.75
    overlap_fraction: float = 0.1

    def overlap_for(self, rung: float, configured: float) -> float:
        return min(configured, rung * self.overlap_fraction)

    @property
    def probe_budget(self) -> float:
        return self.probe_seconds * self.probe_count

    @property
    def safe_segment_seconds(self) -> float:
        return min(self.ladder) if self.ladder else 0.0

    def rungs_below(self, ceiling: float) -> tuple[float, ...]:
        return tuple(rung for rung in sorted(self.ladder, reverse=True) if rung < ceiling)


def _clamped(span: TimeSpan, start: float, seconds: float) -> TimeSpan | None:
    end = min(start + seconds, span.end)
    if end - start < MINIMUM_PROBE_SECONDS:
        return None
    return TimeSpan(start, end)


def _long_enough(spans: Sequence[TimeSpan]) -> tuple[TimeSpan, ...]:
    return tuple(span for span in spans if span.duration >= MINIMUM_PROBE_SECONDS)


def probe_spans(
    speech: Sequence[TimeSpan],
    duration: float,
    policy: DriftGuardPolicy,
) -> tuple[TimeSpan, ...]:
    usable = _long_enough(speech) or _long_enough((TimeSpan(0.0, duration),))
    if not usable or policy.probe_count <= 0:
        return ()
    total = sum(span.duration for span in usable)
    if total <= 0:
        return ()
    picked: list[TimeSpan] = []
    for index in range(policy.probe_count):
        offset = total * (index + 0.5) / policy.probe_count
        span = _span_at(usable, offset)
        if span is None:
            continue
        probe = _clamped(span[0], span[1], policy.probe_seconds)
        if probe is not None and probe not in picked:
            picked.append(probe)
    return tuple(picked)


def _span_at(spans: Sequence[TimeSpan], offset: float) -> tuple[TimeSpan, float] | None:
    travelled = 0.0
    for span in spans:
        if travelled + span.duration >= offset:
            start = span.start + max(0.0, offset - travelled)
            return span, min(start, max(span.start, span.end - MINIMUM_PROBE_SECONDS))
        travelled += span.duration
    return None


def has_drifted(probed: str | None, observed: str | None) -> bool:
    return probed is not None and observed is not None and probed != observed


def language_share(french: float, english: float, language: str | None) -> float:
    total = french + english
    if total <= 0 or language is None:
        return 0.0
    return (french if language == "fr" else english) / total
