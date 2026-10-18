"""Generator script for test pack session YAML files."""

from pathlib import Path
import yaml

SCENARIOS = {
    "01_clean_cut": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Cut the first 10 seconds"},
            {"say": "Cut from 0:20 to 0:30"},
            {"say": "render"}
        ]
    },
    "02_caption_and_cut": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut the first 30 seconds"},
            {"say": "Make that caption yellow"},
            {"say": "render"}
        ]
    },
    "03_speed_up_range": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "render"}
        ]
    },
    "04_undo_redo_flow": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Cut the first 20 seconds"},
            {"say": "Undo"},
            {"say": "Redo"},
            {"say": "render"}
        ]
    },
    "05_clarification_pricing": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Remove the part about pricing", "answer": "the second one"},
            {"say": "render"}
        ]
    },
    "06_filler_words_removal": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Cut out the ums"},
            {"say": "render"}
        ]
    },
    "07_silence_trimming": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Remove silences longer than 1 second"},
            {"say": "render"}
        ]
    },
    "08_audio_bleep_effect": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Bleep 'pricing'"},
            {"say": "render"}
        ]
    },
    "09_audio_mute_effect": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Mute 'pricing'"},
            {"say": "render"}
        ]
    },
    "10_auto_caption_video": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Auto-caption the whole video"},
            {"say": "render"}
        ]
    },
    "11_restore_intro": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Cut the first 30 seconds"},
            {"say": "Actually, put the intro back"},
            {"say": "render"}
        ]
    },
    "12_guest_speaker_dialogue": {
        "video": "sample.mp4",
        "steps": [
            {"say": "remove everything the guest says about their old job"},
            {"say": "render"}
        ]
    },
    "13_repeated_thanks_clarification": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Remove everything after I say thanks", "answer": "the second one"},
            {"say": "render"}
        ]
    },
    "14_rejected_out_of_range": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Add a caption at 5:00"},
            {"say": "render"}
        ]
    },
    "15_rejected_cut_everything": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Cut everything"},
            {"say": "render"}
        ]
    },
    "16_worked_example_full": {
        "video": "sample.mp4",
        "steps": [
            {"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
            {"say": "Cut the first 30 seconds"},
            {"say": "Remove the part about pricing", "answer": "the second one"},
            {"say": "Speed up from 1:00 to 1:30 by 2x"},
            {"say": "Actually, put the intro back"},
            {"say": "Undo"},
            {"say": "Make that caption red"},
            {"say": "render"}
        ]
    }
}


def generate_scenarios(target_dir: str = "./test_pack/scenarios"):
    p = Path(target_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    for name, content in SCENARIOS.items():
        file_path = p / f"{name}.yaml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(content, f, sort_keys=False)
    print(f"Generated {len(SCENARIOS)} scenario YAML files in {p}")


if __name__ == "__main__":
    generate_scenarios()
