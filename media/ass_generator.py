"""
ASS (Advanced SubStation Alpha) subtitle generator for frame-accurate caption rendering.
"""

from __future__ import annotations
import os
from typing import List
from core.schema import Timeline, CaptionEffect
from core.engine import TimelineEngine
from core.time_ticks import ticks_to_seconds


def ticks_to_ass_timestamp(ticks: int) -> str:
    """Format milliseconds into ASS timestamp format: H:MM:SS.cs"""
    total_cs = max(0, ticks // 10)  # centiseconds (100 per sec)
    cs = total_cs % 100
    total_seconds = total_cs // 100
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def color_to_ass_hex(color_name: str) -> str:
    """
    Convert CSS/English color names to ASS color format (&H00BBGGRR&).
    Note: ASS uses BGR order, not RGB!
    """
    c = color_name.strip().lower()
    color_map = {
        "white": "&H00FFFFFF&",
        "red": "&H000000FF&",        # Blue=00, Green=00, Red=FF
        "yellow": "&H0000FFFF&",     # Blue=00, Green=FF, Red=FF
        "blue": "&H00FF0000&",       # Blue=FF, Green=00, Red=00
        "green": "&H0000FF00&",      # Blue=00, Green=FF, Red=00
        "black": "&H00000000&",
        "cyan": "&H00FFFF00&",
        "magenta": "&H00FF00FF&",
    }
    return color_map.get(c, "&H00FFFFFF&")


def alignment_to_ass(position: str) -> int:
    """ASS numpad alignment: 2 = bottom-center, 8 = top-center, 5 = middle-center."""
    p = position.lower()
    if p == "top":
        return 8
    elif p == "center":
        return 5
    return 2  # bottom


def generate_ass_subtitles(timeline: Timeline, output_ass_path: str) -> bool:
    """
    Generate an ASS subtitle file from active captions on the timeline.
    Returns True if any active captions were written, False if no captions.
    """
    engine = TimelineEngine(timeline)
    active_captions = [c for c in timeline.effects.captions if not c.is_suppressed]
    if not active_captions:
        return False

    lines: List[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: DefaultStyle, Arial, 42, &H00FFFFFF&, &H000000FF&, &H00000000&, &H00000000&, -1, 0, 0, 0, 100, 100, 0, 0, 1, 2.5, 1.5, 2, 40, 40, 50, 1",
        "Style: RedStyle, Arial, 42, &H000000FF&, &H000000FF&, &H00000000&, &H00000000&, -1, 0, 0, 0, 100, 100, 0, 0, 1, 2.5, 1.5, 2, 40, 40, 50, 1",
        "Style: YellowStyle, Arial, 42, &H0000FFFF&, &H000000FF&, &H00000000&, &H00000000&, -1, 0, 0, 0, 100, 100, 0, 0, 1, 2.5, 1.5, 2, 40, 40, 50, 1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for cap in active_captions:
        t_out_start = engine.project_source_to_output(cap.source_start_ticks)
        t_out_end = engine.project_source_to_output(cap.source_end_ticks)
        if t_out_start is None or t_out_end is None:
            continue

        # Enforce minimum readable duration (~0.7s)
        eff_dur_s = (t_out_end - t_out_start) / 1000.0
        if eff_dur_s < cap.min_duration_s:
            t_out_end = t_out_start + int(round(cap.min_duration_s * 1000))

        # Clamp to video end
        t_out_end = min(t_out_end, timeline.total_duration_ticks)

        ass_start = ticks_to_ass_timestamp(t_out_start)
        ass_end = ticks_to_ass_timestamp(t_out_end)

        style_name = "DefaultStyle"
        color_lower = cap.color.lower()
        if "red" in color_lower:
            style_name = "RedStyle"
        elif "yellow" in color_lower:
            style_name = "YellowStyle"

        align_code = alignment_to_ass(cap.position)
        ass_color = color_to_ass_hex(cap.color)
        fsize = max(16, min(120, cap.font_size))

        # In-line formatting override: {\anX\fsY\c&HBBGGRR&}
        text_formatted = f"{{\\an{align_code}\\fs{fsize}\\c{ass_color}}}{cap.text}"
        lines.append(f"Dialogue: 0,{ass_start},{ass_end},{style_name},,0,0,0,,{text_formatted}")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return True
