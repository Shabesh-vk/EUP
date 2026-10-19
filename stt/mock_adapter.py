"""
Deterministic mock transcription adapter for credential-free testing and demonstrations.
Explicitly sets is_mock=True and honest provenance.
"""

from __future__ import annotations
import os
from typing import Optional, Dict, Any, List
from core.schema import Transcript, TranscriptWord
from tests.fixtures.transcript_fixtures import create_sample_transcript_words
from .base import BaseTranscriptionAdapter


class MockTranscriptionAdapter(BaseTranscriptionAdapter):
    """
    Deterministic mock transcription adapter.
    Uses the verified test interview transcript fixture containing host/guest dialogue,
    timings, fillers, silences, and multiple keyword occurrences.
    """

    def __init__(self, fixture_name: str = "test_interview"):
        self._fixture_name = fixture_name

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def supports_native_diarization(self) -> bool:
        return True

    def transcribe(
        self,
        media_path: str,
        *,
        language: Optional[str] = "en",
        timebase: int = 1000,
        duration_ticks: Optional[int] = None,
        **kwargs: Any,
    ) -> Transcript:
        words = create_sample_transcript_words()
        if duration_ticks is not None and duration_ticks > 0:
            words = [w for w in words if w.end_ticks <= duration_ticks]

        return Transcript(
            words=words,
            language=language or "en",
            is_mock=True,
        )
