from __future__ import annotations

import math
from enum import StrEnum

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
MILLISECONDS_PER_SECOND = 1000
EN_DASH = "\u2013"
RANGE_SEPARATOR = f" {EN_DASH} "


class TimestampStyle(StrEnum):
    CLOCK = "clock"
    COMPACT = "compact"
    WEB_VTT = "vtt"
    SUB_RIP = "srt"


def _non_negative(seconds: float) -> float:
    return max(0.0, seconds)


def _rounded_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _split_seconds(total_seconds: int) -> tuple[int, int, int]:
    hours, remainder = divmod(total_seconds, SECONDS_PER_HOUR)
    minutes, seconds = divmod(remainder, SECONDS_PER_MINUTE)
    return hours, minutes, seconds


def _split_milliseconds(seconds: float) -> tuple[int, int, int, int]:
    total = _rounded_half_up(_non_negative(seconds) * MILLISECONDS_PER_SECOND)
    whole_seconds, milliseconds = divmod(total, MILLISECONDS_PER_SECOND)
    hours, minutes, remaining_seconds = _split_seconds(whole_seconds)
    return hours, minutes, remaining_seconds, milliseconds


def format_timestamp(seconds: float, style: TimestampStyle = TimestampStyle.CLOCK) -> str:
    if style is TimestampStyle.CLOCK:
        hours, minutes, whole_seconds = _split_seconds(_rounded_half_up(_non_negative(seconds)))
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
    if style is TimestampStyle.COMPACT:
        hours, minutes, whole_seconds = _split_seconds(_rounded_half_up(_non_negative(seconds)))
        return f"{hours * SECONDS_PER_MINUTE + minutes:02d}:{whole_seconds:02d}"
    hours, minutes, whole_seconds, milliseconds = _split_milliseconds(seconds)
    fraction_separator = "," if style is TimestampStyle.SUB_RIP else "."
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{fraction_separator}{milliseconds:03d}"


def format_range(
    start: float,
    end: float,
    style: TimestampStyle = TimestampStyle.CLOCK,
    separator: str = RANGE_SEPARATOR,
) -> str:
    return f"{format_timestamp(start, style)}{separator}{format_timestamp(end, style)}"


def format_iso_duration(seconds: float) -> str:
    hours, minutes, whole_seconds = _split_seconds(_rounded_half_up(_non_negative(seconds)))
    return f"PT{hours}H{minutes}M{whole_seconds}S"
