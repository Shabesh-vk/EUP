"""
Natural Language Understanding and instruction dispatcher.
Translates plain language prompt text into structured operations while managing ambiguity and clarifications:
- Repeated keyword occurrences (e.g., 'pricing' at 1:05, 2:40, 3:15, or 'thanks' uttered 4 times)
- Multi-speaker dialogue ambiguity (e.g., guest comments on old job preceded by host lead-in question)
- Text not found in transcript (rejected with clear message)
- Durations exceeding video length (rejected with clear message)
"""

from __future__ import annotations
import re
from typing import Optional, Tuple, Dict, Any, List
from core.schema import Timeline, TranscriptWord
from core.engine import TimelineEngine, EngineResponse
from core.operations import (
    BaseOperation,
    CutRangeOperation,
    KeepRangeOperation,
    SpeedRangeOperation,
    AddCaptionOperation,
    EditCaptionOperation,
    AutoCaptionOperation,
    MuteWordsOperation,
    BleepWordsOperation,
    RemoveFillerWordsOperation,
    RemoveSilenceOperation,
    AddMusicOperation,
    UndoOperation,
    RedoOperation,
    RestoreTransactionOperation,
)
from core.time_ticks import parse_time_expression, format_ticks_to_clock, seconds_to_ticks, ticks_to_seconds
from nlu.llm_adapter import get_llm_adapter


