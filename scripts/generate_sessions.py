"""
Generates the 15+ scripted sessions required for the IncuBrix Session Pack.
Includes clean runs, clarification runs, and intentional rejection/failure cases.
"""

from pathlib import Path
import yaml

SESSIONS_DATA = {
    "session_01_worked_example": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut the first 30 seconds"},
            {"say": "Remove the part about pricing", "answer": "the second one"},
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "Actually, put the intro back"},
            {"say": "Undo"},
            {"say": "Make that caption red"},
            {"say": "render"},
        ],
    },
    "session_02_cut_and_restore_caption": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut from 40.0 to 45.0"},
            {"say": "Undo"},
            {"say": "render"},
        ],
    },
    "session_03_filler_removal_and_bleep": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Bleep words"},
            {"say": "Remove filler words"},
            {"say": "render"},
        ],
    },
    "session_04_speed_ramping": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "Speed up by 0.5x"},
            {"say": "render"},
        ],
    },
    "session_05_bg_music_and_ducking": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Add background music"},
            {"say": "Cut the first 10 seconds"},
            {"say": "render"},
        ],
    },
    "session_06_multiple_undos": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Cut the first 10 seconds"},
            {"say": "Cut from 20.0 to 30.0"},
            {"say": "Undo"},
            {"say": "Undo"},
            {"say": "render"},
        ],
    },
    "session_07_selective_restore": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Cut the first 30 seconds"},
            {"say": "Add background music"},
            {"say": "Actually, put the intro back"},
            {"say": "render"},
        ],
    },
    "session_08_pricing_clarification": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Remove the part about pricing", "answer": "the first one"},
            {"say": "render"},
        ],
    },
    "session_09_thanks_clarification": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Remove everything after I say thanks"},
        ],
    },
    "session_10_whole_cut_rejection": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Cut everything"},
        ],
    },
    "session_11_out_of_bounds_rejection": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Add a caption at 5:00"},
        ],
    },
    "session_12_style_nonexistent_caption": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Make that caption bigger"},
        ],
    },
    "session_13_two_speakers_interview": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Remove everything the guest says about their old job"},
            {"say": "render"},
        ],
    },
    "session_14_compound_edits": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Cut the first 30 seconds"},
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Make that caption blue"},
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "render"},
        ],
    },
    "session_15_extreme_speed_rejection": {
        "video": "https://example.com/interview.mp4",
        "steps": [
            {"say": "Speed up by 15x"},
        ],
    },
}


def generate_all_sessions(target_dir: str = "n:/Concat/sessions"):
    path = Path(target_dir)
    path.mkdir(parents=True, exist_ok=True)
    for name, content in SESSIONS_DATA.items():
        file_path = path / f"{name}.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f, sort_keys=False)
        print(f"Generated {file_path}")


if __name__ == "__main__":
    generate_all_sessions()
