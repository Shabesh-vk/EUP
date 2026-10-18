"""
Batch Runner CLI Tool.
Requirement (Integration Standard 10):
A command-line tool that runs a folder or file of test inputs against the API and writes all results to one folder.
"""

from __future__ import annotations
import sys
import os
import glob
from pathlib import Path
import argparse
from typing import List, Dict, Any

from .session_runner import run_session


def run_batch(input_path: str | Path, output_dir: str | Path) -> Dict[str, Any]:
    in_p = Path(input_path)
    out_p = Path(output_dir)
    out_p.mkdir(parents=True, exist_ok=True)

    session_files: List[Path] = []
    if in_p.is_file():
        session_files.append(in_p)
    elif in_p.is_dir():
        session_files.extend(sorted(in_p.glob("*.yaml")))
        session_files.extend(sorted(in_p.glob("*.yml")))

    results = {}
    print(f"Executing batch run on {len(session_files)} session file(s)...")

    for s_file in session_files:
        session_name = s_file.stem
        session_out = out_p / session_name
        try:
            res = run_session(s_file, session_out)
            results[session_name] = {
                "status": "success",
                "final_hash": res["final_hash"],
                "final_duration": res["final_duration"],
                "steps_count": res["steps_count"],
            }
            print(f"  [PASS] {session_name} -> {res['final_hash'][:12]} ({res['final_duration']:.1f}s)")
        except Exception as e:
            results[session_name] = {
                "status": "failed",
                "error": str(e),
            }
            print(f"  [FAIL] {session_name}: {e}")

    summary_file = out_p / "batch_summary.json"
    import json
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Batch Runner CLI")
    parser.add_argument("input_path", help="Path to a session YAML file or folder of session YAML files")
    parser.add_argument("--output-dir", default="./output/batch_results", help="Directory to write all results")
    args = parser.parse_args()

    run_batch(args.input_path, args.output_dir)


if __name__ == "__main__":
    main()
