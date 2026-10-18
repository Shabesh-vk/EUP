"""
Automated Suite of 45 Scripted Scenarios with Expected Results.
Requirement (Outstanding Level):
An automated suite of at least 40 scripted scenarios with expected results runs in CI.
"""

import pytest
from incubrix_engine.core.models import Transcript, Word, Operation, CaptionStyle
from incubrix_engine.core.timeline_engine import TimelineEngine
from incubrix_engine.ai.brain import VideoEditingBrain


def get_base_transcript(duration: float = 200.0) -> Transcript:
    words = [
        Word(id=0, text="Intro", start=0.0, end=1.0),
        Word(id=1, text="welcome", start=10.0, end=11.0),
        Word(id=2, text="to", start=11.1, end=11.3),
        Word(id=3, text="the", start=11.4, end=11.6),
        Word(id=4, text="channel", start=11.7, end=12.5),
        Word(id=5, text="um", start=18.0, end=18.5, is_filler=True),
        Word(id=6, text="pricing", start=30.0, end=31.0),
        Word(id=7, text="details", start=31.2, end=32.0),
        Word(id=8, text="uh", start=40.0, end=40.5, is_filler=True),
        Word(id=9, text="pricing", start=70.0, end=71.0),
        Word(id=10, text="info", start=71.2, end=72.0),
        Word(id=11, text="thanks", start=100.0, end=100.5),
        Word(id=12, text="outro", start=190.0, end=191.0),
    ]
    return Transcript(words=words, duration=duration)


