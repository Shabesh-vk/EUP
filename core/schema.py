"""
Pydantic models representing the versioned IncuBrix Timeline.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class SourceMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    filename: str
    sha256_hash: str
    duration_ticks: int = Field(ge=0)
    fps: float = Field(gt=0)
    width: Optional[int] = None
    height: Optional[int] = None
    audio_channels: Optional[int] = None
    sample_rate: Optional[int] = None


class TranscriptWord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    word: str
    start_ticks: int = Field(ge=0)
    end_ticks: int = Field(ge=0)
    speaker: str = "speaker_0"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_filler: bool = False
    is_silence: bool = False


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    words: List[TranscriptWord] = Field(default_factory=list)
    language: str = "en"
    is_mock: bool = False


class ClipSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_id: str
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    speed_ratio: float = Field(default=1.0, gt=0.0)

    @property
    def duration_source_ticks(self) -> int:
        return max(0, self.source_end_ticks - self.source_start_ticks)

    @property
    def duration_output_ticks(self) -> int:
        return int(round(self.duration_source_ticks / self.speed_ratio))


class CaptionEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    anchor_word_ids: List[str] = Field(default_factory=list)
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    group_id: Optional[str] = None
    color: str = "white"
    font_size: int = 36
    position: Literal["bottom", "top", "center"] = "bottom"
    min_duration_s: float = 0.7
    is_suppressed: bool = False
    suppression_reason: Optional[str] = None


class MuteEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    anchor_word_ids: List[str] = Field(default_factory=list)
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    is_suppressed: bool = False


class BleepEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    anchor_word_ids: List[str] = Field(default_factory=list)
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    frequency_hz: int = 1000
    is_suppressed: bool = False


class MusicDucking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    threshold_db: float = -20.0
    attenuation_db: float = -14.0


class MusicEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    asset_url: str
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    volume: float = Field(default=0.3, ge=0.0, le=2.0)
    ducking: MusicDucking = Field(default_factory=MusicDucking)


class TextOverlayEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    color: str = "white"
    is_suppressed: bool = False


class EffectsCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captions: List[CaptionEffect] = Field(default_factory=list)
    mutes: List[MuteEffect] = Field(default_factory=list)
    bleeps: List[BleepEffect] = Field(default_factory=list)
    music: List[MusicEffect] = Field(default_factory=list)
    text_overlays: List[TextOverlayEffect] = Field(default_factory=list)


class TransactionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    instruction: str
    operation_type: str
    status: Literal["applied", "undone", "restored"] = "applied"
    applied_at_step: int
    details: Dict[str, Any] = Field(default_factory=dict)
    # Snapshots / delta patches for reversible undo/redo/restore
    inverse_segments: Optional[List[ClipSegment]] = None
    applied_segments: Optional[List[ClipSegment]] = None
    affected_effect_ids: List[str] = Field(default_factory=list)


class Timeline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0.0"
    project_id: str
    timebase: int = 1000  # ticks per second
    source_media: SourceMedia
    transcript: Transcript = Field(default_factory=Transcript)
    segments: List[ClipSegment] = Field(default_factory=list)
    effects: EffectsCollection = Field(default_factory=EffectsCollection)
    transactions: List[TransactionRecord] = Field(default_factory=list)
    timeline_hash: str = ""

    @property
    def total_duration_ticks(self) -> int:
        return sum(seg.duration_output_ticks for seg in self.segments)

    @property
    def total_duration_seconds(self) -> float:
        return round(self.total_duration_ticks / self.timebase, 3)


class AutoEditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    category: Literal["silence", "filler_word", "auto_caption", "music"]
    description: str
    source_start_ticks: int = Field(ge=0)
    source_end_ticks: int = Field(ge=0)
    output_start_ticks: Optional[int] = None
    output_end_ticks: Optional[int] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_uncertain: bool = False
    excluded: bool = False


class AutoEditPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    project_id: str
    base_timeline_hash: str
    created_at: float
    current_duration_s: float
    estimated_duration_s: float
    items: List[AutoEditItem] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
