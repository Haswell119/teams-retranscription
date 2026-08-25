from __future__ import annotations

import pytest

from hansard.rendering.timecode import (
    TimestampStyle,
    format_iso_duration,
    format_range,
    format_timestamp,
)


@pytest.mark.parametrize(
    ("seconds", "style", "expected"),
    [
        (0.0, TimestampStyle.CLOCK, "00:00:00"),
        (0.0, TimestampStyle.COMPACT, "00:00"),
        (0.0, TimestampStyle.WEB_VTT, "00:00:00.000"),
        (0.0, TimestampStyle.SUB_RIP, "00:00:00,000"),
        (7.25, TimestampStyle.CLOCK, "00:00:07"),
        (7.25, TimestampStyle.WEB_VTT, "00:00:07.250"),
        (7.25, TimestampStyle.SUB_RIP, "00:00:07,250"),
        (59.4, TimestampStyle.CLOCK, "00:00:59"),
        (59.5, TimestampStyle.CLOCK, "00:01:00"),
        (59.5, TimestampStyle.COMPACT, "01:00"),
        (3600.0, TimestampStyle.CLOCK, "01:00:00"),
        (3600.0, TimestampStyle.COMPACT, "60:00"),
        (3661.0, TimestampStyle.CLOCK, "01:01:01"),
        (3661.0, TimestampStyle.COMPACT, "61:01"),
        (3661.0, TimestampStyle.WEB_VTT, "01:01:01.000"),
        (36000.0, TimestampStyle.CLOCK, "10:00:00"),
        (359999.0, TimestampStyle.CLOCK, "99:59:59"),
        (360000.0, TimestampStyle.CLOCK, "100:00:00"),
    ],
)
def test_format_timestamp_known_values(seconds, style, expected):
    assert format_timestamp(seconds, style) == expected


@pytest.mark.parametrize("style", list(TimestampStyle))
def test_negative_seconds_clamp_to_zero(style):
    assert format_timestamp(-12.5, style) == format_timestamp(0.0, style)


def test_default_style_is_clock():
    assert format_timestamp(65.0) == "00:01:05"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.4, "00:00:00"),
        (0.5, "00:00:01"),
        (1.49, "00:00:01"),
        (1.5, "00:00:02"),
    ],
)
def test_clock_rounds_half_up(seconds, expected):
    assert format_timestamp(seconds, TimestampStyle.CLOCK) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (1.9996, "00:00:02.000"),
        (0.0004, "00:00:00.000"),
        (0.0006, "00:00:00.001"),
        (12.3456, "00:00:12.346"),
    ],
)
def test_milliseconds_round_to_nearest(seconds, expected):
    assert format_timestamp(seconds, TimestampStyle.WEB_VTT) == expected


def test_millisecond_carry_into_seconds():
    assert format_timestamp(59.9999, TimestampStyle.WEB_VTT) == "00:01:00.000"


def test_format_range_uses_en_dash_by_default():
    assert format_range(0.0, 4200.0) == "00:00:00 \u2013 01:10:00"


def test_format_range_accepts_custom_separator_and_style():
    assert format_range(1.0, 2.0, TimestampStyle.SUB_RIP, " --> ") == "00:00:01,000 --> 00:00:02,000"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "PT0H0M0S"), (3725.0, "PT1H2M5S"), (-5.0, "PT0H0M0S")],
)
def test_format_iso_duration(seconds, expected):
    assert format_iso_duration(seconds) == expected
