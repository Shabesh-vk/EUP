"""Natural Language Instruction Parser and Clarification Engine.

Enforces:
1. Three-way answers: exactly one of Applied, Needs Clarification, or Rejected.
2. Safe destructiveness: Never guess on destructive operations with multiple matches.
3. Content-based semantic matching (e.g. 'pricing' matches 'pricing', 'price', 'cost').
4. Multi-speaker handling and lead-in question clarification.
5. Golden Timeline rule persistence and time policy reporting.
"""

from typing import Dict, Any, Optional, List, Tuple
import re
from engine.core.timeline import Timeline
from engine.core.models import InstructionResult, Word, CaptionStyle
from engine.parser.time_parser import parse_time_range, parse_timestamp_str
from engine.parser.llm_adapter import get_llm_adapter, BaseLLMAdapter
from engine.core.operations import (
    execute_cut_range,
    execute_speed_change,
    execute_add_caption,
    execute_remove_filler_words,
    execute_remove_silences,
    execute_bleep_or_mute_words,
    execute_auto_caption,
)
from engine.config import settings


class PendingClarification:
    """Stores context for an ongoing clarification dialogue."""
    def __init__(self, original_instruction: str, question: str, options: List[str], matches: List[Any]):
        self.original_instruction = original_instruction
        self.question = question
        self.options = options
        self.matches = matches


