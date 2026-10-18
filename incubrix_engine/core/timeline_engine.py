"""
Deterministic Content-Anchored Timeline Engine.
Handles active segments, word-derived playhead times, history stacks,
selective restoration, and deterministic timeline hashing.
"""

from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Any
import copy
from .models import (
    Timeline,
    Segment,
    Transcript,
    Word,
    Caption,
    CaptionStyle,
    AudioEffect,
    BackgroundMusic,
    Operation,
    StepResponse,
    Clarification
)


class EditRecord:
    def __init__(
        self,
        step_id: int,
        instruction: str,
        operations: List[Operation],
        summary: str,
        timeline_before: Timeline,
        timeline_after: Timeline,
    ):
        self.step_id = step_id
        self.instruction = instruction
        self.operations = operations
        self.summary = summary
        self.timeline_before = timeline_before
        self.timeline_after = timeline_after
        self.is_undone = False


class TimelineEngine:
    """
    Main state machine for non-destructive video editing.
    Maintains untouched source data and applies operations deterministically.
    """

    def __init__(self, transcript: Transcript, source_video_url: str, fps: float = 30.0, width: int = 1920, height: int = 1080):
        self.transcript = transcript
        self.source_video_url = source_video_url
        self.fps = fps
        self.width = width
        self.height = height

        # Base untouched timeline
        initial_segment = Segment(
            id="seg_0",
            source_start=0.0,
            source_end=transcript.duration,
            speed=1.0
        )
        self.timeline = Timeline(
            source_video_url=source_video_url,
            original_duration=transcript.duration,
            fps=fps,
            width=width,
            height=height,
            segments=[initial_segment],
            captions=[],
            audio_effects=[],
            background_music=None
        )

        # History and branch stacks
        self.history: List[EditRecord] = []
        self.redo_stack: List[EditRecord] = []
        self.step_counter = 0

        # Update initial dynamic timings
        self._recompute_timeline_times()

    def get_current_duration(self) -> float:
        return self.timeline.total_duration

    def get_timeline_hash(self) -> str:
        return self.timeline.compute_hash()

    # ---------------------------------------------------------
    # Time Mapping Policy (Must-Have #7 & Advanced)
    # ---------------------------------------------------------
    def source_time_to_timeline_time(self, source_t: float) -> Optional[float]:
        """Maps original video seconds to current edited timeline seconds."""
        accum_timeline = 0.0
        n = len(self.timeline.segments)
        for i, seg in enumerate(self.timeline.segments):
            is_in_seg = (
                seg.source_start <= source_t < seg.source_end
                if i < n - 1
                else seg.source_start <= source_t <= seg.source_end
            )
            if is_in_seg:
                offset = (source_t - seg.source_start) / seg.speed
                return accum_timeline + offset
            accum_timeline += seg.timeline_duration
        return None

    def timeline_time_to_source_time(self, timeline_t: float) -> Optional[float]:
        """Maps current edited timeline seconds back to original video seconds."""
        accum_timeline = 0.0
        for seg in self.timeline.segments:
            seg_dur = seg.timeline_duration
            if accum_timeline <= timeline_t <= accum_timeline + seg_dur + 1e-6:
                offset_in_seg = (timeline_t - accum_timeline) * seg.speed
                return seg.source_start + offset_in_seg
            accum_timeline += seg_dur
        return None

    # ---------------------------------------------------------
    # Dynamic Timing Recomputation (Content-Anchoring)
    # ---------------------------------------------------------
    def _recompute_timeline_times(self) -> None:
        """
        Recomputes start/end times on current timeline for all captions and audio effects.
        Enforces defined rule for partial cuts and readable minimum (0.7s) for sped-up captions.
        """
        for caption in self.timeline.captions:
            w_start = self.transcript.get_word(caption.start_word_id)
            w_end = self.transcript.get_word(caption.end_word_id)

            if not w_start or not w_end:
                caption.is_active = False
                caption.timeline_start = None
                caption.timeline_end = None
                continue

            # Check overlap between [w_start.start, w_end.end] and active segments
            overlap = 0.0
            for seg in self.timeline.segments:
                o_start = max(seg.source_start, w_start.start)
                o_end = min(seg.source_end, w_end.end)
                if o_start < o_end:
                    overlap += (o_end - o_start)

            phrase_dur = max(0.001, w_end.end - w_start.start)
            # Advanced rule: if less than 20% of phrase survives, caption is deactivated
            if overlap < 0.2 * phrase_dur:
                caption.is_active = False
                caption.timeline_start = None
                caption.timeline_end = None
                continue

            t_start = self.source_time_to_timeline_time(w_start.start)
            t_end = self.source_time_to_timeline_time(w_end.end)

            if t_start is None and t_end is None:
                caption.is_active = False
                caption.timeline_start = None
                caption.timeline_end = None
            elif t_start is not None and t_end is not None:
                caption.is_active = True
                caption.timeline_start = round(t_start, 3)
                dur = t_end - t_start
                if dur < 0.7:
                    t_end = min(t_start + 0.7, self.get_current_duration())
                caption.timeline_end = round(t_end, 3)
            elif t_start is not None:
                # Partial cut: end cut off
                caption.is_active = True
                caption.timeline_start = round(t_start, 3)
                caption.timeline_end = round(min(t_start + 0.7, self.get_current_duration()), 3)
            else:
                # Partial cut: start cut off
                caption.is_active = True
                caption.timeline_end = round(t_end, 3)
                caption.timeline_start = round(max(0.0, t_end - 0.7), 3)

        for effect in self.timeline.audio_effects:
            w_start = self.transcript.get_word(effect.start_word_id)
            w_end = self.transcript.get_word(effect.end_word_id)
            if not w_start or not w_end:
                effect.is_active = False
                continue
            t_start = self.source_time_to_timeline_time(w_start.start)
            t_end = self.source_time_to_timeline_time(w_end.end)
            if t_start is None or t_end is None:
                effect.is_active = False
            else:
                effect.is_active = True
                effect.timeline_start = round(t_start, 3)
                effect.timeline_end = round(t_end, 3)

    # ---------------------------------------------------------
    # Core Operations Implementation
    # ---------------------------------------------------------
    def cut_source_range(self, cut_start: float, cut_end: float) -> Tuple[bool, str]:
        """Cuts a source time range [cut_start, cut_end]."""
        if cut_start >= cut_end:
            return False, "cut_start must be strictly less than cut_end"

        # Prevent cutting the entire timeline
        total_active_before = sum(s.source_duration for s in self.timeline.segments)
        new_segments: List[Segment] = []
        seg_idx = 0

        for seg in self.timeline.segments:
            # Case 1: No overlap
            if cut_end <= seg.source_start or cut_start >= seg.source_end:
                new_segments.append(seg)
                continue

            # Case 2: Cut covers entire segment -> skip (cut out)
            if cut_start <= seg.source_start and cut_end >= seg.source_end:
                continue

            # Case 3: Cut trims beginning of segment
            if cut_start <= seg.source_start and cut_end < seg.source_end:
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=cut_end,
                        source_end=seg.source_end,
                        speed=seg.speed
                    )
                )
                seg_idx += 1
                continue

            # Case 4: Cut trims end of segment
            if cut_start > seg.source_start and cut_end >= seg.source_end:
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=seg.source_start,
                        source_end=cut_start,
                        speed=seg.speed
                    )
                )
                seg_idx += 1
                continue

            # Case 5: Cut splits the segment in two
            if cut_start > seg.source_start and cut_end < seg.source_end:
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=seg.source_start,
                        source_end=cut_start,
                        speed=seg.speed
                    )
                )
                seg_idx += 1
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=cut_end,
                        source_end=seg.source_end,
                        speed=seg.speed
                    )
                )
                seg_idx += 1

        if not new_segments:
            return False, "Cannot cut entire video: whole-video cuts are rejected"

        self.timeline.segments = new_segments
        self._recompute_timeline_times()
        return True, f"Cut source range {cut_start:.2f}s - {cut_end:.2f}s"

    def keep_only_source_range(self, keep_start: float, keep_end: float) -> Tuple[bool, str]:
        """Keeps only the specified source range, cutting everything else."""
        if keep_start >= keep_end:
            return False, "keep_start must be less than keep_end"

        new_segments: List[Segment] = []
        seg_idx = 0
        for seg in self.timeline.segments:
            overlap_start = max(seg.source_start, keep_start)
            overlap_end = min(seg.source_end, keep_end)
            if overlap_start < overlap_end:
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=overlap_start,
                        source_end=overlap_end,
                        speed=seg.speed
                    )
                )
                seg_idx += 1

        if not new_segments:
            return False, "Keep range does not overlap with any active video"

        self.timeline.segments = new_segments
        self._recompute_timeline_times()
        return True, f"Kept only source range {keep_start:.2f}s - {keep_end:.2f}s"

    def speed_change_source_range(self, start: float, end: float, speed: float) -> Tuple[bool, str]:
        """
        Changes speed for source range [start, end].
        Follows documented rule: new speed overrides existing range with split segments.
        """
        if speed <= 0.0 or speed > 10.0:
            return False, f"Invalid speed {speed}x: must be between 0.1x and 10.0x"

        new_segments: List[Segment] = []
        seg_idx = 0

        for seg in self.timeline.segments:
            # No overlap
            if end <= seg.source_start or start >= seg.source_end:
                new_segments.append(seg)
                continue

            overlap_start = max(seg.source_start, start)
            overlap_end = min(seg.source_end, end)

            # Left un-sped piece
            if seg.source_start < overlap_start:
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=seg.source_start,
                        source_end=overlap_start,
                        speed=seg.speed
                    )
                )
                seg_idx += 1

            # Sped piece
            new_segments.append(
                Segment(
                    id=f"seg_{seg_idx}",
                    source_start=overlap_start,
                    source_end=overlap_end,
                    speed=speed
                )
            )
            seg_idx += 1

            # Right un-sped piece
            if overlap_end < seg.source_end:
                new_segments.append(
                    Segment(
                        id=f"seg_{seg_idx}",
                        source_start=overlap_end,
                        source_end=seg.source_end,
                        speed=seg.speed
                    )
                )
                seg_idx += 1

        self.timeline.segments = new_segments
        self._recompute_timeline_times()
        return True, f"Changed speed to {speed}x for source range {start:.2f}s - {end:.2f}s"

    def add_caption(self, text: str, start_word_id: int, end_word_id: int, style: Optional[CaptionStyle] = None) -> Tuple[bool, str]:
        """Adds a content-anchored caption attached to word range."""
        if start_word_id > end_word_id or start_word_id < 0 or end_word_id >= len(self.transcript.words):
            return False, f"Invalid word range [{start_word_id}, {end_word_id}]"

        cap_id = f"cap_{len(self.timeline.captions) + 1}"
        cap = Caption(
            id=cap_id,
            text=text,
            start_word_id=start_word_id,
            end_word_id=end_word_id,
            style=style or CaptionStyle()
        )
        self.timeline.captions.append(cap)
        self._recompute_timeline_times()
        return True, f"Added caption '{text}' on words {start_word_id}-{end_word_id}"

    def style_caption(self, caption_id: Optional[str] = None, color: Optional[str] = None, font_size: Optional[int] = None) -> Tuple[bool, str]:
        """Changes style of target caption. Resolves 'that caption' if only one exists."""
        if not self.timeline.captions:
            return False, "No captions exist on the timeline to style"

        target: Optional[Caption] = None
        if caption_id:
            for c in self.timeline.captions:
                if c.id == caption_id:
                    target = c
                    break
        else:
            # If only one caption exists or target refers to latest
            target = self.timeline.captions[-1]

        if not target:
            return False, f"Caption {caption_id} not found"

        if color:
            target.style.color = color
        if font_size:
            target.style.font_size = font_size

        return True, f"Updated style for caption '{target.text}'"

    def add_audio_effect(self, effect_type: Literal["mute", "bleep"], start_word_id: int, end_word_id: int) -> Tuple[bool, str]:
        """Mutes or bleeps a specific word range."""
        eff_id = f"{effect_type}_{len(self.timeline.audio_effects) + 1}"
        eff = AudioEffect(
            id=eff_id,
            effect_type=effect_type,
            start_word_id=start_word_id,
            end_word_id=end_word_id
        )
        self.timeline.audio_effects.append(eff)
        self._recompute_timeline_times()
        return True, f"Added {effect_type} on words {start_word_id}-{end_word_id}"

    def add_background_music(self, url_or_path: str, volume: float = 0.3, ducking: bool = True) -> Tuple[bool, str]:
        self.timeline.background_music = BackgroundMusic(
            id="bg_music_1",
            source_url_or_path=url_or_path,
            volume=volume,
            ducking=ducking,
            duck_volume=0.1
        )
        return True, f"Added background music with auto-ducking (volume: {volume})"

    def remove_fillers(self) -> Tuple[bool, str]:
        """Removes all marked filler words (um, uh, like) by cutting their source ranges."""
        filler_cuts = []
        for w in self.transcript.words:
            if w.is_filler or w.text.lower().strip() in ["um", "uh"]:
                filler_cuts.append((w.start, w.end))

        if not filler_cuts:
            return True, "No filler words found to remove"

        # Apply cuts in reverse time order so earlier timestamps don't shift
        for start, end in sorted(filler_cuts, key=lambda x: x[0], reverse=True):
            self.cut_source_range(start, end)

        return True, f"Removed {len(filler_cuts)} filler words"

    # ---------------------------------------------------------
    # History & Undo / Redo / Selective Restore (Must-Haves #1 & #6)
    # ---------------------------------------------------------
    def apply_step(self, instruction: str, operations: List[Operation], summary: str) -> StepResponse:
        """
        Applies a batch of operations corresponding to one creator instruction.
        Maintains history stack and clears redo stack.
        """
        timeline_before = copy.deepcopy(self.timeline)
        applied_ops = []

        for op in operations:
            success, msg = self._execute_operation(op)
            if not success:
                # Revert to before state if any part of atomic operation fails
                self.timeline = timeline_before
                return StepResponse(
                    status="rejected",
                    summary=f"Operation {op.op} failed: {msg}",
                    rejection_reason=msg,
                    timeline_hash=self.get_timeline_hash(),
                    duration_s=self.get_current_duration()
                )
            applied_ops.append(op)

        self.step_counter += 1
        record = EditRecord(
            step_id=self.step_counter,
            instruction=instruction,
            operations=applied_ops,
            summary=summary,
            timeline_before=timeline_before,
            timeline_after=copy.deepcopy(self.timeline)
        )
        self.history.append(record)
        self.redo_stack.clear()  # A new edit clears redo

        return StepResponse(
            status="applied",
            summary=summary,
            operations=applied_ops,
            timeline_hash=self.get_timeline_hash(),
            duration_s=self.get_current_duration()
        )

    def undo(self) -> StepResponse:
        """Reverses the last applied instruction (Must-Have #6)."""
        active_records = [r for r in self.history if not r.is_undone]
        if not active_records:
            return StepResponse(
                status="rejected",
                summary="Nothing to undo",
                rejection_reason="History stack is empty",
                timeline_hash=self.get_timeline_hash(),
                duration_s=self.get_current_duration()
            )

        last_record = active_records[-1]
        last_record.is_undone = True
        self.redo_stack.append(last_record)

        # Restore previous timeline
        self.timeline = copy.deepcopy(last_record.timeline_before)
        self._recompute_timeline_times()

        return StepResponse(
            status="applied",
            summary=f"Reversed step {last_record.step_id} ('{last_record.instruction}').",
            operations=[Operation(op="undo", params={"step_id": last_record.step_id})],
            timeline_hash=self.get_timeline_hash(),
            duration_s=self.get_current_duration()
        )

    def redo(self) -> StepResponse:
        """Re-applies the most recently undone instruction."""
        if not self.redo_stack:
            return StepResponse(
                status="rejected",
                summary="Nothing to redo",
                rejection_reason="Redo stack is empty",
                timeline_hash=self.get_timeline_hash(),
                duration_s=self.get_current_duration()
            )

        record = self.redo_stack.pop()
        record.is_undone = False
        self.timeline = copy.deepcopy(record.timeline_after)
        self._recompute_timeline_times()

        return StepResponse(
            status="applied",
            summary=f"Redid step {record.step_id} ('{record.instruction}').",
            operations=[Operation(op="redo", params={"step_id": record.step_id})],
            timeline_hash=self.get_timeline_hash(),
            duration_s=self.get_current_duration()
        )

    def restore_specific_edit(self, target_step_id: int) -> StepResponse:
        """
        Selectively restores an earlier edit without undoing intermediate steps.
        Reconstructs the timeline by replaying all valid history steps EXCEPT the restored one.
        """
        target_record = next((r for r in self.history if r.step_id == target_step_id), None)
        if not target_record:
            return StepResponse(
                status="rejected",
                summary=f"Cannot restore step {target_step_id}: not found in history",
                rejection_reason=f"Step ID {target_step_id} does not exist",
                timeline_hash=self.get_timeline_hash(),
                duration_s=self.get_current_duration()
            )

        # Build fresh timeline from scratch and replay all active steps except target_step_id
        fresh_engine = TimelineEngine(
            transcript=self.transcript,
            source_video_url=self.source_video_url,
            fps=self.fps,
            width=self.width,
            height=self.height
        )

        for record in self.history:
            if record.is_undone or record.step_id == target_step_id:
                continue
            for op in record.operations:
                fresh_engine._execute_operation(op)

        # Adopt the recomputed timeline
        timeline_before = copy.deepcopy(self.timeline)
        self.timeline = fresh_engine.timeline
        self._recompute_timeline_times()

        self.step_counter += 1
        summary = f"Restored previous state by reversing step {target_step_id} ('{target_record.instruction}')."
        record = EditRecord(
            step_id=self.step_counter,
            instruction=f"Restore step {target_step_id}",
            operations=[Operation(op="restore_edit", params={"target_step_id": target_step_id})],
            summary=summary,
            timeline_before=timeline_before,
            timeline_after=copy.deepcopy(self.timeline)
        )
        self.history.append(record)
        self.redo_stack.clear()

        return StepResponse(
            status="applied",
            summary=summary,
            operations=[Operation(op="restore_edit", params={"target_step_id": target_step_id})],
            timeline_hash=self.get_timeline_hash(),
            duration_s=self.get_current_duration()
        )

    def _execute_operation(self, op: Operation) -> Tuple[bool, str]:
        params = op.params
        if op.op == "cut_range":
            return self.cut_source_range(params["start"], params["end"])
        elif op.op == "keep_only":
            return self.keep_only_source_range(params["start"], params["end"])
        elif op.op == "speed_change":
            return self.speed_change_source_range(params["start"], params["end"], params["speed"])
        elif op.op == "add_caption":
            style = CaptionStyle(**params["style"]) if "style" in params else None
            return self.add_caption(params["text"], params["start_word_id"], params["end_word_id"], style)
        elif op.op == "style_caption":
            return self.style_caption(params.get("caption_id"), params.get("color"), params.get("font_size"))
        elif op.op == "mute_words":
            return self.add_audio_effect("mute", params["start_word_id"], params["end_word_id"])
        elif op.op == "bleep_words":
            return self.add_audio_effect("bleep", params["start_word_id"], params["end_word_id"])
        elif op.op == "add_bg_music":
            return self.add_background_music(params["url"], params.get("volume", 0.3), params.get("ducking", True))
        elif op.op == "remove_filler":
            return self.remove_fillers()
        elif op.op == "restore_edit":
            return True, "Handled at step level"
        elif op.op in ["undo", "redo"]:
            return True, "Handled at step level"
        return False, f"Unknown operation {op.op}"
