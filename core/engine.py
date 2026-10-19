"""
Deterministic Timeline Editing Engine for IncuBrix.
"""

from __future__ import annotations
import copy
import time
import uuid
from typing import List, Optional, Tuple, Dict, Any, Literal
from pydantic import BaseModel, Field

from .schema import (
    Timeline,
    ClipSegment,
    CaptionEffect,
    MuteEffect,
    BleepEffect,
    MusicEffect,
    TextOverlayEffect,
    TranscriptWord,
    AutoEditItem,
    AutoEditPlan,
)
from .time_ticks import ticks_to_seconds, seconds_to_ticks
from .canonicalizer import compute_timeline_hash
from .history import HistoryManager
from .operations import (
    BaseOperation,
    CutRangeOperation,
    KeepRangeOperation,
    SplitSegmentOperation,
    DeleteSegmentOperation,
    ReorderSegmentsOperation,
    SpeedRangeOperation,
    MuteWordsOperation,
    BleepWordsOperation,
    AddCaptionOperation,
    EditCaptionOperation,
    AutoCaptionOperation,
    RemoveFillerWordsOperation,
    RemoveSilenceOperation,
    AddMusicOperation,
    UndoOperation,
    RedoOperation,
    RestoreTransactionOperation,
)


class EngineResponse(BaseModel):
    status: Literal["applied", "needs_clarification", "rejected"]
    operations: List[str] = Field(default_factory=list)
    summary: str
    question: Optional[str] = None
    options: Optional[List[str]] = None
    timeline_hash: str
    duration_s: float
    time_policy: str = "current_edited_time"
    warnings: List[str] = Field(default_factory=list)
    error: Optional[Dict[str, Any]] = None


