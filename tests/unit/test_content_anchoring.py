"""
Unit tests for content-anchoring, coordinate projection, effect suppression, and restoration.
"""

from core.engine import TimelineEngine
from core.operations import (
    AddCaptionOperation,
    CutRangeOperation,
    SpeedRangeOperation,
    UndoOperation,
)
from tests.fixtures.transcript_fixtures import create_test_timeline


def test_caption_anchoring_shifts_correctly():
    """
    Core Rule:
    A caption added on words at 0:42-0:44 must play at 0:12-0:14 after cutting the first 30 seconds.
    """
    timeline = create_test_timeline(duration_seconds=300.0)
    engine = TimelineEngine(timeline)

    # 1. Add caption anchored to "welcome to the channel" (w_016, w_017, w_018, w_019)
    res_cap = engine.dispatch_operation(
        AddCaptionOperation(
            text="Welcome!",
            anchor_word_ids=["w_016", "w_017", "w_018", "w_019"],
        )
    )
    assert res_cap.status == "applied"
    cap = timeline.effects.captions[0]
    assert cap.source_start_ticks == 42000
    assert cap.source_end_ticks == 44000

    # Before cut: output time is 42s - 44s
    out_start_before = engine.project_source_to_output(cap.source_start_ticks)
    out_end_before = engine.project_source_to_output(cap.source_end_ticks)
    assert out_start_before == 42000
    assert out_end_before == 44000

    # 2. Cut the first 30 seconds (0 to 30,000ms)
    res_cut = engine.dispatch_operation(CutRangeOperation(start_ticks=0, end_ticks=30000))
    assert res_cut.status == "applied"

    # After cut: output time is now 12s - 14s (12,000ms - 14,000ms)
    out_start_after = engine.project_source_to_output(cap.source_start_ticks)
    out_end_after = engine.project_source_to_output(cap.source_end_ticks)
    assert out_start_after == 12000
    assert out_end_after == 14000
    # Still anchored to exactly the same words and same source coordinates
    assert cap.anchor_word_ids == ["w_016", "w_017", "w_018", "w_019"]
    assert cap.source_start_ticks == 42000
    assert cap.source_end_ticks == 44000
    assert not cap.is_suppressed


def test_caption_suppression_and_reactivation_on_restore():
    """
    When a sentence under a caption is cut, the caption is suppressed.
    When that cut is undone or restored, the caption returns.
    """
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Add caption at 42s-44s
    engine.dispatch_operation(
        AddCaptionOperation(
            text="Welcome!",
            anchor_word_ids=["w_016", "w_017", "w_018", "w_019"],
        )
    )
    cap = timeline.effects.captions[0]

    # Cut 40s to 45s (contains the entire caption)
    res_cut = engine.dispatch_operation(CutRangeOperation(start_ticks=40000, end_ticks=45000))
    assert res_cut.status == "applied"
    assert cap.is_suppressed
    assert any("suppressed" in w for w in res_cut.warnings)

    # Undo the cut -> Caption must be reactivated
    res_undo = engine.dispatch_operation(UndoOperation())
    assert res_undo.status == "applied"
    assert not cap.is_suppressed
    assert any("reactivated" in w for w in res_undo.warnings)


def test_partial_cut_of_captioned_phrase():
    """
    Cutting part of a captioned phrase shrinks the anchor to surviving words.
    """
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Caption anchored to w_016 ("welcome" 42.0-42.5), w_017 ("to" 42.5-42.7), w_018 ("the" 42.7-42.9), w_019 ("channel" 42.9-44.0)
    engine.dispatch_operation(
        AddCaptionOperation(
            text="Welcome!",
            anchor_word_ids=["w_016", "w_017", "w_018", "w_019"],
        )
    )
    cap = timeline.effects.captions[0]

    # Cut 42.5s to 42.9s (cuts "to" and "the")
    res_cut = engine.dispatch_operation(CutRangeOperation(start_ticks=42500, end_ticks=42900))
    assert res_cut.status == "applied"
    assert not cap.is_suppressed
    assert cap.anchor_word_ids == ["w_016", "w_019"]
    assert any("shortened to 2 surviving words" in w for w in res_cut.warnings)


def test_readable_caption_minimum_duration():
    """
    Sped-up captions enforce a readable minimum duration of ~0.7s.
    """
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Add short caption of 1.0s (40s - 41s)
    engine.dispatch_operation(
        AddCaptionOperation(
            text="Quick",
            source_start_ticks=40000,
            source_end_ticks=41000,
            min_duration_s=0.7,
        )
    )

    # Speed up 35s to 45s by 4x -> 1.0s speech shrinks to 0.25s
    res_speed = engine.dispatch_operation(SpeedRangeOperation(start_ticks=35000, end_ticks=45000, speed_ratio=4.0))
    assert res_speed.status == "applied"
    assert any("clamped to 0.7s minimum" in w for w in res_speed.warnings)
