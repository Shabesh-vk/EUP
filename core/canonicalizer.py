"""
Canonical serialization and deterministic timeline_hash calculation.
"""

from __future__ import annotations
import hashlib
import json
from urllib.parse import urlparse
from typing import Dict, Any, List
from .schema import Timeline


def _sanitize_asset_path(url: str) -> str:
    """Strip expiring tokens or query parameters from asset URLs to preserve determinism."""
    if not url:
        return ""
    parsed = urlparse(url)
    # Retain scheme, netloc, and path, but strip query params and fragment
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path


def extract_semantic_state(timeline: Timeline) -> Dict[str, Any]:
    """
    Extract strictly semantic editing state, excluding ephemeral session IDs,
    database timestamps, presigned URL tokens, execution latencies, or worker IDs.
    """
    # 1. Source media identity
    source = {
        "sha256": timeline.source_media.sha256_hash,
        "duration_ticks": timeline.source_media.duration_ticks,
        "fps": round(timeline.source_media.fps, 4),
        "timebase": timeline.timebase,
    }

    # 2. Active playback segments in sequence
    segments = [
        {
            "start": seg.source_start_ticks,
            "end": seg.source_end_ticks,
            "speed": round(seg.speed_ratio, 4),
        }
        for seg in timeline.segments
    ]

    # 3. Active & suppressed effects
    captions = [
        {
            "text": cap.text,
            "start": cap.source_start_ticks,
            "end": cap.source_end_ticks,
            "color": cap.color.lower(),
            "font_size": cap.font_size,
            "group_id": cap.group_id or "",
            "position": cap.position,
            "min_duration_s": round(cap.min_duration_s, 2),
            "is_suppressed": cap.is_suppressed,
            "anchor_words": sorted(cap.anchor_word_ids),
        }
        for cap in sorted(timeline.effects.captions, key=lambda c: (c.source_start_ticks, c.text))
    ]

    mutes = [
        {
            "start": m.source_start_ticks,
            "end": m.source_end_ticks,
            "is_suppressed": m.is_suppressed,
        }
        for m in sorted(timeline.effects.mutes, key=lambda m: (m.source_start_ticks, m.source_end_ticks))
    ]

    bleeps = [
        {
            "start": b.source_start_ticks,
            "end": b.source_end_ticks,
            "frequency_hz": b.frequency_hz,
            "is_suppressed": b.is_suppressed,
        }
        for b in sorted(timeline.effects.bleeps, key=lambda b: (b.source_start_ticks, b.source_end_ticks))
    ]

    music = [
        {
            "asset": _sanitize_asset_path(mus.asset_url),
            "start": mus.source_start_ticks,
            "end": mus.source_end_ticks,
            "volume": round(mus.volume, 2),
            "ducking": {
                "enabled": mus.ducking.enabled,
                "threshold_db": round(mus.ducking.threshold_db, 2),
                "attenuation_db": round(mus.ducking.attenuation_db, 2),
            },
        }
        for mus in sorted(timeline.effects.music, key=lambda m: (m.source_start_ticks, m.asset_url))
    ]

    text_overlays = [
        {
            "text": o.text,
            "start": o.source_start_ticks,
            "end": o.source_end_ticks,
            "color": o.color.lower(),
            "is_suppressed": o.is_suppressed,
        }
        for o in sorted(timeline.effects.text_overlays, key=lambda o: (o.source_start_ticks, o.text))
    ]

    # 4. Transactions journal (semantic sequence)
    transactions = [
        {
            "instruction": tx.instruction,
            "operation_type": tx.operation_type,
            "status": tx.status,
            "step": tx.applied_at_step,
        }
        for tx in timeline.transactions
    ]

    return {
        "source": source,
        "segments": segments,
        "effects": {
            "captions": captions,
            "mutes": mutes,
            "bleeps": bleeps,
            "music": music,
            "text_overlays": text_overlays,
        },
        "transactions": transactions,
    }


def compute_timeline_hash(timeline: Timeline) -> str:
    """
    Compute a deterministic SHA-256 hash of the canonicalized semantic timeline state.
    """
    state = extract_semantic_state(timeline)
    canonical_json = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
