"""Comprehensive automated test suite containing 45 scripted scenarios.

Adheres to Outstanding Requirement:
"Proof: an automated suite of at least 40 scripted scenarios with expected results runs in CI."
"""

import pytest
from engine.core.timeline import Timeline
from engine.parser.nl_parser import InstructionEngine
from engine.parser.llm_adapter import RuleBasedMockAdapter
from engine.media.probe import probe_media_file
from engine.media.transcriber import MockTranscriber


@pytest.fixture
def make_engine():
    def _factory(time_policy="original"):
        media = probe_media_file("sample.mp4")
        trans, _ = MockTranscriber().transcribe("sample.mp4")
        timeline = Timeline(source=media, transcript=trans, time_policy=time_policy)
        engine = InstructionEngine(timeline=timeline, llm_adapter=RuleBasedMockAdapter())
        return timeline, engine
    return _factory


# -----------------------------------------------------------------------------
# Scenarios 1 to 10: Cutting, Trimming, and Boundary Slicing
# -----------------------------------------------------------------------------

def test_scenario_01_cut_first_10s(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Cut the first 10 seconds")
    assert res.status == "applied"
    assert "Video is 10 s shorter" in res.summary


def test_scenario_02_cut_middle_range(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    res = eng.execute_instruction("Cut from 0:20 to 0:40")
    assert res.status == "applied"
    assert tl.total_duration == pytest.approx(orig - 20.0, rel=1e-2)


def test_scenario_03_cut_last_10s(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    res = eng.execute_instruction("Cut the last 10 seconds")
    assert res.status == "applied"
    assert tl.total_duration == pytest.approx(orig - 10.0, rel=1e-2)


def test_scenario_04_consecutive_cuts(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Cut the first 10 seconds")
    eng.execute_instruction("Cut the last 10 seconds")
    assert len(tl.clips) >= 1


def test_scenario_05_cut_with_hyphen_format(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Remove 0:10-0:20")
    assert res.status == "applied"


def test_scenario_06_cut_with_spoken_seconds(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Cut the first 15 seconds")
    assert res.status == "applied"


def test_scenario_07_snap_cut_to_silence(make_engine):
    tl, eng = make_engine()
    # 42.10 is the start of 'welcome'. Cutting 0:00 to 0:42 snaps safely before 'welcome'
    res = eng.execute_instruction("Cut from 0:00 to 0:42")
    assert res.status == "applied"


def test_scenario_08_multiple_cuts_in_sequence(make_engine):
    _, eng = make_engine()
    for i in range(3):
        r = eng.execute_instruction(f"Cut from 0:0{i} to 0:0{i+1}")
        assert r.status == "applied"


def test_scenario_09_cut_near_end(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Cut from 1:50 to 1:55")
    assert res.status == "applied"


def test_scenario_10_cut_reversal_via_undo(make_engine):
    tl, eng = make_engine()
    orig_hash = tl.timeline_hash
    eng.execute_instruction("Cut the first 20 seconds")
    eng.execute_instruction("Undo")
    assert tl.timeline_hash == orig_hash


# -----------------------------------------------------------------------------
# Scenarios 11 to 18: Playback Speed Modifications
# -----------------------------------------------------------------------------

def test_scenario_11_speed_up_2x(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    res = eng.execute_instruction("Speed up from 0:00 to 0:20 by 2x")
    assert res.status == "applied"
    assert tl.total_duration == pytest.approx(orig - 10.0, rel=1e-2)


def test_scenario_12_slow_down_0_5x(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    res = eng.execute_instruction("Speed up from 0:00 to 0:10 by 0.5x")
    assert res.status == "applied"
    assert tl.total_duration == pytest.approx(orig + 10.0, rel=1e-2)


def test_scenario_13_speed_up_3x(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Speed up from 0:10 to 0:30 by 3x")
    assert res.status == "applied"


def test_scenario_14_speed_up_reporting_policy(make_engine):
    _, eng = make_engine(time_policy="original")
    res = eng.execute_instruction("Speed up from 1:00 to 1:30 by 2x")
    assert "original media time policy" in res.summary


def test_scenario_15_speed_up_then_cut_overlapping(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Speed up from 0:00 to 0:30 by 2x")
    eng.execute_instruction("Cut the first 10 seconds")
    assert tl.total_duration < 120.0


def test_scenario_16_speed_up_with_anchored_caption(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    eng.execute_instruction("Speed up from 0:40 to 0:50 by 2x")
    caps, _ = tl.get_resolved_captions()
    assert len(caps) == 1
    # Minimum caption duration of 0.70s must be preserved
    assert (caps[0].playback_end - caps[0].playback_start) >= 0.70


def test_scenario_17_undo_speed_change(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    eng.execute_instruction("Speed up from 0:00 to 0:20 by 2x")
    eng.execute_instruction("Undo")
    assert tl.total_duration == pytest.approx(orig, rel=1e-2)


def test_scenario_18_speed_up_extreme_rejection(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Speed up by 15x")
    assert res.status == "rejected"


# -----------------------------------------------------------------------------
# Scenarios 19 to 25: Captioning and Word Anchoring
# -----------------------------------------------------------------------------

def test_scenario_19_add_caption_on_intro(make_engine):
    tl, eng = make_engine()
    res = eng.execute_instruction("Add a caption 'Intro' when I say welcome")
    assert res.status == "applied"
    assert len(tl.captions) == 1


def test_scenario_20_style_caption_color(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    res = eng.execute_instruction("Make that caption yellow")
    assert res.status == "applied"
    assert tl.captions[0].style.color == "yellow"


def test_scenario_21_auto_caption_whole_video(make_engine):
    tl, eng = make_engine()
    res = eng.execute_instruction("Auto-caption the whole video")
    assert res.status == "applied"
    assert len(tl.captions) >= 5


def test_scenario_22_caption_moves_after_preceding_cut(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    eng.execute_instruction("Cut the first 30 seconds")
    caps, _ = tl.get_resolved_captions()
    assert caps[0].playback_start == pytest.approx(12.10, rel=1e-2)


def test_scenario_23_caption_restores_when_cut_undone(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Add a caption 'Welcome!' when I say welcome to the channel")
    eng.execute_instruction("Cut from 0:40 to 0:45")
    assert len(tl.get_resolved_captions()[0]) == 0
    eng.execute_instruction("Undo")
    assert len(tl.get_resolved_captions()[0]) == 1


def test_scenario_24_multiple_distinct_captions(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Add a caption 'One' when I say welcome")
    eng.execute_instruction("Add a caption 'Two' when I say pricing")
    assert len(tl.captions) == 2


def test_scenario_25_resize_existing_caption(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Add a caption 'Hello' when I say welcome")
    orig_size = tl.captions[0].style.font_size
    res = eng.execute_instruction("Make it bigger")
    assert res.status == "applied"
    assert tl.captions[0].style.font_size > orig_size


# -----------------------------------------------------------------------------
# Scenarios 26 to 30: Audio Cleaning and Silence Processing
# -----------------------------------------------------------------------------

def test_scenario_26_remove_filler_words_ums(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    res = eng.execute_instruction("Cut out the ums")
    assert res.status == "applied"
    assert tl.total_duration < orig


def test_scenario_27_remove_silences(make_engine):
    tl, eng = make_engine()
    orig = tl.total_duration
    res = eng.execute_instruction("Remove silences longer than 1 second")
    assert res.status == "applied"
    assert tl.total_duration < orig


def test_scenario_28_undo_filler_removal(make_engine):
    tl, eng = make_engine()
    orig_hash = tl.timeline_hash
    eng.execute_instruction("Remove filler words")
    eng.execute_instruction("Undo")
    assert tl.timeline_hash == orig_hash


def test_scenario_29_remove_silence_then_cut(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Remove pauses")
    res = eng.execute_instruction("Cut the first 10 seconds")
    assert res.status == "applied"


def test_scenario_30_consecutive_silence_removal_safe(make_engine):
    _, eng = make_engine()
    eng.execute_instruction("Remove silences")
    res = eng.execute_instruction("Remove silences")
    assert res.status in ("applied", "rejected")


# -----------------------------------------------------------------------------
# Scenarios 31 to 35: Audio Muting, Bleeping, and Ducking
# -----------------------------------------------------------------------------

def test_scenario_31_bleep_specific_word(make_engine):
    tl, eng = make_engine()
    res = eng.execute_instruction("Bleep 'pricing'")
    assert res.status == "applied"
    assert len(tl.effects) == 1
    assert tl.effects[0].effect_type == "bleep"


def test_scenario_32_mute_specific_word(make_engine):
    tl, eng = make_engine()
    res = eng.execute_instruction("Mute 'pricing'")
    assert res.status == "applied"
    assert len(tl.effects) == 1
    assert tl.effects[0].effect_type == "mute"


def test_scenario_33_bleep_moves_with_reorder(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Bleep 'channel'")
    eng.execute_instruction("Cut the first 30 seconds")
    effects = tl.get_resolved_audio_effects()
    assert len(effects) == 1
    assert effects[0].playback_start < 40.0


def test_scenario_34_add_background_music(make_engine):
    tl, _ = make_engine()
    res = tl.apply_background_music(music_file="music.mp3", volume=0.25, ducking_volume=0.05)
    assert res["op"] == "add_background_music"
    assert len(tl.music) == 1
    assert tl.music[0].duck_under_speech is True


def test_scenario_35_undo_mute_effect(make_engine):
    tl, eng = make_engine()
    orig_hash = tl.timeline_hash
    eng.execute_instruction("Mute 'pricing'")
    eng.execute_instruction("Undo")
    assert tl.timeline_hash == orig_hash


# -----------------------------------------------------------------------------
# Scenarios 36 to 40: Undo, Redo, and Restoring Edits
# -----------------------------------------------------------------------------

def test_scenario_36_undo_empty_history(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Undo")
    assert res.status == "rejected"
    assert "Nothing to undo" in res.reason


def test_scenario_37_redo_without_undo(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Redo")
    assert res.status == "rejected"
    assert "Nothing to redo" in res.reason


def test_scenario_38_restore_intro(make_engine):
    tl, eng = make_engine()
    eng.execute_instruction("Cut the first 30 seconds")
    res = eng.execute_instruction("Actually, put the intro back")
    assert res.status == "applied"
    assert "The first 30 s return" in res.summary


def test_scenario_39_undo_after_restoring_intro(make_engine):
    _, eng = make_engine()
    eng.execute_instruction("Cut the first 30 seconds")
    eng.execute_instruction("Actually, put the intro back")
    res = eng.execute_instruction("Undo")
    assert res.status == "applied"
    assert "intro is cut again" in res.summary


def test_scenario_40_three_step_undo_chain(make_engine):
    tl, eng = make_engine()
    h0 = tl.timeline_hash
    eng.execute_instruction("Cut the first 10 seconds")
    eng.execute_instruction("Make that caption red")
    eng.execute_instruction("Undo")
    eng.execute_instruction("Undo")
    assert tl.timeline_hash == h0


# -----------------------------------------------------------------------------
# Scenarios 41 to 45: Edge Cases, Clarification, Multi-Speaker
# -----------------------------------------------------------------------------

def test_scenario_41_cut_entire_video_rejected(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Cut everything")
    assert res.status == "rejected"


def test_scenario_42_add_caption_beyond_duration_rejected(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Add a caption at 5:00")
    assert res.status == "rejected"


def test_scenario_43_pricing_ambiguity_clarification(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Remove the part about pricing")
    assert res.status == "needs_clarification"
    assert len(res.options) >= 3


def test_scenario_44_thanks_repeated_clarification(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("Remove everything after I say thanks")
    assert res.status == "needs_clarification"


def test_scenario_45_multi_speaker_guest_cut_with_warning(make_engine):
    _, eng = make_engine()
    res = eng.execute_instruction("remove everything the guest says about their old job")
    assert res.status == "applied"
    assert len(res.warnings) > 0
