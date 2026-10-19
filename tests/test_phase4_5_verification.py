"""Verification tests for Phase 4 (Word-ID Anchoring & History Replay) and Phase 5 (FFmpeg Rendering Pipeline)."""

import pytest
from engine.core.timeline import Timeline
from engine.core.models import SourceMedia, Transcript, Word, CaptionStyle
from engine.core.word_anchor import resolve_captions, map_source_time_to_playback
from engine.core.operations import execute_cut_range, execute_add_caption, execute_speed_change
from engine.media.renderer import build_ffmpeg_filtergraph


@pytest.fixture
def base_timeline():
    source = SourceMedia(
        media_id="test_media",
        file_path="sample.mp4",
        sha256="abc123hash",
        duration_s=120.0,
        fps=30.0,
        sample_rate=48000,
        channels=2,
        width=1920,
        height=1080
    )
    words = [
        Word(id="w_0", text="Welcome", start=12.0, end=13.0, confidence=0.99, speaker="speaker_0"),
        Word(id="w_1", text="to", start=13.1, end=13.3, confidence=0.99, speaker="speaker_0"),
        Word(id="w_2", text="channel", start=13.4, end=14.0, confidence=0.98, speaker="speaker_0"),
        Word(id="w_3", text="Today", start=35.0, end=35.8, confidence=0.95, speaker="speaker_0"),
        Word(id="w_4", text="Pricing", start=60.0, end=61.0, confidence=0.96, speaker="speaker_0"),
    ]
    transcript = Transcript(words=words)
    return Timeline(source, transcript)


def test_caption_anchors_to_word_ids_and_shifts_after_cut(base_timeline):
    """When a preceding cut occurs, caption start shifts automatically without manual re-calculation."""
    # Step 1: Add caption anchored to w_0, w_1, w_2 (original 12.0s - 14.0s)
    execute_add_caption(base_timeline, text="Welcome!", word_ids=["w_0", "w_1", "w_2"])
    caps, _ = base_timeline.get_resolved_captions()
    assert len(caps) == 1
    assert caps[0].playback_start == 12.0

    # Step 2: Cut the first 5 seconds (0.0s - 5.0s)
    execute_cut_range(base_timeline, 0.0, 5.0, source_relative=True, snap_silence=False)

    # Caption must now play at 12.0 - 5.0 = 7.0s
    caps2, _ = base_timeline.get_resolved_captions()
    assert len(caps2) == 1
    assert caps2[0].playback_start == 7.0
    assert caps2[0].text == "Welcome!"


def test_caption_hides_when_words_cut_and_reappears_on_undo(base_timeline):
    """If anchored words are cut out, caption is hidden; on undo, it returns."""
    execute_add_caption(base_timeline, text="Welcome!", word_ids=["w_0", "w_1", "w_2"])

    # Cut interval covering w_0, w_1, w_2 (10.0s - 20.0s)
    ops, summary = execute_cut_range(base_timeline, 10.0, 20.0, source_relative=True, snap_silence=False)
    base_timeline.record_step("Cut intro", ops, summary)

    # Words are cut -> caption is hidden
    caps, warnings = base_timeline.get_resolved_captions()
    assert len(caps) == 0

    # Undo the cut -> caption automatically reappears
    base_timeline.undo()
    caps_after_undo, _ = base_timeline.get_resolved_captions()
    assert len(caps_after_undo) == 1
    assert caps_after_undo[0].text == "Welcome!"
    assert caps_after_undo[0].playback_start == 12.0


def test_selective_restoration_preserves_other_edits(base_timeline):
    """Restoring an earlier cut (e.g. putting intro back) preserves subsequent speed changes."""
    # Step 1: Cut the intro (0.0s - 30.0s)
    ops1, s1 = execute_cut_range(base_timeline, 0.0, 30.0, source_relative=True, snap_silence=False)
    step1 = base_timeline.record_step("Cut the first 30 seconds", ops1, s1)

    # Step 2: Speed up 60s - 80s by 2x
    ops2, s2 = execute_speed_change(base_timeline, 60.0, 80.0, speed=2.0, source_relative=True)
    step2 = base_timeline.record_step("Speed up 2x", ops2, s2)

    # Duration should be 90s - 10s (due to 2x speed) = 80.0s
    assert round(base_timeline.total_duration, 1) == 80.0

    # Non-linear selective restore: Restore Step 1 (the intro)
    base_timeline.restore_step(step1.step_index)

    # Intro is back (first clip starts at 0.0s), but speed change is still applied!
    assert base_timeline.clips[0].source_start == 0.0
    # Total duration = 120s - 10s = 110.0s
    assert round(base_timeline.total_duration, 1) == 110.0


def test_ffmpeg_filtergraph_generation_contains_all_operations(base_timeline):
    """Phase 5: FFmpeg filtergraph includes trim, pts speed scaling, and drawtext caption overlay."""
    execute_add_caption(base_timeline, text="Test Caption", word_ids=["w_0", "w_1"])
    execute_cut_range(base_timeline, 0.0, 10.0, source_relative=True, snap_silence=False)
    execute_speed_change(base_timeline, 40.0, 60.0, speed=2.0, source_relative=True)

    filtergraph = build_ffmpeg_filtergraph(base_timeline, has_audio=True)

    # Must contain video trim and setpts
    assert "trim=start=" in filtergraph
    assert "setpts=PTS-STARTPTS" in filtergraph
    # Must contain audio atrim and atempo
    assert "atrim=start=" in filtergraph
    assert "atempo=2.000" in filtergraph
    # Must contain drawtext for caption
    assert "drawtext=" in filtergraph
    assert "Test Caption" in filtergraph
    # Must contain concatenation of all segments
    assert "concat=n=" in filtergraph
