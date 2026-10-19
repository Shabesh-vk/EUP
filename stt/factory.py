"""
Factory for Speech-to-Text transcription adapters.
Provides strict separation between real transcription and deterministic mock adapters.
"""

from __future__ import annotations
import os
from typing import Optional
from api.errors import IncuBrixException
from .base import BaseTranscriptionAdapter
from .mock_adapter import MockTranscriptionAdapter
from .whisper_adapter import FasterWhisperAdapter


def get_transcription_adapter(mode: Optional[str] = None) -> BaseTranscriptionAdapter:
    """
    Get transcription adapter based on requested mode or environment variable `TRANSCRIPTION_MODE`.
    Valid modes: 'real', 'mock', 'auto'.
    """
    selected_mode = (mode or os.environ.get("TRANSCRIPTION_MODE", "mock")).lower().strip()

    if selected_mode == "mock":
        return MockTranscriptionAdapter()

    if selected_mode in ("real", "whisper", "faster_whisper", "faster-whisper"):
        try:
            return FasterWhisperAdapter(model_size=os.environ.get("WHISPER_MODEL", "tiny"))
        except Exception as e:
            raise IncuBrixException(
                code="STT_CONFIGURATION_ERROR",
                message=f"Real transcription requested, but FasterWhisperAdapter failed to initialize: {str(e)}. "
                        f"Ensure model weights and dependencies are available.",
                status_code=500,
            )

    if selected_mode == "auto":
        # Check if faster_whisper is importable
        try:
            import faster_whisper
            return FasterWhisperAdapter(model_size=os.environ.get("WHISPER_MODEL", "tiny"))
        except Exception:
            return MockTranscriptionAdapter()

    raise IncuBrixException(
        code="INVALID_TRANSCRIPTION_MODE",
        message=f"Unknown transcription mode '{selected_mode}'. Must be one of ['real', 'mock', 'auto'].",
        status_code=400,
    )
