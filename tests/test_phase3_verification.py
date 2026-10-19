"""Verification tests for Phase 3: Silence-Snapping & Non-Destructive Timeline Execution."""

import pytest
from engine.core.timeline import Timeline
from engine.core.models import Transcript, Word, SourceMedia, TimelineClip
from engine.core.silence_snap import snap_cut_boundaries_to_silence
from engine.core.operations import execute_cut_range


@pytest.fixture
def sample_timeline():
    source = SourceMedia(
        media_id="test_media",
        file_path="sample.mp4",
        sha256="dummy_hash_12345",
        duration_s=120.0,
        fps=30.0,
        sample_rate=48000,
        channels=2,
        width=1920,
        height=1080
    )
    words = [
        Word(id="w_0", text="Hello", start=0.5, end=1.0, confidence=0.99, speaker="speaker_0"),
        Word(id="w_1", text="world", start=1.2, end=1.8, confidence=0.98, speaker="speaker_0"),
        # Silence gap between 1.8s and 29.5s
        Word(id="w_2", text="Welcome", start=29.5, end=29.9, confidence=0.95, speaker="speaker_0"),
        Word(id="w_3", text="everyone", start=30.1, end=30.6, confidence=0.96, speaker="speaker_0"),
        # Silence gap between 30.6s and 60.0s
        Word(id="w_4", text="Conclusion", start=60.0, end=60.8, confidence=0.97, speaker="speaker_0")
    ]
    transcript = Transcript(words=words)
    return Timeline(source, transcript)


def test_silence_snapping_protects_word_boundary():
    """If a cut boundary is inside a word, silence snap moves it to the nearest inter-word pause."""
    words = [
        Word(id="w_0", text="Welcome", start=29.5, end=29.9, confidence=0.95, speaker="speaker_0"),
        Word(id="w_1", text="everyone", start=30.1, end=30.6, confidence=0.96, speaker="speaker_0")
    ]
    transcript = Transcript(words=words)

    # Cut ending at 30.2s falls right inside 'everyone' (30.1 - 30.6s)
    # Since 30.2 < midpoint 30.35, it should snap before the word (30.1 - 0.05 = 30.05s)
    snapped_start, snapped_end, notes = snap_cut_boundaries_to_silence(0.0, 30.2, transcript, padding_s=0.05)

    assert snapped_end < 30.1, f"Expected snapped_end < 30.1s to protect 'everyone', got {snapped_end}"
    assert len(notes) > 0


def test_execute_cut_range_middle_segment_creates_two_clips(sample_timeline):
    """Cutting a middle segment non-destructively splits the clip into 2 clips."""
    assert len(sample_timeline.clips) == 1
    assert sample_timeline.total_duration == 120.0

    ops, summary = execute_cut_range(sample_timeline, 40.0, 55.0, source_relative=True, snap_silence=False)

    assert len(sample_timeline.clips) == 2
    # Clip 1: 0.0 -> 40.0s
    assert sample_timeline.clips[0].source_start == 0.0
    assert sample_timeline.clips[0].source_end == 40.0
    # Clip 2: 55.0 -> 120.0s
    assert sample_timeline.clips[1].source_start == 55.0
    assert sample_timeline.clips[1].source_end == 120.0

    assert sample_timeline.total_duration == (120.0 - 15.0)


def test_execute_cut_range_first_30s_trims_head(sample_timeline):
    """Cutting the first 30 seconds leaves 1 clip starting at ~30s."""
    initial_hash = sample_timeline.timeline_hash

    ops, summary = execute_cut_range(sample_timeline, 0.0, 30.0, source_relative=True, snap_silence=True)

    assert len(sample_timeline.clips) == 1
    # Boundary snaps to silence around 30.0s
    first_clip = sample_timeline.clips[0]
    assert first_clip.source_start >= 29.9
    assert first_clip.source_end == 120.0
    assert sample_timeline.timeline_hash != initial_hash


def test_word_ids_automatically_reassigned_after_cut(sample_timeline):
    """Words in cut region are removed from active clip word_ids; remaining words stay."""
    execute_cut_range(sample_timeline, 0.0, 30.0, source_relative=True, snap_silence=False)

    remaining_clip = sample_timeline.clips[0]
    # w_0 (0.5-1.0s) and w_1 (1.2-1.8s) were cut
    assert "w_0" not in remaining_clip.word_ids
    assert "w_1" not in remaining_clip.word_ids
    # w_3 (30.1-30.6s) and w_4 (60.0-60.8s) remain active
    assert "w_3" in remaining_clip.word_ids
    assert "w_4" in remaining_clip.word_ids
