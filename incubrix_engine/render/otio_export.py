"""
OpenTimelineIO (OTIO) Exporter.
Requirement (Outstanding level): The timeline exports to OpenTimelineIO so other editors can open it.
"""

from pathlib import Path
import opentimelineio as otio
from ..core.models import Timeline


def export_timeline_to_otio(timeline: Timeline, output_path: str | Path) -> otio.schema.Timeline:
    """
    Exports IncuBrix Timeline to standard OpenTimelineIO Timeline schema.
    Compatible with DaVinci Resolve, Premiere Pro, Final Cut Pro, etc.
    """
    otio_timeline = otio.schema.Timeline(name="IncuBrix_Edited_Timeline")
    rate = timeline.fps or 30.0

    video_track = otio.schema.Track(name="Video_Track", kind=otio.schema.TrackKind.Video)
    audio_track = otio.schema.Track(name="Audio_Track", kind=otio.schema.TrackKind.Audio)
    subtitle_track = otio.schema.Track(name="Captions_Track", kind=otio.schema.TrackKind.Video)

    media_ref = otio.schema.ExternalReference(
        target_url=timeline.source_video_url,
        available_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, rate),
            duration=otio.opentime.RationalTime(int(timeline.original_duration * rate), rate),
        ),
    )

    # 1. Add active video/audio segments
    for idx, seg in enumerate(timeline.segments):
        src_start_frame = int(seg.source_start * rate)
        src_dur_frame = int(seg.source_duration * rate)

        src_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(src_start_frame, rate),
            duration=otio.opentime.RationalTime(src_dur_frame, rate),
        )

        v_clip = otio.schema.Clip(
            name=f"Clip_{idx}_{seg.id}",
            media_reference=media_ref,
            source_range=src_range,
        )

        # Handle speed changes via LinearTimeWarp effect
        if abs(seg.speed - 1.0) > 1e-4:
            speed_effect = otio.schema.LinearTimeWarp(
                name=f"Speed_{seg.speed}x",
                time_scalar=seg.speed,
            )
            v_clip.effects.append(speed_effect)

        video_track.append(v_clip)

        a_clip = otio.schema.Clip(
            name=f"Audio_{idx}_{seg.id}",
            media_reference=media_ref,
            source_range=src_range,
        )
        audio_track.append(a_clip)

    otio_timeline.tracks.append(video_track)
    otio_timeline.tracks.append(audio_track)

    # 2. Add Markers for Captions and Effects
    for cap in timeline.captions:
        if cap.is_active and cap.timeline_start is not None and cap.timeline_end is not None:
            marker_start_frame = int(cap.timeline_start * rate)
            marker_dur_frame = max(1, int((cap.timeline_end - cap.timeline_start) * rate))
            marker = otio.schema.Marker(
                name=f"Caption: {cap.text}",
                marked_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(marker_start_frame, rate),
                    duration=otio.opentime.RationalTime(marker_dur_frame, rate),
                ),
                color=otio.schema.MarkerColor.RED if cap.style.color.lower() == "red" else otio.schema.MarkerColor.CYAN,
                metadata={"incubrix": cap.model_dump()},
            )
            video_track.markers.append(marker)

    # Save to disk
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(otio_timeline, str(path))
    return otio_timeline
