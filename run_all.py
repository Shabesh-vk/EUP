"""Automated End-to-End Runner for IncuBrix Video Editing Engine.

Executes all automated pipelines in sequence:
1. Automated Test Suite (79 tests)
2. Canonical 8-Step Worked Example (Session Runner)
3. Full Test Scenarios Suite (Batch Runner)
4. Artifact and rendered media validation
"""

import os
import sys
import time
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).parent.resolve()
sys.path.insert(0, str(WORKSPACE))

def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  {title.upper()}")
    print("=" * 70)

def run_tests() -> bool:
    print_header("Step 1: Running Automated Test Suite (79 Tests)")
    start = time.time()
    cmd = [sys.executable, "-m", "pytest", "tests/"]
    result = subprocess.run(cmd, cwd=str(WORKSPACE))
    elapsed = time.time() - start
    success = (result.returncode == 0)
    print(f"\n[Test Suite] {'PASSED' if success else 'FAILED'} in {elapsed:.2f}s")
    return success

def run_worked_example() -> bool:
    print_header("Step 2: Executing Worked Example Session Runner")
    start = time.time()
    session_file = WORKSPACE / "test_pack" / "worked_example.yaml"
    out_dir = WORKSPACE / "test_pack" / "worked_example_output"
    
    cmd = [
        sys.executable,
        str(WORKSPACE / "session_runner.py"),
        str(session_file),
        "--output-dir",
        str(out_dir)
    ]
    result = subprocess.run(cmd, cwd=str(WORKSPACE))
    elapsed = time.time() - start
    
    # Validate generated artifacts
    results_json = out_dir / "results.json"
    timeline_json = out_dir / "final_timeline.json"
    rendered_mp4 = out_dir / "final_rendered_video.mp4"
    
    artifacts_ok = (
        results_json.exists() and results_json.stat().st_size > 0 and
        timeline_json.exists() and timeline_json.stat().st_size > 0 and
        rendered_mp4.exists() and rendered_mp4.stat().st_size > 0
    )
    
    success = (result.returncode == 0) and artifacts_ok
    print(f"\n[Worked Example] {'PASSED' if success else 'FAILED'} in {elapsed:.2f}s")
    if artifacts_ok:
        print(f"  - Results:  {results_json.name} ({results_json.stat().st_size:,} bytes)")
        print(f"  - Timeline: {timeline_json.name} ({timeline_json.stat().st_size:,} bytes)")
        print(f"  - Rendered: {rendered_mp4.name} ({rendered_mp4.stat().st_size:,} bytes)")
    return success

def run_batch_scenarios() -> bool:
    print_header("Step 3: Executing Batch Runner (16 Scenarios)")
    start = time.time()
    scenarios_dir = WORKSPACE / "test_pack" / "scenarios"
    out_dir = WORKSPACE / "test_pack" / "batch_results"
    
    cmd = [
        sys.executable,
        str(WORKSPACE / "batch_runner.py"),
        str(scenarios_dir),
        "--output-dir",
        str(out_dir)
    ]
    result = subprocess.run(cmd, cwd=str(WORKSPACE))
    elapsed = time.time() - start
    
    summary_file = out_dir / "batch_summary.json"
    batch_ok = summary_file.exists() and summary_file.stat().st_size > 0
    success = (result.returncode == 0) and batch_ok
    print(f"\n[Batch Runner] {'PASSED' if success else 'FAILED'} in {elapsed:.2f}s")
    if batch_ok:
        import json
        with open(summary_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  - Scenarios: {data.get('successful', 0)}/{data.get('total_sessions', 0)} Succeeded")
    return success

def main():
    total_start = time.time()
    print_header("IncuBrix Automated Execution Engine")
    print(f"Workspace: {WORKSPACE}")
    print(f"Python:    {sys.executable}")
    
    # Run all automated stages
    step1_ok = run_tests()
    step2_ok = run_worked_example()
    step3_ok = run_batch_scenarios()
    
    total_elapsed = time.time() - total_start
    all_ok = step1_ok and step2_ok and step3_ok
    
    print_header("Automated Run Summary")
    print(f"1. Test Suite (79 tests):      {'PASS' if step1_ok else 'FAIL'}")
    print(f"2. 8-Step Worked Example:       {'PASS' if step2_ok else 'FAIL'}")
    print(f"3. 16 Batch Scenarios:          {'PASS' if step3_ok else 'FAIL'}")
    print(f"Total Execution Time:           {total_elapsed:.2f}s")
    print(f"Overall Result:                 {'ALL CHECKS PASSED (100%)' if all_ok else 'FAILURE DETECTED'}")
    print("=" * 70 + "\n")
    
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
