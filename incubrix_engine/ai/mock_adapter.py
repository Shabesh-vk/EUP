"""
Deterministic Mock LLM Adapter.
Guarantees 100% reproducible execution for the 8-step worked example,
integration tests, and CI/CD pipelines with zero external API dependencies.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional
from .adapter_interface import BaseLLMAdapter
from ..core.models import (
    Transcript,
    StepResponse,
    Operation,
    Clarification
)


class MockLLMAdapter(BaseLLMAdapter):
    """
    Deterministic rule-based mock adapter simulating high-fidelity LLM behavior.
    """

    def translate_instruction(
        self,
        instruction: str,
        transcript: Transcript,
        history_summary: List[Dict[str, Any]],
        pending_clarification: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> StepResponse:
        instr = instruction.strip().lower()

        # -------------------------------------------------------------
        # Handle Pending Clarification Reply
        # -------------------------------------------------------------
        if pending_clarification:
            return self._handle_clarification_reply(instruction, pending_clarification, transcript)

        # -------------------------------------------------------------
        # 1. Whole-video or impossible cuts (Must reject)
        # -------------------------------------------------------------
        if "cut everything" in instr or "remove everything" in instr and "thanks" not in instr and "guest" not in instr:
            return StepResponse(
                status="rejected",
                summary="Whole-video cuts are prohibited.",
                rejection_reason="Instruction would result in an empty video (cut entire duration)."
            )

        # Out-of-bounds timestamp rejection
        if "at 5:00" in instr or "at 300" in instr:
            if transcript.duration < 300:
                return StepResponse(
                    status="rejected",
                    summary="Requested timestamp exceeds video length.",
                    rejection_reason=f"Timestamp 5:00 (300s) exceeds video duration of {transcript.duration:.1f}s."
                )

        # -------------------------------------------------------------
        # 2. Undo / Redo Commands
        # -------------------------------------------------------------
        if instr in ["undo", "revert"] or instr.startswith("revert"):
            return StepResponse(
                status="applied",
                summary="Undo previous step.",
                operations=[Operation(op="undo", params={})]
            )

        if instr in ["redo"]:
            return StepResponse(
                status="applied",
                summary="Redo previously undone step.",
                operations=[Operation(op="redo", params={})]
            )

        # -------------------------------------------------------------
        # 3. Restoring specific edits ("put back the intro", "restore...")
        # -------------------------------------------------------------
        if "put the intro back" in instr or "restore the intro" in instr or "bring back the intro" in instr:
            # Find which step cut the intro
            intro_step_id = None
            for h in history_summary:
                if "cut" in h.get("instruction", "").lower() and ("30" in h.get("instruction", "") or "intro" in h.get("instruction", "")):
                    intro_step_id = h.get("step_id")
                    break
            if not intro_step_id and history_summary:
                # Default to step 2 in standard worked example
                intro_step_id = 2

            if intro_step_id:
                return StepResponse(
                    status="applied",
                    summary="The first 30 s return; caption back at 0:42; the pricing cut and speed change stay.",
                    operations=[Operation(op="restore_edit", params={"target_step_id": intro_step_id})]
                )
            else:
                return StepResponse(
                    status="rejected",
                    summary="No intro cut step found in edit history to restore.",
                    rejection_reason="Cannot identify an earlier intro removal step."
                )

        if "undo the second-to-last cut" in instr:
            # Identify cut steps in history
            cut_steps = [h.get("step_id") for h in history_summary if "cut" in h.get("instruction", "").lower()]
            if len(cut_steps) >= 2:
                target_step = cut_steps[-2]
                return StepResponse(
                    status="applied",
                    summary=f"Selectively restored second-to-last cut (step {target_step}) while keeping other edits.",
                    operations=[Operation(op="restore_edit", params={"target_step_id": target_step})]
                )
            else:
                return StepResponse(
                    status="rejected",
                    summary="Fewer than two cuts exist in history.",
                    rejection_reason="Not enough cut operations to target second-to-last."
                )

        # -------------------------------------------------------------
        # 4. Captions Styling ("Make that caption red", "make it blue", "make it bigger")
        # -------------------------------------------------------------
        color_match = re.search(r"make (?:that )?caption (\w+)", instr)
        if color_match and color_match.group(1) in ["red", "blue", "green", "yellow", "white", "black"]:
            chosen_color = color_match.group(1)
            return StepResponse(
                status="applied",
                summary=f"Applied {chosen_color} style to caption.",
                operations=[Operation(op="style_caption", params={"color": chosen_color})]
            )

        if "caption" in instr and ("red" in instr or "color" in instr or "bigger" in instr or "style" in instr):
            color = "red" if "red" in instr else None
            font_size = 32 if "bigger" in instr else None
            return StepResponse(
                status="applied",
                summary="Applied to the Welcome! caption, the only one that exists.",
                operations=[
                    Operation(
                        op="style_caption",
                        params={"color": color, "font_size": font_size}
                    )
                ]
            )

        if "make it bigger" in instr or "make that caption bigger" in instr:
            # Check if any captions exist in history
            has_caption = any("caption" in h.get("instruction", "").lower() for h in history_summary)
            if not has_caption:
                return StepResponse(
                    status="rejected",
                    summary="No caption exists to resize.",
                    rejection_reason="There are currently no captions on the timeline."
                )
            return StepResponse(
                status="applied",
                summary="Increased caption font size.",
                operations=[Operation(op="style_caption", params={"font_size": 32})]
            )

        # -------------------------------------------------------------
        # 5. Add Caption with phrase anchoring
        # -------------------------------------------------------------
        caption_match = re.search(r"add a caption ['\"]([^'\"]+)['\"]", instruction, re.IGNORECASE)
        if caption_match:
            caption_text = caption_match.group(1)
            # Find trigger phrase
            phrase_match = re.search(r"when i say (.+)$", instruction, re.IGNORECASE)
            start_wid, end_wid = 0, 0
            if phrase_match:
                phrase = phrase_match.group(1).strip()
                matches = transcript.find_phrase(phrase)
                if matches:
                    start_wid, end_wid = matches[0]
                else:
                    # Fallback search for first word
                    first_word = phrase.split()[0]
                    word_ids = transcript.find_words_by_text(first_word)
                    if word_ids:
                        start_wid = word_ids[0]
                        end_wid = min(start_wid + 3, len(transcript.words) - 1)
                    else:
                        start_wid, end_wid = 0, min(3, len(transcript.words) - 1)

            # Determine original word times for summary
            w1 = transcript.get_word(start_wid)
            w2 = transcript.get_word(end_wid)
            t1 = f"0:{int(w1.start):02d}" if w1 else "0:42"
            t2 = f"0:{int(w2.end):02d}" if w2 else "0:44"

            return StepResponse(
                status="applied",
                summary=f"Caption attached to those {end_wid - start_wid + 1} words (original time {t1}-{t2}).",
                operations=[
                    Operation(
                        op="add_caption",
                        params={
                            "text": caption_text,
                            "start_word_id": start_wid,
                            "end_word_id": end_wid
                        }
                    )
                ]
            )

        # -------------------------------------------------------------
        # 6. Cut Commands (First N, Last N, and Ranges)
        # -------------------------------------------------------------
        cut_last_match = re.search(r"cut the last (\d+)\s*(?:seconds|s)?", instr)
        if cut_last_match:
            sec = float(cut_last_match.group(1))
            cut_s = max(0.0, transcript.duration - sec)
            cut_e = transcript.duration
            return StepResponse(
                status="applied",
                summary=f"Cut the last {int(sec)} seconds of video.",
                operations=[Operation(op="cut_range", params={"start": cut_s, "end": cut_e})]
            )

        cut_first_match = re.search(r"cut the first (\d+)\s*(?:seconds|s)?", instr)
        if cut_first_match:
            sec = float(cut_first_match.group(1))
            return StepResponse(
                status="applied",
                summary=f"Video is {int(sec)} s shorter. Caption now plays at 0:12-0:14, still on the same words.",
                operations=[
                    Operation(
                        op="cut_range",
                        params={"start": 0.0, "end": sec, "time_policy": "original_time"}
                    )
                ]
            )

        cut_range_match = re.search(r"(?:cut|remove) (?:from )?(\d+:\d+|\d+(?:\.\d+)?)(?:\s*to\s*|-)(\d+:\d+|\d+(?:\.\d+)?)", instr)
        if cut_range_match and "pricing" not in instr and "thanks" not in instr and "first" not in instr and "last" not in instr:
            def _parse_t(s: str) -> float:
                if ":" in s:
                    parts = s.split(":")
                    return float(parts[0]) * 60 + float(parts[1])
                return float(s)

            t_s = _parse_t(cut_range_match.group(1))
            t_e = _parse_t(cut_range_match.group(2))

            if t_s <= 0.0 and t_e >= transcript.duration:
                return StepResponse(
                    status="rejected",
                    summary="Cannot cut entire video.",
                    rejection_reason="Whole-video cuts are prohibited."
                )

            return StepResponse(
                status="applied",
                summary=f"Cut range {t_s:.1f}s to {t_e:.1f}s.",
                operations=[Operation(op="cut_range", params={"start": t_s, "end": t_e})]
            )

        # -------------------------------------------------------------
        # 7. Semantic Ambiguity: "pricing" or "thanks" (Needs Clarification)
        # -------------------------------------------------------------
        if ("pricing" in instr or "cost" in instr or "price" in instr) and "mute" not in instr and "bleep" not in instr:
            # Check how many occurrences in transcript
            matches = transcript.find_words_by_text("pricing") + transcript.find_words_by_text("price") + transcript.find_words_by_text("cost")
            unique_matches = sorted(list(set(matches)))
            if len(unique_matches) > 1 or "remove" in instr or "cut" in instr:
                return StepResponse(
                    status="needs_clarification",
                    summary="Pricing is mentioned multiple times in the video.",
                    clarification=Clarification(
                        question="Pricing is mentioned three times (1:05, 2:40 and 3:15) - which one, or all?",
                        options=[
                            "1. The first one (1:05)",
                            "2. The second one (2:40)",
                            "3. The third one (3:15)",
                            "4. All occurrences"
                        ]
                    )
                )

        if "thanks" in instr and ("remove" in instr or "cut" in instr):
            matches = transcript.find_words_by_text("thanks")
            if len(matches) > 1:
                return StepResponse(
                    status="needs_clarification",
                    summary="'Thanks' is spoken multiple times across the recording.",
                    clarification=Clarification(
                        question="Thanks is spoken 4 times - which instance should be cut after?",
                        options=[
                            "1. First thanks (0:45)",
                            "2. Second thanks (2:10)",
                            "3. Third thanks (4:30)",
                            "4. Final closing thanks (5:50)"
                        ]
                    )
                )

        # -------------------------------------------------------------
        # 8. Speed Changes ("Speed up from 1:00 to 1:30 by 2x", "speed up by 0.5x")
        # -------------------------------------------------------------
        speed_range_match = re.search(r"speed up (?:from )?(\d+(?:\.\d+)?|\d+:\d+) to (\d+(?:\.\d+)?|\d+:\d+) by (\d+(?:\.\d+)?)x", instr)
        if speed_range_match:
            def _parse_spd_t(s: str) -> float:
                if ":" in s:
                    p = s.split(":")
                    return float(p[0]) * 60 + float(p[1])
                return float(s)

            t_start = _parse_spd_t(speed_range_match.group(1))
            t_end = _parse_spd_t(speed_range_match.group(2))
            speed_val = float(speed_range_match.group(3))

            return StepResponse(
                status="applied",
                summary=f"Applied, using original source time policy: sped up range {speed_range_match.group(1)} to {speed_range_match.group(2)} by {speed_val}x.",
                operations=[
                    Operation(
                        op="speed_change",
                        params={
                            "start": t_start,
                            "end": t_end,
                            "speed": speed_val,
                            "time_policy": "original_time"
                        }
                    )
                ]
            )

        speed_simple = re.search(r"speed up (?:by )?(\d+(?:\.\d+)?)x", instr)
        if speed_simple:
            spd = float(speed_simple.group(1))
            if spd > 10.0:
                return StepResponse(
                    status="rejected",
                    summary="Speed change exceeds maximum supported limit.",
                    rejection_reason="Maximum supported playback speed is 10x."
                )
            return StepResponse(
                status="applied",
                summary=f"Changed playback speed to {spd}x.",
                operations=[Operation(op="speed_change", params={"start": 0.0, "end": transcript.duration, "speed": spd})]
            )

        # -------------------------------------------------------------
        # Audio Effects: Mute & Bleep
        # -------------------------------------------------------------
        if "mute" in instr:
            return StepResponse(
                status="applied",
                summary="Muted dialogue words.",
                operations=[Operation(op="mute_words", params={"start_word_id": 6, "end_word_id": 6})]
            )

        if "bleep" in instr:
            return StepResponse(
                status="applied",
                summary="Bleeped dialogue words.",
                operations=[Operation(op="bleep_words", params={"start_word_id": 0, "end_word_id": 0})]
            )

        # -------------------------------------------------------------
        # 9. Filler Word Removal
        # -------------------------------------------------------------
        if "filler" in instr or "cut out the ums" in instr or "remove the ums" in instr:
            return StepResponse(
                status="applied",
                summary="Removed filler words (ums, uhs) from dialogue.",
                operations=[Operation(op="remove_filler", params={})]
            )

        # -------------------------------------------------------------
        # 10. Background Music
        # -------------------------------------------------------------
        if "background music" in instr or "bg music" in instr:
            return StepResponse(
                status="applied",
                summary="Added background music track with automatic speech ducking.",
                operations=[
                    Operation(
                        op="add_bg_music",
                        params={"url": "assets/music.mp3", "volume": 0.3, "ducking": True}
                    )
                ]
            )

        # -------------------------------------------------------------
        # 11. Speaker-specific instruction (Two speakers)
        # -------------------------------------------------------------
        if "guest" in instr and ("job" in instr or "remove" in instr):
            return StepResponse(
                status="applied",
                summary="Removed guest segment about their previous job; preserved host lead-in question.",
                operations=[
                    Operation(
                        op="cut_range",
                        params={"start": 120.0, "end": 180.0, "speaker": "guest"}
                    )
                ]
            )

        # -------------------------------------------------------------
        # Default Ambiguity Fallback
        # -------------------------------------------------------------
        return StepResponse(
            status="needs_clarification",
            summary=f"Instruction '{instruction}' is ambiguous or underspecified.",
            clarification=Clarification(
                question=f"Could you clarify the exact range or target for: '{instruction}'?",
                options=["1. Apply to entire video", "2. Specify timestamp range", "3. Cancel instruction"]
            )
        )

    def _handle_clarification_reply(
        self,
        answer: str,
        pending: Dict[str, Any],
        transcript: Transcript
    ) -> StepResponse:
        """Resolves follow-up user answer to a clarification question."""
        ans = answer.strip().lower()

        # Step 3 of worked example: "the second one" or "2"
        if "second" in ans or "2" in ans:
            # Second pricing occurrence: 2:40 (160s to 180s)
            return StepResponse(
                status="applied",
                summary="Removed the second pricing section (2:40-3:00).",
                operations=[
                    Operation(
                        op="cut_range",
                        params={"start": 160.0, "end": 180.0, "time_policy": "original_time"}
                    )
                ]
            )
        elif "first" in ans or "1" in ans:
            return StepResponse(
                status="applied",
                summary="Removed the first pricing section (1:05-1:25).",
                operations=[Operation(op="cut_range", params={"start": 65.0, "end": 85.0})]
            )
        elif "all" in ans or "4" in ans:
            return StepResponse(
                status="applied",
                summary="Removed all pricing sections.",
                operations=[
                    Operation(op="cut_range", params={"start": 65.0, "end": 85.0}),
                    Operation(op="cut_range", params={"start": 160.0, "end": 180.0}),
                    Operation(op="cut_range", params={"start": 195.0, "end": 210.0}),
                ]
            )

        return StepResponse(
            status="applied",
            summary=f"Applied choice: '{answer}'.",
            operations=[Operation(op="cut_range", params={"start": 160.0, "end": 180.0})]
        )
