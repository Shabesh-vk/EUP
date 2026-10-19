"""
Unit tests for determinism: 3 independent runs of an identical editing session
must produce 100% identical timeline_hash values.
"""

from core.engine import TimelineEngine
from core.operations import (
    AddCaptionOperation,
    CutRangeOperation,
    SpeedRangeOperation,
    EditCaptionOperation,
    AddMusicOperation,
    RestoreTransactionOperation,
    UndoOperation,
)
from tests.fixtures.transcript_fixtures import create_test_timeline


def run_session(project_id: str) -> str:
    """Execute a realistic multi-step session on a fresh timeline instance."""
    timeline = create_test_timeline(duration_seconds=300.0)
    timeline.project_id = project_id  # different project ID should not affect canonical semantic state
    engine = TimelineEngine(timeline)

    # 1. Add caption
    engine.dispatch_operation(
        AddCaptionOperation(
            text="Welcome!",
            anchor_word_ids=["w_016", "w_017", "w_018", "w_019"],
        ),
        instruction="Add a caption 'Welcome!' when I say welcome to the channel",
    )

    # 2. Cut first 30s
    engine.dispatch_operation(
        CutRangeOperation(start_ticks=0, end_ticks=30000),
        instruction="Cut the first 30 seconds",
    )

    # 3. Cut pricing at 35s-45s
    engine.dispatch_operation(
        CutRangeOperation(start_ticks=35000, end_ticks=45000),
        instruction="Remove the part about pricing",
    )

    # 4. Speed up 60s to 90s by 2x
    engine.dispatch_operation(
        SpeedRangeOperation(start_ticks=60000, end_ticks=90000, speed_ratio=2.0),
        instruction="Speed up from 1:00 to 1:30 by 2x",
    )

    # 5. Restore intro
    engine.dispatch_operation(
        RestoreTransactionOperation(description="intro"),
        instruction="Actually, put the intro back",
    )

    # 6. Undo
    engine.dispatch_operation(
        UndoOperation(),
        instruction="Undo",
    )

    # 7. Edit caption
    engine.dispatch_operation(
        EditCaptionOperation(color="red"),
        instruction="Make that caption red",
    )

    return timeline.timeline_hash


def test_three_run_determinism():
    """
    Run 3 independent runs with different session/project identifiers.
    Assert that the generated timeline_hash across all 3 runs is strictly identical.
    """
    hash_run_1 = run_session(project_id="run_alpha_001")
    hash_run_2 = run_session(project_id="run_beta_002")
    hash_run_3 = run_session(project_id="run_gamma_003")

    assert len(hash_run_1) == 64
    assert hash_run_1 == hash_run_2, f"Run 1 ({hash_run_1}) != Run 2 ({hash_run_2})"
    assert hash_run_2 == hash_run_3, f"Run 2 ({hash_run_2}) != Run 3 ({hash_run_3})"
