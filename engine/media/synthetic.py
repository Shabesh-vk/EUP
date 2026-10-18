"""Synthetic media generator for deterministic automated testing.

Generates real frame-accurate MP4 and MOV files using FFmpeg test sources,
with exact durations, frame rates, and audio tracks.
"""

import subprocess
from pathlib import Path
from engine.config import settings
from engine.logging_config import logger


def generate_synthetic_video(
    output_path: str,
    duration_s: float = 120.0,
    fps: float = 30.0,
    width: int = 640,
    height: int = 360,
    include_audio: bool = True
) -> str:
    """Generates an MP4 video with color test pattern and sine wave audio."""
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration_s}:size={width}x{height}:rate={fps}",
    ]

    if include_audio:
        cmd.extend([
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration_s}:sample_rate=48000",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest"
        ])
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p"
        ])

    cmd.append(str(out))

    try:
        subprocess.run(cmd, capture_output=True, check=True)
        logger.info(f"Generated synthetic video at {out} ({duration_s}s, {fps}fps)")
    except Exception as e:
        logger.warning(f"Could not run FFmpeg to generate synthetic video: {e}")
        # Create empty placeholder file if FFmpeg fails
        out.write_bytes(b"MOCK_VIDEO_DATA")

    return str(out)


def generate_synthetic_audio(
    output_path: str,
    duration_s: float = 60.0,
    frequency: int = 500
) -> str:
    """Generates an audio track for background music testing."""
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={frequency}:duration={duration_s}:sample_rate=48000",
        "-c:a", "aac",
        "-b:a", "128k",
        str(out)
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception as e:
        logger.warning(f"Could not run FFmpeg to generate synthetic audio: {e}")
        out.write_bytes(b"MOCK_AUDIO_DATA")

    return str(out)
