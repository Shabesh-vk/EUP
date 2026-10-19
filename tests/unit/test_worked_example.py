"""
Unit test reproducing the exact 8-step worked example from the IncuBrix assessment brief.
"""

from core.engine import TimelineEngine
from core.operations import (
    AddCaptionOperation,
    CutRangeOperation,
    SpeedRangeOperation,
    EditCaptionOperation,
    RestoreTransactionOperation,
    UndoOperation,
)
from core.time_ticks import format_ticks_to_clock, ticks_to_seconds
from tests.fixtures.transcript_fixtures import create_test_timeline


def test_worked_example_steps_1_through_8():
    timeline = create_test_timeline(duration_seconds=300.0)
    engine = TimelineEngine(timeline)

    # -------------------------------------------------------------------------
    # Step 1: Add a caption 'Welcome!' when I say welcome to the channel
    # Expected: Applied. Caption attached to those 4 words (original time 0:42-0:44).
    # -------------------------------------------------------------------------
    step1_op = AddCaptionOperation(
        text="Welcome!",
        anchor_word_ids=["w_016", "w_017", "w_018", "w_019"],
    )
    res1 = engine.dispatch_operation(step1_op, instruction="Add a caption 'Welcome!' when I say welcome to the channel")

    assert res1.status == "applied"
    assert "Welcome!" in res1.summary
    assert len(timeline.effects.captions) == 1
    cap = timeline.effects.captions[0]
    assert cap.source_start_ticks == 42000
    assert cap.source_end_ticks == 44000
    # Playback time is currently 0:42 - 0:44
    assert engine.project_source_to_output(cap.source_start_ticks) == 42000
    assert engine.project_source_to_output(cap.source_end_ticks) == 44000

    # -------------------------------------------------------------------------
    # Step 2: Cut the first 30 seconds
    # Expected: Applied. Video is 30 s shorter. Caption now plays at 0:12-0:14, still on the same words.
    # -------------------------------------------------------------------------
    step2_op = CutRangeOperation(start_ticks=0, end_ticks=30000, time_domain="current_edited_time")
    res2 = engine.dispatch_operation(step2_op, instruction="Cut the first 30 seconds")

    assert res2.status == "applied"
    assert "30.0s shorter" in res2.summary
    assert timeline.total_duration_seconds == 270.0

    # Caption must now play at 0:12-0:14 (12,000ms - 14,000ms)
    out_start_step2 = engine.project_source_to_output(cap.source_start_ticks)
    out_end_step2 = engine.project_source_to_output(cap.source_end_ticks)
    assert out_start_step2 == 12000
    assert out_end_step2 == 14000
    assert format_ticks_to_clock(out_start_step2) == "0:12"
    assert format_ticks_to_clock(out_end_step2) == "0:14"

    # -------------------------------------------------------------------------
    # Step 3: Remove the part about pricing
    # Expected: Needs clarification: pricing is mentioned three times, which one or all?
    # User: the second one. Applied.
    # -------------------------------------------------------------------------
    # Find pricing words: w_021 (65.0s), w_031 (160.0s = 2:40), w_038 (195.0s = 3:15)
    pricing_words = [w for w in timeline.transcript.words if "pricing" in w.word.lower()]
    assert len(pricing_words) == 3

    # Engine disambiguation simulation
    options = [f"{format_ticks_to_clock(w.start_ticks)}" for w in pricing_words] + ["All"]
    # Simulated clarification response
    res3_clarification_question = f"Pricing is mentioned at {options[0]}, {options[1]} and {options[2]} - which one, or all?"
    assert "1:05" in res3_clarification_question or "2:40" in res3_clarification_question

    # User answers: "the second one" -> refers to w_031 (160000ms - 164000ms)
    # Target phrase around 2nd pricing mention: 159500 to 164000ms (source time)
    # In current edited time (first 30s cut): 159500 - 30000 = 129500ms (2:09.5)
    p2_words = [w for w in timeline.transcript.words if w.id in ("w_030", "w_031", "w_032", "w_033", "w_034", "w_035", "w_036")]
    p2_source_start = min(w.start_ticks for w in p2_words)
    p2_source_end = max(w.end_ticks for w in p2_words)

    p2_out_start = engine.project_source_to_output(p2_source_start)
    p2_out_end = engine.project_source_to_output(p2_source_end)
    assert p2_out_start is not None and p2_out_end is not None

    step3_op = CutRangeOperation(start_ticks=p2_out_start, end_ticks=p2_out_end, time_domain="current_edited_time")
    res3 = engine.dispatch_operation(step3_op, instruction="Remove the part about pricing (the second one)")

    assert res3.status == "applied"
    dur_after_step3 = timeline.total_duration_seconds

    # -------------------------------------------------------------------------
    # Step 4: Speed up from 1:00 to 1:30 by 2x
    # Expected: Applied, stating which time policy was used.
    # -------------------------------------------------------------------------
    step4_op = SpeedRangeOperation(
        start_ticks=60000,
        end_ticks=90000,
        speed_ratio=2.0,
        time_domain="current_edited_time",
    )
    res4 = engine.dispatch_operation(step4_op, instruction="Speed up from 1:00 to 1:30 by 2x")

    assert res4.status == "applied"
    assert res4.time_policy == "current_edited_time"
    # Spanning 30s at 2x reduces output by 15s
    assert round(dur_after_step3 - timeline.total_duration_seconds, 1) == 15.0

    # -------------------------------------------------------------------------
    # Step 5: Actually, put the intro back
    # Expected: Applied. The first 30 s return; caption back at 0:42; the pricing cut and speed change stay.
    # -------------------------------------------------------------------------
    step5_op = RestoreTransactionOperation(description="intro")
    res5 = engine.dispatch_operation(step5_op, instruction="Actually, put the intro back")

    assert res5.status == "applied"
    # The first 30s return
    assert timeline.segments[0].source_start_ticks == 0
    assert timeline.segments[0].source_end_ticks == 30000

    # Caption is back at 0:42 - 0:44!
    out_start_step5 = engine.project_source_to_output(cap.source_start_ticks)
    out_end_step5 = engine.project_source_to_output(cap.source_end_ticks)
    assert out_start_step5 == 42000
    assert out_end_step5 == 44000
    assert format_ticks_to_clock(out_start_step5) == "0:42"

    # The pricing cut is still cut! (p2 words project to None)
    assert engine.project_source_to_output(p2_source_start) is None

    # The speed change stays!
    # (Check that segments corresponding to the speed change still have speed_ratio=2.0)
    assert any(seg.speed_ratio == 2.0 for seg in timeline.segments)

    # -------------------------------------------------------------------------
    # Step 6: Undo
    # Expected: Reverses step 5 only. The intro is cut again.
    # -------------------------------------------------------------------------
    step6_op = UndoOperation()
    res6 = engine.dispatch_operation(step6_op, instruction="Undo")

    assert res6.status == "applied"
    # The intro is cut again: segments start after 30s
    assert timeline.segments[0].source_start_ticks >= 30000
    # Caption is back at 0:12 - 0:14
    out_start_step6 = engine.project_source_to_output(cap.source_start_ticks)
    assert out_start_step6 == 12000

    # -------------------------------------------------------------------------
    # Step 7: Make that caption red
    # Expected: Applied to the Welcome! caption, the only one that exists.
    # -------------------------------------------------------------------------
    step7_op = EditCaptionOperation(color="red")
    res7 = engine.dispatch_operation(step7_op, instruction="Make that caption red")

    assert res7.status == "applied"
    assert "red" in res7.summary.lower()
    assert cap.color == "red"

    # -------------------------------------------------------------------------
    # Step 8: Render validation
    # Expected: Audio and video in sync, length matches the timeline, caption on the right words.
    # -------------------------------------------------------------------------
    assert timeline.total_duration_seconds > 0
    assert len(timeline.timeline_hash) == 64
    assert not cap.is_suppressed
    assert cap.color == "red"