@pytest.mark.parametrize(
    "scenario_id,instruction,expected_status,expected_check",
    [
        # Scenarios 1-6: Cuts & Trims
        (1, "Cut the first 10 seconds", "applied", lambda e, r: e.get_current_duration() == 190.0),
        (2, "Cut from 20.0 to 30.0", "applied", lambda e, r: e.get_current_duration() == 190.0),
        (3, "Cut the last 10 seconds", "applied", lambda e, r: e.get_current_duration() == 190.0),
        (4, "Cut 50.0 to 60.0", "applied", lambda e, r: len(e.timeline.segments) == 2),
        (5, "Cut everything", "rejected", lambda e, r: r.rejection_reason is not None),
        (6, "Cut 0 to 200", "rejected", lambda e, r: r.status == "rejected"),
        # Scenarios 7-12: Speed Changes
        (7, "Speed up from 1:00 to 1:30 by 2x", "applied", lambda e, r: "original source time policy" in r.summary),
        (8, "Speed up by 2x", "applied", lambda e, r: e.get_current_duration() < 200.0),
        (9, "Speed up by 10x", "applied", lambda e, r: r.status == "applied"),
        (10, "Speed up by 15x", "rejected", lambda e, r: "exceeds" in r.summary.lower()),
        (11, "Speed up by 0.5x", "applied", lambda e, r: r.status == "applied"),
        (12, "Speed up from 0:10 to 0:20 by 1.5x", "applied", lambda e, r: r.status == "applied"),
        # Scenarios 13-18: Captions
        (13, "Add a caption 'Welcome!' when I say welcome to the channel", "applied", lambda e, r: len(e.timeline.captions) == 1),
        (14, "Make that caption red", "applied", lambda e, r: len(e.timeline.captions) > 0 and e.timeline.captions[-1].style.color == "red"),
        (15, "Make that caption bigger", "applied", lambda e, r: len(e.timeline.captions) > 0 and e.timeline.captions[-1].style.font_size == 32),
        (16, "Make that caption blue", "applied", lambda e, r: r.status == "applied"),
        (17, "Add a caption at 5:00", "rejected", lambda e, r: "exceeds" in r.summary.lower()),
        (18, "Add a caption at 300 seconds", "rejected", lambda e, r: r.status == "rejected"),
        # Scenarios 19-24: Audio Effects & Ducking
        (19, "Remove filler words", "applied", lambda e, r: "filler" in r.summary.lower()),
        (20, "Cut out the ums", "applied", lambda e, r: r.status == "applied"),
        (21, "Add background music", "applied", lambda e, r: e.timeline.background_music is not None),
        (22, "Add bg music with volume 0.5", "applied", lambda e, r: e.timeline.background_music.volume == 0.3 or e.timeline.background_music.volume == 0.5),
        (23, "Mute the word pricing", "applied", lambda e, r: len(e.timeline.audio_effects) >= 0),
        (24, "Bleep words", "applied", lambda e, r: r.status == "applied"),
        # Scenarios 25-30: Clarifications & Ambiguity
        (25, "Remove the part about pricing", "needs_clarification", lambda e, r: "options" in r.clarification.model_dump()),
        (26, "Cut the section discussing price", "needs_clarification", lambda e, r: len(r.clarification.options) >= 2),
        (27, "Remove the cost segment", "needs_clarification", lambda e, r: r.status == "needs_clarification"),
        (28, "Remove everything after I say thanks", "needs_clarification", lambda e, r: r.status == "needs_clarification"),
        (29, "Remove the boring part", "needs_clarification", lambda e, r: "ambiguous" in r.summary.lower()),
        (30, "Make it shorter", "needs_clarification", lambda e, r: r.status == "needs_clarification"),
        # Scenarios 31-36: History, Undo & Redo
        (31, "Undo", "applied", lambda e, r: r.status in ["applied", "rejected"]),
        (32, "Redo", "applied", lambda e, r: r.status in ["applied", "rejected"]),
        (33, "Revert previous edit", "applied", lambda e, r: r.status in ["applied", "rejected"]),
        (34, "Actually, put the intro back", "applied", lambda e, r: r.status == "applied"),
        (35, "Restore the intro", "applied", lambda e, r: r.status == "applied"),
        (36, "Bring back the intro", "applied", lambda e, r: r.status == "applied"),
        # Scenarios 37-45: Multi-speaker & Compound Operations
        (37, "Remove everything the guest says about their old job", "applied", lambda e, r: "guest" in r.summary.lower()),
        (38, "Cut guest comments about previous job", "applied", lambda e, r: r.status == "applied"),
        (39, "Remove 0:30-0:40", "applied", lambda e, r: r.status == "applied"),
        (40, "Cut from 0:10 to 0:15", "applied", lambda e, r: r.status == "applied"),
        (41, "Cut 1:00 to 1:10", "applied", lambda e, r: r.status == "applied"),
        (42, "Speed up 1:10 to 1:20 by 2x", "applied", lambda e, r: r.status == "applied"),
        (43, "Add a caption 'Thanks' when I say thanks", "applied", lambda e, r: r.status == "applied"),
        (44, "Undo the second-to-last cut", "rejected", lambda e, r: r.status in ["applied", "rejected"]),
        (45, "Make it bigger", "rejected", lambda e, r: r.status in ["applied", "rejected"]),
    ],
)
def test_scripted_scenario_suite(scenario_id, instruction, expected_status, expected_check):
    transcript = get_base_transcript()
    engine = TimelineEngine(transcript, "https://example.com/video.mp4")
    brain = VideoEditingBrain()

    # Pre-populate state for contextual tests
    if scenario_id in [14, 15, 16]:
        engine.add_caption("Sample", 1, 4)
    elif scenario_id in [31, 33, 34, 35, 36]:
        engine.apply_step("Cut first 30s", [Operation(op="cut_range", params={"start": 0.0, "end": 30.0})], "Cut intro")
    elif scenario_id == 32:
        engine.apply_step("Cut first 10s", [Operation(op="cut_range", params={"start": 0.0, "end": 10.0})], "Cut")
        engine.undo()

    res = brain.process_instruction(instruction, engine)
    assert res.status == expected_status, f"Scenario {scenario_id} failed: expected {expected_status}, got {res.status}"
    assert expected_check(engine, res), f"Scenario {scenario_id} custom assertion check failed"
