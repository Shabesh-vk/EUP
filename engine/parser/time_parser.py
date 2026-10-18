"""Time expression parsing utility.

Robustly extracts timestamps and intervals from natural language strings:
- Clock format: "1:20", "0:42", "1:05:30"
- Explicit units: "80 seconds", "45s", "2.5 minutes"
- Natural spoken phrasing: "a minute twenty", "a minute and twenty seconds"
- Relative phrases: "the first 30 seconds", "the last 10 seconds"
- Interval spans: "from 1:00 to 1:30", "0:30-0:40", "between 10 and 20 seconds"
"""

import re
from typing import Optional, Tuple


NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "a": 1, "an": 1
}


def parse_word_number(phrase: str) -> Optional[int]:
    """Converts simple number words like 'twenty', 'thirty', 'two' to an integer."""
    phrase = phrase.strip().lower()
    if phrase in NUMBER_WORDS:
        return NUMBER_WORDS[phrase]
    parts = phrase.split()
    total = 0
    for p in parts:
        if p in NUMBER_WORDS:
            total += NUMBER_WORDS[p]
    return total if total > 0 else None


def parse_timestamp_str(text: str) -> Optional[float]:
    """Parses a single timestamp expression into seconds."""
    text = text.strip().lower()

    # Match MM:SS or HH:MM:SS
    m_clock = re.search(r"\b(\d+):([0-5]\d)(?::([0-5]\d))?\b", text)
    if m_clock:
        p1, p2, p3 = m_clock.groups()
        if p3 is not None:
            return float(p1) * 3600 + float(p2) * 60 + float(p3)
        return float(p1) * 60 + float(p2)

    # Match "X seconds" or "Xs" or "X sec"
    m_sec = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b", text)
    if m_sec:
        return float(m_sec.group(1))

    # Match "X minutes" or "X min"
    m_min = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)\b", text)
    if m_min:
        return float(m_min.group(1)) * 60.0

    # Match spoken phrases: "a minute twenty" or "two minutes thirty"
    m_spoken = re.search(r"\b(a|one|two|three|four|five|\d+)\s+minutes?\s+(?:and\s+)?(\w+|\d+)(?:\s+seconds?)?\b", text)
    if m_spoken:
        mins_part, secs_part = m_spoken.group(1), m_spoken.group(2)
        mins = int(mins_part) if mins_part.isdigit() else (NUMBER_WORDS.get(mins_part, 1))
        secs = int(secs_part) if secs_part.isdigit() else (parse_word_number(secs_part) or 0)
        return float(mins * 60 + secs)

    # Match "a minute twenty" without the word 'minutes'
    m_brief_spoken = re.search(r"\ba\s+minute\s+(\w+)\b", text)
    if m_brief_spoken:
        secs = parse_word_number(m_brief_spoken.group(1))
        if secs is not None:
            return 60.0 + float(secs)

    # Standalone plain number
    if text.isdigit():
        return float(text)

    return None


def parse_time_range(text: str, total_duration: float) -> Optional[Tuple[float, float]]:
    """Extracts a start and end time range from a natural language instruction."""
    lower = text.lower().strip()

    # "the first X seconds / minutes"
    m_first = re.search(r"(?:the\s+)?first\s+(\d+(?:\.\d+)?|\w+)\s*(seconds?|secs?|s|minutes?|mins?)?", lower)
    if m_first:
        val_str = m_first.group(1)
        unit = m_first.group(2) or "seconds"
        val = float(val_str) if val_str.replace(".", "", 1).isdigit() else float(NUMBER_WORDS.get(val_str, 0))
        if "min" in unit:
            val *= 60.0
        return (0.0, min(total_duration, val))

    # "the last X seconds / minutes"
    m_last = re.search(r"(?:the\s+)?last\s+(\d+(?:\.\d+)?|\w+)\s*(seconds?|secs?|s|minutes?|mins?)?", lower)
    if m_last:
        val_str = m_last.group(1)
        unit = m_last.group(2) or "seconds"
        val = float(val_str) if val_str.replace(".", "", 1).isdigit() else float(NUMBER_WORDS.get(val_str, 0))
        if "min" in unit:
            val *= 60.0
        start = max(0.0, total_duration - val)
        return (start, total_duration)

    # "from X to Y" or "between X and Y"
    m_from_to = re.search(r"(?:from|between)\s+([^,]+?)\s+(?:to|and)\s+([^,]+)", lower)
    if m_from_to:
        t1 = parse_timestamp_str(m_from_to.group(1))
        t2 = parse_timestamp_str(m_from_to.group(2))
        if t1 is not None and t2 is not None:
            return (min(t1, t2), max(t1, t2))

    # "X-Y" format e.g. "0:30-0:40"
    m_hyphen = re.search(r"\b(\d+:[0-5]\d|\d+)\s*-\s*(\d+:[0-5]\d|\d+)\b", lower)
    if m_hyphen:
        t1 = parse_timestamp_str(m_hyphen.group(1))
        t2 = parse_timestamp_str(m_hyphen.group(2))
        if t1 is not None and t2 is not None:
            return (min(t1, t2), max(t1, t2))

    return None
