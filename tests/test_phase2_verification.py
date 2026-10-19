"""Verification tests for Phase 2: Instruction Parsing, Disambiguation & Options Display."""

import pytest
from engine.parser.nl_parser import InstructionEngine
from engine.core.timeline import Timeline
from engine.media.probe import probe_media_file
from engine.media.transcriber import get_transcriber
from engine.parser.llm_adapter import RuleBasedMockAdapter


@pytest.fixture
def engine():
    probe = probe_media_file("sample.mp4")
    transcriber = get_transcriber()
    transcript, _ = transcriber.transcribe("sample.mp4")
    timeline = Timeline(probe, transcript)
    adapter = RuleBasedMockAdapter()
    return InstructionEngine(timeline, llm_adapter=adapter)


def test_ambiguous_cut_returns_clarification_with_options(engine):
    """'Cut the video 30sec' must NOT guess or reject blindly; it must return needs_clarification with options."""
    res = engine.execute_instruction("Cut the video 30sec")

    assert res.status == "needs_clarification"
    assert res.question is not None
    assert "cut 30s of the video" in res.question
    assert res.options is not None
    assert len(res.options) == 2
    assert "Cut the first 30 seconds" in res.options[0]
    assert "Cut the last 30 seconds" in res.options[1]


def test_ambiguous_cut_resolved_with_first_option(engine):
    """Answering 'the first one' to an ambiguous cut cuts from 0.0s to 30.0s."""
    # Step 1: Prompt triggers clarification
    res1 = engine.execute_instruction("Cut the video 30sec")
    assert res1.status == "needs_clarification"

    # Step 2: Answering resolves to cut
    res2 = engine.execute_instruction("Cut the video 30sec", answer="the first one")
    assert res2.status == "applied"
    assert res2.duration_s < 120.0
    assert len(engine.timeline.clips) == 1
    # First clip should start after the cut
    assert engine.timeline.clips[0].source_start >= 29.0


def test_ambiguous_cut_resolved_with_last_option(engine):
    """Answering 'the second one' or 'last' cuts the end of the video."""
    res = engine.execute_instruction("Cut the video 30sec", answer="the second one")
    assert res.status == "applied"
    assert res.duration_s < 120.0
    # First clip starts at 0, end is trimmed
    assert engine.timeline.clips[0].source_start == 0.0


def test_ambiguous_cut_resolved_with_option_label_or_number(engine):
    """Answering with the full option label (which contains 'seconds') or '1' cuts the beginning."""
    res_num = engine.execute_instruction("Cut the video 30sec", answer="1")
    assert res_num.status == "applied"
    assert engine.timeline.clips[0].source_start >= 29.0

    # Reset
    engine.timeline._reset_to_base()
    res_lbl = engine.execute_instruction("Cut the video 30sec", answer="Cut the first 30 seconds (0:00 - 0:30)")
    assert res_lbl.status == "applied"
    assert engine.timeline.clips[0].source_start >= 29.0

