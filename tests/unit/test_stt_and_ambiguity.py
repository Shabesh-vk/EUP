"""
Unit tests for STT transcription adapters, provenance, and conversational ambiguity resolution:
- FasterWhisperAdapter and MockTranscriptionAdapter
- Missing credentials / configuration error enforcement
- Multi-speaker dialogue ambiguity ('remove what the guest said about their old job')
- Option 1 (cut only guest response) vs Option 2 (cut both host lead-in and guest response)
- Missing target text rejection
- Duration exceeding video rejection
"""

import pytest
import os
from core.engine import TimelineEngine
from core.schema import TranscriptWord
from stt.base import BaseTranscriptionAdapter
from stt.mock_adapter import MockTranscriptionAdapter
from stt.whisper_adapter import FasterWhisperAdapter
from stt.factory import get_transcription_adapter
from nlu.dispatcher import process_instruction
from tests.fixtures.transcript_fixtures import create_test_timeline
from api.errors import IncuBrixException


def test_mock_transcription_adapter():
    adapter = MockTranscriptionAdapter()
    assert adapter.provider_name == "mock"
    assert adapter.supports_native_diarization is True

    transcript = adapter.transcribe("dummy.mp4", duration_ticks=60000)
    assert transcript.is_mock is True
    assert len(transcript.words) > 0
    assert all(w.end_ticks <= 60000 for w in transcript.words)


def test_stt_factory_modes_and_errors():
    # 1. Mode 'mock' returns MockTranscriptionAdapter
    adapter_mock = get_transcription_adapter("mock")
    assert isinstance(adapter_mock, MockTranscriptionAdapter)

    # 2. Mode 'invalid' raises 400 IncuBrixException
    with pytest.raises(IncuBrixException) as exc_info:
        get_transcription_adapter("unsupported_provider")
    assert exc_info.value.code == "INVALID_TRANSCRIPTION_MODE"

    # 3. Mode 'real' returns FasterWhisperAdapter
    adapter_real = get_transcription_adapter("real")
    assert isinstance(adapter_real, FasterWhisperAdapter)
    assert adapter_real.provider_name == "faster-whisper"
    assert adapter_real.supports_native_diarization is False


def test_multi_speaker_dialogue_ambiguity_lead_in():
    """
    Test: 'remove what the guest said about their old job'
    Host says: 'tell me about your old job' (220s - 222.2s)
    Guest says: 'at my old job i managed video pipelines' (222.5s - 226.2s)
    System must ask whether to cut only guest or both host and guest!
    """
    timeline = create_test_timeline(duration_seconds=300.0)
    engine = TimelineEngine(timeline)

    # 1. Ask instruction
    res, pending = process_instruction(engine, "remove what the guest said about their old job")
    assert res.status == "needs_clarification"
    assert "host's question" in res.question.lower()
    assert len(res.options) == 3
    assert pending is not None
    assert pending.get("type") == "speaker_lead_in"

    # 2. Test Choice 1: "Cut only the guest's response (keep the host's question)"
    engine1 = TimelineEngine(create_test_timeline(duration_seconds=300.0))
    res1, pending1 = process_instruction(engine1, "1", pending_context=pending)
    assert res1.status == "applied"
    assert "kept host question" in res1.summary.lower() or "kept host's lead-in" in res1.summary.lower()
    # Host's question (220s) must still be playable in timeline!
    assert engine1.project_source_to_output(221000) is not None
    # Guest's response (224s) must be cut!
    assert engine1.project_source_to_output(224000) is None

    # 3. Test Choice 2: "Cut both the host's question and the guest's response"
    engine2 = TimelineEngine(create_test_timeline(duration_seconds=300.0))
    res2, pending2 = process_instruction(engine2, "2", pending_context=pending)
    assert res2.status == "applied"
    assert "both" in res2.summary.lower()
    # Both host's question (221s) AND guest's response (224s) must be cut!
    assert engine2.project_source_to_output(221000) is None
    assert engine2.project_source_to_output(224000) is None


def test_target_text_not_found_rejection():
    """
    Test: 'remove the part about quantum physics'
    Text does not appear in transcript -> must return status 'rejected' with clear reason.
    """
    timeline = create_test_timeline(duration_seconds=300.0)
    engine = TimelineEngine(timeline)

    res, pending = process_instruction(engine, "remove the part about quantum physics")
    assert res.status == "rejected"
    assert "not found in the transcript" in res.summary.lower()
    assert pending is None


def test_duration_exceeding_video_rejection():
    """
    Test: 'cut from 0:00 to 10:00' on a 5-minute (300s) video.
    Must return status 'rejected' indicating 10:00 exceeds 300s.
    """
    timeline = create_test_timeline(duration_seconds=300.0)
    engine = TimelineEngine(timeline)

    # 1. Range exceeding duration
    res_range, _ = process_instruction(engine, "cut 0:00 to 10:00")
    assert res_range.status == "rejected"
    assert "exceeds video duration" in res_range.summary.lower()

    # 2. First N minutes exceeding duration
    res_first, _ = process_instruction(engine, "cut the first 10 minutes")
    assert res_first.status == "rejected"
    assert "exceeds video duration" in res_first.summary.lower()
