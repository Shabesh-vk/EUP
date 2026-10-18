"""Tests for IncuBrix Assessment Hard Cases."""

import pytest
from engine.core.timeline import Timeline
from engine.parser.nl_parser import InstructionEngine
from engine.parser.llm_adapter import RuleBasedMockAdapter
from engine.media.probe import probe_media_file
from engine.media.transcriber import MockTranscriber


@pytest.fixture
def test_setup():
    media = probe_media_file("sample.mp4")
    trans, _ = MockTranscriber().transcribe("sample.mp4")
    timeline = Timeline(source=media, transcript=trans, time_policy="original")
    engine = InstructionEngine(timeline=timeline, llm_adapter=RuleBasedMockAdapter())
    return timeline, engine


def test_hard_case_caption_cut_and_restored(test_setup):
    """A caption added, then the exact sentence under it cut; then that cut restored (the caption should come back)."""
    timeline, engine = test_setup

    # 1. Add caption on welcome words (42s-44s)
    r1 = engine.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    assert r1.status == "applied"
    assert len(timeline.get_resolved_captions()[0]) == 1

    # 2. Cut the exact sentence under it (40s-45s)
    r2 = engine.execute_instruction("Remove from 0:40 to 0:45")
    assert r2.status == "applied"
    # Caption must now be hidden
    assert len(timeline.get_resolved_captions()[0]) == 0

    # 3. Restore the cut (undo)
    r3 = engine.execute_instruction("Undo")
    assert r3.status == "applied"
    # Caption should come back!
    caps, _ = timeline.get_resolved_captions()
    assert len(caps) == 1
    assert caps[0].text == "Welcome!"
    assert caps[0].playback_start == 42.10


def test_hard_case_repeated_cut(test_setup):
    """'Remove 0:30-0:40' sent twice."""
    timeline, engine = test_setup

    r1 = engine.execute_instruction("Remove 0:30-0:40")
    assert r1.status == "applied"

    # Sent second time
    r2 = engine.execute_instruction("Remove 0:30-0:40")
    # If in original mode, second cut of already removed range is safe/idempotent or rejected
    assert r2.status in ("applied", "rejected")


def test_hard_case_caption_beyond_duration(test_setup):
    """'add a caption at 5:00' on a shorter video."""
    timeline, engine = test_setup  # 120s video (2:00)

    res = engine.execute_instruction("add a caption at 5:00")
    assert res.status == "rejected"
    assert "Out of range" in res.reason or "beyond video duration" in res.reason


def test_hard_case_natural_spoken_time_expressions(test_setup):
    """Times as '80 seconds', 'a minute twenty', 'the last 10 seconds'."""
    from engine.parser.time_parser import parse_timestamp_str, parse_time_range

    assert parse_timestamp_str("80 seconds") == 80.0
    assert parse_timestamp_str("a minute twenty") == 80.0

    r = parse_time_range("the last 10 seconds", total_duration=120.0)
    assert r == (110.0, 120.0)


def test_hard_case_resize_caption_when_none_exists(test_setup):
    """'make it bigger' when no caption exists."""
    timeline, engine = test_setup

    res = engine.execute_instruction("make it bigger")
    assert res.status == "rejected"
    assert "No caption exists" in res.reason


def test_hard_case_ambiguous_phrase_said_four_times(test_setup):
    """'Remove everything after I say thanks' where thanks is said four times."""
    timeline, engine = test_setup

    # First attempt: triggers clarification because thanks is said multiple times
    res = engine.execute_instruction("Remove everything after I say thanks")
    assert res.status == "needs_clarification"
    assert "Thanks is said" in res.question
    assert len(res.options) >= 3

    # Resolve with 'the second one'
    res_ans = engine.execute_instruction("Remove everything after I say thanks", answer="the second one")
    assert res_ans.status == "applied"


def test_hard_case_cut_everything(test_setup):
    """'cut everything' is rejected."""
    timeline, engine = test_setup

    res = engine.execute_instruction("cut everything")
    assert res.status == "rejected"
    assert "Cannot cut everything" in res.reason


def test_hard_case_multi_speaker_guest_and_host(test_setup):
    """Two speakers: 'remove everything the guest says about their old job' removes guest's lines and notes host lead-in."""
    timeline, engine = test_setup

    res = engine.execute_instruction("remove everything the guest says about their old job")
    assert res.status == "applied"
    assert "Removed guest's lines about old job" in res.summary
    assert any("host's lead-in" in w.lower() for w in res.warnings)
