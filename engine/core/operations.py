"""High-level deterministic video editing operations.

Translates intent and parameters into timeline modifications while enforcing:
- Immutability
- Silence snapping to avoid word clipping
- Word ID anchoring
- Minimum caption readability constraints
"""

from typing import List, Dict, Any, Optional, Tuple
from engine.core.timeline import Timeline
from engine.core.models import CaptionStyle, Word
from engine.core.silence_snap import snap_cut_boundaries_to_silence


def execute_cut_range(
    timeline: Timeline,
    start_s: float,
    end_s: float,
    source_relative: bool = True,
    snap_silence: bool = True
) -> Tuple[List[Dict[str, Any]], str]:
    """Cuts a time interval, optionally snapping boundaries to adjacent silence."""
    if snap_silence:
        snapped_start, snapped_end, _ = snap_cut_boundaries_to_silence(
            start_s, end_s, timeline.transcript
        )
    else:
        snapped_start, snapped_end = start_s, end_s

    op_result = timeline.apply_cut(snapped_start, snapped_end, source_relative=source_relative)

    cut_dur = snapped_end - snapped_start
    summary = f"Cut {cut_dur:.2f}s from {snapped_start:.2f}s to {snapped_end:.2f}s. New total duration: {timeline.total_duration:.2f}s."
    return [op_result], summary


def execute_speed_change(
    timeline: Timeline,
    start_s: float,
    end_s: float,
    speed: float,
    source_relative: bool = False
) -> Tuple[List[Dict[str, Any]], str]:
    """Applies speed change to a range."""
    op_result = timeline.apply_speed(start_s, end_s, speed, source_relative=source_relative)
    policy_str = "original source time" if source_relative else "current playback time"
    summary = (
        f"Sped up range {start_s:.2f}s to {end_s:.2f}s by {speed}x using {policy_str} policy. "
        f"New total duration: {timeline.total_duration:.2f}s."
    )
    return [op_result], summary


def execute_add_caption(
    timeline: Timeline,
    text: str,
    target_phrase: Optional[str] = None,
    word_ids: Optional[List[str]] = None,
    color: str = "white",
    font_size: int = 28
) -> Tuple[List[Dict[str, Any]], str]:
    """Adds a caption anchored to specific words."""
    matched_ids = word_ids or []
    if not matched_ids and target_phrase:
        # Search transcript for matching phrase
        phrase_words = target_phrase.lower().strip().split()
        all_words = timeline.transcript.words
        for i in range(len(all_words) - len(phrase_words) + 1):
            window = [all_words[i + j].text.lower().strip(".,!?:;\"'") for j in range(len(phrase_words))]
            if window == phrase_words:
                matched_ids = [all_words[i + j].id for j in range(len(phrase_words))]
                break

    if not matched_ids:
        # Fallback to the first few words or all words
        matched_ids = [w.id for w in timeline.transcript.words[:4]]

    style = CaptionStyle(color=color, font_size=font_size)
    op_result = timeline.apply_add_caption(text=text, word_ids=matched_ids, style=style)

    first_word = timeline.transcript.get_word(matched_ids[0])
    last_word = timeline.transcript.get_word(matched_ids[-1])
    orig_time_str = f"{first_word.start:.2f}-{last_word.end:.2f}s" if first_word and last_word else ""

    summary = (
        f"Added caption '{text}' attached to {len(matched_ids)} words "
        f"(original time {orig_time_str})."
    )
    return [op_result], summary