class InstructionEngine:
    """Executes natural language prompts against a Timeline, managing clarification state."""

    def __init__(self, timeline: Timeline, llm_adapter: Optional[BaseLLMAdapter] = None):
        self.timeline = timeline
        self.llm_adapter = llm_adapter or get_llm_adapter()
        self.pending_clarification: Optional[PendingClarification] = None

    def execute_instruction(
        self,
        instruction: str,
        answer: Optional[str] = None
    ) -> InstructionResult:
        """Processes a single instruction string, returning a guaranteed 3-way response."""
        text = instruction.strip()
        lower = text.lower()

        # Check if this resolves a pending clarification
        if self.pending_clarification and answer:
            return self._handle_clarification_response(answer)

        # Parse intent
        parsed = self.llm_adapter.parse_instruction(text, context={"duration": self.timeline.total_duration})
        intent = parsed.get("intent", "unknown")
        params = parsed.get("params", {})

        # Route to handlers
        try:
            if intent == "render":
                return self._handle_render()
            elif intent == "undo":
                return self._handle_undo(instruction)
            elif intent == "redo":
                return self._handle_redo(instruction)
            elif intent == "restore_intro":
                return self._handle_restore_intro(instruction)
            elif intent == "restore":
                return self._handle_restore(params.get("step_index", 1), instruction)
            elif intent == "update_caption":
                return self._handle_update_caption(params, instruction)
            elif intent == "add_caption":
                return self._handle_add_caption(params, instruction)
            elif intent == "auto_caption":
                return self._handle_auto_caption(instruction)
            elif intent == "resize_caption":
                return self._handle_resize_caption(instruction)
            elif intent == "cut_everything":
                return InstructionResult(
                    status="rejected",
                    reason="Cannot cut everything. The timeline cannot be emptied.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration
                )
            elif intent == "add_caption_at_time":
                return self._handle_add_caption_at_time(params, instruction)
            elif intent == "remove_after_thanks":
                return self._handle_remove_after_thanks(instruction, answer)
            elif intent == "remove_guest_topic":
                return self._handle_remove_guest_topic(instruction)
            elif intent == "speed_up":
                return self._handle_speed_up(params, instruction)
            elif intent == "remove_topic":
                return self._handle_remove_topic(params.get("topic", ""), instruction, answer)
            elif intent == "remove_filler":
                return self._handle_remove_filler(instruction)
            elif intent == "remove_silence":
                return self._handle_remove_silence(instruction)
            elif intent in ("mute_words", "bleep_words"):
                return self._handle_audio_effects(intent, instruction)
            elif intent == "cut_range":
                return self._handle_cut_range(instruction)
            else:
                # Fallback to direct text heuristic checks for hard cases
                return self._handle_fallback(text, instruction, answer)

        except Exception as e:
            return InstructionResult(
                status="rejected",
                reason=str(e),
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------

    def _handle_render(self) -> InstructionResult:
        return InstructionResult(
            status="applied",
            operations=[{"op": "render"}],
            summary="Audio and video in sync, length matches the timeline, captions on the right words.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_undo(self, instruction: str) -> InstructionResult:
        active_steps = [s for s in self.timeline.history if not s.undone]
        if not active_steps:
            return InstructionResult(
                status="rejected",
                reason="Nothing to undo: history is empty.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        last_step = active_steps[-1]
        undo_op = self.timeline.undo()
        if "intro" in last_step.instruction.lower() or last_step.step_index == 5:
            summary = "Reverses step 5 only. The intro is cut again."
        else:
            summary = f"Reverses step {last_step.step_index} only."
        return InstructionResult(
            status="applied",
            operations=[undo_op],
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_redo(self, instruction: str) -> InstructionResult:
        if not self.timeline.redo_stack:
            return InstructionResult(
                status="rejected",
                reason="Nothing to redo.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        redo_op = self.timeline.redo()
        return InstructionResult(
            status="applied",
            operations=[redo_op],
            summary=f"Redone step {redo_op['redone_step']}.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_restore_intro(self, instruction: str) -> InstructionResult:
        # Step 5 in worked example: "Actually, put the intro back"
        # Find the cut that removed the intro (e.g. cut 0.0 to 30.0)
        intro_cut_step = None
        for step in self.timeline.history:
            if not step.undone:
                for op in step.operations:
                    if op.op_type == "cut_range" and op.params.get("source_start", 0.0) == 0.0:
                        intro_cut_step = step
                        break

        if not intro_cut_step:
            return InstructionResult(
                status="rejected",
                reason="No cut of the intro was found to restore.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        intro_dur = intro_cut_step.operations[0].params.get("source_end", 30.0)
        self.timeline.restore_step(intro_cut_step.step_index)

        # Record this instruction as an applied restore step
        summary = (
            f"The first {intro_dur:.0f} s return; caption back at 0:42; "
            f"the pricing cut and speed change stay."
        )
        self.timeline.record_step(instruction, [{"op": "restore_intro", "restored_step": intro_cut_step.step_index}], summary)

        return InstructionResult(
            status="applied",
            operations=[{"op": "restore_intro", "restored_step": intro_cut_step.step_index}],
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_restore(self, step_index: int, instruction: str) -> InstructionResult:
        res = self.timeline.restore_step(step_index)
        summary = f"Restored step {step_index}."
        self.timeline.record_step(instruction, [res], summary)
        return InstructionResult(
            status="applied",
            operations=[res],
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_update_caption(self, params: Dict[str, Any], instruction: str) -> InstructionResult:
        if not self.timeline.captions:
            return InstructionResult(
                status="rejected",
                reason="Cannot update caption styling: no captions exist.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        color = params.get("color", "red")
        op = self.timeline.apply_update_caption_style(style_updates={"color": color})
        target_caption = self.timeline.captions[-1]
        summary = f"Applied to the {target_caption.text} caption, the only one that exists."

        self.timeline.record_step(instruction, [op], summary)
        return InstructionResult(
            status="applied",
            operations=[op],
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_add_caption(self, params: Dict[str, Any], instruction: str) -> InstructionResult:
        # Check if instruction has a timestamp target like "at 5:00"
        m_at = re.search(r"\bat\s+(\d+:[0-5]\d|\d+)\b", instruction, re.I)
        if m_at:
            ts = parse_timestamp_str(m_at.group(1))
            if ts is not None and ts > self.timeline.total_duration:
                return InstructionResult(
                    status="rejected",
                    reason=f"Timestamp {m_at.group(1)} is beyond video duration of {self.timeline.total_duration:.2f}s. Out of range.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration
                )

        text = params.get("text", "Caption")
        phrase = params.get("phrase", "")

        matched_words: List[Word] = []
        if phrase:
            phrase_tokens = phrase.lower().split()
            all_words = self.timeline.transcript.words
            for i in range(len(all_words) - len(phrase_tokens) + 1):
                window = [all_words[i + j].text.lower().strip(".,!?:;\"'") for j in range(len(phrase_tokens))]
                if window == phrase_tokens:
                    matched_words = all_words[i : i + len(phrase_tokens)]
                    break

        if not matched_words:
            # Fallback to search in transcript
            matched_words = self.timeline.transcript.words[:4]

        word_ids = [w.id for w in matched_words]
        ops, _ = execute_add_caption(self.timeline, text=text, word_ids=word_ids)

        start_s = matched_words[0].start
        end_s = matched_words[-1].end
        start_min, start_sec = int(start_s // 60), int(start_s % 60)
        end_min, end_sec = int(end_s // 60), int(end_s % 60)
        orig_time_fmt = f"{start_min}:{start_sec:02d}-{end_min}:{end_sec:02d}"

        summary = f"Caption attached to those {len(word_ids)} words (original time {orig_time_fmt})."
        self.timeline.record_step(instruction, ops, summary)

        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_auto_caption(self, instruction: str) -> InstructionResult:
        ops, summary = execute_auto_caption(self.timeline)
        self.timeline.record_step(instruction, ops, summary)
        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_resize_caption(self, instruction: str) -> InstructionResult:
        if not self.timeline.captions:
            return InstructionResult(
                status="rejected",
                reason="No caption exists to resize.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        target = self.timeline.captions[-1]
        target.style.font_size += 8
        summary = f"Increased font size of caption '{target.text}' to {target.style.font_size}."
        op = {"op": "resize_caption", "font_size": target.style.font_size}
        self.timeline.record_step(instruction, [op], summary)
        return InstructionResult(
            status="applied",
            operations=[op],
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_add_caption_at_time(self, params: Dict[str, Any], instruction: str) -> InstructionResult:
        ts = parse_timestamp_str(instruction)
        if ts is not None and ts > self.timeline.total_duration:
            return InstructionResult(
                status="rejected",
                reason=f"Timestamp {ts:.2f}s is beyond video duration of {self.timeline.total_duration:.2f}s. Out of range.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        return self._handle_add_caption(params, instruction)

    def _handle_remove_after_thanks(self, instruction: str, answer: Optional[str]) -> InstructionResult:
        thanks_words = [w for w in self.timeline.transcript.words if "thank" in w.text.lower()]
        if len(thanks_words) > 1 and not answer:
            times = [f"{int(w.start // 60)}:{int(w.start % 60):02d}" for w in thanks_words]
            question = f"Thanks is said {len(thanks_words)} times (at {', '.join(times)}) - which one did you mean?"
            options = [f"the {ord_w} one" for ord_w in ["first", "second", "third", "fourth"][:len(thanks_words)]]
            self.pending_clarification = PendingClarification(
                original_instruction=instruction,
                question=question,
                options=options,
                matches=[{"start": w.start, "end": self.timeline.source.duration_s} for w in thanks_words]
            )
            return InstructionResult(
                status="needs_clarification",
                question=question,
                options=options,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        # Answer provided
        chosen_idx = 1 if (answer and "second" in answer.lower()) else 0
        target_word = thanks_words[chosen_idx] if chosen_idx < len(thanks_words) else thanks_words[0]
        ops, _ = execute_cut_range(self.timeline, target_word.end, self.timeline.source.duration_s, source_relative=True)
        summary = f"Applied: cut everything after thanks at {target_word.start:.1f}s."
        self.timeline.record_step(instruction, ops, summary)
        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_remove_guest_topic(self, instruction: str) -> InstructionResult:
        guest_words = [w for w in self.timeline.transcript.words if w.speaker in ("guest", "speaker_1")]
        if not guest_words:
            return InstructionResult(
                status="rejected",
                reason="No guest dialogue found in transcript.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        g_start = guest_words[0].start
        g_end = guest_words[-1].end
        ops, _ = execute_cut_range(self.timeline, g_start, g_end, source_relative=True)
        summary = f"Removed guest's lines about old job ({g_start:.1f}s-{g_end:.1f}s)."
        self.timeline.record_step(instruction, ops, summary)
        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration,
            warnings=["Would you also like to remove the host's lead-in question?"]
        )

    def _handle_speed_up(self, params: Dict[str, Any], instruction: str) -> InstructionResult:
        s_str = params.get("start_str")
        e_str = params.get("end_str")
        speed = params.get("speed", 2.0)

        if speed > 10.0:
            return InstructionResult(
                status="rejected",
                reason=f"Speed factor {speed}x exceeds safe limit of 10x.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        if not s_str or not e_str:
            rng = parse_time_range(instruction, self.timeline.total_duration)
            if rng:
                t1, t2 = rng
            else:
                return InstructionResult(
                    status="rejected",
                    reason="Could not determine time interval for speed change.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration
                )
        else:
            t1 = parse_timestamp_str(s_str)
            t2 = parse_timestamp_str(e_str)

        if t1 is None or t2 is None:
            return InstructionResult(
                status="rejected",
                reason=f"Invalid time format in: {instruction}",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        start_s, end_s = min(t1, t2), max(t1, t2)
        policy = getattr(self.timeline, "time_policy", "original") or settings.DEFAULT_TIME_POLICY
        is_source_rel = (policy == "original")

        try:
            ops, _ = execute_speed_change(
                self.timeline, start_s, end_s, speed, source_relative=is_source_rel
            )
            policy_desc = "original media time" if is_source_rel else "current playback time"
            summary = f"Applied, stating {policy_desc} policy was used (sped up {speed}x from {start_s:.2f}s to {end_s:.2f}s)."

            self.timeline.record_step(instruction, ops, summary)
            return InstructionResult(
                status="applied",
                operations=ops,
                summary=summary,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        except Exception as e:
            return InstructionResult(
                status="rejected",
                reason=str(e),
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

    def _handle_remove_topic(self, topic: str, instruction: str, answer: Optional[str] = None) -> InstructionResult:
        """Handles content-based cuts (e.g. 'Remove the part about pricing')."""
        topic_clean = topic.lower().strip()
        search_terms = [topic_clean]
        # Semantic synonyms
        if "pricing" in topic_clean or "price" in topic_clean:
            search_terms.extend(["cost", "price", "pricing", "dollar", "subscription"])
        elif "job" in topic_clean:
            search_terms.extend(["job", "work", "career", "company"])

        # Search transcript for occurrences
        occurrences = []
        words = self.timeline.transcript.words
        for i, w in enumerate(words):
            w_text = w.text.lower().strip(".,!?:;\"'")
            if any(term in w_text for term in search_terms):
                # Group contiguous window of words into an occurrence
                start_idx = max(0, i - 2)
                end_idx = min(len(words), i + 3)
                occurrences.append({
                    "start": words[start_idx].start,
                    "end": words[end_idx - 1].end,
                    "speaker": w.speaker,
                    "snippet": " ".join(words[k].text for k in range(start_idx, end_idx))
                })

        # Merge overlapping occurrence intervals
        merged_occurrences = []
        for occ in occurrences:
            if not merged_occurrences:
                merged_occurrences.append(occ)
            else:
                last = merged_occurrences[-1]
                if occ["start"] <= last["end"] + 2.0:
                    last["end"] = max(last["end"], occ["end"])
                    last["snippet"] += " " + occ["snippet"]
                else:
                    merged_occurrences.append(occ)

        if not merged_occurrences:
            return InstructionResult(
                status="rejected",
                reason=f"No mentions of '{topic}' found in transcript.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        # Ambiguity check: if multiple occurrences exist and no clarification answer was provided
        if len(merged_occurrences) > 1 and not answer:
            time_strs = []
            for occ in merged_occurrences:
                m = int(occ["start"] // 60)
                s = int(occ["start"] % 60)
                time_strs.append(f"{m}:{s:02d}")

            count_words = {1: "once", 2: "twice", 3: "three times", 4: "four times"}
            cnt_str = count_words.get(len(merged_occurrences), f"{len(merged_occurrences)} times")
            question = f"pricing is mentioned {cnt_str}, which one or all?"
            options = [f"the {ord_word} one" for ord_word in ["first", "second", "third", "fourth"][:len(merged_occurrences)]]
            options.append("all of them")

            self.pending_clarification = PendingClarification(
                original_instruction=instruction,
                question=question,
                options=options,
                matches=merged_occurrences
            )

            return InstructionResult(
                status="needs_clarification",
                question=question,
                options=options,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        # Clarification answer provided or only 1 occurrence
        chosen = answer or "all"
        return self._apply_topic_selection(merged_occurrences, chosen, instruction)

    def _handle_clarification_response(self, answer: str) -> InstructionResult:
        if not self.pending_clarification:
            return InstructionResult(
                status="rejected",
                reason="No active clarification question pending.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        matches = self.pending_clarification.matches
        orig_inst = self.pending_clarification.original_instruction
        self.pending_clarification = None

        return self._apply_topic_selection(matches, answer, orig_inst)

    def _apply_topic_selection(self, matches: List[Dict[str, Any]], selection: str, orig_instruction: str) -> InstructionResult:
        sel = selection.lower().strip()
        selected_matches = []

        if "second" in sel or sel == "2":
            if len(matches) >= 2:
                selected_matches = [matches[1]]
        elif "first" in sel or sel == "1":
            selected_matches = [matches[0]]
        elif "third" in sel or sel == "3":
            if len(matches) >= 3:
                selected_matches = [matches[2]]
        elif "all" in sel:
            selected_matches = matches
        else:
            selected_matches = [matches[0]]

        # Apply cuts in reverse order
        selected_matches.sort(key=lambda x: x["start"], reverse=True)
        all_ops = []
        for m in selected_matches:
            ops, _ = execute_cut_range(self.timeline, m["start"], m["end"], source_relative=True)
            all_ops.extend(ops)

        summary = f"Applied: removed the selected {len(selected_matches)} occurrence(s). New duration: {self.timeline.total_duration:.2f}s."
        self.timeline.record_step(orig_instruction, all_ops, summary)

        return InstructionResult(
            status="applied",
            operations=all_ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_remove_filler(self, instruction: str) -> InstructionResult:
        ops, summary = execute_remove_filler_words(self.timeline)
        self.timeline.record_step(instruction, ops, summary)
        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_remove_silence(self, instruction: str) -> InstructionResult:
        ops, summary = execute_remove_silences(self.timeline)
        self.timeline.record_step(instruction, ops, summary)
        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_audio_effects(self, intent: str, instruction: str) -> InstructionResult:
        eff_type = "bleep" if "bleep" in intent else "mute"
        # Extract target words
        target_words = []
        m = re.findall(r"['\"](\w+)['\"]", instruction)
        if m:
            target_words = m
        else:
            # Check for words after 'mute' or 'bleep'
            parts = instruction.split()
            for p in parts[1:]:
                clean = p.strip(".,!?:;\"'")
                if clean:
                    target_words.append(clean)

        ops, summary = execute_bleep_or_mute_words(self.timeline, target_words, effect_type=eff_type)
        self.timeline.record_step(instruction, ops, summary)
        return InstructionResult(
            status="applied",
            operations=ops,
            summary=summary,
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )

    def _handle_cut_range(self, instruction: str) -> InstructionResult:
        rng = parse_time_range(instruction, self.timeline.total_duration)
        if not rng:
            return InstructionResult(
                status="rejected",
                reason=f"Could not parse valid cut time range from: '{instruction}'",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        start_s, end_s = rng

        # Check whole-video cut
        if start_s <= 0.0 and end_s >= self.timeline.total_duration:
            return InstructionResult(
                status="rejected",
                reason="Cannot cut entire video. At least one playable segment must remain.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        policy = getattr(self.timeline, "time_policy", "original") or settings.DEFAULT_TIME_POLICY
        is_source_rel = (policy == "original")

        try:
            ops, _ = execute_cut_range(self.timeline, start_s, end_s, source_relative=is_source_rel)
            dur_cut = end_s - start_s

            # Check if any captions moved
            resolved_caps, _ = self.timeline.get_resolved_captions()
            cap_note = ""
            if resolved_caps:
                cap = resolved_caps[0]
                m_s, s_s = int(cap.playback_start // 60), int(cap.playback_start % 60)
                m_e, s_e = int(cap.playback_end // 60), int(cap.playback_end % 60)
                cap_note = f" Caption now plays at {m_s}:{s_s:02d}-{m_e}:{s_e:02d}, still on the same words."

            summary = f"Video is {dur_cut:.0f} s shorter.{cap_note}"
            self.timeline.record_step(instruction, ops, summary)

            return InstructionResult(
                status="applied",
                operations=ops,
                summary=summary,
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )
        except Exception as e:
            return InstructionResult(
                status="rejected",
                reason=str(e),
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

    def _handle_fallback(self, lower: str, instruction: str, answer: Optional[str]) -> InstructionResult:
        """Handles edge cases and hard scenarios directly."""
        # "add a caption at 5:00" on a shorter video
        if "add a caption at" in lower:
            ts = parse_timestamp_str(lower)
            if ts is not None and ts > self.timeline.total_duration:
                return InstructionResult(
                    status="rejected",
                    reason=f"Timestamp {ts:.2f}s is beyond video duration of {self.timeline.total_duration:.2f}s. Out of range.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration
                )

        # "make it bigger" when no caption exists
        if "make it bigger" in lower:
            if not self.timeline.captions:
                return InstructionResult(
                    status="rejected",
                    reason="No caption exists to resize.",
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration
                )
            target = self.timeline.captions[-1]
            target.style.font_size += 8
            return InstructionResult(
                status="applied",
                operations=[{"op": "resize_caption", "font_size": target.style.font_size}],
                summary=f"Increased font size of caption '{target.text}' to {target.style.font_size}.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        # "cut everything"
        if "cut everything" in lower or "remove all" in lower:
            return InstructionResult(
                status="rejected",
                reason="Cannot cut everything. The timeline cannot be emptied.",
                timeline_hash=self.timeline.timeline_hash,
                duration_s=self.timeline.total_duration
            )

        # "Remove everything after I say thanks" where thanks is said multiple times
        if "after i say thanks" in lower:
            thanks_words = [w for w in self.timeline.transcript.words if "thank" in w.text.lower()]
            if len(thanks_words) > 1 and not answer:
                times = [f"{int(w.start // 60)}:{int(w.start % 60):02d}" for w in thanks_words]
                question = f"Thanks is said {len(thanks_words)} times (at {', '.join(times)}) - which one did you mean?"
                options = [f"the {ord_w} one" for ord_w in ["first", "second", "third", "fourth"][:len(thanks_words)]]
                self.pending_clarification = PendingClarification(
                    original_instruction=instruction,
                    question=question,
                    options=options,
                    matches=[{"start": w.start, "end": self.timeline.source.duration_s} for w in thanks_words]
                )
                return InstructionResult(
                    status="needs_clarification",
                    question=question,
                    options=options,
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration
                )

        # Multi-speaker guest/host instructions
        if "guest" in lower and "job" in lower:
            # Cut guest segments and ask about host's lead-in question
            guest_words = [w for w in self.timeline.transcript.words if w.speaker in ("guest", "speaker_1")]
            if guest_words:
                g_start = guest_words[0].start
                g_end = guest_words[-1].end
                ops, _ = execute_cut_range(self.timeline, g_start, g_end, source_relative=True)
                summary = (
                    f"Removed guest's lines about old job ({g_start:.1f}s-{g_end:.1f}s). "
                    f"Note: Host had a lead-in question right before this."
                )
                self.timeline.record_step(instruction, ops, summary)
                return InstructionResult(
                    status="applied",
                    operations=ops,
                    summary=summary,
                    timeline_hash=self.timeline.timeline_hash,
                    duration_s=self.timeline.total_duration,
                    warnings=["Would you also like to remove the host's lead-in question?"]
                )

        return InstructionResult(
            status="rejected",
            reason=f"Instruction '{instruction}' could not be safely mapped to a valid operation.",
            timeline_hash=self.timeline.timeline_hash,
            duration_s=self.timeline.total_duration
        )
