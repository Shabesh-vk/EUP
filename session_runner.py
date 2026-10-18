"""IncuBrix Session Runner CLI.

Adheres strictly to the IncuBrix Specification:
- Accepts a session YAML or JSON file.
- Executes scripted steps sequentially.
- Automatically supplies 'answer' when clarification is triggered.
- Generates:
  1. results.json (status, operations, summary, question, options, timeline_hash, duration_s for each step)
  2. final_timeline.json (complete timeline state)
  3. final_rendered_video.mp4 (rendered output)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List
import yaml

from engine.core.timeline import Timeline
from engine.parser.nl_parser import InstructionEngine
from engine.media.probe import probe_media_file
from engine.media.transcriber import get_transcriber
from engine.media.renderer import render_timeline_video
from engine.storage.s3_minio import get_storage
from engine.logging_config import logger


def run_session(session_file_path: str, output_dir: str) -> Dict[str, Any]:
    """Executes a scripted editing session and produces results.json and rendered media."""
    session_path = Path(session_file_path).resolve()
    if not session_path.exists():
        raise FileNotFoundError(f"Session file not found: {session_file_path}")

    # Load session YAML or JSON
    with open(session_path, "r", encoding="utf-8") as f:
        if session_path.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(f)
        else:
            data = json.load(f)

    video_input = data.get("video", "sample.mp4")
    steps = data.get("steps", [])

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve video
    storage = get_storage()
    if video_input.startswith("http://") or video_input.startswith("https://"):
        local_video = str(out_dir / "input_video.mp4")
        video_path = storage.fetch_file(video_input, local_video)
    else:
        # Check relative to session file
        cand = session_path.parent / video_input
        if cand.exists():
            video_path = str(cand)
        elif Path(video_input).exists():
            video_path = str(Path(video_input).resolve())
        else:
            # Fallback to local test media
            video_path = video_input

    # Probe & Transcribe
    source_media = probe_media_file(video_path)
    transcriber = get_transcriber()
    transcript, warnings = transcriber.transcribe(video_path)

    timeline = Timeline(source=source_media, transcript=transcript)
    engine = InstructionEngine(timeline=timeline)

    step_results: List[Dict[str, Any]] = []
    render_requested = False

    logger.info(f"Starting session with {len(steps)} steps for {video_path}...")

    for i, step in enumerate(steps, 1):
        say_text = step.get("say", "")
        answer_text = step.get("answer")

        if say_text.strip().lower() == "render":
            render_requested = True

        # Execute instruction first without answer to verify whether clarification is triggered
        res = engine.execute_instruction(say_text)

        clarif_question = None
        clarif_options = None

        # If needs clarification and step provided answer, apply answer
        if res.status == "needs_clarification" and answer_text:
            clarif_question = res.question
            clarif_options = res.options
            res = engine.execute_instruction(say_text, answer=answer_text)
            res.question = clarif_question
            res.options = clarif_options

        step_record = {
            "step": i,
            "say": say_text,
            "status": res.status,
            "operations": res.operations,
            "summary": res.summary,
            "question": res.question,
            "options": res.options,
            "reason": res.reason,
            "timeline_hash": res.timeline_hash,
            "duration_s": res.duration_s,
            "warnings": res.warnings
        }
        step_results.append(step_record)
        logger.info(f"Step {i}: '{say_text}' -> [{res.status.upper()}] {res.summary or res.reason or res.question}")

    # Output: results.json
    results_payload = {
        "video": video_input,
        "initial_duration_s": source_media.duration_s,
        "final_duration_s": timeline.total_duration,
        "final_timeline_hash": timeline.timeline_hash,
        "steps": step_results
    }

    results_file = out_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2)

    # Output: final_timeline.json
    resolved_caps, _ = timeline.get_resolved_captions()
    resolved_effs = timeline.get_resolved_audio_effects()
    final_timeline_payload = {
        "timeline_hash": timeline.timeline_hash,
        "total_duration_s": timeline.total_duration,
        "time_policy": timeline.time_policy,
        "clips": [c.model_dump() for c in timeline.clips],
        "captions": [c.model_dump() for c in resolved_caps],
        "effects": [e.model_dump() for e in resolved_effs],
        "history": [h.model_dump() for h in timeline.history]
    }
    with open(out_dir / "final_timeline.json", "w", encoding="utf-8") as f:
        json.dump(final_timeline_payload, f, indent=2)

    # Render video if requested or always create final render
    video_out = str(out_dir / "final_rendered_video.mp4")
    render_timeline_video(timeline, video_out)
    logger.info(f"Session finished. Results written to {out_dir}")

    return results_payload


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Session Runner CLI")
    parser.add_argument("positional_input", nargs="?", default=None, help="Path to session YAML/JSON file")
    parser.add_argument("--input", "-i", dest="flag_input", default=None, help="Path to session YAML/JSON file")
    parser.add_argument("--output-dir", "-o", default="./session_output", help="Directory to save results")
    args = parser.parse_args()

    input_file = args.flag_input or args.positional_input
    if not input_file:
        parser.error("Must provide session file as positional argument or via --input/-i")

    try:
        results = run_session(input_file, args.output_dir)
        print(f"\nSession Complete! Hash: {results['final_timeline_hash']} (Duration: {results['final_duration_s']}s)")
        print(f"Results saved to: {Path(args.output_dir).resolve() / 'results.json'}")
        sys.exit(0)
    except Exception as e:
        print(f"Error executing session: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
