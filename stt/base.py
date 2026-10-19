"""
Base interfaces and data structures for Speech-to-Text (STT) transcription and diarization.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from core.schema import Transcript, TranscriptWord


class BaseTranscriptionAdapter(ABC):
    """
    Abstract Base Class for STT transcription providers.
    Supports honest reporting of provenance, confidence, and diarization capabilities.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g., 'faster-whisper', 'openai', 'mock')."""
        pass

    @property
    @abstractmethod
    def supports_native_diarization(self) -> bool:
        """Whether this provider can natively assign confident speaker diarization labels."""
        pass

    @abstractmethod
    def transcribe(
        self,
        media_path: str,
        *,
        language: Optional[str] = "en",
        timebase: int = 1000,
        **kwargs: Any,
    ) -> Transcript:
        """
        Transcribe the audio/video file at `media_path` and return a valid Transcript
        containing word-level timings, IDs, confidence, speaker assignments, and provenance.
        """
        pass
