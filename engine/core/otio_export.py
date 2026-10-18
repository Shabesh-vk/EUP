"""OpenTimelineIO export module.

Adheres to Outstanding Requirement:
"Export: the timeline exports to OpenTimelineIO so other editors can open it."
Serializes the edited timeline into industry-standard .otio format.
"""

from typing import Optional
from pathlib import Path
import opentimelineio as otio
from engine.core.timeline import Timeline


def export_to_otio(
    timeline: Timeline,
    output_path: str,
    timeline_name: str = "IncuBrix Edited Sequence"
) -> str:
    """Exports the current timeline state to an OpenTimelineIO (.otio) file."""
    fps = timeline.source.fps or 30.0
    otio_timeline = otio.schema.Timeline(name=timeline_name)

    video_track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    audio_track = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)

    media_ref = otio.schema.ExternalReference(
        target_url=Path(timeline.source.file_path).as_uri(),
        available_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=otio.opentime.RationalTime(timeline.source.duration_s * fps, fps)
        )
    )

    for i, clip in enumerate(timeline.clips):
        start_frame = int(round(clip.source_start * fps))
        duration_frames = int(round(clip.source_duration * fps))

        time_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(start_frame, fps),
            duration=otio.opentime.RationalTime(duration_frames, fps)
        )

        v_clip = otio.schema.Clip(
            name=f"Clip_{i+1}",
            media_reference=media_ref,
            source_range=time_range
        )

        # If clip has non-standard speed, attach LinearTimeWarp effect
        if abs(clip.speed - 1.0) > 1e-3:
            warp = otio.schema.LinearTimeWarp(time_scalar=clip.speed)
            v_clip.effects.append(warp)

        video_track.append(v_clip)

        a_clip = otio.schema.Clip(
            name=f"Audio_{i+1}",
            media_reference=media_ref,
            source_range=time_range
        )
        if abs(clip.speed - 1.0) > 1e-3:
            warp = otio.schema.LinearTimeWarp(time_scalar=clip.speed)
            a_clip.effects.append(warp)

        audio_track.append(a_clip)

    otio_timeline.tracks.append(video_track)
    otio_timeline.tracks.append(audio_track)

    # Attach captions as markers on the timeline
    resolved_caps, _ = timeline.get_resolved_captions()
    for cap in resolved_caps:
        marker_start = otio.opentime.RationalTime(round(cap.playback_start * fps), fps)
        marker_dur = otio.opentime.RationalTime(round((cap.playback_end - cap.playback_start) * fps), fps)
        marker = otio.schema.Marker(
            name=f"Caption: {cap.text}",
            marked_range=otio.opentime.TimeRange(marker_start, marker_dur),
            color=otio.schema.MarkerColor.YELLOW
        )
        video_track.markers.append(marker)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(otio_timeline, str(output_file))

    return str(output_file)
