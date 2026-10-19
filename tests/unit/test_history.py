"""
Unit tests for transactional history, linear undo/redo, redo clearance, and targeted selective restore.
"""

from core.engine import TimelineEngine
from core.operations import (
    CutRangeOperation,
    SpeedRangeOperation,
    AddMusicOperation,
    UndoOperation,
    RedoOperation,
    RestoreTransactionOperation,
)
from tests.fixtures.transcript_fixtures import create_test_timeline


def test_linear_undo_and_redo():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Cut 10s to 20s
    engine.dispatch_operation(CutRangeOperation(start_ticks=10000, end_ticks=20000))
    assert timeline.total_duration_seconds == 90.0

    # Undo
    res_undo = engine.dispatch_operation(UndoOperation())
    assert res_undo.status == "applied"
    assert timeline.total_duration_seconds == 100.0

    # Redo
    res_redo = engine.dispatch_operation(RedoOperation())
    assert res_redo.status == "applied"
    assert timeline.total_duration_seconds == 90.0


def test_new_edit_clears_redo():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Cut 10s to 20s
    engine.dispatch_operation(CutRangeOperation(start_ticks=10000, end_ticks=20000))
    # Undo
    engine.dispatch_operation(UndoOperation())
    assert len(engine.history.redo_stack) == 1

    # New edit: Cut 50s to 60s
    engine.dispatch_operation(CutRangeOperation(start_ticks=50000, end_ticks=60000))
    # Redo stack must be empty now
    assert len(engine.history.redo_stack) == 0

    res_redo = engine.dispatch_operation(RedoOperation())
    assert res_redo.status == "rejected"
    assert "Nothing to redo" in res_redo.summary


def test_targeted_selective_restore_retaining_later_edits():
    """
    Test targeted restore:
    1. Cut the first 30 seconds (intro).
    2. Cut 10s of pricing (e.g. at 50s-60s).
    3. Speed up 10s by 2x.
    4. Add background music.
    5. Put the intro back.
    -> The intro (first 30s) returns!
    -> The pricing cut remains cut!
    -> The speedup remains!
    -> The background music remains!
    """
    timeline = create_test_timeline(duration_seconds=200.0)
    engine = TimelineEngine(timeline)

    # Step 1: Cut first 30s (intro)
    res1 = engine.dispatch_operation(CutRangeOperation(start_ticks=0, end_ticks=30000), instruction="Cut the first 30 seconds")
    assert res1.status == "applied"
    assert timeline.total_duration_seconds == 170.0

    # Step 2: Cut pricing at 35s-45s (current time)
    res2 = engine.dispatch_operation(CutRangeOperation(start_ticks=35000, end_ticks=45000), instruction="Remove the part about pricing")
    assert res2.status == "applied"
    assert timeline.total_duration_seconds == 160.0

    # Step 3: Speed up 60s-80s by 2x
    res3 = engine.dispatch_operation(SpeedRangeOperation(start_ticks=60000, end_ticks=80000, speed_ratio=2.0), instruction="Speed up 60s-80s by 2x")
    assert res3.status == "applied"
    assert timeline.total_duration_seconds == 150.0

    # Step 4: Add music
    res4 = engine.dispatch_operation(AddMusicOperation(asset_url="https://assets.local/bg.mp3"), instruction="Add background music")
    assert res4.status == "applied"
    assert len(timeline.effects.music) == 1

    # Step 5: Restore the intro ("put the intro back")
    res5 = engine.dispatch_operation(RestoreTransactionOperation(description="intro"), instruction="Actually, put the intro back")
    assert res5.status == "applied"

    # Intro returned (+30s), so duration is 150 + 30 = 180s
    assert timeline.total_duration_seconds == 180.0
    # Music is still active
    assert len(timeline.effects.music) == 1
    # Check segments: the first segment starts at source 0
    assert timeline.segments[0].source_start_ticks == 0
    assert timeline.segments[0].source_end_ticks == 30000

    # Step 6: Undo reverses the restore!
    res6 = engine.dispatch_operation(UndoOperation(), instruction="Undo")
    assert res6.status == "applied"
    # Intro is cut again -> length returns to 150.0s
    assert timeline.total_duration_seconds == 150.0
    assert timeline.segments[0].source_start_ticks >= 30000
    assert len(timeline.effects.music) == 1
