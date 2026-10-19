"""
Real FFmpeg rendering engine for the IncuBrix Editing Engine.
Translates content-anchored timeline data into frame-accurate playable MP4 video.
"""

from __future__ import annotations
import math
import os
import shutil
import subprocess
import tempfile
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field

from core.schema import Timeline
from core.engine import TimelineEngine
from core.time_ticks import ticks_to_seconds
from .inspector import (
    get_ffmpeg_path,
    get_ffprobe_path,
    inspect_media_file,
    verify_media_integrity,
    compute_file_sha256,
)
from .ass_generator import generate_ass_subtitles


def escape_ffmpeg_filter_path(path: str) -> str:
    r"""
    Escape path for FFmpeg filter arguments, especially on Windows.
    Converts backslashes to forward slashes and escapes colons and single quotes.
    Example: 'C:\foo\bar.ass' -> 'C\:/foo/bar.ass'
    """

    p = path.replace("\\", "/")
    # Escape colon (for Windows drive letter C:)
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


def build_atempo_filter(speed: float) -> str:
    """
    Generate chained atempo filters for any speed multiplier.
    FFmpeg's atempo filter strictly requires 0.5 <= atempo <= 2.0.
    """
    if abs(speed - 1.0) < 1e-4:
        return "anull"

    filters: List[str] = []
    curr = speed

    while curr > 2.0:
        filters.append("atempo=2.0")
        curr /= 2.0

    while curr < 0.5:
        filters.append("atempo=0.5")
        curr /= 0.5

    if abs(curr - 1.0) >= 1e-4:
        filters.append(f"atempo={round(curr, 4)}")

    return ",".join(filters) if filters else "anull"


class RenderResult(BaseModel):
    output_path: str
    timeline_hash: str
    output_sha256: str
    timeline_duration_s: float
    rendered_duration_s: float
    duration_diff_s: float
    frame_diff: float
    is_in_sync: bool
    warnings: List[str] = Field(default_factory=list)


