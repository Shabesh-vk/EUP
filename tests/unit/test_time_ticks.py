"""
Unit tests for time tick conversions and natural time expression parsing.
"""

from core.time_ticks import (
    seconds_to_ticks,
    ticks_to_seconds,
    format_ticks_to_clock,
    parse_time_expression,
)


def test_seconds_ticks_roundtrip():
    assert seconds_to_ticks(1.5) == 1500
    assert seconds_to_ticks(0.042) == 42
    assert ticks_to_seconds(1500) == 1.5
    assert ticks_to_seconds(42) == 0.042


def test_format_ticks_to_clock():
    assert format_ticks_to_clock(42000) == "0:42"
    assert format_ticks_to_clock(80000) == "1:20"
    assert format_ticks_to_clock(3665000) == "1:01:05"


def test_parse_clock_formats():
    assert parse_time_expression("1:20") == 80000
    assert parse_time_expression("0:42") == 42000
    assert parse_time_expression("01:30") == 90000
    assert parse_time_expression("1:00:00") == 3600000


def test_parse_natural_and_relative_expressions():
    # 80 seconds
    assert parse_time_expression("80s") == 80000
    assert parse_time_expression("80 seconds") == 80000
    assert parse_time_expression("80 sec") == 80000

    # a minute twenty
    assert parse_time_expression("a minute twenty") == 80000
    assert parse_time_expression("a minute and twenty seconds") == 80000
    assert parse_time_expression("a minute") == 60000

    # explicit minutes and seconds
    assert parse_time_expression("1m 20s") == 80000
    assert parse_time_expression("2 min 30 sec") == 150000

    # relative: "the last 10 seconds" with total duration of 300s
    total_ticks = 300000
    assert parse_time_expression("the last 10 seconds", total_duration_ticks=total_ticks) == 290000
    assert parse_time_expression("last 30s", total_duration_ticks=total_ticks) == 270000
