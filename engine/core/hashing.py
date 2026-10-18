"""Deterministic timeline hashing.

Ensures 100% deterministic timeline hashing across multiple runs:
Running the same session multiple times produces identical SHA-256 timeline_hash.
Floating-point timestamps are canonically rounded to 3 decimal places (millisecond precision)
to ensure cross-platform reproducibility.
"""

import hashlib
import json
from typing import List, Dict, Any
from engine.core.models import TimelineClip, AnchoredCaption, AnchoredAudioEffect, BackgroundMusicTrack


def compute_timeline_hash(
    clips: List[TimelineClip],
    captions: List[AnchoredCaption],
    effects: List[AnchoredAudioEffect],
    music: List[BackgroundMusicTrack],
    source_sha256: str
) -> str:
    """Computes a deterministic SHA-256 hash of the resolved timeline state."""
    canonical_clips = []
    for c in clips:
        canonical_clips.append({
            "source_start": round(c.source_start, 3),
            "source_end": round(c.source_end, 3),
            "speed": round(c.speed, 3),
            "word_ids": sorted(c.word_ids)
        })

    canonical_captions = []
    for cap in captions:
        if cap.active:
            canonical_captions.append({
                "id": cap.caption_id,
                "text": cap.text.strip(),
                "word_ids": sorted(cap.word_ids),
                "color": cap.style.color.lower(),
                "position": cap.style.position.lower(),
                "font_size": cap.style.font_size
            })
    canonical_captions.sort(key=lambda x: x["id"])

    canonical_effects = []
    for eff in effects:
        if eff.active:
            canonical_effects.append({
                "id": eff.effect_id,
                "type": eff.effect_type,
                "word_ids": sorted(eff.word_ids)
            })
    canonical_effects.sort(key=lambda x: x["id"])

    canonical_music = []
    for m in music:
        canonical_music.append({
            "id": m.track_id,
            "volume": round(m.volume, 3),
            "ducking_volume": round(m.ducking_volume, 3),
            "duck_under_speech": m.duck_under_speech
        })
    canonical_music.sort(key=lambda x: x["id"])

    payload = {
        "source_sha256": source_sha256,
        "clips": canonical_clips,
        "captions": canonical_captions,
        "effects": canonical_effects,
        "music": canonical_music
    }

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
