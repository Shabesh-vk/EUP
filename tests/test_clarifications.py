"""Tests for Three-Way Answers ('applied', 'needs_clarification', 'rejected') and Ambiguity handling."""

import pytest
from engine.core.timeline import Timeline
from engine.parser.nl_parser import InstructionEngine
from engine.parser.llm_adapter import RuleBasedMockAdapter
from engine.media.probe import probe_media_file
from engine.media.transcriber import MockTranscriber


@pytest.fixture
def engine():
    media = probe_media_file("sample.mp4")
    trans, _ = MockTranscriber().transcribe("sample.mp4")
    timeline = Timeline(source=media, transcript=trans, time_policy="original")
    return InstructionEngine(timeline=timeline, llm_adapter=RuleBasedMockAdapter())


def test_three_way_answer_applied(engine):
    res = engine.execute_instruction("Cut the first 30 seconds")
    assert res.status == "applied"
    assert res.operations is not None
    assert res.summary is not None
    assert res.timeline_hash is not None


def test_three_way_answer_needs_clarification(engine):
    res = engine.execute_instruction("Remove the part about pricing")
    assert res.status == "needs_clarification"
    assert res.question is not None
    assert "pricing is mentioned" in res.question
    assert res.options is not None
    assert len(res.options) >= 2


def test_three_way_answer_rejected(engine):
    # Impossible cut (cutting entire video)
    res = engine.execute_instruction("Cut everything")
    assert res.status == "rejected"
    assert res.reason is not None
    assert "Cannot cut everything" in res.reason


def test_clarification_resolution(engine):
    # Step 1: Prompt triggers clarification
    r1 = engine.execute_instruction("Remove the part about pricing")
    assert r1.status == "needs_clarification"

    # Step 2: Answering clarification applies the edit
    r2 = engine.execute_instruction("Remove the part about pricing", answer="the first one")
    assert r2.status == "applied"
    assert "Applied: removed the selected" in r2.summary
