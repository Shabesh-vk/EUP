"""
OpenTimelineIO (.otio) export adapter for the IncuBrix Editing Engine.
Enables interoperability with Adobe Premiere Pro, DaVinci Resolve, and Final Cut Pro.
Conforms to the Outstanding level specification.
"""

from __future__ import annotations
import os
from typing import Optional
import opentimelineio as otio
from core.schema import Timeline
from core.time_ticks import ticks_to_seconds


def export_timeline_to_otio(timeline: Timeline, output_file: Optional[str] = None) -> otio.schema.Timeline:
    """
    Export an IncuBrix Timeline to an OpenTimelineIO Timeline object.
    Optionally serializes to an .otio JSON file.
    """
    fps = timeline.source_media.fps or 30.0

    otio_timeline = otio.schema.Timeline(
        name=f"IncuBrix_{timeline.project_id}",
        global_start_time=otio.opentime.RationalTime(0, fps),
    )

    video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
    audio_track = otio.schema.Track(name="Audio Track", kind=otio.schema.TrackKind.Audio)

    media_ref = otio.schema.ExternalReference(
        target_url=timeline.source_media.filename,
        available_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=otio.opentime.RationalTime(
                round(timeline.source_media.duration_ticks * fps / 1000.0), fps
            ),
        ),
    )

    # Add clip segments to tracks
    for seg in timeline.segments:
        start_frame = int(round(seg.source_start_ticks * fps / 1000.0))
        dur_frame = max(1, int(round(seg.duration_source_ticks * fps / 1000.0)))

        time_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(start_frame, fps),
            duration=otio.opentime.RationalTime(dur_frame, fps),
        )

        v_clip = otio.schema.Clip(
            name=seg.segment_id,
            media_reference=media_ref,
            source_range=time_range,
        )

        a_clip = otio.schema.Clip(
            name=f"{seg.segment_id}_audio",
            media_reference=media_ref,
            source_range=time_range,
        )

        # Attach speed change effect if not 1.0x
        if abs(seg.speed_ratio - 1.0) > 1e-4:
            speed_effect = otio.schema.LinearTimeWarp(
                name=f"Speed_{seg.speed_ratio}x",
                time_scalar=seg.speed_ratio,
            )
            v_clip.effects.append(speed_effect)
            a_clip.effects.append(speed_effect)

        video_track.append(v_clip)
        audio_track.append(a_clip)

    otio_timeline.tracks.append(video_track)
    otio_timeline.tracks.append(audio_track)

    # Attach captions as markers on the video track
    from core.engine import TimelineEngine
    engine = TimelineEngine(timeline)

    for cap in timeline.effects.captions:
        if not cap.is_suppressed:
            t_start = engine.project_source_to_output(cap.source_start_ticks)
            t_end = engine.project_source_to_output(cap.source_end_ticks)
            if t_start is not None and t_end is not None:
                start_frame = int(round(t_start * fps / 1000.0))
                dur_frame = max(1, int(round((t_end - t_start) * fps / 1000.0)))
                marker_color = otio.schema.MarkerColor.RED if "red" in cap.color.lower() else otio.schema.MarkerColor.GREEN

                marker = otio.schema.Marker(
                    name=cap.text,
                    marked_range=otio.opentime.TimeRange(
                        start_time=otio.opentime.RationalTime(start_frame, fps),
                        duration=otio.opentime.RationalTime(dur_frame, fps),
                    ),
                    color=marker_color,
                )
                video_track.markers.append(marker)

    if output_file:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        otio.adapters.write_to_file(otio_timeline, output_file)

    return otio_timeline
