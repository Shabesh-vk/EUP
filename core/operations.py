"""
Structured editing operation definitions for the IncuBrix Editing Engine.
"""

from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any, Tuple
from pydantic import BaseModel, Field, ConfigDict


class BaseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_type: str


class CutRangeOperation(BaseOperation):
    operation_type: Literal["cut_range"] = "cut_range"
    start_ticks: int = Field(ge=0)
    end_ticks: int = Field(ge=0)
    time_domain: Literal["current_edited_time", "source_time"] = "current_edited_time"


class KeepRangeOperation(BaseOperation):
    operation_type: Literal["keep_range"] = "keep_range"
    start_ticks: int = Field(ge=0)
    end_ticks: int = Field(ge=0)
    time_domain: Literal["current_edited_time", "source_time"] = "current_edited_time"


class SplitSegmentOperation(BaseOperation):
    operation_type: Literal["split_segment"] = "split_segment"
    split_ticks: int = Field(ge=0)
    time_domain: Literal["current_edited_time", "source_time"] = "current_edited_time"


class DeleteSegmentOperation(BaseOperation):
    operation_type: Literal["delete_segment"] = "delete_segment"
    segment_id: str


class ReorderSegmentsOperation(BaseOperation):
    operation_type: Literal["reorder_segments"] = "reorder_segments"
    # Order of segments by segment_id or index
    new_order_segment_ids: List[str]


class SpeedRangeOperation(BaseOperation):
    operation_type: Literal["speed_range"] = "speed_range"
    start_ticks: int = Field(ge=0)
    end_ticks: int = Field(ge=0)
    speed_ratio: float = Field(gt=0.0)
    time_domain: Literal["current_edited_time", "source_time"] = "current_edited_time"


class MuteWordsOperation(BaseOperation):
    operation_type: Literal["mute_words"] = "mute_words"
    word_ids: List[str] = Field(default_factory=list)
    source_start_ticks: Optional[int] = None
    source_end_ticks: Optional[int] = None


class BleepWordsOperation(BaseOperation):
    operation_type: Literal["bleep_words"] = "bleep_words"
    word_ids: List[str] = Field(default_factory=list)
    source_start_ticks: Optional[int] = None
    source_end_ticks: Optional[int] = None
    frequency_hz: int = 1000


class AddCaptionOperation(BaseOperation):
    operation_type: Literal["add_caption"] = "add_caption"
    text: str
    anchor_word_ids: List[str] = Field(default_factory=list)
    source_start_ticks: Optional[int] = None
    source_end_ticks: Optional[int] = None
    color: str = "white"
    font_size: int = 36
    position: Literal["bottom", "top", "center"] = "bottom"
    min_duration_s: float = 0.7


class EditCaptionOperation(BaseOperation):
    operation_type: Literal["edit_caption"] = "edit_caption"
    caption_id: Optional[str] = None
    group_id: Optional[str] = None
    target: Optional[str] = None  # e.g. "them", "all", "group"
    color: Optional[str] = None
    font_size: Optional[int] = None
    font_size_delta: Optional[int] = None  # e.g. +8 for "bigger", -6 for "smaller"
    position: Optional[Literal["bottom", "top", "center"]] = None
    text: Optional[str] = None


class AutoCaptionOperation(BaseOperation):
    operation_type: Literal["auto_caption"] = "auto_caption"
    group_id: str = "captions_main"
    max_words_per_caption: int = 6
    font_size: int = 36
    color: str = "white"
    position: Literal["bottom", "top", "center"] = "bottom"


class RemoveFillerWordsOperation(BaseOperation):
    operation_type: Literal["remove_filler_words"] = "remove_filler_words"
    target_fillers: List[str] = Field(default_factory=lambda: ["um", "uh", "like"])
    only_when_filler: bool = True


class RemoveSilenceOperation(BaseOperation):
    operation_type: Literal["remove_silence"] = "remove_silence"
    min_duration_ticks: int = Field(ge=100)  # default: e.g. 1000ms
    respect_protected_pauses: bool = True
    protected_ranges: List[Tuple[int, int]] = Field(default_factory=list)


class AddMusicOperation(BaseOperation):
    operation_type: Literal["add_music"] = "add_music"
    asset_url: str
    volume: float = Field(default=0.3, ge=0.0, le=2.0)
    ducking_enabled: bool = True
    ducking_threshold_db: float = -20.0
    ducking_attenuation_db: float = -14.0


class UndoOperation(BaseOperation):
    operation_type: Literal["undo"] = "undo"


class RedoOperation(BaseOperation):
    operation_type: Literal["redo"] = "redo"


class RestoreTransactionOperation(BaseOperation):
    operation_type: Literal["restore_transaction"] = "restore_transaction"
    target_transaction_id: Optional[str] = None
    target_step: Optional[int] = None
    description: Optional[str] = None
