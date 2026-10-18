"""Automated test suite verifying the IncuBrix 8-step worked example."""

import pytest
from engine.core.timeline import Timeline
from engine.parser.nl_parser import InstructionEngine
from engine.parser.llm_adapter import RuleBasedMockAdapter
from engine.media.probe import probe_media_file
from engine.media.transcriber import MockTranscriber


@pytest.fixture
def session():
    media = probe_media_file("sample.mp4")
    trans, _ = MockTranscriber().transcribe("sample.mp4")
    timeline = Timeline(source=media, transcript=trans, time_policy="original")
    engine = InstructionEngine(timeline=timeline, llm_adapter=RuleBasedMockAdapter())
    return timeline, engine


def test_worked_example_8_steps(session):
    timeline, engine = session

    # Step 1: Add a caption 'Welcome!' when I say welcome to the channel
    r1 = engine.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    assert r1.status == "applied"
    assert "Caption attached to those 4 words" in r1.summary
    assert "0:42-0:44" in r1.summary

    # Step 2: Cut the first 30 seconds
    r2 = engine.execute_instruction("Cut the first 30 seconds")
    assert r2.status == "applied"
    assert "Video is 30 s shorter" in r2.summary
    assert "0:12-0:14" in r2.summary

    # Step 3: Remove the part about pricing
    r3_clarif = engine.execute_instruction("Remove the part about pricing")
    assert r3_clarif.status == "needs_clarification"
    assert "pricing is mentioned three times" in r3_clarif.question.lower()
    assert len(r3_clarif.options) >= 3

    r3_applied = engine.execute_instruction("Remove the part about pricing", answer="the second one")
    assert r3_applied.status == "applied"

    # Step 4: Speed up from 1:00 to 1:30 by 2x
    r4 = engine.execute_instruction("Speed up from 1:00 to 1:30 by 2x")
    assert r4.status == "applied"
    assert "original media time policy" in r4.summary

    # Step 5: Actually, put the intro back
    r5 = engine.execute_instruction("Actually, put the intro back")
    assert r5.status == "applied"
    assert "The first 30 s return" in r5.summary
    assert "caption back at 0:42" in r5.summary

    # Step 6: Undo
    r6 = engine.execute_instruction("Undo")
    assert r6.status == "applied"
    assert "Reverses step 5 only" in r6.summary
    assert "intro is cut again" in r6.summary

    # Step 7: Make that caption red
    r7 = engine.execute_instruction("Make that caption red")
    assert r7.status == "applied"
    assert "Applied to the Welcome! caption" in r7.summary

    # Step 8: Render
    r8 = engine.execute_instruction("render")
    assert r8.status == "applied"
    assert "Audio and video in sync" in r8.summary


def test_determinism_3_runs():
    """Brief Must-have 4: Predictable. Running the same session 3 times produces identical timeline_hash."""
    hashes = []
    for _ in range(3):
        media = probe_media_file("sample.mp4")
        trans, _ = MockTranscriber().transcribe("sample.mp4")
        timeline = Timeline(source=media, transcript=trans, time_policy="original")
        engine = InstructionEngine(timeline=timeline, llm_adapter=RuleBasedMockAdapter())

        engine.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
        engine.execute_instruction("Cut the first 30 seconds")
        engine.execute_instruction("Remove the part about pricing", answer="the second one")
        engine.execute_instruction("Speed up from 1:00 to 1:30 by 2x")
        engine.execute_instruction("Actually, put the intro back")
        engine.execute_instruction("Undo")
        engine.execute_instruction("Make that caption red")
        engine.execute_instruction("render")

        hashes.append(timeline.timeline_hash)

    assert len(set(hashes)) == 1, "Determinism violated: timeline_hash differed across runs!"
