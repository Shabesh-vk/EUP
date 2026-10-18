"""Unit tests for every individual video editing operation."""

import pytest
from engine.core.timeline import Timeline
from engine.media.probe import probe_media_file
from engine.media.transcriber import MockTranscriber
from engine.core.operations import (
    execute_cut_range,
    execute_speed_change,
    execute_add_caption,
    execute_remove_filler_words,
    execute_remove_silences,
    execute_bleep_or_mute_words,
    execute_auto_caption,
)


@pytest.fixture
def clean_timeline():
    media = probe_media_file("sample.mp4")
    trans, _ = MockTranscriber().transcribe("sample.mp4")
    return Timeline(source=media, transcript=trans, time_policy="original")


def test_op_cut_range(clean_timeline):
    orig_dur = clean_timeline.total_duration
    ops, summary = execute_cut_range(clean_timeline, 10.0, 20.0, source_relative=True, snap_silence=False)
    assert len(ops) == 1
    assert clean_timeline.total_duration == pytest.approx(orig_dur - 10.0, rel=1e-2)
    assert "Cut 10.00s" in summary


def test_op_speed_up_slow_down(clean_timeline):
    orig_dur = clean_timeline.total_duration
    # Speed up 0 to 10s by 2x (takes 5s instead of 10s)
    ops, summary = execute_speed_change(clean_timeline, 0.0, 10.0, speed=2.0, source_relative=True)
    assert len(ops) == 1
    assert clean_timeline.total_duration == pytest.approx(orig_dur - 5.0, rel=1e-2)
    assert "Sped up" in summary

    # Slow down 10 to 20s by 0.5x (takes 20s instead of 10s)
    execute_speed_change(clean_timeline, 10.0, 20.0, speed=0.5, source_relative=True)
    assert clean_timeline.total_duration == pytest.approx(orig_dur + 5.0, rel=1e-2)


def test_op_add_caption_and_update_style(clean_timeline):
    ops, summary = execute_add_caption(clean_timeline, text="Subscribe!", target_phrase="welcome to the channel")
    assert len(ops) == 1
    assert clean_timeline.captions[0].style.color == "white"

    clean_timeline.apply_update_caption_style(style_updates={"color": "yellow", "font_size": 36})
    assert clean_timeline.captions[0].style.color == "yellow"
    assert clean_timeline.captions[0].style.font_size == 36


def test_op_remove_filler_words(clean_timeline):
    orig_dur = clean_timeline.total_duration
    ops, summary = execute_remove_filler_words(clean_timeline)
    assert len(ops) >= 2  # 'um', 'uh', 'like'
    assert clean_timeline.total_duration < orig_dur
    assert "Removed" in summary


def test_op_remove_silences(clean_timeline):
    orig_dur = clean_timeline.total_duration
    ops, summary = execute_remove_silences(clean_timeline, min_silence_s=0.5, keep_pause_s=0.2)
    assert len(ops) > 0
    assert clean_timeline.total_duration < orig_dur
    assert "Removed" in summary


def test_op_mute_and_bleep_words(clean_timeline):
    ops, summary = execute_bleep_or_mute_words(clean_timeline, ["pricing"], effect_type="bleep")
    assert len(ops) == 1
    assert len(clean_timeline.effects) == 1
    assert clean_timeline.effects[0].effect_type == "bleep"

    ops2, summary2 = execute_bleep_or_mute_words(clean_timeline, ["enterprise"], effect_type="mute")
    assert len(clean_timeline.effects) == 2
    assert clean_timeline.effects[1].effect_type == "mute"


def test_op_auto_caption(clean_timeline):
    ops, summary = execute_auto_caption(clean_timeline, words_per_caption=4)
    assert len(ops) > 5
    assert len(clean_timeline.captions) == len(ops)
    assert "Generated" in summary


def test_op_undo_redo_cycle(clean_timeline):
    initial_hash = clean_timeline.timeline_hash

    # Step 1: cut
    c1 = clean_timeline.apply_cut(0.0, 10.0, source_relative=True)
    clean_timeline.record_step("Cut 0-10", [c1], "Cut 10s")
    cut_hash = clean_timeline.timeline_hash
    assert cut_hash != initial_hash

    # Step 2: add caption
    cap = clean_timeline.apply_add_caption("Hello", ["w_5"])
    clean_timeline.record_step("Add cap", [cap], "Added cap")
    cap_hash = clean_timeline.timeline_hash

    # Undo step 2
    clean_timeline.undo()
    assert clean_timeline.timeline_hash == cut_hash

    # Redo step 2
    clean_timeline.redo()
    assert clean_timeline.timeline_hash == cap_hash

    # New edit clears redo stack
    clean_timeline.undo()
    c2 = clean_timeline.apply_cut(20.0, 30.0, source_relative=True)
    clean_timeline.record_step("Cut 20-30", [c2], "Cut another 10s")
    assert len(clean_timeline.redo_stack) == 0
