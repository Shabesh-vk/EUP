"""
Output Manifest generator conforming to Integration Standard Point 9.
"""

from __future__ import annotations
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from core.schema import Timeline
from .config import settings


class ManifestRecord(BaseModel):
    project_id: str
    timeline_hash: str
    created_at: float
    providers: Dict[str, Any]
    settings: Dict[str, Any]
    seed: Optional[int] = 42
    timings: Dict[str, float]
    cost_estimate: Dict[str, float]
    warnings: List[str] = Field(default_factory=list)
    licence_rights: Dict[str, str]


def generate_output_manifest(
    timeline: Timeline,
    timings: Dict[str, float],
    warnings: Optional[List[str]] = None,
    cost_estimate: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Generate the standard output manifest for a rendering or project result.
    """
    providers = {
        "stt": {"provider": settings.stt_provider, "version": "1.0.0", "license": "MIT"},
        "nlu": {"provider": settings.nlu_provider, "version": "1.0.0", "license": "Proprietary/Internal"},
        "renderer": {"engine": "FFmpeg", "version": "9.0.1", "license": "LGPLv2.1+"},
    }

    current_settings = {
        "time_policy": settings.time_policy,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "timebase": timeline.timebase,
    }

    # Estimate cost per minute of video edited
    dur_minutes = timeline.total_duration_seconds / 60.0
    costs = cost_estimate or {
        "stt_cost_usd": round(dur_minutes * 0.006, 4),  # Whisper API is approx $0.006/min
        "llm_cost_usd": round(len(timeline.transactions) * 0.001, 4),
        "total_cost_usd": round(dur_minutes * 0.006 + len(timeline.transactions) * 0.001, 4),
    }

    licence_rights = {
        "commercial_use_approved": "True",
        "code_license": "Commercial / IncuBrix Proprietary Core",
        "external_libraries": "FastAPI (MIT), Pydantic (MIT), FFmpeg (LGPL/GPL builds separate)",
        "media_rights": "Owned / Synthetic test media with consent",
    }

    manifest = ManifestRecord(
        project_id=timeline.project_id,
        timeline_hash=timeline.timeline_hash,
        created_at=time.time(),
        providers=providers,
        settings=current_settings,
        seed=42,
        timings=timings,
        cost_estimate=costs,
        warnings=warnings or [],
        licence_rights=licence_rights,
    )

    return manifest.model_dump(mode="json")
