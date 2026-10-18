"""Word ID anchoring and resolution engine.

Implements the Golden Timeline Rule:
Anchored captions and effects stick to Word IDs across:
- Cuts (if cut, inactive; if restored, automatically reappears)
- Speed changes (duration scales with clip speed, respecting min readable duration of 0.7s)
- Reordering (captions and effects follow their words to their new playback positions)
"""

from typing import List, Optional, Tuple
from engine.core.models import (
    Word,
    Transcript,
    TimelineClip,
    AnchoredCaption,
    AnchoredAudioEffect,
    ResolvedCaption,
    ResolvedAudioEffect,
)


def map_source_time_to_playback(
    source_time: float,
    clips: List[TimelineClip]
) -> Optional[float]:
    """Maps a timestamp in the original media to the playback clock time on the timeline.

    Returns None if the source time falls within a cut region.
    """
    accumulated_playback = 0.0

    for clip in clips:
        # Check if source_time falls within this clip (inclusive with tiny epsilon)
        if (clip.source_start - 1e-4) <= source_time <= (clip.source_end + 1e-4):
            offset_in_clip = max(0.0, source_time - clip.source_start)
            playback_offset = offset_in_clip / clip.speed
            return accumulated_playback + playback_offset

        accumulated_playback += clip.playback_duration

    return None


def map_playback_time_to_source(
    playback_time: float,
    clips: List[TimelineClip]
) -> Optional[float]:
    """Maps a playback clock time back to original media source time."""
    accumulated_playback = 0.0

    for clip in clips:
        clip_dur = clip.playback_duration
        if accumulated_playback <= playback_time <= (accumulated_playback + clip_dur + 1e-4):
            offset_in_clip = (playback_time - accumulated_playback) * clip.speed
            return clip.source_start + offset_in_clip

        accumulated_playback += clip_dur

    return None


def resolve_captions(
    captions: List[AnchoredCaption],
    clips: List[TimelineClip],
    transcript: Transcript,
    min_duration_s: float = 0.70
) -> Tuple[List[ResolvedCaption], List[str]]:
    """Resolves all anchored captions to playback timestamps.

    Returns:
        (resolved_captions, list_of_warning_messages)
    """
    resolved = []
    warnings = []

    for cap in captions:
        if not cap.active or not cap.word_ids:
            continue

        words = [transcript.get_word(wid) for wid in cap.word_ids]
        valid_words = [w for w in words if w is not None]

        if not valid_words:
            continue

        # Check which words are still present in playback
        present_word_times = []
        for w in valid_words:
            p_start = map_source_time_to_playback(w.start, clips)
            p_end = map_source_time_to_playback(w.end, clips)
            if p_start is not None and p_end is not None:
                present_word_times.append((p_start, p_end))

        if not present_word_times:
            warnings.append(
                f"Caption '{cap.text}' is hidden because its anchored words were cut."
            )
            continue

        if len(present_word_times) < len(valid_words):
            warnings.append(
                f"Caption '{cap.text}' partially cut: displaying on {len(present_word_times)}/{len(valid_words)} remaining words."
            )

        start_time = min(pt[0] for pt in present_word_times)
        end_time = max(pt[1] for pt in present_word_times)

        # Enforce minimum readable duration (~0.7s) if sped up or very brief
        duration = end_time - start_time
        if duration < min_duration_s:
            end_time = start_time + min_duration_s

        resolved.append(
            ResolvedCaption(
                caption_id=cap.caption_id,
                text=cap.text,
                playback_start=round(start_time, 3),
                playback_end=round(end_time, 3),
                style=cap.style
            )
        )

    # Sort resolved captions by playback start time
    resolved.sort(key=lambda c: c.playback_start)
    return resolved, warnings


def resolve_audio_effects(
    effects: List[AnchoredAudioEffect],
    clips: List[TimelineClip],
    transcript: Transcript
) -> List[ResolvedAudioEffect]:
    """Resolves anchored mutes and bleeps to current playback timestamps."""
    resolved = []

    for eff in effects:
        if not eff.active or not eff.word_ids:
            continue

        for wid in eff.word_ids:
            word = transcript.get_word(wid)
            if not word:
                continue

            p_start = map_source_time_to_playback(word.start, clips)
            p_end = map_source_time_to_playback(word.end, clips)

            if p_start is not None and p_end is not None:
                resolved.append(
                    ResolvedAudioEffect(
                        effect_id=eff.effect_id,
                        effect_type=eff.effect_type,
                        playback_start=round(min(p_start, p_end), 3),
                        playback_end=round(max(p_start, p_end), 3)
                    )
                )

    resolved.sort(key=lambda e: e.playback_start)
    return resolved
