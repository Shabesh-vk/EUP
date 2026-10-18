"""Tests for OpenTimelineIO (.otio) export."""

from pathlib import Path
import opentimelineio as otio
from engine.core.timeline import Timeline
from engine.core.otio_export import export_to_otio
from engine.media.probe import probe_media_file
from engine.media.transcriber import MockTranscriber


def test_export_timeline_to_otio(tmp_path):
    media = probe_media_file("sample.mp4")
    trans, _ = MockTranscriber().transcribe("sample.mp4")
    timeline = Timeline(source=media, transcript=trans)

    # Perform edits
    timeline.apply_cut(0.0, 30.0, source_relative=True)
    timeline.apply_speed(40.0, 60.0, speed=2.0, source_relative=True)
    timeline.apply_add_caption(text="Test Caption", word_ids=["w_13"])

    otio_file = tmp_path / "test_sequence.otio"
    exported_path = export_to_otio(timeline, str(otio_file))

    assert Path(exported_path).exists()

    # Re-read exported OTIO file to verify validity
    read_otio = otio.adapters.read_from_file(exported_path)
    assert isinstance(read_otio, otio.schema.Timeline)
    assert len(read_otio.tracks) >= 2  # V1 and A1 tracks
    assert len(read_otio.tracks[0]) == len(timeline.clips)
