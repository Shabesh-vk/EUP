"""
Time and tick conversion utilities for the IncuBrix Editing Engine.

Rounding Policy:
- Millisecond ticks (1000 ticks/sec) are used as the canonical integer temporal representation.
- Conversions from seconds to ticks use deterministic nearest-integer rounding: int(round(seconds * TICKS_PER_SECOND)).
- All range intersections and segment projections operate on closed-open tick intervals: [start_ticks, end_ticks).
"""

from __future__ import annotations
import re
from typing import Optional

TICKS_PER_SECOND = 1000  # 1 tick = 1 millisecond


def seconds_to_ticks(seconds: float) -> int:
    """Convert float seconds to integer ticks (milliseconds)."""
    return int(round(seconds * TICKS_PER_SECOND))


def ticks_to_seconds(ticks: int) -> float:
    """Convert integer ticks to float seconds rounded to 3 decimal places."""
    return round(ticks / TICKS_PER_SECOND, 3)


def format_ticks_to_clock(ticks: int) -> str:
    """Format ticks into clock string M:SS or H:MM:SS."""
    total_seconds = ticks // 1000
    ms = ticks % 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    hours = minutes // 60
    minutes = minutes % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def parse_time_expression(expr: str, total_duration_ticks: Optional[int] = None) -> Optional[int]:
    """
    Parse natural and standard time expressions into integer ticks.
    
    Supported formats:
    - Clock formats: "1:20" -> 80,000 ms, "0:42" -> 42,000 ms, "01:30:00" -> 5,400,000 ms
    - Numeric seconds: "80s", "80 seconds", "80.5s", "80 sec" -> 80,000 ms
    - Minutes & seconds: "1m 20s", "1 min 20 sec", "a minute twenty" -> 80,000 ms
    - Relative expressions: "the last 10 seconds", "last 30s" -> (total - 10s)
    """
    if not expr:
        return None
    s = expr.strip().lower()

    # Relative to end: "the last X seconds / mins"
    m_last = re.match(r"^(?:the\s+)?last\s+([0-9]+(?:\.[0-9]+)?)\s*(s|sec|seconds|m|min|minutes)?$", s)
    if m_last:
        if total_duration_ticks is None:
            return None
        val = float(m_last.group(1))
        unit = m_last.group(2) or "s"
        span_ticks = seconds_to_ticks(val * 60 if unit.startswith("m") else val)
        return max(0, total_duration_ticks - span_ticks)

    # Colloquial: "a minute twenty", "a minute and twenty seconds", "two minutes"
    if s in ("a minute", "one minute"):
        return 60 * TICKS_PER_SECOND
    m_colloquial = re.match(r"^a\s+minute(?:\s+and)?\s+([a-z0-9]+)(?:\s+seconds)?$", s)
    if m_colloquial:
        word_num = m_colloquial.group(1)
        word_to_num = {
            "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25,
            "thirty": 30, "thirty-five": 35, "forty": 40, "forty-five": 45, "fifty": 50
        }
        sec_val = word_to_num.get(word_num)
        if sec_val is not None:
            return (60 + sec_val) * TICKS_PER_SECOND
        if word_num.isdigit():
            return (60 + int(word_num)) * TICKS_PER_SECOND

    # Standard clock: HH:MM:SS or MM:SS
    m_clock = re.match(r"^(\d+):(\d{2})(?::(\d{2}))?$", s)
    if m_clock:
        parts = [int(p) for p in m_clock.groups() if p is not None]
        if len(parts) == 2:
            mins, secs = parts
            return (mins * 60 + secs) * TICKS_PER_SECOND
        elif len(parts) == 3:
            hours, mins, secs = parts
            return (hours * 3600 + mins * 60 + secs) * TICKS_PER_SECOND

    # Explicit minutes & seconds: "1m 20s", "1m20s", "1 min 20 sec"
    m_min_sec = re.match(r"^(\d+)\s*(?:m|min|minutes)\s*(?:and\s*)?(\d+)?\s*(?:s|sec|seconds)?$", s)
    if m_min_sec:
        mins = int(m_min_sec.group(1))
        secs = int(m_min_sec.group(2)) if m_min_sec.group(2) else 0
        return (mins * 60 + secs) * TICKS_PER_SECOND

    # Pure seconds: "80s", "80 seconds", "80", "12.5s"
    m_sec = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(?:s|sec|seconds)?$", s)
    if m_sec:
        return seconds_to_ticks(float(m_sec.group(1)))

    return None
