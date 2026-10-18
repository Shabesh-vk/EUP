"""
Core Data Models for the IncuBrix Prompt-Based Video Editing Engine.
Fully compliant with Content-Based Anchoring and Integration Standards.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
import hashlib
import json


class Word(BaseModel):
    """Word-level transcript entry."""
    id: int = Field(..., description="Unique 0-indexed word identifier")
    text: str = Field(..., description="The spoken word text")
    start: float = Field(..., description="Start timestamp in original video seconds")
    end: float = Field(..., description="End timestamp in original video seconds")
    speaker: str = Field(default="speaker_0", description="Speaker identifier")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Transcription confidence score")
    is_filler: bool = Field(default=False, description="True if marked as filler word (um, uh, like)")


class Transcript(BaseModel):
    """Immutable source transcript of the video."""
    words: List[Word] = Field(default_factory=list)
    duration: float = Field(..., description="Total duration of original source video in seconds")
    language: str = Field(default="en")

    def get_word(self, word_id: int) -> Optional[Word]:
        if 0 <= word_id < len(self.words):
            return self.words[word_id]
        return None

    def find_words_by_text(self, text: str, case_sensitive: bool = False) -> List[int]:
        target = text if case_sensitive else text.lower()
        matches = []
        for w in self.words:
            w_text = w.text if case_sensitive else w.text.lower()
            if target in w_text:
                matches.append(w.id)
        return matches

    def find_phrase(self, phrase: str) -> List[tuple[int, int]]:
        """Find occurrences of multi-word phrase; returns list of (start_word_id, end_word_id)."""
        phrase_words = [w.strip().lower() for w in phrase.split() if w.strip()]
        if not phrase_words:
            return []
        
        occurrences = []
        n = len(phrase_words)
        m = len(self.words)
        
        for i in range(m - n + 1):
            match = True
            for j in range(n):
                cleaned_word = ''.join(c for c in self.words[i + j].text.lower() if c.isalnum())
                target_word = ''.join(c for c in phrase_words[j] if c.isalnum())
                if cleaned_word != target_word:
                    match = False
                    break
            if match:
                occurrences.append((i, i + n - 1))
        return occurrences


class Segment(BaseModel):
    """
    Active slice of original media.
    All edits compose segments deterministically.
    """
    id: str
    source_start: float = Field(..., description="Start time in original media seconds")
    source_end: float = Field(..., description="End time in original media seconds")
    speed: float = Field(default=1.0, gt=0.0, description="Playback speed multiplier")

    @property
    def source_duration(self) -> float:
        return max(0.0, self.source_end - self.source_start)

    @property
    def timeline_duration(self) -> float:
        return self.source_duration / self.speed


class CaptionStyle(BaseModel):
    color: str = Field(default="white")
    font_size: int = Field(default=24)
    font_name: str = Field(default="Arial")
    alignment: Literal["bottom", "top", "center"] = Field(default="bottom")
    outline_color: str = Field(default="black")
    outline_width: int = Field(default=2)


class Caption(BaseModel):
    """
    Content-anchored caption.
    Pinned to word IDs so it follows content regardless of cuts/speeds.
    """
    id: str
    text: str
    start_word_id: int
    end_word_id: int
    style: CaptionStyle = Field(default_factory=CaptionStyle)
    # Cached timeline playback times, computed dynamically by engine
    timeline_start: Optional[float] = None
    timeline_end: Optional[float] = None
    is_active: bool = True


class AudioEffect(BaseModel):
    """Content-anchored audio effect (mute or bleep)."""
    id: str
    effect_type: Literal["mute", "bleep"]
    start_word_id: int
    end_word_id: int
    timeline_start: Optional[float] = None
    timeline_end: Optional[float] = None
    is_active: bool = True


class BackgroundMusic(BaseModel):
    """Background audio track with automatic ducking under speech."""
    id: str
    source_url_or_path: str
    volume: float = Field(default=0.3, ge=0.0, le=1.0)
    ducking: bool = Field(default=True)
    duck_volume: float = Field(default=0.1, ge=0.0, le=1.0)


class Timeline(BaseModel):
    """
    The complete edited video timeline described as data.
    """
    source_video_url: str
    original_duration: float
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    segments: List[Segment] = Field(default_factory=list)
    captions: List[Caption] = Field(default_factory=list)
    audio_effects: List[AudioEffect] = Field(default_factory=list)
    background_music: Optional[BackgroundMusic] = None

    @property
    def total_duration(self) -> float:
        return sum(seg.timeline_duration for seg in self.segments)

    def compute_hash(self) -> str:
        """
        Deterministic SHA-256 hash of the timeline structure.
        Ensures identical timeline structure produces identical hash across runs.
        """
        canonical = {
            "source_video_url": self.source_video_url,
            "segments": [
                {
                    "source_start": round(s.source_start, 4),
                    "source_end": round(s.source_end, 4),
                    "speed": round(s.speed, 4),
                }
                for s in self.segments
            ],
            "captions": [
                {
                    "id": c.id,
                    "text": c.text,
                    "start_word_id": c.start_word_id,
                    "end_word_id": c.end_word_id,
                    "style": c.style.model_dump(),
                    "is_active": c.is_active,
                }
                for c in sorted(self.captions, key=lambda x: x.id)
            ],
            "audio_effects": [
                {
                    "id": a.id,
                    "type": a.effect_type,
                    "start_word_id": a.start_word_id,
                    "end_word_id": a.end_word_id,
                    "is_active": a.is_active,
                }
                for a in sorted(self.audio_effects, key=lambda x: x.id)
            ],
            "background_music": self.background_music.model_dump() if self.background_music else None,
        }
        encoded = json.dumps(canonical, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class Operation(BaseModel):
    """Structured operation emitted by AI brain or user action."""
    op: Literal[
        "cut_range",
        "keep_only",
        "speed_change",
        "mute_words",
        "bleep_words",
        "add_caption",
        "auto_caption",
        "remove_filler",
        "remove_silence",
        "add_bg_music",
        "undo",
        "redo",
        "restore_edit",
        "style_caption"
    ]
    params: Dict[str, Any] = Field(default_factory=dict)


class Clarification(BaseModel):
    question: str
    options: List[str]


class StepResponse(BaseModel):
    """
    Standard output format for every instruction.
    Strictly follows IncuBrix rules: applied | needs_clarification | rejected.
    """
    status: Literal["applied", "needs_clarification", "rejected"]
    summary: str
    operations: List[Operation] = Field(default_factory=list)
    clarification: Optional[Clarification] = None
    rejection_reason: Optional[str] = None
    timeline_hash: Optional[str] = None
    duration_s: Optional[float] = None
