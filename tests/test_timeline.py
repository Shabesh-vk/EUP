"""Tests verifying the Golden Timeline Rule, immutability, and Word ID tracking."""

import pytest
from engine.core.models import SourceMedia, Word, Transcript, CaptionStyle
from engine.core.timeline import Timeline
from engine.media.probe import calculate_file_sha256


@pytest.fixture
def mock_source_and_transcript():
    source = SourceMedia(
        media_id="test_media",
        file_path="sample.mp4",
        sha256=calculate_file_sha256("sample.mp4"),
        duration_s=100.0,
        fps=30.0
    )
    words = [
        Word(id="w_0", text="Intro", start=1.0, end=3.0, speaker="speaker_0"),
        Word(id="w_1", text="Middle", start=40.0, end=42.0, speaker="speaker_0"),
        Word(id="w_2", text="Outro", start=90.0, end=92.0, speaker="speaker_0"),
    ]
    transcript = Transcript(language="en", words=words)
    return source, transcript


def test_source_file_untouched(mock_source_and_transcript):
    """Must-have 1: Never damage original. Source file hash stays identical."""
    source, transcript = mock_source_and_transcript
    original_hash = source.sha256

    tl = Timeline(source=source, transcript=transcript)
    tl.apply_cut(0.0, 20.0, source_relative=True)
    tl.apply_speed(30.0, 60.0, speed=2.0, source_relative=True)
    tl.apply_add_caption(text="Middle caption", word_ids=["w_1"])

    # Source hash must remain unaltered
    current_source_hash = calculate_file_sha256(source.file_path)
    assert current_source_hash == original_hash


def test_caption_anchoring_across_cuts(mock_source_and_transcript):
    """Must-have 2: Captions stick to Word IDs across cuts."""
    source, transcript = mock_source_and_transcript
    tl = Timeline(source=source, transcript=transcript)

    # Attach caption to 'Middle' word (original time 40.0 - 42.0s)
    tl.apply_add_caption(text="Middle Word", word_ids=["w_1"])
    caps, _ = tl.get_resolved_captions()
    assert len(caps) == 1
    assert caps[0].playback_start == 40.0
    assert caps[0].playback_end == 42.0

    # Cut the first 20 seconds (0.0 to 20.0s)
    tl.apply_cut(0.0, 20.0, source_relative=True)
    caps, _ = tl.get_resolved_captions()
    assert len(caps) == 1
    # Caption must shift exactly by 20s
    assert caps[0].playback_start == 20.0
    assert caps[0].playback_end == 22.0


def test_caption_anchoring_across_speed_changes(mock_source_and_transcript):
    """Captions stick to words and scale with speed changes, enforcing min duration."""
    source, transcript = mock_source_and_transcript
    tl = Timeline(source=source, transcript=transcript)

    tl.apply_add_caption(text="Middle", word_ids=["w_1"])
    # Speed up 30s to 50s by 2x (which contains w_1: 40s - 42s)
    tl.apply_speed(30.0, 50.0, speed=2.0, source_relative=True)

    caps, _ = tl.get_resolved_captions()
    assert len(caps) == 1
    # Original duration is 2.0s. At 2x speed, duration is 1.0s (>= min readable duration 0.7s)
    dur = caps[0].playback_end - caps[0].playback_start
    assert round(dur, 2) == 1.0


def test_caption_hides_when_words_cut_and_restores(mock_source_and_transcript):
    """When anchored words are cut, caption hides. When cut is restored, caption returns."""
    source, transcript = mock_source_and_transcript
    tl = Timeline(source=source, transcript=transcript)

    tl.apply_add_caption(text="Middle Word", word_ids=["w_1"])
    assert len(tl.get_resolved_captions()[0]) == 1

    # Cut the range containing w_1 (35s to 45s)
    cut_op = tl.apply_cut(35.0, 45.0, source_relative=True)
    tl.record_step("Cut middle", [cut_op], "Cut middle section")

    # Caption is now hidden
    caps, warnings = tl.get_resolved_captions()
    assert len(caps) == 0
    assert any("hidden because its anchored words were cut" in w for w in warnings)

    # Undo the cut
    tl.undo()
    caps, _ = tl.get_resolved_captions()
    assert len(caps) == 1
    assert caps[0].playback_start == 40.0


def test_reorder_clips_tracks_anchored_effects(mock_source_and_transcript):
    """Effects stick to words across clip reordering."""
    source, transcript = mock_source_and_transcript
    tl = Timeline(source=source, transcript=transcript)

    tl.apply_audio_effect(effect_type="mute", word_ids=["w_2"])  # Outro word at 90s
    tl.apply_cut(45.0, 50.0, source_relative=True)  # Split into two clips

    assert len(tl.clips) == 2
    clip1, clip2 = tl.clips[0], tl.clips[1]

    # Swap clips
    tl.apply_reorder([clip2.clip_id, clip1.clip_id])

    effects = tl.get_resolved_audio_effects()
    assert len(effects) == 1
    # Outro was in clip2, which is now first!
    assert effects[0].playback_start < 50.0
