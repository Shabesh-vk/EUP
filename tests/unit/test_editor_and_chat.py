"""
Comprehensive unit and integration tests for:
1. Real NLU & Auto-captioning paraphrases ("add captions to the video", etc.)
2. Multi-turn conversational caption follow-ups ("make them bigger", "change them to yellow")
3. Multi-level Undo/Redo preserving independent caption attributes
4. No-caption fallback prompt
5. Repeated cut disambiguation
6. Auto Edit Plan generation (non-destructive) and atomic execution
7. Stale Auto Edit plan rejection
8. SQLite chat persistence and project isolation
9. ASS subtitle font size (\\fs) generation
10. Selective restore with structured transaction IDs
"""

import pytest
import os
import tempfile
from core.schema import (
    Timeline,
    CaptionEffect,
)
from core.time_ticks import seconds_to_ticks
from core.engine import TimelineEngine
from nlu.dispatcher import process_instruction
from media.ass_generator import generate_ass_subtitles
from tests.fixtures.transcript_fixtures import create_test_timeline
from db.database import DatabaseManager


def test_ass_subtitle_font_size_formatting():
    tl = create_test_timeline(duration_seconds=100.0)
    tl.effects.captions = [
        CaptionEffect(
            id="cap_test",
            text="Big Green Subtitle",
            source_start_ticks=0,
            source_end_ticks=seconds_to_ticks(5.0),
            color="#00FF00",
            font_size=52,
            position="bottom",
        )
    ]

    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
        out_path = f.name

    try:
        generate_ass_subtitles(tl, out_path)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check font size \fs52 and BGR color in override tags
        assert r"\fs52" in content
        assert "Big Green Subtitle" in content
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)


def test_sqlite_chat_persistence_and_isolation(tmp_path):
    db_file = tmp_path / "test_chat.db"
    db = DatabaseManager(db_path=str(db_file))

    # Project 1 messages
    db.save_chat_message("proj_1", "user", "Hello project 1")
    db.save_chat_message("proj_1", "assistant", "Hi there!", metadata={"status": "applied"})

    # Project 2 messages
    db.save_chat_message("proj_2", "user", "Hello project 2")

    # Verify Project 1 isolation
    hist1 = db.get_chat_history("proj_1")
    assert len(hist1) == 2
    assert hist1[0]["role"] == "user"
    assert hist1[0]["content"] == "Hello project 1"
    assert hist1[1]["role"] == "assistant"
    assert hist1[1]["metadata"]["status"] == "applied"

    # Verify Project 2 isolation
    hist2 = db.get_chat_history("proj_2")
    assert len(hist2) == 1
    assert hist2[0]["content"] == "Hello project 2"

    # Verify conversation context persistence
    db.save_conversation_context("proj_1", {"last_cut": "0-5s", "topic": "captions"})
    ctx = db.get_conversation_context("proj_1")
    assert ctx["last_cut"] == "0-5s"
    assert ctx["topic"] == "captions"


def test_nlu_add_captions_paraphrases():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    paraphrases = [
        "add captions to the video",
        "subtitle the whole clip",
        "show the spoken words as captions",
        "can you transcribe and add subtitles",
    ]

    for phrase in paraphrases:
        res, _ = process_instruction(engine, phrase)
        assert res.status == "applied", f"Failed for phrase: '{phrase}'"
        assert "captions" in res.summary.lower()
        assert len(engine.timeline.effects.captions) > 0
        # Check that group_id is 'captions_main'
        for cap in engine.timeline.effects.captions:
            assert cap.group_id == "captions_main"
            assert cap.font_size == 36
        # Revert for next test
        engine.history.undo()


def test_distinguish_auto_caption_from_custom_overlay():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    res, _ = process_instruction(engine, "caption 'Special Offer' at 5s to 10s")
    assert res.status == "applied"
    assert len(engine.timeline.effects.captions) == 1
    assert engine.timeline.effects.captions[0].text == "Special Offer"
    assert engine.timeline.effects.captions[0].group_id is None