class TimelineEngine:
    """
    Pure deterministic timeline logic engine.
    """

    def __init__(self, timeline: Timeline):
        self.timeline = timeline
        self.history = HistoryManager(self.timeline)
        if not self.timeline.timeline_hash:
            self.recompute_hash()

    def recompute_hash(self) -> str:
        self.timeline.timeline_hash = compute_timeline_hash(self.timeline)
        return self.timeline.timeline_hash

    # -------------------------------------------------------------------------
    # Coordinate Projection Helpers
    # -------------------------------------------------------------------------

    def project_source_to_output(self, source_ticks: int) -> Optional[int]:
        """
        Map an immutable source tick coordinate to current output playback ticks.
        Returns None if source_ticks is currently cut.
        """
        accumulated_output = 0
        for seg in self.timeline.segments:
            if seg.source_start_ticks <= source_ticks < seg.source_end_ticks:
                offset_source = source_ticks - seg.source_start_ticks
                offset_output = int(round(offset_source / seg.speed_ratio))
                return accumulated_output + offset_output
            accumulated_output += seg.duration_output_ticks
        return None

    def project_output_to_source(self, output_ticks: int) -> Optional[int]:
        """
        Map a current output playback tick coordinate to immutable source ticks.
        """
        if output_ticks < 0:
            return None
        accumulated = 0
        for seg in self.timeline.segments:
            seg_out_dur = seg.duration_output_ticks
            if accumulated <= output_ticks < accumulated + seg_out_dur:
                offset_out = output_ticks - accumulated
                offset_source = int(round(offset_out * seg.speed_ratio))
                return seg.source_start_ticks + offset_source
            accumulated += seg_out_dur
        if self.timeline.segments and output_ticks == accumulated:
            # End boundary
            return self.timeline.segments[-1].source_end_ticks
        return None

    def map_output_range_to_source(
        self, out_start: int, out_end: int
    ) -> List[Tuple[int, int, float, int]]:
        """
        Map an output interval [out_start, out_end) to a list of:
        (source_start, source_end, speed_ratio, segment_index)
        """
        results: List[Tuple[int, int, float, int]] = []
        accumulated = 0

        for idx, seg in enumerate(self.timeline.segments):
            seg_out_start = accumulated
            seg_out_end = accumulated + seg.duration_output_ticks
            accumulated = seg_out_end

            # Check overlap
            overlap_out_start = max(out_start, seg_out_start)
            overlap_out_end = min(out_end, seg_out_end)

            if overlap_out_start < overlap_out_end:
                # Convert overlap to source coordinates
                delta_start = overlap_out_start - seg_out_start
                delta_end = overlap_out_end - seg_out_start

                src_start = seg.source_start_ticks + int(round(delta_start * seg.speed_ratio))
                src_end = seg.source_start_ticks + int(round(delta_end * seg.speed_ratio))
                results.append((src_start, src_end, seg.speed_ratio, idx))

        return results

    def _sync_effects_anchoring(self) -> List[str]:
        """
        Check all anchored effects against active segments.
        If content was cut: suppress with warning or shorten anchor for partial cut.
        If restored: reactivate.
        """
        warnings: List[str] = []

        for cap in self.timeline.effects.captions:
            # Find active words
            active_words = []
            if cap.anchor_word_ids:
                for wid in cap.anchor_word_ids:
                    word_obj = next((w for w in self.timeline.transcript.words if w.id == wid), None)
                    if word_obj and self.project_source_to_output(word_obj.start_ticks) is not None:
                        active_words.append(word_obj)

                if len(active_words) == len(cap.anchor_word_ids):
                    # Fully active
                    if cap.is_suppressed:
                        cap.is_suppressed = False
                        cap.suppression_reason = None
                        warnings.append(f"Caption '{cap.text}' reactivated after content restore.")
                elif len(active_words) > 0:
                    # Partially active: shrink anchor
                    cap.anchor_word_ids = [w.id for w in active_words]
                    cap.source_start_ticks = min(w.start_ticks for w in active_words)
                    cap.source_end_ticks = max(w.end_ticks for w in active_words)
                    cap.is_suppressed = False
                    warnings.append(f"Caption '{cap.text}' anchor shortened to {len(active_words)} surviving words.")
                else:
                    # Zero surviving words: suppress
                    if not cap.is_suppressed:
                        cap.is_suppressed = True
                        cap.suppression_reason = "Anchored words cut from timeline"
                        warnings.append(f"Caption '{cap.text}' suppressed because anchored words were cut.")
            else:
                # Fallback to source range check
                has_active = any(
                    not (seg.source_end_ticks <= cap.source_start_ticks or seg.source_start_ticks >= cap.source_end_ticks)
                    for seg in self.timeline.segments
                )
                if not has_active:
                    cap.is_suppressed = True
                    cap.suppression_reason = "Anchored range cut from timeline"
                elif cap.is_suppressed:
                    cap.is_suppressed = False
                    cap.suppression_reason = None

        return warnings

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    def apply_cut(
        self, start_ticks: int, end_ticks: int, time_domain: str = "source_time", instruction: str = ""
    ) -> EngineResponse:
        total_dur = self.timeline.total_duration_ticks
        if total_dur == 0:
            return EngineResponse(
                status="rejected",
                summary="Cannot cut: timeline is empty.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=0.0,
                time_policy=time_domain,
            )

        if start_ticks >= end_ticks:
            return EngineResponse(
                status="rejected",
                summary=f"Invalid cut range: start ({start_ticks}ms) >= end ({end_ticks}ms).",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        # Whole video cut rejection
        if (time_domain == "current_edited_time" and start_ticks == 0 and end_ticks >= total_dur) or (
            time_domain == "source_time" and start_ticks <= 0 and end_ticks >= self.timeline.source_media.duration_ticks
        ):
            return EngineResponse(
                status="rejected",
                summary="Cannot cut entire video: at least one segment must remain in the timeline.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        # Check out of range
        if time_domain == "current_edited_time" and start_ticks >= total_dur:
            return EngineResponse(
                status="rejected",
                summary=f"Cut start {ticks_to_seconds(start_ticks)}s is beyond current video duration {self.timeline.total_duration_seconds}s.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        before_segments = copy.deepcopy(self.timeline.segments)
        before_dur = self.timeline.total_duration_seconds

        # Map cut range to source cuts
        cut_source_ranges: List[Tuple[int, int, float]] = []

        if time_domain == "current_edited_time":
            mapped = self.map_output_range_to_source(start_ticks, end_ticks)
            if not mapped:
                return EngineResponse(
                    status="rejected",
                    summary="Specified cut range does not overlap any active content.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration_seconds,
                    time_policy=time_domain,
                )
            for s_start, s_end, speed, _ in mapped:
                cut_source_ranges.append((s_start, s_end, speed))
        else:
            cut_source_ranges.append((start_ticks, end_ticks, 1.0))

        # Perform slicing on segments
        new_segments: List[ClipSegment] = []
        seg_counter = 1

        for seg in self.timeline.segments:
            # Check overlap against each cut source range
            current_pieces = [seg]
            for c_start, c_end, _ in cut_source_ranges:
                next_pieces = []
                for p in current_pieces:
                    # Case 1: No overlap
                    if c_end <= p.source_start_ticks or c_start >= p.source_end_ticks:
                        next_pieces.append(p)
                    else:
                        # Overlap: Keep left portion if any
                        if p.source_start_ticks < c_start:
                            next_pieces.append(
                                ClipSegment(
                                    segment_id=f"seg_{seg_counter}",
                                    source_start_ticks=p.source_start_ticks,
                                    source_end_ticks=c_start,
                                    speed_ratio=p.speed_ratio,
                                )
                            )
                            seg_counter += 1
                        # Keep right portion if any
                        if c_end < p.source_end_ticks:
                            next_pieces.append(
                                ClipSegment(
                                    segment_id=f"seg_{seg_counter}",
                                    source_start_ticks=c_end,
                                    source_end_ticks=p.source_end_ticks,
                                    speed_ratio=p.speed_ratio,
                                )
                            )
                            seg_counter += 1
                current_pieces = next_pieces
            new_segments.extend(current_pieces)

        if not new_segments:
            return EngineResponse(
                status="rejected",
                summary="Cannot cut entire video: at least one segment must remain.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        self.timeline.segments = new_segments
        warnings = self._sync_effects_anchoring()

        # Record transaction
        self.history.record_transaction(
            instruction=instruction or f"Cut {ticks_to_seconds(start_ticks)}s - {ticks_to_seconds(end_ticks)}s",
            operation_type="cut_range",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={
                "start_ticks": start_ticks,
                "end_ticks": end_ticks,
                "time_domain": time_domain,
                "cut_source_ranges": cut_source_ranges,
            },
        )

        new_dur = self.timeline.total_duration_seconds
        diff = round(before_dur - new_dur, 3)
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["cut_range"],
            summary=f"Video is {diff}s shorter (new length: {new_dur}s).",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=new_dur,
            time_policy=time_domain,
            warnings=warnings,
        )

    def apply_speed(
        self, start_ticks: int, end_ticks: int, speed_ratio: float, time_domain: str, instruction: str = ""
    ) -> EngineResponse:
        total_dur = self.timeline.total_duration_ticks

        # Honest supported speed limits check (0.25x to 8.0x)
        if speed_ratio > 8.0:
            return EngineResponse(
                status="rejected",
                summary=f"Speed {speed_ratio}x exceeds maximum supported limit of 8x.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )
        if speed_ratio < 0.25:
            return EngineResponse(
                status="rejected",
                summary=f"Speed {speed_ratio}x is below minimum supported limit of 0.25x.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        if start_ticks >= end_ticks or start_ticks >= total_dur:
            return EngineResponse(
                status="rejected",
                summary=f"Invalid speed range: {ticks_to_seconds(start_ticks)}s to {ticks_to_seconds(end_ticks)}s.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        before_segments = copy.deepcopy(self.timeline.segments)
        before_dur = self.timeline.total_duration_seconds

        # Map output range to source intervals
        mapped = self.map_output_range_to_source(start_ticks, end_ticks)
        if not mapped:
            return EngineResponse(
                status="rejected",
                summary="Speed range does not overlap any active content.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
                time_policy=time_domain,
            )

        new_segments: List[ClipSegment] = []
        seg_counter = 1

        for seg in self.timeline.segments:
            # Slices that intersect this segment
            seg_slices = [m for m in mapped if seg.source_start_ticks <= m[0] < seg.source_end_ticks or seg.source_start_ticks < m[1] <= seg.source_end_ticks]
            if not seg_slices:
                new_segments.append(seg)
                continue

            current_src = seg.source_start_ticks
            for s_start, s_end, _, _ in seg_slices:
                if current_src < s_start:
                    new_segments.append(
                        ClipSegment(
                            segment_id=f"seg_{seg_counter}",
                            source_start_ticks=current_src,
                            source_end_ticks=s_start,
                            speed_ratio=seg.speed_ratio,
                        )
                    )
                    seg_counter += 1
                # The sped-up subsegment (Last-applied segment split rule)
                new_segments.append(
                    ClipSegment(
                        segment_id=f"seg_{seg_counter}",
                        source_start_ticks=s_start,
                        source_end_ticks=s_end,
                        speed_ratio=speed_ratio,
                    )
                )
                seg_counter += 1
                current_src = s_end

            if current_src < seg.source_end_ticks:
                new_segments.append(
                    ClipSegment(
                        segment_id=f"seg_{seg_counter}",
                        source_start_ticks=current_src,
                        source_end_ticks=seg.source_end_ticks,
                        speed_ratio=seg.speed_ratio,
                    )
                )
                seg_counter += 1

        self.timeline.segments = new_segments
        warnings = self._sync_effects_anchoring()

        # Enforce readable caption minimum duration (~0.7s)
        for cap in self.timeline.effects.captions:
            if not cap.is_suppressed:
                out_start = self.project_source_to_output(cap.source_start_ticks)
                out_end = self.project_source_to_output(cap.source_end_ticks)
                if out_start is not None and out_end is not None:
                    eff_dur = (out_end - out_start) / 1000.0
                    if eff_dur < cap.min_duration_s:
                        warnings.append(
                            f"Caption '{cap.text}' duration ({round(eff_dur, 2)}s) clamped to {cap.min_duration_s}s minimum for readability."
                        )

        self.history.record_transaction(
            instruction=instruction or f"Speed up {ticks_to_seconds(start_ticks)}s - {ticks_to_seconds(end_ticks)}s by {speed_ratio}x",
            operation_type="speed_range",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={
                "start_ticks": start_ticks,
                "end_ticks": end_ticks,
                "speed_ratio": speed_ratio,
                "time_domain": time_domain,
            },
        )

        new_dur = self.timeline.total_duration_seconds
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["speed_range"],
            summary=f"Sped up range by {speed_ratio}x. Duration adjusted from {before_dur}s to {new_dur}s.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=new_dur,
            time_policy=time_domain,
            warnings=warnings,
        )

    def apply_caption(
        self,
        text: str,
        anchor_word_ids: List[str],
        source_range: Optional[Tuple[int, int]] = None,
        color: str = "white",
        font_size: int = 36,
        position: Literal["bottom", "top", "center"] = "bottom",
        min_duration_s: float = 0.7,
        instruction: str = "",
    ) -> EngineResponse:
        before_segments = copy.deepcopy(self.timeline.segments)

        # Resolve bounds
        if anchor_word_ids:
            words = [w for w in self.timeline.transcript.words if w.id in anchor_word_ids]
            if not words:
                return EngineResponse(
                    status="rejected",
                    summary="Could not find specified anchor words in transcript.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration_seconds,
                )
            src_start = min(w.start_ticks for w in words)
            src_end = max(w.end_ticks for w in words)
        elif source_range:
            src_start, src_end = source_range
        else:
            return EngineResponse(
                status="rejected",
                summary="Caption must provide either anchor words or a source time range.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        cap_id = f"cap_{len(self.timeline.effects.captions) + 1}"
        caption = CaptionEffect(
            id=cap_id,
            text=text,
            anchor_word_ids=anchor_word_ids,
            source_start_ticks=src_start,
            source_end_ticks=src_end,
            color=color,
            font_size=font_size,
            position=position,
            min_duration_s=min_duration_s,
        )
        self.timeline.effects.captions.append(caption)

        self.history.record_transaction(
            instruction=instruction or f"Add caption '{text}'",
            operation_type="add_caption",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"caption_id": cap_id, "text": text, "source_start": src_start, "source_end": src_end},
            affected_effect_ids=[cap_id],
        )

        self.recompute_hash()
        start_sec = ticks_to_seconds(src_start)
        end_sec = ticks_to_seconds(src_end)

        return EngineResponse(
            status="applied",
            operations=["add_caption"],
            summary=f"Caption '{text}' attached to {len(anchor_word_ids)} words (original time {start_sec}-{end_sec}s).",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
        )

    def apply_auto_caption(
        self,
        max_words_per_caption: int = 6,
        color: str = "white",
        font_size: int = 36,
        position: str = "bottom",
        group_id: str = "captions_main",
        instruction: str = "Add captions to the video",
    ) -> EngineResponse:
        """
        Generate automatic captions from active transcript words.
        Groups words into readable chunks (4-6 words) anchored to source coordinates.
        All generated captions share an identifiable group_id.
        """
        if not self.timeline.transcript.words:
            return EngineResponse(
                status="rejected",
                summary="No transcript available to generate captions. Please upload or transcribe media first.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        # Remove previous auto-captions from the same group if re-generating
        before_segments = copy.deepcopy(self.timeline.segments)
        existing_in_group = [c for c in self.timeline.effects.captions if c.group_id == group_id]
        if existing_in_group:
            self.timeline.effects.captions = [c for c in self.timeline.effects.captions if c.group_id != group_id]

        words = self.timeline.transcript.words
        new_captions: List[CaptionEffect] = []
        chunk_words: List[TranscriptWord] = []

        cap_counter = len(self.timeline.effects.captions) + 1
        for idx, w in enumerate(words):
            chunk_words.append(w)
            is_sentence_end = w.word.rstrip().endswith((".", "!", "?"))
            is_pause_after = (idx + 1 < len(words) and (words[idx + 1].start_ticks - w.end_ticks) > 800)
            if len(chunk_words) >= max_words_per_caption or is_sentence_end or is_pause_after:
                cap_text = " ".join(cw.word for cw in chunk_words).strip()
                c_id = f"cap_auto_{cap_counter}"
                cap_counter += 1
                c_effect = CaptionEffect(
                    id=c_id,
                    text=cap_text,
                    anchor_word_ids=[cw.id for cw in chunk_words],
                    source_start_ticks=chunk_words[0].start_ticks,
                    source_end_ticks=chunk_words[-1].end_ticks,
                    group_id=group_id,
                    color=color,
                    font_size=font_size,
                    position=position,
                    min_duration_s=0.7,
                )
                new_captions.append(c_effect)
                chunk_words = []

        if chunk_words:
            cap_text = " ".join(cw.word for cw in chunk_words).strip()
            c_id = f"cap_auto_{cap_counter}"
            c_effect = CaptionEffect(
                id=c_id,
                text=cap_text,
                anchor_word_ids=[cw.id for cw in chunk_words],
                source_start_ticks=chunk_words[0].start_ticks,
                source_end_ticks=chunk_words[-1].end_ticks,
                group_id=group_id,
                color=color,
                font_size=font_size,
                position=position,
                min_duration_s=0.7,
            )
            new_captions.append(c_effect)

        self.timeline.effects.captions.extend(new_captions)

        self.history.record_transaction(
            instruction=instruction,
            operation_type="auto_caption",
            before_segments=before_segments,
            after_segments=copy.deepcopy(self.timeline.segments),
            details={
                "group_id": group_id,
                "caption_ids": [c.id for c in new_captions],
                "count": len(new_captions),
            },
            affected_effect_ids=[c.id for c in new_captions],
        )

        self.recompute_hash()
        return EngineResponse(
            status="applied",
            operations=["auto_caption"],
            summary=f"Added {len(new_captions)} automatic captions across the video (group: {group_id}).",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
        )

    def apply_edit_caption(
        self,
        caption_id: Optional[str] = None,
        group_id: Optional[str] = None,
        target: Optional[str] = None,
        color: Optional[str] = None,
        text: Optional[str] = None,
        font_size: Optional[int] = None,
        font_size_delta: Optional[int] = None,
        position: Optional[str] = None,
        instruction: str = "",
    ) -> EngineResponse:
        active_captions = [c for c in self.timeline.effects.captions if not c.is_suppressed]
        if not active_captions:
            return EngineResponse(
                status="rejected",
                summary="No active caption exists to edit. Would you like to add automatic captions or a custom title first?",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        # Check if targeting a group or all captions ("them", "all", or explicit group)
        is_group_edit = False
        target_group: List[CaptionEffect] = []

        if group_id:
            target_group = [c for c in active_captions if c.group_id == group_id]
            is_group_edit = len(target_group) > 0
        elif target in ("them", "all", "group", "captions") or (not caption_id and len(active_captions) > 1 and all(c.group_id for c in active_captions)):
            target_group = active_captions
            is_group_edit = True

        if is_group_edit and target_group:
            prev_colors = {c.id: c.color for c in target_group}
            prev_font_sizes = {c.id: c.font_size for c in target_group}

            for c in target_group:
                if color:
                    c.color = color
                if font_size is not None:
                    c.font_size = font_size
                elif font_size_delta is not None:
                    c.font_size = max(16, min(120, c.font_size + font_size_delta))
                if position in ("bottom", "top", "center"):
                    c.position = position

            new_size = target_group[0].font_size
            new_color = target_group[0].color

            self.history.record_transaction(
                instruction=instruction or "Edit captions",
                operation_type="edit_caption",
                before_segments=copy.deepcopy(self.timeline.segments),
                after_segments=copy.deepcopy(self.timeline.segments),
                details={
                    "is_group": True,
                    "group_id": target_group[0].group_id,
                    "caption_ids": [c.id for c in target_group],
                    "previous_colors": prev_colors,
                    "previous_font_sizes": prev_font_sizes,
                    "new_color": color,
                    "new_font_size": new_size,
                },
                affected_effect_ids=[c.id for c in target_group],
            )

            self.recompute_hash()
            desc_parts = []
            if color:
                desc_parts.append(f"color: {new_color}")
            if font_size is not None or font_size_delta is not None:
                desc_parts.append(f"font size: {new_size}pt")
            summary_desc = ", ".join(desc_parts) or "updated"
            return EngineResponse(
                status="applied",
                operations=["edit_caption"],
                summary=f"Updated {len(target_group)} captions in group ({summary_desc}).",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        # Single caption edit
        target_cap: Optional[CaptionEffect] = None
        if caption_id:
            target_cap = next((c for c in active_captions if c.id == caption_id), None)
        elif len(active_captions) == 1:
            target_cap = active_captions[0]
        else:
            options = [f"'{c.text}' at {ticks_to_seconds(c.source_start_ticks)}s" for c in active_captions]
            return EngineResponse(
                status="needs_clarification",
                summary="Multiple captions exist.",
                question="Multiple captions exist. Which one would you like to edit? Or would you like to edit them all?",
                options=options,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        if not target_cap:
            return EngineResponse(
                status="rejected",
                summary=f"Caption '{caption_id}' not found.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        prev_color = target_cap.color
        prev_font_size = target_cap.font_size
        if color:
            target_cap.color = color
        if text:
            target_cap.text = text
        if font_size is not None:
            target_cap.font_size = font_size
        elif font_size_delta is not None:
            target_cap.font_size = max(16, min(120, target_cap.font_size + font_size_delta))
        if position in ("bottom", "top", "center"):
            target_cap.position = position

        self.history.record_transaction(
            instruction=instruction or f"Edit caption '{target_cap.text}'",
            operation_type="edit_caption",
            before_segments=copy.deepcopy(self.timeline.segments),
            after_segments=copy.deepcopy(self.timeline.segments),
            details={
                "caption_id": target_cap.id,
                "previous_color": prev_color,
                "previous_font_size": prev_font_size,
                "new_color": color,
                "new_font_size": target_cap.font_size,
            },
            affected_effect_ids=[target_cap.id],
        )

        self.recompute_hash()
        return EngineResponse(
            status="applied",
            operations=["edit_caption"],
            summary=f"Updated caption '{target_cap.text}' (color: {target_cap.color}, font size: {target_cap.font_size}pt).",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
        )

    def apply_mute_or_bleep(
        self,
        word_ids: List[str],
        is_bleep: bool = False,
        frequency_hz: int = 1000,
        instruction: str = "",
    ) -> EngineResponse:
        words = [w for w in self.timeline.transcript.words if w.id in word_ids]
        if not words:
            return EngineResponse(
                status="rejected",
                summary="No matching words found to mute/bleep.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        src_start = min(w.start_ticks for w in words)
        src_end = max(w.end_ticks for w in words)
        eff_id = f"{'bleep' if is_bleep else 'mute'}_{uuid.uuid4().hex[:6]}"

        if is_bleep:
            bleep = BleepEffect(
                id=eff_id,
                anchor_word_ids=word_ids,
                source_start_ticks=src_start,
                source_end_ticks=src_end,
                frequency_hz=frequency_hz,
            )
            self.timeline.effects.bleeps.append(bleep)
        else:
            mute = MuteEffect(
                id=eff_id,
                anchor_word_ids=word_ids,
                source_start_ticks=src_start,
                source_end_ticks=src_end,
            )
            self.timeline.effects.mutes.append(mute)

        self.history.record_transaction(
            instruction=instruction or f"{'Bleep' if is_bleep else 'Mute'} words",
            operation_type="bleep_words" if is_bleep else "mute_words",
            before_segments=copy.deepcopy(self.timeline.segments),
            after_segments=copy.deepcopy(self.timeline.segments),
            details={"effect_id": eff_id, "word_ids": word_ids},
            affected_effect_ids=[eff_id],
        )

        self.recompute_hash()
        action_name = "bleeped" if is_bleep else "muted"
        return EngineResponse(
            status="applied",
            operations=["bleep_words" if is_bleep else "mute_words"],
            summary=f"Successfully {action_name} {len(words)} word(s) from {ticks_to_seconds(src_start)}s to {ticks_to_seconds(src_end)}s.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
        )

    def apply_remove_fillers(
        self, target_fillers: List[str] = ["um", "uh", "like"], instruction: str = ""
    ) -> EngineResponse:
        matching_words = [
            w for w in self.timeline.transcript.words
            if w.word.strip().lower() in [f.lower() for f in target_fillers] and w.is_filler
        ]
        if not matching_words:
            return EngineResponse(
                status="applied",
                operations=["remove_filler_words"],
                summary="No filler words found to remove.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        before_dur = self.timeline.total_duration_seconds
        before_segments = copy.deepcopy(self.timeline.segments)

        # Cut each word's source span
        cut_ranges = [(w.start_ticks, w.end_ticks) for w in matching_words]
        new_segments: List[ClipSegment] = []
        seg_counter = 1

        for seg in self.timeline.segments:
            current_pieces = [seg]
            for c_start, c_end in cut_ranges:
                next_pieces = []
                for p in current_pieces:
                    if c_end <= p.source_start_ticks or c_start >= p.source_end_ticks:
                        next_pieces.append(p)
                    else:
                        if p.source_start_ticks < c_start:
                            next_pieces.append(
                                ClipSegment(
                                    segment_id=f"seg_{seg_counter}",
                                    source_start_ticks=p.source_start_ticks,
                                    source_end_ticks=c_start,
                                    speed_ratio=p.speed_ratio,
                                )
                            )
                            seg_counter += 1
                        if c_end < p.source_end_ticks:
                            next_pieces.append(
                                ClipSegment(
                                    segment_id=f"seg_{seg_counter}",
                                    source_start_ticks=c_end,
                                    source_end_ticks=p.source_end_ticks,
                                    speed_ratio=p.speed_ratio,
                                )
                            )
                            seg_counter += 1
                current_pieces = next_pieces
            new_segments.extend(current_pieces)

        self.timeline.segments = new_segments
        warnings = self._sync_effects_anchoring()

        self.history.record_transaction(
            instruction=instruction or "Remove filler words",
            operation_type="remove_filler_words",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"filler_words_cut_count": len(matching_words)},
        )

        new_dur = self.timeline.total_duration_seconds
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["remove_filler_words"],
            summary=f"Removed {len(matching_words)} filler word(s). Length reduced from {before_dur}s to {new_dur}s.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=new_dur,
            warnings=warnings,
        )

    def apply_remove_silence(
        self,
        min_duration_ticks: int = 1500,
        respect_protected_pauses: bool = True,
        protected_ranges: Optional[List[Tuple[int, int]]] = None,
        instruction: str = "",
    ) -> EngineResponse:
        # Identify silences from transcript words gaps
        sorted_words = sorted(self.timeline.transcript.words, key=lambda w: w.start_ticks)
        silence_spans: List[Tuple[int, int]] = []
        protected = protected_ranges or []

        # Leading silence
        if sorted_words and sorted_words[0].start_ticks >= min_duration_ticks:
            silence_spans.append((0, sorted_words[0].start_ticks))

        # Inter-word silences
        for i in range(len(sorted_words) - 1):
            gap_start = sorted_words[i].end_ticks
            gap_end = sorted_words[i + 1].start_ticks
            if gap_end - gap_start >= min_duration_ticks:
                # Check if protected
                is_prot = respect_protected_pauses and any(
                    not (p_end <= gap_start or p_start >= gap_end) for p_start, p_end in protected
                )
                if not is_prot:
                    silence_spans.append((gap_start, gap_end))

        if not silence_spans:
            return EngineResponse(
                status="applied",
                operations=["remove_silence"],
                summary=f"No silences longer than {ticks_to_seconds(min_duration_ticks)}s found.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        before_dur = self.timeline.total_duration_seconds
        before_segments = copy.deepcopy(self.timeline.segments)

        new_segments: List[ClipSegment] = []
        seg_counter = 1

        for seg in self.timeline.segments:
            current_pieces = [seg]
            for s_start, s_end in silence_spans:
                next_pieces = []
                for p in current_pieces:
                    if s_end <= p.source_start_ticks or s_start >= p.source_end_ticks:
                        next_pieces.append(p)
                    else:
                        if p.source_start_ticks < s_start:
                            next_pieces.append(
                                ClipSegment(
                                    segment_id=f"seg_{seg_counter}",
                                    source_start_ticks=p.source_start_ticks,
                                    source_end_ticks=s_start,
                                    speed_ratio=p.speed_ratio,
                                )
                            )
                            seg_counter += 1
                        if s_end < p.source_end_ticks:
                            next_pieces.append(
                                ClipSegment(
                                    segment_id=f"seg_{seg_counter}",
                                    source_start_ticks=s_end,
                                    source_end_ticks=p.source_end_ticks,
                                    speed_ratio=p.speed_ratio,
                                )
                            )
                            seg_counter += 1
                current_pieces = next_pieces
            new_segments.extend(current_pieces)

        self.timeline.segments = new_segments
        warnings = self._sync_effects_anchoring()

        self.history.record_transaction(
            instruction=instruction or f"Remove silences > {ticks_to_seconds(min_duration_ticks)}s",
            operation_type="remove_silence",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"silences_removed": len(silence_spans)},
        )

        new_dur = self.timeline.total_duration_seconds
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["remove_silence"],
            summary=f"Removed {len(silence_spans)} silence(s). Length reduced from {before_dur}s to {new_dur}s.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=new_dur,
            warnings=warnings,
        )

    def apply_add_music(
        self, asset_url: str, volume: float = 0.3, instruction: str = ""
    ) -> EngineResponse:
        mus_id = f"music_{len(self.timeline.effects.music) + 1}"
        music = MusicEffect(
            id=mus_id,
            asset_url=asset_url,
            source_start_ticks=0,
            source_end_ticks=self.timeline.source_media.duration_ticks,
            volume=volume,
        )
        self.timeline.effects.music.append(music)

        self.history.record_transaction(
            instruction=instruction or "Add background music",
            operation_type="add_music",
            before_segments=copy.deepcopy(self.timeline.segments),
            after_segments=copy.deepcopy(self.timeline.segments),
            details={"music_id": mus_id, "asset_url": asset_url},
            affected_effect_ids=[mus_id],
        )

        self.recompute_hash()
        return EngineResponse(
            status="applied",
            operations=["add_music"],
            summary="Added background music track with automatic speech ducking.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
        )

    def apply_undo(self) -> EngineResponse:
        success, msg, undone_tx = self.history.undo()
        if not success:
            return EngineResponse(
                status="rejected",
                summary=msg,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        warnings = self._sync_effects_anchoring()
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["undo"],
            summary=f"Reversed step: {undone_tx.instruction if undone_tx else 'previous edit'}.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def apply_redo(self) -> EngineResponse:
        success, msg, redone_tx = self.history.redo()
        if not success:
            return EngineResponse(
                status="rejected",
                summary=msg,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        warnings = self._sync_effects_anchoring()
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["redo"],
            summary=f"Re-applied step: {redone_tx.instruction if redone_tx else 'undone edit'}.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def apply_restore_transaction(self, query: str) -> EngineResponse:
        success, msg, tx = self.history.selective_restore(query)
        if not success:
            return EngineResponse(
                status="rejected",
                summary=msg,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        warnings = self._sync_effects_anchoring()
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["restore_transaction"],
            summary=msg,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def selective_restore(self, query: str) -> EngineResponse:
        return self.apply_restore_transaction(query)

    def apply_reorder_segments(
        self, new_order_segment_ids: List[str], instruction: str = ""
    ) -> EngineResponse:
        current_ids = [s.segment_id for s in self.timeline.segments]
        if sorted(current_ids) != sorted(new_order_segment_ids):
            return EngineResponse(
                status="rejected",
                summary="Invalid reorder: provided segment IDs do not match active segments.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        before_segments = copy.deepcopy(self.timeline.segments)
        id_to_seg = {s.segment_id: s for s in self.timeline.segments}
        self.timeline.segments = [id_to_seg[sid] for sid in new_order_segment_ids]
        warnings = self._sync_effects_anchoring()

        self.history.record_transaction(
            instruction=instruction or "Reorder segments",
            operation_type="reorder_segments",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"new_order": new_order_segment_ids},
        )
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["reorder_segments"],
            summary=f"Reordered {len(new_order_segment_ids)} segments successfully.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def apply_split_segment(
        self, split_ticks: int, time_domain: str = "current_edited_time", instruction: str = ""
    ) -> EngineResponse:
        total_dur = self.timeline.total_duration_ticks
        if split_ticks <= 0 or split_ticks >= total_dur:
            return EngineResponse(
                status="rejected",
                summary=f"Split timestamp {ticks_to_seconds(split_ticks)}s must be strictly within current video duration (0s - {self.timeline.total_duration_seconds}s).",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        before_segments = copy.deepcopy(self.timeline.segments)
        new_segments: List[ClipSegment] = []
        split_done = False
        current_out = 0

        for seg in self.timeline.segments:
            seg_out_dur = seg.duration_output_ticks
            seg_out_end = current_out + seg_out_dur

            if not split_done and current_out < split_ticks < seg_out_end:
                # Split inside this segment
                offset_out = split_ticks - current_out
                offset_src = int(round(offset_out * seg.speed_ratio))
                src_split = seg.source_start_ticks + offset_src

                seg_a = ClipSegment(
                    segment_id=f"{seg.segment_id}_a",
                    source_start_ticks=seg.source_start_ticks,
                    source_end_ticks=src_split,
                    speed_ratio=seg.speed_ratio,
                )
                seg_b = ClipSegment(
                    segment_id=f"{seg.segment_id}_b",
                    source_start_ticks=src_split,
                    source_end_ticks=seg.source_end_ticks,
                    speed_ratio=seg.speed_ratio,
                )
                new_segments.extend([seg_a, seg_b])
                split_done = True
            else:
                new_segments.append(seg)
            current_out = seg_out_end

        if not split_done:
            return EngineResponse(
                status="rejected",
                summary=f"Split point {ticks_to_seconds(split_ticks)}s falls exactly on an existing cut boundary.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        self.timeline.segments = new_segments
        warnings = self._sync_effects_anchoring()

        self.history.record_transaction(
            instruction=instruction or f"Split clip at {ticks_to_seconds(split_ticks)}s",
            operation_type="split_segment",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"split_ticks": split_ticks},
        )
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["split_segment"],
            summary=f"Split clip into two segments at {ticks_to_seconds(split_ticks)}s.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def apply_delete_segment(self, segment_id: str, instruction: str = "") -> EngineResponse:
        if len(self.timeline.segments) <= 1:
            return EngineResponse(
                status="rejected",
                summary="Cannot delete segment: at least one segment must remain in the timeline.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        target = next((s for s in self.timeline.segments if s.segment_id == segment_id), None)
        if not target:
            return EngineResponse(
                status="rejected",
                summary=f"Segment '{segment_id}' not found in active timeline.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        before_segments = copy.deepcopy(self.timeline.segments)
        self.timeline.segments = [s for s in self.timeline.segments if s.segment_id != segment_id]
        warnings = self._sync_effects_anchoring()

        self.history.record_transaction(
            instruction=instruction or f"Delete segment '{segment_id}'",
            operation_type="delete_segment",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"deleted_segment_id": segment_id},
        )
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=["delete_segment"],
            summary=f"Deleted clip segment '{segment_id}'.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def apply_multipart_operations(
        self, operations: List[BaseOperation], instruction: str = ""
    ) -> EngineResponse:
        """
        Execute multiple operations atomically with an all-or-nothing policy.
        If ANY part fails validation or is rejected, NO state is changed and the
        rejection specifies exactly which part failed.
        """
        if not operations:
            return EngineResponse(
                status="rejected",
                summary="Empty multipart instruction.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        # Create a deep copy sandbox to simulate all operations
        sandbox_timeline = copy.deepcopy(self.timeline)
        sandbox_engine = TimelineEngine(sandbox_timeline)

        part_summaries = []
        for idx, op in enumerate(operations, 1):
            res = sandbox_engine.dispatch_operation(op, instruction=f"{instruction} (part {idx})")
            if res.status != "applied":
                return EngineResponse(
                    status="rejected",
                    summary=f"Multipart instruction failed on part {idx} ({op.operation_type}): {res.summary}. Zero changes applied.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration_seconds,
                    time_policy=res.time_policy,
                )
            part_summaries.append(f"Part {idx}: {res.summary}")

        # All parts succeeded in sandbox: apply atomically to live timeline
        before_segments = copy.deepcopy(self.timeline.segments)
        self.timeline.segments = sandbox_timeline.segments
        self.timeline.effects = sandbox_timeline.effects
        warnings = self._sync_effects_anchoring()

        self.history.record_transaction(
            instruction=instruction or "Multipart operation",
            operation_type="multipart",
            before_segments=before_segments,
            after_segments=self.timeline.segments,
            details={"parts_count": len(operations), "part_summaries": part_summaries},
        )
        self.recompute_hash()

        return EngineResponse(
            status="applied",
            operations=[op.operation_type for op in operations],
            summary="All parts applied successfully: " + "; ".join(part_summaries),
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
            warnings=warnings,
        )

    def dispatch_operation(self, op: BaseOperation, instruction: str = "") -> EngineResponse:
        """
        Dispatch a strongly-typed BaseOperation to the corresponding handler.
        """
        if isinstance(op, CutRangeOperation):
            return self.apply_cut(op.start_ticks, op.end_ticks, op.time_domain, instruction)
        elif isinstance(op, SpeedRangeOperation):
            return self.apply_speed(op.start_ticks, op.end_ticks, op.speed_ratio, op.time_domain, instruction)
        elif isinstance(op, ReorderSegmentsOperation):
            return self.apply_reorder_segments(op.new_order_segment_ids, instruction)
        elif isinstance(op, SplitSegmentOperation):
            return self.apply_split_segment(op.split_ticks, op.time_domain, instruction)
        elif isinstance(op, DeleteSegmentOperation):
            return self.apply_delete_segment(op.segment_id, instruction)
        elif isinstance(op, AddCaptionOperation):
            return self.apply_caption(
                op.text,
                op.anchor_word_ids,
                (op.source_start_ticks, op.source_end_ticks) if op.source_start_ticks is not None else None,
                op.color,
                op.font_size,
                op.position,
                op.min_duration_s,
                instruction,
            )
        elif isinstance(op, AutoCaptionOperation):
            return self.apply_auto_caption(
                max_words_per_caption=op.max_words_per_caption,
                color=op.color,
                font_size=op.font_size,
                position=op.position,
                group_id=op.group_id,
                instruction=instruction,
            )
        elif isinstance(op, EditCaptionOperation):
            return self.apply_edit_caption(
                caption_id=op.caption_id,
                group_id=op.group_id,
                target=op.target,
                color=op.color,
                text=op.text,
                font_size=op.font_size,
                font_size_delta=op.font_size_delta,
                position=op.position,
                instruction=instruction,
            )
        elif isinstance(op, MuteWordsOperation):
            return self.apply_mute_or_bleep(op.word_ids, is_bleep=False, instruction=instruction)
        elif isinstance(op, BleepWordsOperation):
            return self.apply_mute_or_bleep(op.word_ids, is_bleep=True, frequency_hz=op.frequency_hz, instruction=instruction)
        elif isinstance(op, RemoveFillerWordsOperation):
            return self.apply_remove_fillers(op.target_fillers, instruction)
        elif isinstance(op, RemoveSilenceOperation):
            return self.apply_remove_silence(
                op.min_duration_ticks, op.respect_protected_pauses, op.protected_ranges, instruction
            )
        elif isinstance(op, AddMusicOperation):
            return self.apply_add_music(op.asset_url, op.volume, instruction)
        elif isinstance(op, UndoOperation):
            return self.apply_undo()
        elif isinstance(op, RedoOperation):
            return self.apply_redo()
        elif isinstance(op, RestoreTransactionOperation):
            return self.apply_restore_transaction(op.description or "earlier edit")
        else:
            return EngineResponse(
                status="rejected",
                summary=f"Unsupported operation type: {op.operation_type}",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

    # -------------------------------------------------------------------------
    # Auto Edit Planning and Atomic Execution
    # -------------------------------------------------------------------------

    def generate_auto_edit_plan(
        self,
        options: Optional[Dict[str, Any]] = None,
    ) -> AutoEditPlan:
        """
        Analyze the media and transcript to generate a reviewable Auto Edit Plan.
        Does NOT modify the active timeline.
        Clean Up preset checks:
        1. Trimming silences longer than threshold (default 1200ms).
        2. Removing high-confidence filler words ("um", "uh", confident "like").
        3. Adding automatic captions if requested (default True).
        4. Optional ducked background music if requested.
        """
        opts = options or {}
        silence_thresh_ms = opts.get("silence_threshold_ms", 1200)
        remove_fillers = opts.get("remove_fillers", True)
        remove_silences = opts.get("remove_silences", True)
        add_captions = opts.get("add_captions", True)
        add_music = opts.get("add_music", False)
        music_url = opts.get("music_url", "")

        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        items: List[AutoEditItem] = []
        warnings: List[str] = []
        item_counter = 1

        # 1. Silences > threshold
        if remove_silences and len(self.timeline.transcript.words) > 1:
            words = sorted(self.timeline.transcript.words, key=lambda w: w.start_ticks)
            for i in range(len(words) - 1):
                gap = words[i + 1].start_ticks - words[i].end_ticks
                if gap >= silence_thresh_ms:
                    s_start = words[i].end_ticks
                    s_end = words[i + 1].start_ticks
                    out_start = self.project_source_to_output(s_start)
                    out_end = self.project_source_to_output(s_end)
                    if out_start is not None and out_end is not None and out_end > out_start:
                        dur_s = round((s_end - s_start) / 1000.0, 2)
                        items.append(
                            AutoEditItem(
                                item_id=f"item_{item_counter}",
                                category="silence",
                                description=f"Trim silence pause ({dur_s}s) between '{words[i].word}' and '{words[i + 1].word}'",
                                source_start_ticks=s_start,
                                source_end_ticks=s_end,
                                output_start_ticks=out_start,
                                output_end_ticks=out_end,
                                confidence=1.0,
                                is_uncertain=False,
                                excluded=False,
                            )
                        )
                        item_counter += 1

        # 2. Filler words
        if remove_fillers:
            for w in self.timeline.transcript.words:
                clean_w = w.word.lower().strip(",.!? ")
                is_filler = False
                is_uncertain = False

                if clean_w in ("um", "uh"):
                    is_filler = True
                elif clean_w == "like":
                    if w.is_filler or w.confidence < 0.75:
                        is_filler = True
                        is_uncertain = (w.confidence < 0.8)

                if is_filler:
                    out_start = self.project_source_to_output(w.start_ticks)
                    out_end = self.project_source_to_output(w.end_ticks)
                    if out_start is not None and out_end is not None and out_end > out_start:
                        items.append(
                            AutoEditItem(
                                item_id=f"item_{item_counter}",
                                category="filler_word",
                                description=f"Remove filler word '{w.word}' ({round((w.end_ticks - w.start_ticks) / 1000.0, 2)}s)",
                                source_start_ticks=w.start_ticks,
                                source_end_ticks=w.end_ticks,
                                output_start_ticks=out_start,
                                output_end_ticks=out_end,
                                confidence=w.confidence,
                                is_uncertain=is_uncertain,
                                excluded=is_uncertain,
                            )
                        )
                        item_counter += 1
                        if is_uncertain:
                            warnings.append(
                                f"Excluded uncertain filler '{w.word}' at {ticks_to_seconds(w.start_ticks)}s by default for review."
                            )

        # 3. Auto Captions
        if add_captions and self.timeline.transcript.words:
            items.append(
                AutoEditItem(
                    item_id=f"item_{item_counter}",
                    category="auto_caption",
                    description=f"Generate automatic subtitle captions for entire video ({len(self.timeline.transcript.words)} words)",
                    source_start_ticks=0,
                    source_end_ticks=self.timeline.source_media.duration_ticks,
                    output_start_ticks=0,
                    output_end_ticks=self.timeline.total_duration_ticks,
                    confidence=1.0,
                    is_uncertain=False,
                    excluded=False,
                )
            )
            item_counter += 1

        # 4. Background music
        if add_music and music_url:
            items.append(
                AutoEditItem(
                    item_id=f"item_{item_counter}",
                    category="music",
                    description=f"Add ducked background music across video ({music_url})",
                    source_start_ticks=0,
                    source_end_ticks=self.timeline.source_media.duration_ticks,
                    output_start_ticks=0,
                    output_end_ticks=self.timeline.total_duration_ticks,
                    confidence=1.0,
                    is_uncertain=False,
                    excluded=False,
                )
            )
            item_counter += 1

        cut_ticks = 0
        for it in items:
            if not it.excluded and it.category in ("silence", "filler_word"):
                if it.output_start_ticks is not None and it.output_end_ticks is not None:
                    cut_ticks += (it.output_end_ticks - it.output_start_ticks)

        curr_dur = self.timeline.total_duration_seconds
        est_dur = max(0.0, round(curr_dur - (cut_ticks / self.timeline.timebase), 3))

        return AutoEditPlan(
            plan_id=plan_id,
            project_id=self.timeline.project_id,
            base_timeline_hash=self.timeline.timeline_hash,
            created_at=time.time(),
            current_duration_s=curr_dur,
            estimated_duration_s=est_dur,
            items=items,
            warnings=warnings,
        )

    def apply_auto_edit_plan(
        self,
        plan: AutoEditPlan,
        excluded_item_ids: Optional[List[str]] = None,
    ) -> EngineResponse:
        """
        Apply an approved Auto Edit Plan atomically as ONE undoable transaction.
        Preserves manual edits, and validates against base timeline hash.
        """
        # Stale plan validation
        if plan.base_timeline_hash != self.timeline.timeline_hash:
            return EngineResponse(
                status="rejected",
                summary="Stale plan rejected: timeline revision has changed since the plan was generated. Please regenerate plan.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        excluded = set(excluded_item_ids or [])
        active_items = [it for it in plan.items if it.item_id not in excluded and not it.excluded]

        if not active_items:
            return EngineResponse(
                status="rejected",
                summary="No active changes selected in the Auto Edit plan.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration_seconds,
            )

        before_segments = copy.deepcopy(self.timeline.segments)
        added_cap_ids: List[str] = []
        added_music_ids: List[str] = []

        # 1. Cuts: gather all silence & filler source intervals
        cut_source_ranges: List[Tuple[int, int]] = []
        for it in active_items:
            if it.category in ("silence", "filler_word"):
                cut_source_ranges.append((it.source_start_ticks, it.source_end_ticks))

        if cut_source_ranges:
            cut_source_ranges.sort(key=lambda r: r[0])
            merged_cuts: List[Tuple[int, int]] = []
            for r_start, r_end in cut_source_ranges:
                if not merged_cuts:
                    merged_cuts.append((r_start, r_end))
                else:
                    last_s, last_e = merged_cuts[-1]
                    if r_start <= last_e:
                        merged_cuts[-1] = (last_s, max(last_e, r_end))
                    else:
                        merged_cuts.append((r_start, r_end))

            new_segments: List[ClipSegment] = []
            seg_counter = 1
            for seg in self.timeline.segments:
                seg_s = seg.source_start_ticks
                seg_e = seg.source_end_ticks
                curr_start = seg_s

                for c_start, c_end in merged_cuts:
                    if c_end <= curr_start or c_start >= seg_e:
                        continue
                    overlap_cut_s = max(curr_start, c_start)
                    overlap_cut_e = min(seg_e, c_end)
                    if overlap_cut_s > curr_start:
                        new_segments.append(
                            ClipSegment(
                                segment_id=f"seg_ae_{seg_counter}",
                                source_start_ticks=curr_start,
                                source_end_ticks=overlap_cut_s,
                                speed_ratio=seg.speed_ratio,
                            )
                        )
                        seg_counter += 1
                    curr_start = max(curr_start, overlap_cut_e)

                if curr_start < seg_e:
                    new_segments.append(
                        ClipSegment(
                            segment_id=f"seg_ae_{seg_counter}",
                            source_start_ticks=curr_start,
                            source_end_ticks=seg_e,
                            speed_ratio=seg.speed_ratio,
                        )
                    )
                    seg_counter += 1

            self.timeline.segments = new_segments

        # 2. Add captions if requested in plan
        has_caption_item = any(it.category == "auto_caption" for it in active_items)
        if has_caption_item:
            res_cap = self.apply_auto_caption(instruction="Auto-generated captions via Clean Up")
            if self.timeline.transactions and self.timeline.transactions[-1].operation_type == "auto_caption":
                added_cap_ids = self.timeline.transactions[-1].details.get("caption_ids", [])
                self.timeline.transactions.pop()

        # 3. Add music if requested
        music_item = next((it for it in active_items if it.category == "music"), None)
        if music_item:
            res_mus = self.apply_add_music(asset_url="bg_music.mp3", volume=0.25, instruction="Auto background music")
            if self.timeline.transactions and self.timeline.transactions[-1].operation_type == "add_music":
                m_id = self.timeline.transactions[-1].details.get("music_id")
                if m_id:
                    added_music_ids.append(m_id)
                self.timeline.transactions.pop()

        self._sync_effects_anchoring()

        # Record atomic transaction
        tx = self.history.record_transaction(
            instruction=f"Auto Edit Clean Up ({len(active_items)} actions applied)",
            operation_type="auto_edit_cleanup",
            before_segments=before_segments,
            after_segments=copy.deepcopy(self.timeline.segments),
            details={
                "plan_id": plan.plan_id,
                "actions_count": len(active_items),
                "added_caption_ids": added_cap_ids,
                "added_music_ids": added_music_ids,
            },
        )

        self.recompute_hash()
        return EngineResponse(
            status="applied",
            operations=["auto_edit_cleanup"],
            summary=f"Clean Up preset applied: {len(active_items)} changes committed. Duration adjusted to {self.timeline.total_duration_seconds}s.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration_seconds,
        )

