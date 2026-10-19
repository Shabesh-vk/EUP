"""
Real transcription adapter powered by faster-whisper.
Extracts word-level timestamps, confidence scores, filler tags, and honest provenance.
"""

from __future__ import annotations
import os
import re
from typing import Optional, Dict, Any, List
from core.schema import Transcript, TranscriptWord
from .base import BaseTranscriptionAdapter

FILLER_WORDS = {"um", "uh", "like", "hmm", "ah", "er"}


class FasterWhisperAdapter(BaseTranscriptionAdapter):
    """
    Real local Speech-to-Text adapter using faster-whisper (CTranslate2).
    Generates word-level timestamps, probabilities, and honest provenance records.
    """

    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    @property
    def provider_name(self) -> str:
        return "faster-whisper"

    @property
    def supports_native_diarization(self) -> bool:
        # Vanilla faster-whisper does not natively perform speaker diarization
        return False

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to initialize faster-whisper model '{self.model_size}': {str(e)}"
                ) from e
        return self._model

    def transcribe(
        self,
        media_path: str,
        *,
        language: Optional[str] = "en",
        timebase: int = 1000,
        **kwargs: Any,
    ) -> Transcript:
        if not os.path.isfile(media_path):
            raise FileNotFoundError(f"Media file not found for transcription: {media_path}")

        model = self._get_model()
        whisper_lang = None if language in (None, "auto", "") else language
        segments, info = model.transcribe(
            media_path,
            word_timestamps=True,
            language=whisper_lang,
            vad_filter=True,
        )

        words: List[TranscriptWord] = []
        word_idx = 0

        for segment in segments:
            # Segment level fallback if word_timestamps wasn't emitted for some reason
            if not segment.words:
                cleaned_text = segment.text.strip()
                raw_words = cleaned_text.split()
                if not raw_words:
                    continue
                seg_duration = max(0.1, segment.end - segment.start)
                word_dur = seg_duration / len(raw_words)
                for i, rw in enumerate(raw_words):
                    s_sec = segment.start + (i * word_dur)
                    e_sec = s_sec + word_dur
                    clean_w = re.sub(r"[^\w\s']", "", rw).strip()
                    if not clean_w:
                        continue
                    w_item = TranscriptWord(
                        id=f"w_{word_idx:05d}",
                        word=clean_w,
                        start_ticks=int(round(s_sec * timebase)),
                        end_ticks=int(round(e_sec * timebase)),
                        speaker="speaker_0",
                        confidence=0.85,
                        is_filler=clean_w.lower() in FILLER_WORDS,
                        is_silence=False,
                    )
                    words.append(w_item)
                    word_idx += 1
                continue

            for w in segment.words:
                clean_w = re.sub(r"[^\w\s']", "", w.word).strip()
                if not clean_w:
                    continue
                w_item = TranscriptWord(
                    id=f"w_{word_idx:05d}",
                    word=clean_w,
                    start_ticks=int(round(w.start * timebase)),
                    end_ticks=int(round(w.end * timebase)),
                    speaker="speaker_0",  # Honest unassigned speaker label
                    confidence=round(float(w.probability), 3),
                    is_filler=clean_w.lower() in FILLER_WORDS,
                    is_silence=False,
                )
                words.append(w_item)
                word_idx += 1

        return Transcript(
            words=words,
            language=info.language or language or "en",
            is_mock=False,
        )
