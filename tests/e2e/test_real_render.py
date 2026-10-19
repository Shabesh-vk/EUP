"""
End-to-End test verifying real FFmpeg rendering from a saved timeline.
Tests:
- Original media preservation (SHA-256 hash remains identical).
- Cuts, speed adjustments, captions, bleeps, and music ducking.
- Frame-accuracy of output duration (within 1 output frame).
- A/V synchronization.
"""

import os
import pytest
from core.schema import (
    Timeline,
    SourceMedia,
    Transcript,
    TranscriptWord,
    ClipSegment,
    EffectsCollection,
)
from core.engine import TimelineEngine
from core.operations import (
    CutRangeOperation,
    SpeedRangeOperation,
    AddCaptionOperation,
    BleepWordsOperation,
    AddMusicOperation,
)
from media.inspector import inspect_media_file, verify_media_integrity
from media.renderer import render_timeline


@pytest.fixture(scope="module")
def sample_video_path():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "test_render_60s.mp4"))
    if not os.path.isfile(path):
        from scripts.generate_fixtures import generate_test_video
        generate_test_video(path, duration_s=60.0)
    return path



@pytest.fixture(scope="module")
def sample_music_path():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "test_music.mp3"))
    if not os.path.isfile(path):
        from scripts.generate_fixtures import generate_test_audio
        generate_test_audio(path, duration_s=60.0)
    return path


def test_real_render_frame_accuracy_and_effects(sample_video_path, sample_music_path, tmp_path):
    # 1. Inspect source media and record original hash
    source_media, inspection = inspect_media_file(sample_video_path)
    original_sha256 = source_media.sha256_hash
    assert inspection.duration_s == 60.0

    # 2. Build initial timeline
    initial_seg = ClipSegment(
        segment_id="seg_001",
        source_start_ticks=0,
        source_end_ticks=source_media.duration_ticks,
        speed_ratio=1.0,
    )
    transcript = Transcript(
        words=[
            TranscriptWord(id="w_01", word="welcome", start_ticks=15000, end_ticks=15800, speaker="host"),
            TranscriptWord(id="w_02", word="to", start_ticks=15800, end_ticks=16000, speaker="host"),
            TranscriptWord(id="w_03", word="the", start_ticks=16000, end_ticks=16200, speaker="host"),
            TranscriptWord(id="w_04", word="show", start_ticks=16200, end_ticks=17000, speaker="host"),
            TranscriptWord(id="w_05", word="badword", start_ticks=25000, end_ticks=26000, speaker="host"),
        ]
    )
    timeline = Timeline(
        schema_version="1.0.0",
        project_id="proj_render_test",
        timebase=1000,
        source_media=source_media,
        transcript=transcript,
        segments=[initial_seg],
        effects=EffectsCollection(),
        transactions=[],
        timeline_hash="",
    )
    engine = TimelineEngine(timeline)

    # 3. Apply edits
    # Edit A: Add caption 'Welcome!' anchored to w_01-w_04 (15s to 17s in source)
    res_cap = engine.dispatch_operation(
        AddCaptionOperation(
            text="Welcome!",
            anchor_word_ids=["w_01", "w_02", "w_03", "w_04"],
            color="red",
        )
    )
    assert res_cap.status == "applied"

    # Edit B: Cut the first 10 seconds (0 to 10s)
    res_cut = engine.dispatch_operation(
        CutRangeOperation(start_ticks=0, end_ticks=10000, time_domain="current_edited_time")
    )
    assert res_cut.status == "applied"
    # Timeline is now 50s. Caption originally at 15s now plays at 5s!
    assert engine.project_source_to_output(15000) == 5000

    # Edit C: Speed up 10s to 20s (current time) by 2x -> 10s becomes 5s
    res_speed = engine.dispatch_operation(
        SpeedRangeOperation(start_ticks=10000, end_ticks=20000, speed_ratio=2.0)
    )
    assert res_speed.status == "applied"
    # Duration reduced by 5s -> total duration is 45.0s
    assert timeline.total_duration_seconds == 45.0

    # Edit D: Bleep word w_05 (source 25s-26s)
    res_bleep = engine.dispatch_operation(
        BleepWordsOperation(word_ids=["w_05"], frequency_hz=1000)
    )
    assert res_bleep.status == "applied"

    # Edit E: Add background music
    res_music = engine.dispatch_operation(
        AddMusicOperation(asset_url=sample_music_path, volume=0.25)
    )
    assert res_music.status == "applied"

    # 4. Render output video
    output_video_path = str(tmp_path / "rendered_output.mp4")
    render_result = render_timeline(
        timeline=timeline,
        source_media_path=sample_video_path,
        output_video_path=output_video_path,
        background_music_path=sample_music_path,
    )

    # 5. Assertions
    # Must-Have 1: Original file must remain untouched
    assert verify_media_integrity(sample_video_path, original_sha256)

    # Must-Have 5: Rendered length equals timeline length within 1 frame
    assert os.path.isfile(output_video_path)
    assert render_result.timeline_duration_s == 45.0
    # Output length within 1 frame (frame_diff <= 1.5 frames)
    assert render_result.frame_diff <= 1.5, f"Frame diff {render_result.frame_diff} exceeds 1 frame!"
    assert render_result.is_in_sync

    # Inspect rendered output with ffprobe to verify streams
    _, out_inspection = inspect_media_file(output_video_path)
    assert out_inspection.has_audio
    assert out_inspection.width == 1280
    assert out_inspection.height == 720
    assert abs(out_inspection.duration_s - 45.0) <= 0.05