def process_instruction(
    engine: TimelineEngine,
    instruction: str,
    pending_context: Optional[Dict[str, Any]] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[EngineResponse, Optional[Dict[str, Any]]]:
    """
    Process a user instruction against the timeline engine.
    Returns (EngineResponse, updated_pending_context).
    """
    text = instruction.strip()
    lower = text.lower()

    # 1. Check if this is a reply resolving a pending clarification
    if pending_context:
        # A. Resolving repeated keyword ambiguity
        if pending_context.get("type") == "disambiguate_keyword":
            matches: List[TranscriptWord] = pending_context.get("matches", [])
            keyword = pending_context.get("keyword", "item")

            choice_idx = None
            if "first" in lower or "1" in lower:
                choice_idx = 0
            elif "second" in lower or "2" in lower:
                choice_idx = 1
            elif "third" in lower or "3" in lower:
                choice_idx = 2
            elif "fourth" in lower or "4" in lower:
                choice_idx = 3
            elif "all" in lower:
                choice_idx = -1

            if choice_idx is not None and choice_idx != -1 and choice_idx < len(matches):
                target_word = matches[choice_idx]
                s_start = max(0, target_word.start_ticks - 500)
                s_end = min(engine.timeline.source_media.duration_ticks, target_word.end_ticks + 2500)

                out_start = engine.project_source_to_output(s_start)
                out_end = engine.project_source_to_output(s_end)

                if out_start is None or out_end is None:
                    return (
                        EngineResponse(
                            status="rejected",
                            summary=f"Selected {keyword} occurrence is already cut.",
                            timeline_hash=engine.timeline.timeline_hash,
                            duration_s=engine.timeline.total_duration_seconds,
                        ),
                        None,
                    )

                op = CutRangeOperation(start_ticks=out_start, end_ticks=out_end)
                res = engine.dispatch_operation(op, instruction=f"Remove {keyword} ({text})")
                return res, None

            elif choice_idx == -1:
                # Cut all occurrences
                ops: List[BaseOperation] = []
                for target_word in matches:
                    s_start = max(0, target_word.start_ticks - 500)
                    s_end = min(engine.timeline.source_media.duration_ticks, target_word.end_ticks + 2500)
                    out_start = engine.project_source_to_output(s_start)
                    out_end = engine.project_source_to_output(s_end)
                    if out_start is not None and out_end is not None:
                        ops.append(CutRangeOperation(start_ticks=out_start, end_ticks=out_end))

                res = engine.apply_multipart_operations(ops, instruction=f"Remove all parts about {keyword}")
                return res, None

        # B. Resolving multi-speaker dialogue lead-in ambiguity
        if pending_context.get("type") == "speaker_lead_in":
            guest_span = pending_context["guest_span"]
            host_span = pending_context["host_span"]
            topic = pending_context.get("topic", "topic")

            if "cancel" in lower or "3" in lower:
                return (
                    EngineResponse(
                        status="rejected",
                        summary="Edit cancelled by user.",
                        timeline_hash=engine.timeline.timeline_hash,
                        duration_s=engine.timeline.total_duration_seconds,
                    ),
                    None,
                )

            if "2" in lower or "both" in lower:
                # Cut both host question and guest response
                s_start = host_span[0]
                s_end = guest_span[1]
                out_start = engine.project_source_to_output(s_start)
                out_end = engine.project_source_to_output(s_end)
                if out_start is None or out_end is None:
                    return (
                        EngineResponse(
                            status="rejected",
                            summary="Target section is already cut.",
                            timeline_hash=engine.timeline.timeline_hash,
                            duration_s=engine.timeline.total_duration_seconds,
                        ),
                        None,
                    )
                op = CutRangeOperation(start_ticks=out_start, end_ticks=out_end)
                res = engine.dispatch_operation(op, instruction=f"Cut both host question and guest response about {topic}")
                res.summary = f"Cut both host question and guest response about {topic}: {res.summary}"
                return res, None

            if "1" in lower or "only" in lower or "guest" in lower or "keep" in lower:
                # Cut only guest response
                s_start = guest_span[0]
                s_end = guest_span[1]
                out_start = engine.project_source_to_output(s_start)
                out_end = engine.project_source_to_output(s_end)
                if out_start is None or out_end is None:
                    return (
                        EngineResponse(
                            status="rejected",
                            summary="Target section is already cut.",
                            timeline_hash=engine.timeline.timeline_hash,
                            duration_s=engine.timeline.total_duration_seconds,
                        ),
                        None,
                    )
                op = CutRangeOperation(start_ticks=out_start, end_ticks=out_end)
                res = engine.dispatch_operation(op, instruction=f"Cut guest response about {topic} (kept host question)")
                res.summary = f"Cut guest response about {topic} (kept host question): {res.summary}"
                return res, None

        # C. Resolving repeated cut confirmation
        if pending_context.get("type") == "repeat_cut_confirmation":
            if "yes" in lower or "cut" in lower or "1" in lower:
                dur_ticks = pending_context.get("duration_ticks", 30000)
                op = CutRangeOperation(start_ticks=0, end_ticks=dur_ticks, time_domain="current_edited_time")
                res = engine.dispatch_operation(op, instruction=f"Cut another {ticks_to_seconds(dur_ticks)}s from current edited playback")
                return res, None
            else:
                return (
                    EngineResponse(
                        status="rejected",
                        summary="Repeated cut cancelled by user.",
                        timeline_hash=engine.timeline.timeline_hash,
                        duration_s=engine.timeline.total_duration_seconds,
                    ),
                    None,
                )

    # 1.5. Querying changes ("what did you change?", "show changes", "what was changed")
    if re.search(r"what\s+(?:did\s+you\s+change|was\s+changed|changes\s+were\s+made)|show\s+(?:edits|history|changes)", lower):
        if not engine.timeline.transactions:
            return (
                EngineResponse(
                    status="applied",
                    summary="No edits have been made yet. The project is at its original untouched state.",
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                None,
            )
        applied_txs = [t for t in engine.timeline.transactions if t.status == "applied"]
        tx_summaries = [f"#{i+1} [{t.operation_type}] {t.instruction}" for i, t in enumerate(applied_txs)]
        return (
            EngineResponse(
                status="applied",
                summary="Committed edits:\n" + "\n".join(tx_summaries),
                timeline_hash=engine.timeline.timeline_hash,
                duration_s=engine.timeline.total_duration_seconds,
            ),
            None,
        )

    # 2. Undo
    if lower == "undo" or lower.startswith("undo "):
        res = engine.dispatch_operation(UndoOperation(), instruction=text)
        return res, None

    # 3. Redo
    if lower == "redo" or lower.startswith("redo "):
        res = engine.dispatch_operation(RedoOperation(), instruction=text)
        return res, None

    # 4. Restore earlier edit: "put the intro back", "restore the intro", "put back the first 30 seconds", "restore transaction #1"
    m_restore = re.search(r"(?:put\s+(?:back\s+)?|restore\s+)(?:the\s+)?([a-z0-9\s#]+?)(?:\s+back)?$", lower)
    if "put" in lower or "restore" in lower or "put back" in lower or "bring that section back" in lower:
        target_desc = m_restore.group(1) if m_restore else text
        res = engine.dispatch_operation(RestoreTransactionOperation(description=target_desc), instruction=text)
        return res, None

    # 4.5. Automatic captioning paraphrases
    # "Add captions to the video", "Subtitle the whole clip", "Show the spoken words as captions", "Can you caption everything?", "auto caption"
    has_quoted_text = bool(re.search(r"['\"][^'\"]+['\"]", lower))
    has_explicit_at = bool(re.search(r"\bat\s+[0-9:]+", lower))
    auto_cap_patterns = [
        r"^(?:add\s+)?captions?(?:\s+to\s+(?:the\s+)?video)?$",
        r"^(?:can\s+you\s+)?(?:subtitle|caption)\s+(?:the\s+whole\s+clip|everything|the\s+video|all)$",
        r"^show\s+(?:the\s+)?spoken\s+words\s+as\s+captions$",
        r"^(?:auto\s*caption|auto\s*subtitles?|generate\s+captions?)$",
        r"^(?:add\s+)?subtitles?(?:\s+to\s+(?:the\s+)?video)?$",
        r"(?:can\s+you\s+)?transcribe\s+(?:and\s+)?(?:add\s+)?(?:captions?|subtitles?)",
        r"captions?\s+to\s+the\s+video",
    ]
    if not has_quoted_text and not has_explicit_at and any(re.search(pat, lower) for pat in auto_cap_patterns):
        op = AutoCaptionOperation(color="white", font_size=36, position="bottom")
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    # 4.6. Caption modification follow-ups (font size & color):
    # "Make them bigger", "Make it bigger", "Make that caption bigger", "Make them smaller"
    m_bigger = re.search(r"(?:make\s+(?:them|it|that|captions?)\s+|increase\s+(?:the\s+)?(?:caption\s+)?font\s+size\s+by\s+)?(bigger|larger|smaller)", lower)
    if (m_bigger and any(w in lower for w in ("them", "it", "that", "caption", "captions", "font", "bigger", "smaller", "larger"))) or "make them bigger" in lower or "make it bigger" in lower:
        target = "them" if "them" in lower or "captions" in lower else None
        delta = 8 if (not m_bigger or m_bigger.group(1) in ("bigger", "larger")) else -6
        op = EditCaptionOperation(target=target, font_size_delta=delta)
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    # Caption color changes: "Now change it to red", "Make them yellow", "Change them to yellow", "Change caption to blue"
    m_color = re.search(r"(?:(?:make|change)\s+(?:them|it|that|captions?)\s+(?:to\s+)?|color\s+(?:to\s+)?)(red|yellow|blue|green|white|black|cyan|magenta)", lower)
    if m_color:
        color = m_color.group(1)
        target = "them" if "them" in lower or "captions" in lower else None
        op = EditCaptionOperation(target=target, color=color)
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    # 5. Custom captioning: "Add a caption '...' when I say ..." or "add caption '...'"
    m_cap = re.search(r"caption\s+['\"]([^'\"]+)['\"](?:\s+when\s+I\s+say\s+([a-z0-9\s]+))?", text, re.IGNORECASE)
    if m_cap:
        caption_text = m_cap.group(1)
        target_phrase = m_cap.group(2)
        anchor_ids: List[str] = []

        if target_phrase:
            words = target_phrase.strip().lower().split()
            matched_words = []
            transcript_words = engine.timeline.transcript.words
            for i in range(len(transcript_words) - len(words) + 1):
                slice_words = [transcript_words[i + k].word.strip().lower() for k in range(len(words))]
                if slice_words == words:
                    matched_words = transcript_words[i : i + len(words)]
                    break
            if matched_words:
                anchor_ids = [w.id for w in matched_words]

        # If no specific phrase matched, anchor to first active words or output start
        if not anchor_ids:
            for w in engine.timeline.transcript.words:
                if engine.project_source_to_output(w.start_ticks) is not None:
                    anchor_ids.append(w.id)
                    if len(anchor_ids) >= 4:
                        break

        op = AddCaptionOperation(text=caption_text, anchor_word_ids=anchor_ids)
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    # 6. Edit caption: "Make that caption red", "make caption blue", "make it red"
    m_color = re.search(r"make\s+(?:that\s+)?caption\s+([a-z]+)", lower) or re.search(r"make\s+it\s+([a-z]+)", lower)
    if m_color:
        color = m_color.group(1)
        if color in ("red", "blue", "yellow", "green", "white", "black"):
            op = EditCaptionOperation(color=color)
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

    # 7. Speed adjustment: "Speed up from 1:00 to 1:30 by 2x" or "speed up 10-20 by 2x"
    m_speed = re.search(r"speed\s+up\s+(?:from\s+)?([0-9:apm\s]+?)\s+to\s+([0-9:apm\s]+?)\s+by\s+([0-9]+(?:\.[0-9]+)?x?)", lower)
    if m_speed:
        t1_str = m_speed.group(1).strip()
        t2_str = m_speed.group(2).strip()
        ratio_str = m_speed.group(3).replace("x", "").strip()

        t1 = parse_time_expression(t1_str, engine.timeline.total_duration_ticks)
        t2 = parse_time_expression(t2_str, engine.timeline.total_duration_ticks)
        speed_ratio = float(ratio_str)

        if speed_ratio > 8.0:
            return (
                EngineResponse(
                    status="rejected",
                    summary=f"Speed {speed_ratio}x exceeds maximum supported limit of 8x.",
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                None,
            )
        if speed_ratio < 0.25:
            return (
                EngineResponse(
                    status="rejected",
                    summary=f"Speed {speed_ratio}x is below minimum supported limit of 0.25x.",
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                None,
            )

        if t1 is not None and t2 is not None:
            op = SpeedRangeOperation(start_ticks=t1, end_ticks=t2, speed_ratio=speed_ratio)
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

    # 8. Multi-speaker dialogue handling: "Remove what the guest said about their old job"
    m_speaker_topic = re.search(r"(?:remove|cut)\s+(?:everything\s+)?(?:what\s+)?(?:the\s+)?(guest|host)\s+(?:said|says|spoke)?\s*(?:about\s+)?(.+)", lower)
    if m_speaker_topic:
        target_speaker = m_speaker_topic.group(1).lower()
        topic_phrase = m_speaker_topic.group(2).strip()
        clean_words = [w for w in re.split(r"[^\w]+", topic_phrase) if w and w not in ("the", "their", "a", "an", "about", "his", "her")]

        # Check for words by target speaker matching topic
        speaker_words = [
            w for w in engine.timeline.transcript.words
            if w.speaker.lower() == target_speaker and any(cw in w.word.lower() for cw in clean_words)
        ]
        if speaker_words:
            guest_start = min(w.start_ticks for w in speaker_words)
            guest_end = max(w.end_ticks for w in speaker_words) + 1500
            # Look for host lead-in question right before guest start
            host_words = [
                w for w in engine.timeline.transcript.words
                if w.speaker.lower() != target_speaker and (guest_start - 6000) <= w.start_ticks < guest_start
            ]
            if host_words:
                host_start = min(w.start_ticks for w in host_words)
                host_end = max(w.end_ticks for w in host_words)
                host_text = " ".join(w.word for w in host_words)
                question = f"The {target_speaker}'s response about '{topic_phrase}' was preceded by the host's question ('{host_text.capitalize()}'). Would you like to:"
                options = [
                    f"Cut only the {target_speaker}'s response (keep the host's question)",
                    "Cut both the host's question and the guest's response",
                    "Cancel edit",
                ]
                return (
                    EngineResponse(
                        status="needs_clarification",
                        summary=f"Multi-speaker ambiguity: host introduced {target_speaker} topic '{topic_phrase}'.",
                        question=question,
                        options=options,
                        timeline_hash=engine.timeline.timeline_hash,
                        duration_s=engine.timeline.total_duration_seconds,
                    ),
                    {
                        "type": "speaker_lead_in",
                        "guest_span": (guest_start, guest_end),
                        "host_span": (host_start, host_end),
                        "topic": topic_phrase,
                    },
                )

    # 9. Cut time range: "Cut the first 30 seconds", "remove 0:30-0:40", "cut 10 to 20"
    m_cut_first = re.search(r"(?:cut|remove)\s+(?:the\s+)?first\s+([0-9]+(?:\.[0-9]+)?)\s*(s|sec|seconds|m|min|minutes)?", lower)
    if m_cut_first:
        val = float(m_cut_first.group(1))
        unit = m_cut_first.group(2) or ""
        sec = val * 60.0 if "m" in unit else val
        cut_ticks = seconds_to_ticks(sec)
        if cut_ticks > engine.timeline.total_duration_ticks:
            return (
                EngineResponse(
                    status="rejected",
                    summary=f"Specified duration {sec}s exceeds video duration {engine.timeline.total_duration_seconds}s.",
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                None,
            )

        # Disambiguate repeat destructive cuts: "Cut the first 30 seconds" when already cut
        prior_first_cut = next((t for t in engine.timeline.transactions if t.status == "applied" and ("first" in t.instruction.lower() or "intro" in t.instruction.lower())), None)
        if prior_first_cut:
            return (
                EngineResponse(
                    status="needs_clarification",
                    summary="The first section was already cut in an earlier edit.",
                    question=f"The first section was already cut in an earlier edit ('{prior_first_cut.instruction}'). Do you want to cut another {sec}s from current edited playback?",
                    options=[f"Yes, cut another {sec}s from current playback", "No, cancel this cut"],
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                {"type": "repeat_cut_confirmation", "duration_ticks": cut_ticks},
            )

        op = CutRangeOperation(start_ticks=0, end_ticks=cut_ticks)
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    m_cut_range = re.search(r"(?:cut|remove)\s+([0-9:]+s?)\s*(?:-|to)\s*([0-9:]+s?)", lower)
    if m_cut_range:
        t1 = parse_time_expression(m_cut_range.group(1), engine.timeline.total_duration_ticks)
        t2 = parse_time_expression(m_cut_range.group(2), engine.timeline.total_duration_ticks)
        if t1 is not None and t2 is not None:
            if t2 > engine.timeline.total_duration_ticks:
                return (
                    EngineResponse(
                        status="rejected",
                        summary=f"Specified end time {ticks_to_seconds(t2)}s exceeds video duration {engine.timeline.total_duration_seconds}s.",
                        timeline_hash=engine.timeline.timeline_hash,
                        duration_s=engine.timeline.total_duration_seconds,
                    ),
                    None,
                )

            if t1 == 0:
                prior_first_cut = next((t for t in engine.timeline.transactions if t.status == "applied" and ("first" in t.instruction.lower() or "intro" in t.instruction.lower() or "0" in t.instruction.lower())), None)
                if prior_first_cut:
                    sec = ticks_to_seconds(t2)
                    return (
                        EngineResponse(
                            status="needs_clarification",
                            summary="The first section was already cut in an earlier edit.",
                            question=f"The first section was already cut in an earlier edit ('{prior_first_cut.instruction}'). Do you want to cut another {sec}s from current edited playback?",
                            options=["Yes, cut from current playback", "No, cancel this cut"],
                            timeline_hash=engine.timeline.timeline_hash,
                            duration_s=engine.timeline.total_duration_seconds,
                        ),
                        {"type": "repeat_cut_confirmation", "duration_ticks": t2},
                    )

            op = CutRangeOperation(start_ticks=t1, end_ticks=t2)
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

    # 10. Filler removal: "Remove the ums and uhs" / "remove filler words"
    if re.search(r"\b(filler|fillers|um|ums|uh|uhs)\b", lower):
        op = RemoveFillerWordsOperation(target_fillers=["um", "uh", "like"])
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    # 11. Silence removal: "Remove silences" / "cut pauses"
    if re.search(r"\b(silence|silences|pause|pauses)\b", lower):
        op = RemoveSilenceOperation(min_duration_ticks=1500)
        res = engine.dispatch_operation(op, instruction=text)
        return res, None

    # 12. Disambiguation / Keyword searches: "Remove the part about pricing" / "Remove pricing" / "cut thanks"
    m_keyword = re.search(r"(?:remove|cut)\s+(?:everything\s+after\s+I\s+say\s+|the\s+part\s+about\s+)?([a-z0-9\s]+)", lower)
    if m_keyword:
        raw_kw = m_keyword.group(1).strip()
        keyword = re.sub(r"^(?:the\s+part\s+about\s+|everything\s+after\s+i\s+say\s+)", "", raw_kw).strip()
        synonyms = [keyword]
        if keyword in ("pricing", "price"):
            synonyms.extend(["cost", "pricing", "plans"])

        clean_search = [w for w in re.split(r"\s+", keyword) if w and w not in ("the", "a", "an", "part", "about")]
        matches = [
            w for w in engine.timeline.transcript.words
            if any(syn in w.word.lower() for syn in synonyms) or any(cw == w.word.lower() for cw in clean_search)
        ]

        if not matches:
            return (
                EngineResponse(
                    status="rejected",
                    summary=f"Target text '{keyword}' was not found in the transcript.",
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                None,
            )

        if len(matches) > 1:
            options = [format_ticks_to_clock(w.start_ticks) for w in matches] + ["All"]
            times_str = ", ".join(options[:-2]) + f" and {options[-2]}" if len(options) > 2 else options[0]
            question = f"{keyword.capitalize()} is mentioned at {times_str} - which one, or all?"
            return (
                EngineResponse(
                    status="needs_clarification",
                    summary=f"{keyword.capitalize()} is mentioned multiple times.",
                    question=question,
                    options=options,
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                {"type": "disambiguate_keyword", "keyword": keyword, "matches": matches},
            )
        elif len(matches) == 1:
            target_w = matches[0]
            s_start = max(0, target_w.start_ticks - 500)
            s_end = min(engine.timeline.source_media.duration_ticks, target_w.end_ticks + 2500)
            out_start = engine.project_source_to_output(s_start)
            out_end = engine.project_source_to_output(s_end)
            if out_start is not None and out_end is not None:
                op = CutRangeOperation(start_ticks=out_start, end_ticks=out_end)
                res = engine.dispatch_operation(op, instruction=text)
                return res, None

    # 13. Pass to configured LLM adapter for natural language intent proposals
    try:
        adapter = get_llm_adapter()

        # Build authoritative video editing context
        timeline_summary = {
            "duration_seconds": engine.timeline.total_duration_seconds,
            "timeline_hash": engine.timeline.timeline_hash,
            "clip_count": len(engine.timeline.segments),
            "clips": [
                {
                    "segment_id": s.segment_id,
                    "source_start": s.source_start_ticks / 1000,
                    "source_end": s.source_end_ticks / 1000,
                    "speed": s.speed_ratio,
                }
                for s in engine.timeline.segments[:6]
            ],
            "captions": [
                {
                    "id": c.id,
                    "group_id": c.group_id,
                    "text": c.text,
                    "color": c.color,
                    "font_size": c.font_size,
                    "position": c.position,
                }
                for c in (engine.timeline.effects.captions or [])
                if not c.is_suppressed
            ],
            "recent_transactions": [
                {
                    "tx_id": t.id,
                    "operation": t.operation_type,
                    "instruction": t.instruction,
                    "step": t.applied_at_step,
                }
                for t in engine.timeline.transactions[-4:]
            ],
        }

        full_context = {
            "timeline": timeline_summary,
            "pending_clarification": pending_context,
            "recent_dialogue": (chat_history or [])[-4:],
        }

        proposal = adapter.parse_instruction(text, conversation_context=full_context)

        if proposal.intent_type == "add_automatic_captions":
            op = AutoCaptionOperation(color="white", font_size=36, position="bottom")
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "add_custom_caption":
            cap_text = proposal.parameters.get("text") or text
            start_s = proposal.parameters.get("start")
            end_s = proposal.parameters.get("end")
            start_ticks = int(float(start_s) * 1000) if start_s is not None else 0
            end_ticks = int(float(end_s) * 1000) if end_s is not None else 3000
            op = AddCaptionOperation(
                text=cap_text,
                source_start_ticks=start_ticks,
                source_end_ticks=end_ticks,
                color=proposal.parameters.get("color", "white"),
                font_size=int(proposal.parameters.get("font_size", 36)),
                position=proposal.parameters.get("position", "bottom"),
            )
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "edit_caption":
            op = EditCaptionOperation(
                target=proposal.parameters.get("target"),
                color=proposal.parameters.get("color"),
                font_size=proposal.parameters.get("font_size"),
                font_size_delta=proposal.parameters.get("font_size_delta"),
                position=proposal.parameters.get("position"),
            )
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "cut_range":
            start_s = proposal.parameters.get("start")
            end_s = proposal.parameters.get("end")
            target_name = proposal.parameters.get("target_name")
            if target_name == "intro" and (start_s is None or end_s is None):
                start_ticks = 0
                end_ticks = 30000
            else:
                try:
                    start_ticks = parse_time_expression(str(start_s), engine.timeline.timebase) if start_s else 0
                    end_ticks = parse_time_expression(str(end_s), engine.timeline.timebase) if end_s else 30000
                except Exception:
                    start_ticks = 0
                    end_ticks = 30000
            op = CutRangeOperation(start_ticks=start_ticks, end_ticks=end_ticks, time_domain="current_edited_time")
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "speed_range":
            speed_ratio = float(proposal.parameters.get("speed_ratio", 1.5))
            start_s = proposal.parameters.get("start")
            end_s = proposal.parameters.get("end")
            start_ticks = int(float(start_s) * 1000) if start_s is not None else 0
            end_ticks = int(float(end_s) * 1000) if end_s is not None else engine.timeline.source_media.duration_ticks
            op = SpeedRangeOperation(
                start_ticks=start_ticks,
                end_ticks=end_ticks,
                speed_ratio=speed_ratio,
                time_domain="current_edited_time",
            )
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "undo":
            res = engine.dispatch_operation(UndoOperation(), instruction=text)
            return res, None

        elif proposal.intent_type == "redo":
            res = engine.dispatch_operation(RedoOperation(), instruction=text)
            return res, None

        elif proposal.intent_type == "restore_transaction":
            target_desc = proposal.parameters.get("target") or text
            res = engine.dispatch_operation(RestoreTransactionOperation(description=target_desc), instruction=text)
            return res, None

        elif proposal.intent_type == "remove_filler_words":
            op = RemoveFillerWordsOperation(target_fillers=["um", "uh", "like"])
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "remove_silence":
            min_dur = float(proposal.parameters.get("min_duration_s", 1.5)) * 1000
            op = RemoveSilenceOperation(min_duration_ticks=int(min_dur))
            res = engine.dispatch_operation(op, instruction=text)
            return res, None

        elif proposal.intent_type == "query_change":
            applied_txs = [t for t in engine.timeline.transactions if t.status == "applied"]
            if not applied_txs:
                summary_text = "No edits have been committed yet to this timeline."
            else:
                summary_items = [f"Step {t.applied_at_step}: {t.instruction} ({t.operation_type})" for t in applied_txs[-5:]]
                summary_text = "Recent timeline edits:\n• " + "\n• ".join(summary_items)
            return (
                EngineResponse(
                    status="success",
                    summary=summary_text,
                    timeline_hash=engine.timeline.timeline_hash,
                    duration_s=engine.timeline.total_duration_seconds,
                ),
                None,
            )

    except Exception as e:
        # If real inference fails, report the actual provider error clearly
        return (
            EngineResponse(
                status="rejected",
                summary=f"Model inference error: {str(e)}",
                timeline_hash=engine.timeline.timeline_hash,
                duration_s=engine.timeline.total_duration_seconds,
            ),
            None,
        )

    # Fallback rejection for completely unrecognized commands
    return (
        EngineResponse(
            status="rejected",
            summary=f"Unrecognized instruction: '{text}'.",
            timeline_hash=engine.timeline.timeline_hash,
            duration_s=engine.timeline.total_duration_seconds,
        ),
        None,
    )
