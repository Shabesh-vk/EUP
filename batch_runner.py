"""Batch Runner CLI adhering to Integration Standard #10.

"A command-line tool that runs a folder or file of test inputs against the API
and writes all results to one folder. We use this to test every submission the same way."
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
from session_runner import run_session
from engine.logging_config import logger


def run_batch_against_api(
    session_file: Path,
    api_url: str,
    output_dir: Path
) -> Dict[str, Any]:
    """Runs a session file by making HTTP requests to the live service API."""
    import yaml
    with open(session_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) if session_file.suffix in (".yaml", ".yml") else json.load(f)

    video_input = data.get("video", "sample.mp4")
    steps = data.get("steps", [])

    base_url = api_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        # Create session
        res = client.post("/api/v1/sessions", json={"video_url_or_path": video_input})
        res.raise_for_status()
        session_id = res.json()["session_id"]

        step_results = []
        for i, s in enumerate(steps, 1):
            step_req = {"say": s.get("say", ""), "answer": s.get("answer")}
            s_res = client.post(f"/api/v1/sessions/{session_id}/step", json=step_req)
            s_res.raise_for_status()
            step_results.append(s_res.json())

        # Retrieve timeline
        tl_res = client.get(f"/api/v1/timeline/{session_id}")
        tl_res.raise_for_status()
        final_timeline = tl_res.json()

        # Save results
        out_sub = output_dir / session_file.stem
        out_sub.mkdir(parents=True, exist_ok=True)

        results_payload = {
            "session_file": str(session_file.name),
            "video": video_input,
            "final_timeline_hash": final_timeline.get("timeline_hash"),
            "final_duration_s": final_timeline.get("total_duration_s"),
            "steps": step_results
        }
        with open(out_sub / "results.json", "w", encoding="utf-8") as f:
            json.dump(results_payload, f, indent=2)

        with open(out_sub / "final_timeline.json", "w", encoding="utf-8") as f:
            json.dump(final_timeline, f, indent=2)

        return results_payload


def run_batch(input_path: str, output_dir: str, api_url: Optional[str] = None):
    inp = Path(input_path).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    files_to_run: List[Path] = []
    if inp.is_file():
        files_to_run.append(inp)
    elif inp.is_dir():
        files_to_run.extend(sorted(inp.glob("*.yaml")))
        files_to_run.extend(sorted(inp.glob("*.yml")))
        files_to_run.extend(sorted(inp.glob("*.json")))

    if not files_to_run:
        print(f"No session files found at {inp}")
        return

    print(f"\n==========================================")
    print(f"IncuBrix Batch Runner: Processing {len(files_to_run)} sessions")
    print(f"Target Output Folder: {out}")
    print(f"API URL: {api_url or 'In-Process Runner'}")
    print(f"==========================================\n")

    summary_records = []
    total_start = time.time()

    for idx, f in enumerate(files_to_run, 1):
        print(f"[{idx}/{len(files_to_run)}] Running {f.name}...")
        sub_dir = out / f.stem
        sub_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        try:
            if api_url:
                result = run_batch_against_api(f, api_url, out)
            else:
                result = run_session(str(f), str(sub_dir))

            elapsed = time.time() - t0
            summary_records.append({
                "file": f.name,
                "status": "success",
                "timeline_hash": result.get("final_timeline_hash"),
                "duration_s": result.get("final_duration_s"),
                "steps_count": len(result.get("steps", [])),
                "elapsed_s": round(elapsed, 2)
            })
            print(f"    -> SUCCESS in {elapsed:.2f}s (Hash: {result.get('final_timeline_hash')[:12]}...)")
        except Exception as e:
            elapsed = time.time() - t0
            summary_records.append({
                "file": f.name,
                "status": "failed",
                "error": str(e),
                "elapsed_s": round(elapsed, 2)
            })
            print(f"    -> FAILED in {elapsed:.2f}s: {e}")

    total_elapsed = time.time() - total_start
    success_count = sum(1 for r in summary_records if r["status"] == "success")

    summary_payload = {
        "timestamp": time.time(),
        "total_sessions": len(files_to_run),
        "successful": success_count,
        "failed": len(files_to_run) - success_count,
        "total_elapsed_s": round(total_elapsed, 2),
        "sessions": summary_records
    }

    with open(out / "batch_summary.json", "w", encoding="utf-8") as sf:
        json.dump(summary_payload, sf, indent=2)

    print(f"\nBatch Run Complete: {success_count}/{len(files_to_run)} succeeded in {total_elapsed:.2f}s.")
    print(f"Summary saved to: {out / 'batch_summary.json'}\n")


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Batch Runner CLI")
    parser.add_argument("positional_input", nargs="?", default=None, help="Path to folder or single session file")
    parser.add_argument("--input", "-i", dest="flag_input", default=None, help="Path to folder or single session file")
    parser.add_argument("--output-dir", "-o", default="./batch_results", help="Directory to write all outputs")
    parser.add_argument("--api-url", default=None, help="Optional HTTP API base URL to run against")
    args = parser.parse_args()

    input_path = args.flag_input or args.positional_input
    if not input_path:
        parser.error("Must provide session folder/file as positional argument or via --input/-i")

    run_batch(input_path, args.output_dir, args.api_url)


if __name__ == "__main__":
    main()
