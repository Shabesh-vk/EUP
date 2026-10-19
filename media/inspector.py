"""
Media inspection, stream validation, and cryptographic hash verification using ffprobe.
"""

from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field

from core.schema import SourceMedia
from core.time_ticks import seconds_to_ticks


def get_ffprobe_path() -> str:
    """Find ffprobe binary on PATH or common installation paths."""
    env_path = os.environ.get("FFPROBE_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    found = shutil.which("ffprobe")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    candidates = [
        os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "ffprobe.exe"),
        os.path.join(local_app_data, "Programs", "ffmpeg", "bin", "ffprobe.exe"),
        "C:\\ProgramData\\chocolatey\\bin\\ffprobe.exe",
        os.path.join(user_profile, "scoop", "shims", "ffprobe.exe"),
    ]
    import glob
    winget_matches = glob.glob(
        os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "ffprobe.exe"),
        recursive=True
    )
    candidates.extend(winget_matches)
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return "ffprobe"


def get_ffmpeg_path() -> str:
    """Find ffmpeg binary on PATH or common installation paths."""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    candidates = [
        os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        os.path.join(local_app_data, "Programs", "ffmpeg", "bin", "ffmpeg.exe"),
        "C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe",
        os.path.join(user_profile, "scoop", "shims", "ffmpeg.exe"),
    ]
    import glob
    winget_matches = glob.glob(
        os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "ffmpeg.exe"),
        recursive=True
    )
    candidates.extend(winget_matches)
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return "ffmpeg"



def compute_file_sha256(filepath: str) -> str:
    """
    Compute cryptographic SHA-256 hash of a file using buffered reads.
    Guarantees that large video files are hashed efficiently without excessive RAM use.
    """
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_media_integrity(filepath: str, expected_hash: str) -> bool:
    """
    Verify that the source media file is untouched by comparing SHA-256 hashes.
    Must-Have 1 verification helper.
    """
    actual_hash = compute_file_sha256(filepath)
    return actual_hash.lower() == expected_hash.lower()


class MediaInspectionResult(BaseModel):
    duration_s: float
    duration_ticks: int
    fps: float
    width: Optional[int] = None
    height: Optional[int] = None
    video_codec: Optional[str] = None
    has_audio: bool = False
    audio_channels: Optional[int] = None
    audio_sample_rate: Optional[int] = None
    audio_codec: Optional[str] = None
    is_vfr: bool = False
    sha256_hash: str
    warnings: list[str] = Field(default_factory=list)


def inspect_media_file(filepath: str, media_id: Optional[str] = None) -> Tuple[SourceMedia, MediaInspectionResult]:
    """
    Inspect a media file (MP4/MOV) using ffprobe, compute its SHA-256 hash,
    and return both a SourceMedia object and full technical metadata.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Media file not found: {filepath}")

    file_sha256 = compute_file_sha256(filepath)
    ffprobe_cmd = get_ffprobe_path()

    cmd = [
        ffprobe_cmd,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        probe_data = json.loads(proc.stdout)
    except Exception as e:
        raise RuntimeError(f"Failed to probe media file '{filepath}': {e}")

    format_info = probe_data.get("format", {})
    streams = probe_data.get("streams", [])

    duration_s = float(format_info.get("duration", 0.0))
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    warnings: list[str] = []

    # Parse FPS
    fps = 30.0
    width = None
    height = None
    video_codec = None
    is_vfr = False

    if video_stream:
        width = int(video_stream.get("width", 0)) or None
        height = int(video_stream.get("height", 0)) or None
        video_codec = video_stream.get("codec_name")
        r_fps = video_stream.get("r_frame_rate", "30/1")
        avg_fps = video_stream.get("avg_frame_rate", "30/1")

        def _eval_ratio(r: str) -> float:
            if "/" in r:
                num, den = r.split("/", 1)
                return float(num) / float(den) if float(den) != 0 else 30.0
            return float(r)

        fps_val = _eval_ratio(avg_fps) if avg_fps != "0/0" else _eval_ratio(r_fps)
        if fps_val > 0:
            fps = round(fps_val, 3)

        # Detect Variable Frame Rate (VFR)
        if avg_fps != r_fps and avg_fps != "0/0" and r_fps != "0/0":
            diff = abs(_eval_ratio(avg_fps) - _eval_ratio(r_fps))
            if diff > 0.05:
                is_vfr = True
                warnings.append("Variable frame rate (VFR) detected; rendering will normalize to CFR.")
    else:
        warnings.append("No video stream found in container.")

    # Audio stream
    has_audio = audio_stream is not None
    audio_channels = None
    audio_sample_rate = None
    audio_codec = None

    if audio_stream:
        audio_channels = int(audio_stream.get("channels", 2))
        audio_sample_rate = int(audio_stream.get("sample_rate", 48000))
        audio_codec = audio_stream.get("codec_name")
    else:
        warnings.append("No audio track detected in media file.")

    if duration_s <= 0.0 and video_stream:
        duration_s = float(video_stream.get("duration", 0.0))

    duration_ticks = seconds_to_ticks(duration_s)

    source_media = SourceMedia(
        id=media_id or f"media_{file_sha256[:12]}",
        filename=os.path.basename(filepath),
        sha256_hash=file_sha256,
        duration_ticks=duration_ticks,
        fps=fps,
        width=width,
        height=height,
        audio_channels=audio_channels,
        sample_rate=audio_sample_rate,
    )

    inspection = MediaInspectionResult(
        duration_s=round(duration_s, 3),
        duration_ticks=duration_ticks,
        fps=fps,
        width=width,
        height=height,
        video_codec=video_codec,
        has_audio=has_audio,
        audio_channels=audio_channels,
        audio_sample_rate=audio_sample_rate,
        audio_codec=audio_codec,
        is_vfr=is_vfr,
        sha256_hash=file_sha256,
        warnings=warnings,
    )

    return source_media, inspection
