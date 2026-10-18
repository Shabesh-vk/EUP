"""
Test suite validating the 8-step worked example from the IncuBrix Brief.
Must-Have #4: The same session always produces the same timeline across 3 runs.
"""

import pytest
from incubrix_engine.core.models import Transcript, Word
from incubrix_engine.core.timeline_engine import TimelineEngine
from incubrix_engine.ai.brain import VideoEditingBrain


def create_sample_interview_transcript() -> Transcript:
    """
    Creates a realistic 5-minute (300s) interview transcript with:
    - 'welcome to the channel' at 42.0s - 44.0s
    - Pricing mentions at 1:05 (65s), 2:40 (160s), and 3:15 (195s)
    """
    words = []
    # 0 to 41s
    words.append(Word(id=0, text="Hello", start=0.0, end=0.8))
    words.append(Word(id=1, text="everyone", start=0.9, end=1.5))
    
    # 42s to 44s: "welcome to the channel"
    words.append(Word(id=2, text="welcome", start=42.0, end=42.5))
    words.append(Word(id=3, text="to", start=42.6, end=42.8))
    words.append(Word(id=4, text="the", start=42.9, end=43.1))
    words.append(Word(id=5, text="channel", start=43.2, end=44.0))

    # Pricing mention 1 at 1:05 (65s)
    words.append(Word(id=6, text="our", start=64.0, end=64.8))
    words.append(Word(id=7, text="pricing", start=65.0, end=66.0))
    words.append(Word(id=8, text="tiers", start=66.2, end=67.0))

    # Pricing mention 2 at 2:40 (160s)
    words.append(Word(id=9, text="about", start=159.0, end=159.8))
    words.append(Word(id=10, text="pricing", start=160.0, end=161.0))
    words.append(Word(id=11, text="details", start=161.2, end=162.0))

    # Pricing mention 3 at 3:15 (195s)
    words.append(Word(id=12, text="final", start=194.0, end=194.8))
    words.append(Word(id=13, text="price", start=195.0, end=196.0))

    # End
    words.append(Word(id=14, text="thanks", start=295.0, end=296.0))
    words.append(Word(id=15, text="bye", start=297.0, end=298.0))

    return Transcript(words=words, duration=300.0)


def run_worked_example_session():
    transcript = create_sample_interview_transcript()
    engine = TimelineEngine(transcript, source_video_url="https://example.com/interview.mp4")
    brain = VideoEditingBrain()
    results = []

    # Step 1: Add caption 'Welcome!' when I say welcome to the channel
    res1 = brain.process_instruction("Add a caption 'Welcome!' when I say welcome to the channel", engine)
    assert res1.status == "applied"
    cap = engine.timeline.captions[0]
    assert cap.text == "Welcome!"
    assert cap.timeline_start == 42.0
    results.append(res1)

    # Step 2: Cut the first 30 seconds
    res2 = brain.process_instruction("Cut the first 30 seconds", engine)
    assert res2.status == "applied"
    # Video is 30s shorter: 300 - 30 = 270s
    assert engine.get_current_duration() == 270.0
    # Caption now plays at 0:12-0:14 (42 - 30 = 12)
    assert cap.timeline_start == 12.0
    results.append(res2)

    # Step 3: Remove the part about pricing -> needs clarification
    res3 = brain.process_instruction("Remove the part about pricing", engine)
    assert res3.status == "needs_clarification"
    assert "three times" in res3.clarification.question
    results.append(res3)

    # Step 3 reply: "the second one"
    res3_reply = brain.process_instruction(
        instruction="Remove the part about pricing",
        engine=engine,
        answer="the second one",
        pending_clarification=res3.clarification.model_dump()
    )
    assert res3_reply.status == "applied"
    results.append(res3_reply)

    # Step 4: Speed up from 1:00 to 1:30 by 2x
    res4 = brain.process_instruction("Speed up from 1:00 to 1:30 by 2x", engine)
    assert res4.status == "applied"
    assert "original source time policy" in res4.summary
    results.append(res4)

    # Step 5: Actually, put the intro back
    res5 = brain.process_instruction("Actually, put the intro back", engine)
    assert res5.status == "applied"
    # Intro returned: caption is back at 0:42!
    assert engine.timeline.captions[0].timeline_start == 42.0
    results.append(res5)

    # Step 6: Undo -> reverses step 5 only. The intro is cut again!
    res6 = brain.process_instruction("Undo", engine)
    assert res6.status == "applied"
    assert engine.timeline.captions[0].timeline_start == 12.0
    results.append(res6)

    # Step 7: Make that caption red
    res7 = brain.process_instruction("Make that caption red", engine)
    assert res7.status == "applied"
    assert engine.timeline.captions[0].style.color == "red"
    results.append(res7)

    return results, engine.get_timeline_hash()


def test_worked_example_8_steps():
    results, final_hash = run_worked_example_session()
    assert len(results) == 8


def test_determinism_across_three_runs():
    """Must-Have #4: Run each session 3 times and verify timeline_hash is 100% identical."""
    _, hash1 = run_worked_example_session()
    _, hash2 = run_worked_example_session()
    _, hash3 = run_worked_example_session()

    assert hash1 == hash2 == hash3, f"Non-deterministic timeline hashes: {hash1}, {hash2}, {hash3}"
