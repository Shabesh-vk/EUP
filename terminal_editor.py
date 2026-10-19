"""Interactive Terminal CLI for IncuBrix Prompt-Based Video Editing Engine.

Allows creators to interact with the AI editor directly from the command line:
- Single-prompt execution: python terminal_editor.py --prompt "Cut the first 30 seconds"
- Interactive REPL mode:    python terminal_editor.py
"""

import argparse
import sys
import os
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).parent.resolve()
sys.path.insert(0, str(WORKSPACE))

from engine.config import settings
from engine.core.timeline import Timeline
from engine.media.probe import probe_media_file
from engine.media.transcriber import get_transcriber
from engine.parser.nl_parser import InstructionEngine
from engine.parser.llm_adapter import get_llm_adapter, OllamaAdapter, RuleBasedMockAdapter
from engine.media.renderer import render_timeline_video
from engine.logging_config import logger


def init_engine(video_path: str, llm_choice: str = "ollama"):
    """Initializes the media probe, transcriber, timeline, and AI engine."""
    p = Path(video_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Media file not found: {video_path}")

    probe = probe_media_file(str(p))
    transcriber = get_transcriber()
    transcript, warnings = transcriber.transcribe(str(p))

    timeline = Timeline(probe, transcript, time_policy=settings.DEFAULT_TIME_POLICY)

    # Configure AI adapter
    if llm_choice == "ollama":
        adapter = OllamaAdapter(base_url=settings.OLLAMA_BASE_URL, model=settings.OLLAMA_MODEL)
    else:
        adapter = RuleBasedMockAdapter()

    engine = InstructionEngine(timeline, llm_adapter=adapter)
    return timeline, engine


def format_status_bar(timeline: Timeline) -> str:
    caps, _ = timeline.get_resolved_captions()
    fx = timeline.get_resolved_audio_effects()
    return (
        f"Duration: {timeline.total_duration:.2f}s | "
        f"Clips: {len(timeline.clips)} | "
        f"Captions: {len(caps)} | "
        f"Effects: {len(fx)} | "
        f"Hash: {timeline.timeline_hash[:12]}..."
    )


def execute_single_prompt(engine: InstructionEngine, prompt: str, answer: Optional[str] = None):
    """Executes a single prompt and prints formatted output."""
    print(f"\n[USER PROMPT]: \"{prompt}\"")
    result = engine.execute_instruction(prompt, answer=answer)

    if result.status == "applied":
        print(f"Status:   [APPLIED]")
        print(f"Summary:  {result.summary}")
        print(f"Duration: {result.duration_s:.2f}s")
        print(f"Hash:     {result.timeline_hash}")
        if result.warnings:
            print(f"Warnings: {', '.join(result.warnings)}")

    elif result.status == "needs_clarification":
        print(f"Status:   [NEEDS CLARIFICATION]")
        print(f"Question: {result.question}")
        if result.options:
            print("Options:")
            for idx, opt in enumerate(result.options, 1):
                print(f"  [{idx}] {opt}")

    elif result.status == "rejected":
        print(f"Status:   [REJECTED]")
        print(f"Reason:   {result.reason}")

    return result


def interactive_repl(video_path: str, llm_choice: str):
    """Runs an interactive REPL terminal session."""
    print("\n" + "=" * 65)
    print("  INCUBRIX AI VIDEO EDITOR - TERMINAL SESSION")
    print("=" * 65)
    print(f"Media File:   {video_path}")
    print(f"AI Provider:  {llm_choice.upper()} (Ollama: {settings.OLLAMA_MODEL})")
    print("Type your editing instructions in natural language.")
    print("Special commands: 'status', 'render', 'undo', 'redo', 'exit'")
    print("-" * 65)

    timeline, engine = init_engine(video_path, llm_choice)
    print(f"Initial State: {format_status_bar(timeline)}")

    while True:
        try:
            user_input = input("\nAI Editor > ").strip()
            if not user_input:
                continue

            lower = user_input.lower()
            if lower in ("exit", "quit", "q"):
                print("Exiting interactive session.")
                break

            if lower == "status":
                print(f"\nTimeline Status: {format_status_bar(timeline)}")
                for i, c in enumerate(timeline.clips, 1):
                    print(f"  Clip {i}: {c.source_start:.2f}s - {c.source_end:.2f}s (speed: {c.speed}x)")
                caps, _ = timeline.get_resolved_captions()
                for c in caps:
                    print(f"  Caption '{c.text}': {c.playback_start:.2f}s - {c.playback_end:.2f}s (color: {c.style.color})")
                continue

            if lower == "render":
                out_file = str(WORKSPACE / "output" / "interactive_render.mp4")
                print(f"Rendering timeline to {out_file}...")
                out_path, manifest = render_timeline_video(timeline, out_file)
                print(f"Render Complete! File: {out_path} ({manifest['duration_s']}s)")
                continue

            # Process prompt
            result = engine.execute_instruction(user_input)

            if result.status == "needs_clarification":
                print(f"\n[AI CLARIFICATION REQUIRED]")
                print(f"Question: {result.question}")
                if result.options:
                    for i, opt in enumerate(result.options, 1):
                        print(f"  [{i}] {opt}")
                    ans = input("\nYour Choice (number or text) > ").strip()
                    # Check if number entered
                    if ans.isdigit() and 1 <= int(ans) <= len(result.options):
                        ans_text = result.options[int(ans) - 1]
                    else:
                        ans_text = ans
                    resolved_result = engine.execute_instruction(user_input, answer=ans_text)
                    print(f"\n[APPLIED]: {resolved_result.summary}")
                    print(f"Current State: {format_status_bar(timeline)}")
            elif result.status == "applied":
                print(f"\n[APPLIED]: {result.summary}")
                print(f"Current State: {format_status_bar(timeline)}")
            elif result.status == "rejected":
                print(f"\n[REJECTED]: {result.reason}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting session.")
            break
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Terminal AI Video Editor")
    parser.add_argument("--video", "-v", default="sample.mp4", help="Path to input video")
    parser.add_argument("--prompt", "-p", default=None, help="Single instruction to execute")
    parser.add_argument("--answer", "-a", default=None, help="Answer to clarification if required")
    parser.add_argument("--render", "-r", action="store_true", help="Render video after prompt")
    parser.add_argument("--open", action="store_true", help="Automatically open rendered video in media player")
    parser.add_argument("--output", "-o", default=None, help="Output MP4 file path")
    parser.add_argument("--llm", default="ollama", choices=["ollama", "mock"], help="LLM backend")
    args = parser.parse_args()

    if args.prompt:
        # Single prompt execution
        timeline, engine = init_engine(args.video, args.llm)
        res = execute_single_prompt(engine, args.prompt, answer=args.answer)
        if args.render or args.open:
            out_file = args.output or str(WORKSPACE / "output" / "terminal_render.mp4")
            print(f"\n[RENDERING VIDEO] with FFmpeg -> {out_file}...")
            out_path, manifest = render_timeline_video(timeline, out_file)
            print(f"[RENDER COMPLETE]: {out_path} ({manifest['duration_s']}s)")
            if args.open:
                try:
                    os.startfile(out_path)
                except Exception as e:
                    print(f"Could not open file: {e}")
    else:
        # Interactive REPL mode
        interactive_repl(args.video, args.llm)


if __name__ == "__main__":
    main()