def test_multiturn_caption_group_sizing_and_coloring():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    # Step 1: Add captions
    res1, ctx1 = process_instruction(engine, "add captions to the video")
    assert res1.status == "applied"
    initial_font_size = engine.timeline.effects.captions[0].font_size
    assert initial_font_size == 36

    # Step 2: "make them bigger"
    res2, ctx2 = process_instruction(engine, "make them bigger", pending_context=ctx1)
    assert res2.status == "applied"
    for cap in engine.timeline.effects.captions:
        assert cap.font_size == 44, "Expected font size delta of +8 (36 -> 44)"

    # Step 3: "change them to yellow"
    res3, ctx3 = process_instruction(engine, "change them to yellow", pending_context=ctx2)
    assert res3.status == "applied"
    for cap in engine.timeline.effects.captions:
        assert cap.color == "yellow"
        assert cap.font_size == 44

    # Step 4: Undo color change
    undo1 = engine.history.undo()
    assert undo1 is not None
    for cap in engine.timeline.effects.captions:
        assert cap.color == "white", "Color should have reverted to white"
        assert cap.font_size == 44, "Font size should still be 44"

    # Step 5: Undo size change
    undo2 = engine.history.undo()
    assert undo2 is not None
    for cap in engine.timeline.effects.captions:
        assert cap.font_size == 36, "Font size should have reverted to 36"


def test_no_caption_fallback_prompt():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    res, _ = process_instruction(engine, "make them bigger")
    assert res.status == "rejected"
    assert "No active caption exists" in res.summary
    assert "Would you like to add automatic captions" in res.summary


def test_repeated_cut_disambiguation():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    # First cut: cut 0s to 5s
    res1, ctx1 = process_instruction(engine, "cut 0s to 5s")
    assert res1.status == "applied"
    assert engine.timeline.total_duration_seconds < 100.0

    # Second cut with the same wording
    res2, ctx2 = process_instruction(engine, "cut 0s to 5s", pending_context=ctx1)
    assert res2.status == "needs_clarification"
    assert "already cut in an earlier edit" in res2.question
    assert "Yes, cut from current playback" in res2.options


def test_auto_edit_plan_non_destructive():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    initial_hash = tl.timeline_hash
    initial_dur = tl.total_duration_seconds

    # Generate plan
    plan = engine.generate_auto_edit_plan()
    assert len(plan.items) >= 2  # silences, fillers, or captions
    assert plan.base_timeline_hash == initial_hash

    # Verify zero mutations
    assert tl.timeline_hash == initial_hash
    assert tl.total_duration_seconds == initial_dur
    assert len(tl.effects.captions) == 0


def test_auto_edit_plan_atomic_apply_and_undo():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    plan = engine.generate_auto_edit_plan()

    # Apply all items
    res = engine.apply_auto_edit_plan(plan, excluded_item_ids=[])
    assert res.status == "applied"
    assert "clean up" in res.summary.lower()
    assert engine.timeline.total_duration_seconds < 100.0
    assert len(engine.timeline.effects.captions) > 0

    # Verify single transaction in history
    assert len(engine.history.transactions) == 1
    assert engine.history.transactions[0].operation_type == "auto_edit_cleanup"

    # Revert with single undo
    undo_res = engine.history.undo()
    assert undo_res is not None
    assert engine.timeline.total_duration_seconds == 100.0
    assert len(engine.timeline.effects.captions) == 0


def test_stale_auto_edit_plan_rejection():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    # Generate plan at initial state
    plan = engine.generate_auto_edit_plan()

    # Make an intermediate cut
    engine.apply_cut(0, seconds_to_ticks(2.0))

    # Now attempt to apply the stale plan
    res = engine.apply_auto_edit_plan(plan, excluded_item_ids=[])
    assert res.status == "rejected"
    assert "stale" in res.summary.lower()


def test_selective_restore_by_transaction_id():
    tl = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(tl)

    # 3 distinct operations
    r1 = engine.apply_cut(0, seconds_to_ticks(5.0))
    tx1_id = engine.history.transactions[-1].id

    r2 = engine.apply_auto_caption()
    tx2_id = engine.history.transactions[-1].id

    r3 = engine.apply_cut(seconds_to_ticks(10.0), seconds_to_ticks(15.0))
    tx3_id = engine.history.transactions[-1].id

    assert len(engine.history.transactions) == 3

    # Selective restore to tx1 puts the 0-5s cut back without undoing later edits
    restore_res = engine.selective_restore(tx1_id)
    assert restore_res.status == "applied"
    assert "restored content" in restore_res.summary.lower()
    # 0-5s is restored, 10-15s remains cut -> total duration is 95s
    assert engine.timeline.total_duration_seconds == 95.0
    # Later captions from tx2 are preserved
    assert len(engine.timeline.effects.captions) > 0


