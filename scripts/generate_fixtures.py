"""
Utility to generate synthetic deterministic test media fixtures with precise audio and video sync markers.
"""

import os
import sys
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from media.inspector import get_ffmpeg_path



def generate_test_video(output_path: str, duration_s: float = 30.0, fps: int = 30, width: int = 1280, height: int = 720) -> str:
    """Generate a test MP4 video with burnt-in timecode and audio tone."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ffmpeg_bin = get_ffmpeg_path()

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration_s}:size={width}x{height}:rate={fps}",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration_s}:sample_rate=48000",
        "-vf", f"drawtext=text='%{{pts\\:hms}}':rate={fps}:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h-th-40",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return output_path


def generate_test_audio(output_path: str, duration_s: float = 30.0) -> str:
    """Generate a background music test audio file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ffmpeg_bin = get_ffmpeg_path()

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={duration_s}:sample_rate=48000",
        "-c:a", "libmp3lame" if output_path.endswith(".mp3") else "aac",
        "-b:a", "128k",
        output_path,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return output_path



if __name__ == "__main__":
    fixtures_dir = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")
    video_path = os.path.join(fixtures_dir, "test_interview.mp4")
    music_path = os.path.join(fixtures_dir, "test_music.mp3")

    print(f"Generating test video: {video_path}")
    generate_test_video(video_path, duration_s=300.0)

    print(f"Generating test music: {music_path}")
    generate_test_audio(music_path, duration_s=300.0)


    print("Fixtures generated successfully.")
