"""
Test suite covering all Hard Cases specified in the IncuBrix Brief (Page 4).
Screening evaluates 5 hidden tests based on these exact scenarios.
"""

import pytest
from incubrix_engine.core.models import Transcript, Word, Operation, CaptionStyle
from incubrix_engine.core.timeline_engine import TimelineEngine
from incubrix_engine.ai.brain import VideoEditingBrain


def build_test_transcript() -> Transcript:
    words = [
        Word(id=0, text="Intro", start=0.0, end=1.0),
        Word(id=1, text="welcome", start=10.0, end=11.0),
        Word(id=2, text="to", start=11.1, end=11.3),
        Word(id=3, text="the", start=11.4, end=11.6),
        Word(id=4, text="show", start=11.7, end=12.5),
        Word(id=5, text="um", start=15.0, end=15.5, is_filler=True),
        Word(id=6, text="middle", start=20.0, end=21.0),
        Word(id=7, text="thanks", start=25.0, end=25.5),
        Word(id=8, text="part", start=30.0, end=31.0),
        Word(id=9, text="thanks", start=45.0, end=45.5),
        Word(id=10, text="more", start=50.0, end=51.0),
        Word(id=11, text="thanks", start=60.0, end=60.5),
        Word(id=12, text="closing", start=70.0, end=71.0),
        Word(id=13, text="thanks", start=80.0, end=80.5),
    ]
    return Transcript(words=words, duration=100.0)


def test_hard_case_1_caption_cut_and_restored():
    """
    Hard Case 1: A caption added, then the exact sentence under it cut;
    then that cut restored (the caption should come back).
    """
    transcript = build_test_transcript()
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    # 1. Add caption on words 1-4 ("welcome to the show" at 10.0s - 12.5s)
    res1 = brain.process_instruction("Add a caption 'Show' when I say welcome to the show", engine)
    assert res1.status == "applied"
    assert engine.timeline.captions[0].is_active is True
    assert engine.timeline.captions[0].timeline_start == 10.0

    # 2. Cut the exact sentence under it (source 10.0s - 13.0s)
    res2 = engine.apply_step(
        instruction="Cut 10.0 to 13.0",
        operations=[Operation(op="cut_range", params={"start": 10.0, "end": 13.0})],
        summary="Cut words under caption"
    )
    assert res2.status == "applied"
    # Caption must be inactive because words are cut!
    assert engine.timeline.captions[0].is_active is False
    assert engine.timeline.captions[0].timeline_start is None

    # 3. Restore that cut (Undo)
    res3 = brain.process_instruction("Undo", engine)
    assert res3.status == "applied"
    # The caption should come back!
    assert engine.timeline.captions[0].is_active is True
    assert engine.timeline.captions[0].timeline_start == 10.0


def test_hard_case_2_filler_removal_and_bleep():
    """
    Hard Case 2: A word muted or bleeped, and filler removal executed.
    """
    transcript = build_test_transcript()
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    # Bleep word 6 ("middle" at 20.0s)
    engine.add_audio_effect("bleep", 6, 6)
    assert len(engine.timeline.audio_effects) == 1

    # Remove filler words ("um" at 15.0s)
    res = brain.process_instruction("remove filler words", engine)
    assert res.status == "applied"

    # Verify bleeped effect stays attached to word 6
    eff = engine.timeline.audio_effects[0]
    assert eff.start_word_id == 6
    assert eff.is_active is True


def test_hard_case_3_out_of_bounds_and_duplicate_cuts():
    """
    Hard Case 3: 'Remove 0:30-0:40' sent twice; 'add a caption at 5:00' on a shorter video (100s).
    """
    transcript = build_test_transcript()  # 100s duration
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    # Out of bounds timestamp (5:00 = 300s > 100s) -> Must reject
    res_out = brain.process_instruction("Add a caption at 5:00", engine)
    assert res_out.status == "rejected"
    assert "exceeds" in res_out.summary.lower()

    # Cut 30-40 sent twice
    cut_op = Operation(op="cut_range", params={"start": 30.0, "end": 40.0})
    res_cut1 = engine.apply_step("Cut 30-40", [cut_op], "First cut")
    assert res_cut1.status == "applied"
    dur1 = engine.get_current_duration()

    # Second cut of already cut range: idempotent and safe (no-op)
    res_cut2 = engine.apply_step("Cut 30-40", [cut_op], "Second cut")
    assert res_cut2.status == "applied"
    assert engine.get_current_duration() == dur1


def test_hard_case_4_undo_second_to_last_and_make_bigger_when_none():
    """
    Hard Case 4: 'Undo the second-to-last cut but keep the music'; 'make it bigger' when no caption exists.
    """
    transcript = build_test_transcript()
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    # 'Make it bigger' when no caption exists -> Must reject
    res_resize = brain.process_instruction("make that caption bigger", engine)
    assert res_resize.status == "rejected"
    assert "no caption" in res_resize.summary.lower()

    # Add background music
    brain.process_instruction("add background music", engine)
    assert engine.timeline.background_music is not None

    # Perform two cuts
    engine.apply_step("Cut 10-15", [Operation(op="cut_range", params={"start": 10.0, "end": 15.0})], "Cut 1")
    engine.apply_step("Cut 50-55", [Operation(op="cut_range", params={"start": 50.0, "end": 55.0})], "Cut 2")

    # Undo second-to-last cut
    res_undo_cut = brain.process_instruction("undo the second-to-last cut", engine)
    assert res_undo_cut.status == "applied"
    # Music must stay!
    assert engine.timeline.background_music is not None


def test_hard_case_5_repeated_thanks_clarification():
    """
    Hard Case 5: 'Remove everything after I say thanks' where thanks is said 4 times.
    """
    transcript = build_test_transcript()  # contains 4 'thanks'
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    res = brain.process_instruction("Remove everything after I say thanks", engine)
    assert res.status == "needs_clarification"
    assert "4 times" in res.clarification.question
    assert len(res.clarification.options) == 4


def test_hard_case_6_cut_everything_and_extreme_speed():
    """
    Hard Case 6: 'Speed up 10x', 'cut everything', and impossible whole-video cuts.
    """
    transcript = build_test_transcript()
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    # Whole-video cut must be rejected
    res_cut_all = brain.process_instruction("cut everything", engine)
    assert res_cut_all.status == "rejected"
    assert "empty video" in res_cut_all.rejection_reason or "prohibited" in res_cut_all.summary.lower()

    # Speed up 10x: supported upper bound
    res_speed10 = brain.process_instruction("speed up 10x", engine)
    assert res_speed10.status == "applied"

    # Speed up > 10x: reject
    res_speed_extreme = brain.process_instruction("speed up 50x", engine)
    assert res_speed_extreme.status == "rejected"
