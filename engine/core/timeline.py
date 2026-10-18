"""Timeline implementation adhering strictly to the Golden Timeline Rule.

Key Principles:
1. Source media is untouched and immutable.
2. Edit operations are maintained in an append-only event log.
3. Timeline state can be deterministically replayed from the event log at any time.
4. Word ID anchoring ensures captions, mutes, and bleeps stick to words across
   cuts, speed changes, reorders, and restores.
"""

from __future__ import annotations
import uuid
from typing import List, Dict, Any, Optional, Tuple, Literal
from engine.core.models import (
    Word,
    Transcript,
    SourceMedia,
    TimelineClip,
    AnchoredCaption,
    AnchoredAudioEffect,
    BackgroundMusicTrack,
    EditOperation,
    EditStep,
    CaptionStyle,
    ResolvedCaption,
    ResolvedAudioEffect,
)
from engine.core.hashing import compute_timeline_hash
from engine.core.word_anchor import (
    map_source_time_to_playback,
    map_playback_time_to_source,
    resolve_captions,
    resolve_audio_effects,
)


class Timeline:
    """The central Golden Timeline data structure."""

    def __init__(
        self,
        source: SourceMedia,
        transcript: Transcript,
        time_policy: Literal["current", "original"] = "original"
    ):
        self.source = source
        self.transcript = transcript
        self.time_policy = time_policy

        self.history: List[EditStep] = []
        self.redo_stack: List[EditStep] = []

        # Base items defined before history steps
        self.base_captions: List[AnchoredCaption] = []
        self.base_effects: List[AnchoredAudioEffect] = []
        self.base_music: List[BackgroundMusicTrack] = []
        self._in_replay: bool = False

        # Active derived state
        self.clips: List[TimelineClip] = []
        self.captions: List[AnchoredCaption] = []
        self.effects: List[AnchoredAudioEffect] = []
        self.music: List[BackgroundMusicTrack] = []

        # Initialize base clip spanning the untouched media
        self._reset_to_base()

    def _reset_to_base(self):
        """Resets derived timeline state to original media before applying history."""
        base_words = [w.id for w in self.transcript.words]
        self.clips = [
            TimelineClip(
                clip_id="clip_0",
                source_start=0.0,
                source_end=self.source.duration_s,
                speed=1.0,
                word_ids=base_words
            )
        ]
        self.captions = [c.model_copy(deep=True) for c in self.base_captions]
        self.effects = [e.model_copy(deep=True) for e in self.base_effects]
        self.music = [m.model_copy(deep=True) for m in self.base_music]

    @property
    def total_duration(self) -> float:
        """Returns the total playback duration of the current edited timeline."""
        return round(sum(c.playback_duration for c in self.clips), 3)

    @property
    def timeline_hash(self) -> str:
        """Returns the deterministic hash of the current timeline state."""
        return compute_timeline_hash(
            clips=self.clips,
            captions=self.captions,
            effects=self.effects,
            music=self.music,
            source_sha256=self.source.sha256
        )

    def _reassign_clip_words(self, clip: TimelineClip):
        """Populates clip.word_ids with words whose midpoints fall within [source_start, source_end]."""
        words = self.transcript.words_in_range(clip.source_start, clip.source_end)
        clip.word_ids = [w.id for w in words]

    # -------------------------------------------------------------------------
    # Core Operations (Deterministic Transformations)
    # -------------------------------------------------------------------------

    def apply_cut(self, start_s: float, end_s: float, source_relative: bool = True) -> Dict[str, Any]:
        """Cuts the interval [start_s, end_s] from the timeline."""
        orig_start = start_s if source_relative else map_playback_time_to_source(start_s, self.clips)
        orig_end = end_s if source_relative else map_playback_time_to_source(end_s, self.clips)

        if orig_start is None or orig_end is None:
            raise ValueError(f"Time range [{start_s}, {end_s}] does not exist in current playback.")

        orig_start = max(0.0, min(self.source.duration_s, orig_start))
        orig_end = max(0.0, min(self.source.duration_s, orig_end))

        if orig_start >= orig_end:
            raise ValueError(f"Invalid cut range: start {orig_start:.2f}s >= end {orig_end:.2f}s")

        new_clips: List[TimelineClip] = []
        for c in self.clips:
            # Completely before or completely after
            if c.source_end <= orig_start or c.source_start >= orig_end:
                new_clips.append(c)
                continue

            # Clip is split or trimmed
            if c.source_start < orig_start:
                left_clip = TimelineClip(
                    clip_id=f"clip_{uuid.uuid4().hex[:6]}",
                    source_start=c.source_start,
                    source_end=orig_start,
                    speed=c.speed
                )
                self._reassign_clip_words(left_clip)
                new_clips.append(left_clip)

            if c.source_end > orig_end:
                right_clip = TimelineClip(
                    clip_id=f"clip_{uuid.uuid4().hex[:6]}",
                    source_start=orig_end,
                    source_end=c.source_end,
                    speed=c.speed
                )
                self._reassign_clip_words(right_clip)
                new_clips.append(right_clip)

        self.clips = new_clips
        return {
            "op": "cut_range",
            "source_start": round(orig_start, 3),
            "source_end": round(orig_end, 3),
            "policy": "original" if source_relative else "current"
        }

    def apply_speed(
        self,
        start_s: float,
        end_s: float,
        speed: float,
        source_relative: bool = False
    ) -> Dict[str, Any]:
        """Changes playback speed for the interval [start_s, end_s]."""
        if speed <= 0:
            raise ValueError(f"Speed factor must be positive: {speed}")

        orig_start = start_s if source_relative else map_playback_time_to_source(start_s, self.clips)
        orig_end = end_s if source_relative else map_playback_time_to_source(end_s, self.clips)

        if orig_start is None or orig_end is None:
            raise ValueError(f"Playback range [{start_s}, {end_s}] does not exist in current timeline.")

        new_clips: List[TimelineClip] = []
        for c in self.clips:
            # Completely outside
            if c.source_end <= orig_start or c.source_start >= orig_end:
                new_clips.append(c)
                continue

            # Slicing clip into parts: before range, within range, after range
            points = sorted(list({c.source_start, max(c.source_start, orig_start), min(c.source_end, orig_end), c.source_end}))
            for i in range(len(points) - 1):
                p1, p2 = points[i], points[i + 1]
                if p2 - p1 < 1e-4:
                    continue

                is_in_speed_range = (p1 >= orig_start - 1e-4) and (p2 <= orig_end + 1e-4)
                clip_speed = speed if is_in_speed_range else c.speed

                part_clip = TimelineClip(
                    clip_id=f"clip_{uuid.uuid4().hex[:6]}",
                    source_start=p1,
                    source_end=p2,
                    speed=clip_speed
                )
                self._reassign_clip_words(part_clip)
                new_clips.append(part_clip)

        self.clips = new_clips
        return {
            "op": "speed_up",
            "start_s": start_s,
            "end_s": end_s,
            "speed": speed,
            "policy": "original" if source_relative else "current",
            "orig_start": round(orig_start, 3),
            "orig_end": round(orig_end, 3)
        }

    def apply_add_caption(
        self,
        text: str,
        word_ids: List[str],
        style: Optional[CaptionStyle] = None,
        caption_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Attaches a caption anchored to specific Word IDs."""
        cid = caption_id or f"cap_{len(self.captions) + 1}"
        for existing in self.captions:
            if existing.caption_id == cid or (existing.word_ids == word_ids and existing.text == text):
                existing.text = text
                existing.word_ids = word_ids
                if style:
                    existing.style = style
                return {
                    "op": "add_caption",
                    "caption_id": existing.caption_id,
                    "text": text,
                    "word_ids": word_ids
                }

        cap = AnchoredCaption(
            caption_id=cid,
            text=text,
            word_ids=word_ids,
            style=style or CaptionStyle(),
            created_step=len(self.history) + 1,
            active=True
        )
        self.captions.append(cap)
        if not self._in_replay and not self.history:
            self.base_captions.append(cap.model_copy(deep=True))
        return {
            "op": "add_caption",
            "caption_id": cid,
            "text": text,
            "word_ids": word_ids
        }

    def apply_update_caption_style(
        self,
        caption_id: Optional[str] = None,
        style_updates: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Updates styling on an existing caption."""
        target: Optional[AnchoredCaption] = None
        if caption_id:
            for c in self.captions:
                if c.caption_id == caption_id:
                    target = c
                    break
        elif self.captions:
            # Default to the most recent or only caption
            target = self.captions[-1]

        if not target:
            raise ValueError("No caption found to update.")

        if style_updates:
            for k, v in style_updates.items():
                if hasattr(target.style, k):
                    setattr(target.style, k, v)

        return {
            "op": "update_caption_style",
            "caption_id": target.caption_id,
            "style": target.style.model_dump()
        }

    def apply_audio_effect(
        self,
        effect_type: Literal["mute", "bleep"],
        word_ids: List[str]
    ) -> Dict[str, Any]:
        """Applies an audio mute or bleep anchored to Word IDs."""
        effect_id = f"eff_{len(self.effects) + 1}"
        eff = AnchoredAudioEffect(
            effect_id=effect_id,
            effect_type=effect_type,
            word_ids=word_ids,
            created_step=len(self.history) + 1,
            active=True
        )
        self.effects.append(eff)
        return {
            "op": f"{effect_type}_words",
            "effect_id": effect_id,
            "word_ids": word_ids
        }

    def apply_background_music(
        self,
        music_file: str,
        volume: float = 0.20,
        ducking_volume: float = 0.05
    ) -> Dict[str, Any]:
        """Adds a background music track with auto-ducking under speech."""
        track_id = f"music_{len(self.music) + 1}"
        track = BackgroundMusicTrack(
            track_id=track_id,
            music_file_path=music_file,
            volume=volume,
            ducking_volume=ducking_volume,
            duck_under_speech=True
        )
        self.music.append(track)
        return {
            "op": "add_background_music",
            "track_id": track_id,
            "music_file": music_file,
            "volume": volume,
            "ducking_volume": ducking_volume
        }

    def apply_reorder(self, clip_ids: List[str]) -> Dict[str, Any]:
        """Reorders the timeline clips by clip_id."""
        clip_map = {c.clip_id: c for c in self.clips}
        if set(clip_ids) != set(clip_map.keys()):
            raise ValueError("Reorder list must contain exactly the existing clip IDs.")

        self.clips = [clip_map[cid] for cid in clip_ids]
        return {
            "op": "reorder",
            "order": clip_ids
        }

    # -------------------------------------------------------------------------
    # Replay, Undo, Redo, and Restore
    # -------------------------------------------------------------------------

    def replay_history(self):
        """Re-executes all active history operations from the base media.

        Guarantees 100% mathematical consistency and immutability.
        """
        self._in_replay = True
        try:
            self._reset_to_base()
            for step in self.history:
                if step.undone:
                    continue

                for op in step.operations:
                    op_type = op.op_type
                    p = op.params

                    if op_type == "cut_range":
                        self.apply_cut(
                            start_s=p["source_start"],
                            end_s=p["source_end"],
                            source_relative=True
                        )
                    elif op_type == "speed_up":
                        self.apply_speed(
                            start_s=p.get("orig_start", p["start_s"]),
                            end_s=p.get("orig_end", p["end_s"]),
                            speed=p["speed"],
                            source_relative=True
                        )
                    elif op_type == "add_caption":
                        style = CaptionStyle(**p["style"]) if "style" in p else CaptionStyle()
                        self.apply_add_caption(
                            text=p["text"],
                            word_ids=p["word_ids"],
                            style=style
                        )
                    elif op_type == "update_caption_style":
                        self.apply_update_caption_style(
                            caption_id=p.get("caption_id"),
                            style_updates=p.get("style")
                        )
                    elif op_type in ("mute_words", "bleep_words"):
                        eff_type = "mute" if "mute" in op_type else "bleep"
                        self.apply_audio_effect(
                            effect_type=eff_type,
                            word_ids=p["word_ids"]
                        )
                    elif op_type == "add_background_music":
                        self.apply_background_music(
                            music_file=p["music_file"],
                            volume=p.get("volume", 0.20),
                            ducking_volume=p.get("ducking_volume", 0.05)
                        )
        finally:
            self._in_replay = False

    def undo(self) -> Dict[str, Any]:
        """Reverses the last applied instruction (Must-have #6)."""
        active_steps = [s for s in self.history if not s.undone]
        if not active_steps:
            raise ValueError("Nothing to undo.")

        last_step = active_steps[-1]
        last_step.undone = True
        self.redo_stack.append(last_step)
        self.replay_history()

        return {
            "op": "undo",
            "reversed_step": last_step.step_index,
            "reversed_instruction": last_step.instruction
        }

    def redo(self) -> Dict[str, Any]:
        """Redoes the last undone instruction."""
        if not self.redo_stack:
            raise ValueError("Nothing to redo.")

        step_to_redo = self.redo_stack.pop()
        step_to_redo.undone = False
        self.replay_history()

        return {
            "op": "redo",
            "redone_step": step_to_redo.step_index,
            "redone_instruction": step_to_redo.instruction
        }

    def restore_step(self, step_index: int) -> Dict[str, Any]:
        """Restores a specific earlier step (e.g., puts an intro back)."""
        target_step = None
        for s in self.history:
            if s.step_index == step_index:
                target_step = s
                break

        if not target_step:
            raise ValueError(f"Step {step_index} not found in history.")

        # Invert/cancel this specific step
        target_step.undone = True
        self.replay_history()

        return {
            "op": "restore_edit",
            "restored_step": step_index,
            "instruction": target_step.instruction
        }

    def record_step(
        self,
        instruction: str,
        operations: List[Dict[str, Any]],
        summary: str
    ) -> EditStep:
        """Appends a new step to the immutable history and clears redo stack."""
        self.redo_stack.clear()
        step_index = len(self.history) + 1
        edit_ops = [EditOperation(op_type=op["op"], params=op) for op in operations]

        step = EditStep(
            step_index=step_index,
            instruction=instruction,
            operations=edit_ops,
            summary=summary,
            undone=False
        )
        self.history.append(step)
        return step

    def get_resolved_captions(self) -> Tuple[List[ResolvedCaption], List[str]]:
        """Returns all captions resolved to current playback timestamps."""
        return resolve_captions(self.captions, self.clips, self.transcript)

    def get_resolved_audio_effects(self) -> List[ResolvedAudioEffect]:
        """Returns all mutes/bleeps resolved to current playback timestamps."""
        return resolve_audio_effects(self.effects, self.clips, self.transcript)