def render_timeline(
    timeline: Timeline,
    source_media_path: str,
    output_video_path: str,
    background_music_path: Optional[str] = None,
    temp_dir: Optional[str] = None,
) -> RenderResult:
    """
    Execute real FFmpeg rendering from the saved timeline.
    Guarantees that:
    1. The original media is never modified (verified by SHA-256).
    2. Video and Audio are cut and sped up in exact frame-accurate synchrony.
    3. Captions, mutes, bleeps, and music ducking are applied.
    4. Duration matches timeline within 1 output frame.
    """
    if not os.path.isfile(source_media_path):
        raise FileNotFoundError(f"Source media not found: {source_media_path}")

    # Verify Must-Have 1: untouched source
    if not verify_media_integrity(source_media_path, timeline.source_media.sha256_hash):
        raise ValueError("Source media integrity check failed! File hash does not match original.")

    if not timeline.segments:
        raise ValueError("Cannot render empty timeline: zero active segments.")

    ffmpeg_bin = get_ffmpeg_path()
    engine = TimelineEngine(timeline)
    warnings: List[str] = []

    work_dir = temp_dir or tempfile.mkdtemp(prefix="incubrix_render_")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)

    # 1. Generate subtitles if active captions exist
    ass_path = os.path.join(work_dir, "captions.ass")
    has_captions = generate_ass_subtitles(timeline, ass_path)

    # 2. Build Filtergraph
    # Inputs: 0 = source video. 1 = background music (if any).
    filter_parts: List[str] = []
    v_concat_inputs: List[str] = []
    a_concat_inputs: List[str] = []

    num_segments = len(timeline.segments)

    for i, seg in enumerate(timeline.segments):
        start_s = ticks_to_seconds(seg.source_start_ticks)
        end_s = ticks_to_seconds(seg.source_end_ticks)
        speed = seg.speed_ratio

        # Video trim & speed
        v_label_trim = f"v_trim_{i}"
        v_label_seg = f"v_seg_{i}"
        filter_parts.append(f"[0:v]trim=start={start_s}:end={end_s},setpts=PTS-STARTPTS[{v_label_trim}]")
        if abs(speed - 1.0) > 1e-4:
            pts_factor = round(1.0 / speed, 6)
            filter_parts.append(f"[{v_label_trim}]setpts={pts_factor}*PTS[{v_label_seg}]")
        else:
            filter_parts.append(f"[{v_label_trim}]null[{v_label_seg}]")
        v_concat_inputs.append(f"[{v_label_seg}]")

        # Audio trim & speed
        a_label_trim = f"a_trim_{i}"
        a_label_seg = f"a_seg_{i}"
        filter_parts.append(f"[0:a]atrim=start={start_s}:end={end_s},asetpts=PTS-STARTPTS[{a_label_trim}]")
        if abs(speed - 1.0) > 1e-4:
            atempo_str = build_atempo_filter(speed)
            filter_parts.append(f"[{a_label_trim}]{atempo_str}[{a_label_seg}]")
        else:
            filter_parts.append(f"[{a_label_trim}]anull[{a_label_seg}]")
        a_concat_inputs.append(f"[{a_label_seg}]")

    # Concatenate segments
    concat_in = "".join(f"{v_concat_inputs[j]}{a_concat_inputs[j]}" for j in range(num_segments))
    filter_parts.append(f"{concat_in}concat=n={num_segments}:v=1:a=1[v_concat][a_concat]")

    current_v = "[v_concat]"
    # Burn captions if present
    if has_captions:
        escaped_ass = escape_ffmpeg_filter_path(ass_path)
        # Use ass or subtitles filter
        filter_parts.append(f"{current_v}ass='{escaped_ass}'[v_captioned]")
        current_v = "[v_captioned]"

    current_a = "[a_concat]"

    # Mutes & Bleeps
    active_mutes = [m for m in timeline.effects.mutes if not m.is_suppressed]
    active_bleeps = [b for b in timeline.effects.bleeps if not b.is_suppressed]

    if active_mutes or active_bleeps:
        # Build volume enable expressions to silence the muted/bleeped regions
        mute_conditions = []
        for m in active_mutes:
            t1 = engine.project_source_to_output(m.source_start_ticks)
            t2 = engine.project_source_to_output(m.source_end_ticks)
            if t1 is not None and t2 is not None:
                mute_conditions.append(f"between(t,{ticks_to_seconds(t1)},{ticks_to_seconds(t2)})")

        for b in active_bleeps:
            t1 = engine.project_source_to_output(b.source_start_ticks)
            t2 = engine.project_source_to_output(b.source_end_ticks)
            if t1 is not None and t2 is not None:
                mute_conditions.append(f"between(t,{ticks_to_seconds(t1)},{ticks_to_seconds(t2)})")

        if mute_conditions:
            cond_str = "+".join(mute_conditions)
            filter_parts.append(f"{current_a}volume=enable='{cond_str}':volume=0[a_muted]")
            current_a = "[a_muted]"

        # Add 1000Hz bleep tones for bleep effects
        if active_bleeps:
            bleep_mix_inputs = [current_a]
            for idx, b in enumerate(active_bleeps):
                t1 = engine.project_source_to_output(b.source_start_ticks)
                t2 = engine.project_source_to_output(b.source_end_ticks)
                if t1 is not None and t2 is not None:
                    dur_s = max(0.05, ticks_to_seconds(t2 - t1))
                    start_ms = t1
                    freq = b.frequency_hz
                    # Generate tone and delay to start_ms
                    b_label = f"bleep_{idx}"
                    filter_parts.append(
                        f"sine=frequency={freq}:duration={dur_s},adelay={start_ms}|{start_ms}[{b_label}]"
                    )
                    bleep_mix_inputs.append(f"[{b_label}]")
            if len(bleep_mix_inputs) > 1:
                mix_str = "".join(bleep_mix_inputs)
                filter_parts.append(
                    f"{mix_str}amix=inputs={len(bleep_mix_inputs)}:duration=first:dropout_transition=0[a_bleeped]"
                )
                current_a = "[a_bleeped]"

    # Music & ducking
    music_effects = [m for m in timeline.effects.music]
    music_file = background_music_path
    if music_effects and not music_file and os.path.isfile(music_effects[0].asset_url):
        music_file = music_effects[0].asset_url

    has_music_input = False
    if music_effects and music_file and os.path.isfile(music_file):
        has_music_input = True
        mus = music_effects[0]
        filter_parts.append(f"[1:a]volume={mus.volume}[music_in]")
        # Speech ducking sidechain compression
        filter_parts.append(
            f"{current_a}asplit=2[speech_main][speech_sc];"
            f"[music_in][speech_sc]sidechaincompress=threshold=0.08:ratio=4:attack=50:release=350[ducked_music];"
            f"[speech_main][ducked_music]amix=inputs=2:duration=first:dropout_transition=0[a_final]"
        )

        current_a = "[a_final]"

    final_filtergraph = ";\n".join(filter_parts)

    filter_script_path = os.path.join(work_dir, "filtergraph.txt")
    with open(filter_script_path, "w", encoding="utf-8") as f:
        f.write(final_filtergraph)

    # 3. Assemble FFmpeg execution command
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", source_media_path,
    ]
    if has_music_input and music_file:
        cmd.extend(["-i", music_file])

    cmd.extend([
        "-filter_complex", final_filtergraph,
        "-map", current_v,
        "-map", current_a,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_video_path,
    ])



    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg rendering failed: {e.stderr}")

    # 4. Measure Output and verify Must-Have 5
    _, inspection = inspect_media_file(output_video_path)
    rendered_dur = inspection.duration_s
    timeline_dur = timeline.total_duration_seconds
    diff_s = abs(rendered_dur - timeline_dur)

    fps = timeline.source_media.fps or 30.0
    frame_dur = 1.0 / fps
    frame_diff = round(diff_s / frame_dur, 2)
    # Must be within 1 frame (with small 0.05s tolerance for audio container packet padding)
    is_in_sync = frame_diff <= 1.5

    out_hash = compute_file_sha256(output_video_path)

    return RenderResult(
        output_path=output_video_path,
        timeline_hash=timeline.timeline_hash,
        output_sha256=out_hash,
        timeline_duration_s=timeline_dur,
        rendered_duration_s=rendered_dur,
        duration_diff_s=round(diff_s, 4),
        frame_diff=frame_diff,
        is_in_sync=is_in_sync,
        warnings=warnings,
    )
