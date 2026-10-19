"""
Unit test verifying OpenTimelineIO (.otio) export of IncuBrix Timelines.
"""

from core.otio_export import export_timeline_to_otio
from core.operations import AddCaptionOperation, SpeedRangeOperation, CutRangeOperation
from core.engine import TimelineEngine
from tests.fixtures.transcript_fixtures import create_test_timeline
import opentimelineio as otio


def test_otio_export():
    timeline = create_test_timeline(duration_seconds=120.0)
    engine = TimelineEngine(timeline)

    # Add edits: cut, speed, caption
    engine.dispatch_operation(AddCaptionOperation(text="Intro Caption", source_start_ticks=10000, source_end_ticks=15000, color="red"))
    engine.dispatch_operation(CutRangeOperation(start_ticks=0, end_ticks=5000))
    engine.dispatch_operation(SpeedRangeOperation(start_ticks=20000, end_ticks=30000, speed_ratio=2.0))

    otio_timeline = export_timeline_to_otio(timeline)

    assert isinstance(otio_timeline, otio.schema.Timeline)
    assert len(otio_timeline.tracks) == 2  # Video & Audio tracks

    v_track = otio_timeline.tracks[0]
    a_track = otio_timeline.tracks[1]
    assert v_track.kind == otio.schema.TrackKind.Video
    assert a_track.kind == otio.schema.TrackKind.Audio

    # Verify speed effect exists on sped-up clips
    speed_effects = [e for clip in v_track for e in clip.effects if isinstance(e, otio.schema.LinearTimeWarp)]
    assert len(speed_effects) > 0
    assert speed_effects[0].time_scalar == 2.0

    # Verify markers for captions exist
    assert len(v_track.markers) == 1
    assert v_track.markers[0].name == "Intro Caption"
    assert v_track.markers[0].color == otio.schema.MarkerColor.RED
