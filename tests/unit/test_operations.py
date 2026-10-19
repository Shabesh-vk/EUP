"""
Unit tests for individual editing operations, constraints, and rejection logic.
"""

from core.engine import TimelineEngine
from core.operations import (
    CutRangeOperation,
    SpeedRangeOperation,
    AddCaptionOperation,
    EditCaptionOperation,
    MuteWordsOperation,
    BleepWordsOperation,
    RemoveFillerWordsOperation,
    RemoveSilenceOperation,
    AddMusicOperation,
)
from tests.fixtures.transcript_fixtures import create_test_timeline


def test_cut_operation():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Cut 0 to 30s (30,000ms)
    op = CutRangeOperation(start_ticks=0, end_ticks=30000)
    res = engine.dispatch_operation(op)

    assert res.status == "applied"
    assert res.duration_s == 70.0
    assert "30.0s shorter" in res.summary


def test_cut_rejections():
    timeline = create_test_timeline(duration_seconds=50.0)
    engine = TimelineEngine(timeline)

    # 1. Whole video cut
    res_whole = engine.dispatch_operation(CutRangeOperation(start_ticks=0, end_ticks=50000))
    assert res_whole.status == "rejected"
    assert "at least one segment must remain" in res_whole.summary

    # 2. Inverted bounds
    res_inv = engine.dispatch_operation(CutRangeOperation(start_ticks=30000, end_ticks=10000))
    assert res_inv.status == "rejected"
    assert "Invalid cut range" in res_inv.summary

    # 3. Beyond duration
    res_out = engine.dispatch_operation(CutRangeOperation(start_ticks=60000, end_ticks=70000))
    assert res_out.status == "rejected"
    assert "beyond current video duration" in res_out.summary


def test_speed_operation_and_limits():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # Valid 2x speed over 20s (10s to 30s) -> 20s becomes 10s -> total 90s
    res = engine.dispatch_operation(SpeedRangeOperation(start_ticks=10000, end_ticks=30000, speed_ratio=2.0))
    assert res.status == "applied"
    assert res.duration_s == 90.0

    # Speed up 10x rejection (honest supported limits)
    res_10x = engine.dispatch_operation(SpeedRangeOperation(start_ticks=0, end_ticks=10000, speed_ratio=10.0))
    assert res_10x.status == "rejected"
    assert "exceeds maximum supported limit" in res_10x.summary


def test_overlapping_speed_changes():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    # First speedup: 0 to 40s @ 2.0x
    engine.dispatch_operation(SpeedRangeOperation(start_ticks=0, end_ticks=40000, speed_ratio=2.0))
    # Overlapping speedup: 10s to 30s (current time) @ 4.0x
    res2 = engine.dispatch_operation(SpeedRangeOperation(start_ticks=10000, end_ticks=30000, speed_ratio=4.0))
    assert res2.status == "applied"
    # The overlapping section takes 4.0x according to the last-applied segment split rule


def test_edit_caption_when_no_caption_exists():
    timeline = create_test_timeline(duration_seconds=50.0)
    engine = TimelineEngine(timeline)

    # "make it bigger" or "make it red" when no caption exists
    res = engine.dispatch_operation(EditCaptionOperation(color="red"))
    assert res.status == "rejected"
    assert "No active caption exists" in res.summary


def test_edit_caption_when_multiple_captions_exist():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    engine.dispatch_operation(AddCaptionOperation(text="Intro", source_start_ticks=1000, source_end_ticks=3000))
    engine.dispatch_operation(AddCaptionOperation(text="Outro", source_start_ticks=80000, source_end_ticks=85000))

    # Edit without specifying which caption
    res = engine.dispatch_operation(EditCaptionOperation(color="red"))
    assert res.status == "needs_clarification"
    assert "Which one would you like to edit?" in res.question
    assert len(res.options) == 2


def test_filler_removal():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    initial_dur = timeline.total_duration_seconds
    res = engine.dispatch_operation(RemoveFillerWordsOperation(target_fillers=["um", "uh", "like"]))
    assert res.status == "applied"
    assert res.duration_s < initial_dur
    assert "Removed 2 filler word(s)" in res.summary


def test_silence_removal_with_protected_pauses():
    # Test with a self-contained transcript having exactly one 3-second silence between word 1 and word 2
    timeline = create_test_timeline(duration_seconds=20.0)
    timeline.transcript.words = [
        timeline.transcript.words[0],  # "hey" 1000-1400
        timeline.transcript.words[1],  # "everyone" 1400-2000
        # gap 2000 to 5000 is 3000ms silence
        timeline.transcript.words[3],  # "today" 5000-5500
    ]
    timeline.transcript.words[2].start_ticks = 5000
    timeline.transcript.words[2].end_ticks = 5500
    engine = TimelineEngine(timeline)

    # 1. Without protection: 3s silence is removed
    res1 = engine.dispatch_operation(RemoveSilenceOperation(min_duration_ticks=2500, respect_protected_pauses=False))
    assert res1.status == "applied"
    assert "Removed 1 silence" in res1.summary

    # 2. With protection: 3s silence survives
    timeline2 = create_test_timeline(duration_seconds=20.0)
    timeline2.transcript.words = [
        timeline2.transcript.words[0],
        timeline2.transcript.words[1],
        timeline2.transcript.words[3],
    ]
    timeline2.transcript.words[2].start_ticks = 5000
    timeline2.transcript.words[2].end_ticks = 5500
    engine2 = TimelineEngine(timeline2)
    res2 = engine2.dispatch_operation(
        RemoveSilenceOperation(min_duration_ticks=2500, respect_protected_pauses=True, protected_ranges=[(2000, 5000)])
    )
    assert res2.status == "applied"
    assert "No silences longer than" in res2.summary



def test_mute_and_bleep():
    timeline = create_test_timeline(duration_seconds=100.0)
    engine = TimelineEngine(timeline)

    res_mute = engine.dispatch_operation(MuteWordsOperation(word_ids=["w_000", "w_001"]))
    assert res_mute.status == "applied"
    assert len(timeline.effects.mutes) == 1

    res_bleep = engine.dispatch_operation(BleepWordsOperation(word_ids=["w_007", "w_008"], frequency_hz=1000))
    assert res_bleep.status == "applied"
    assert len(timeline.effects.bleeps) == 1
