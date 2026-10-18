"""Core data models representing the timeline, transcript, and edit operations.

Implements the Golden Timeline Rule:
- Original media is immutable.
- All edits are recorded as an append-only event history.
- Overlays (captions), audio effects (mutes, bleeps), and modifications are
  anchored to Word IDs rather than clock timestamps, guaranteeing that cuts,
  speed shifts, and reorders track content automatically.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class Word(BaseModel):
    """A single transcribed word with timestamps and speaker attribution."""
    id: str = Field(..., description="Unique word identifier, e.g. 'w_0'")
    text: str = Field(..., description="Clean text of the word")
    start: float = Field(..., description="Start timestamp in original media (seconds)")
    end: float = Field(..., description="End timestamp in original media (seconds)")
    confidence: float = Field(default=1.0, description="Transcription confidence score (0.0 to 1.0)")
    speaker: str = Field(default="speaker_0", description="Speaker label (e.g., 'host', 'guest')")


class Transcript(BaseModel):
    """Full transcript of the original media."""
    language: str = "en"
    words: List[Word] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return " ".join(w.text for w in self.words)

    def get_word(self, word_id: str) -> Optional[Word]:
        for w in self.words:
            if w.id == word_id:
                return w
        return None

    def words_in_range(self, start: float, end: float) -> List[Word]:
        """Returns words whose midpoint falls within [start, end]."""
        matches = []
        for w in self.words:
            mid = (w.start + w.end) / 2.0
            if start <= mid <= end:
                matches.append(w)
        return matches


class SourceMedia(BaseModel):
    """Metadata of the original untouched media file."""
    media_id: str
    file_path: str
    sha256: str
    duration_s: float
    fps: float = 30.0
    sample_rate: int = 48000
    channels: int = 2
    width: int = 1920
    height: int = 1080


class TimelineClip(BaseModel):
    """A contiguous slice of original media playing at a specified speed."""
    clip_id: str
    source_start: float = Field(..., description="Start offset in original media (seconds)")
    source_end: float = Field(..., description="End offset in original media (seconds)")
    speed: float = Field(default=1.0, description="Playback speed factor (e.g. 1.0, 2.0, 0.5)")
    word_ids: List[str] = Field(default_factory=list, description="IDs of words falling in this clip")

    @property
    def source_duration(self) -> float:
        return max(0.0, self.source_end - self.source_start)

    @property
    def playback_duration(self) -> float:
        if self.speed <= 0:
            return 0.0
        return self.source_duration / self.speed


class CaptionStyle(BaseModel):
    """Visual presentation parameters for captions."""
    color: str = "white"
    font_size: int = 28
    position: str = "bottom"
    background_box: bool = True
    highlight_color: Optional[str] = None


class AnchoredCaption(BaseModel):
    """A caption anchored to specific Word IDs from the transcript."""
    caption_id: str
    text: str
    word_ids: List[str] = Field(..., description="Word IDs this caption is anchored to")
    style: CaptionStyle = Field(default_factory=CaptionStyle)
    created_step: int = 0
    active: bool = True


class AnchoredAudioEffect(BaseModel):
    """An audio effect (mute or bleep) anchored to specific Word IDs."""
    effect_id: str
    effect_type: Literal["mute", "bleep"]
    word_ids: List[str]
    created_step: int = 0
    active: bool = True


class BackgroundMusicTrack(BaseModel):
    """Background music overlay with automated ducking under speech."""
    track_id: str
    music_file_path: str
    volume: float = 0.20
    ducking_volume: float = 0.05
    duck_under_speech: bool = True


class EditOperation(BaseModel):
    """Structured operation record."""
    op_type: str = Field(..., description="e.g. cut_range, speed_up, add_caption, mute_words")
    params: Dict[str, Any] = Field(default_factory=dict)


class EditStep(BaseModel):
    """A user instruction and its resulting structured operations in the immutable event log."""
    step_index: int
    instruction: str
    operations: List[EditOperation] = Field(default_factory=list)
    summary: str = ""
    timestamp: str = ""
    undone: bool = False


class InstructionResult(BaseModel):
    """Standardized three-way answer returned for every user instruction."""
    status: Literal["applied", "needs_clarification", "rejected"]
    operations: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    question: Optional[str] = None
    options: Optional[List[str]] = None
    reason: Optional[str] = None
    timeline_hash: Optional[str] = None
    duration_s: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)


class ResolvedCaption(BaseModel):
    """A caption whose playback start and end times have been derived from current clips."""
    caption_id: str
    text: str
    playback_start: float
    playback_end: float
    style: CaptionStyle


class ResolvedAudioEffect(BaseModel):
    """An audio effect whose playback start and end times have been derived from current clips."""
    effect_id: str
    effect_type: Literal["mute", "bleep"]
    playback_start: float
    playback_end: float