def execute_remove_filler_words(
    timeline: Timeline,
    fillers: Optional[List[str]] = None
) -> Tuple[List[Dict[str, Any]], str]:
    """Detects and cuts filler words ('um', 'uh', and hesitation 'like') without clipping words."""
    if fillers is None:
        fillers = ["um", "uh", "er", "ah"]

    words = timeline.transcript.words
    cuts_to_make: List[Tuple[float, float, str]] = []

    for i, w in enumerate(words):
        clean_text = w.text.lower().strip(".,!?:;\"'")
        is_filler = clean_text in fillers

        # Check for contextual 'like' (only when used as filler, e.g. surrounded by pauses or fillers)
        if clean_text == "like":
            prev_word = words[i - 1] if i > 0 else None
            next_word = words[i + 1] if i + 1 < len(words) else None
            # If isolated by > 250ms silence or adjacent to filler, treat as filler
            gap_before = (w.start - prev_word.end) if prev_word else 0.5
            gap_after = (next_word.start - w.end) if next_word else 0.5
            if gap_before > 0.25 or gap_after > 0.25 or (prev_word and prev_word.text.lower() in fillers):
                is_filler = True

        if is_filler:
            cuts_to_make.append((w.start - 0.03, w.end + 0.03, clean_text))

    if not cuts_to_make:
        return [], "No filler words found."

    # Sort descending by start time to apply cuts from end to beginning
    cuts_to_make.sort(key=lambda x: x[0], reverse=True)
    ops = []
    for c_start, c_end, word_text in cuts_to_make:
        snapped_s, snapped_e, _ = snap_cut_boundaries_to_silence(c_start, c_end, timeline.transcript)
        op = timeline.apply_cut(snapped_s, snapped_e, source_relative=True)
        ops.append(op)

    summary = f"Removed {len(cuts_to_make)} filler words ({', '.join(set(w[2] for w in cuts_to_make))}). New duration: {timeline.total_duration:.2f}s."
    return ops, summary


def execute_remove_silences(
    timeline: Timeline,
    min_silence_s: float = 1.0,
    keep_pause_s: float = 0.20
) -> Tuple[List[Dict[str, Any]], str]:
    """Detects silence gaps > min_silence_s and truncates them down to keep_pause_s."""
    words = sorted(timeline.transcript.words, key=lambda w: w.start)
    if not words:
        return [], "Transcript empty, cannot detect speech silences."

    silences: List[Tuple[float, float]] = []

    # Initial silence before first word
    if words[0].start > min_silence_s:
        silences.append((0.0, words[0].start - keep_pause_s))

    # Silences between consecutive words
    for i in range(len(words) - 1):
        gap = words[i + 1].start - words[i].end
        if gap > min_silence_s:
            cut_start = words[i].end + (keep_pause_s / 2.0)
            cut_end = words[i + 1].start - (keep_pause_s / 2.0)
            if cut_end > cut_start:
                silences.append((cut_start, cut_end))

    # Silence after last word
    if (timeline.source.duration_s - words[-1].end) > min_silence_s:
        silences.append((words[-1].end + keep_pause_s, timeline.source.duration_s))

    if not silences:
        return [], f"No silences longer than {min_silence_s:.1f}s detected."

    # Cut silences in reverse order to keep timestamps valid
    silences.sort(key=lambda s: s[0], reverse=True)
    ops = []
    total_cut_duration = 0.0
    for s_start, s_end in silences:
        total_cut_duration += (s_end - s_start)
        op = timeline.apply_cut(s_start, s_end, source_relative=True)
        ops.append(op)

    summary = (
        f"Removed {len(silences)} silence gaps longer than {min_silence_s:.1f}s "
        f"(trimmed {total_cut_duration:.2f}s total). New duration: {timeline.total_duration:.2f}s."
    )
    return ops, summary


def execute_bleep_or_mute_words(
    timeline: Timeline,
    words_to_mute: List[str],
    effect_type: str = "mute"
) -> Tuple[List[Dict[str, Any]], str]:
    """Applies mute or bleep tone anchored to specific words."""
    all_words = timeline.transcript.words
    target_ids = []
    for w in all_words:
        clean = w.text.lower().strip(".,!?:;\"'")
        if clean in [wt.lower() for wt in words_to_mute]:
            target_ids.append(w.id)

    if not target_ids:
        return [], f"None of the target words ({words_to_mute}) found in transcript."

    op = timeline.apply_audio_effect(
        effect_type="bleep" if effect_type == "bleep" else "mute",
        word_ids=target_ids
    )
    summary = f"Applied {effect_type} to {len(target_ids)} words anchored across timeline."
    return [op], summary


def execute_auto_caption(
    timeline: Timeline,
    words_per_caption: int = 4
) -> Tuple[List[Dict[str, Any]], str]:
    """Generates whole-video auto captions anchored to transcript words."""
    words = timeline.transcript.words
    if not words:
        return [], "Transcript empty, cannot generate auto-captions."

    ops = []
    count = 0
    for i in range(0, len(words), words_per_caption):
        chunk = words[i:i + words_per_caption]
        text = " ".join(w.text for w in chunk)
        chunk_ids = [w.id for w in chunk]
        op = timeline.apply_add_caption(text=text, word_ids=chunk_ids)
        ops.append(op)
        count += 1

    summary = f"Generated {count} auto-captions covering full video anchored to words."
    return ops, summary
