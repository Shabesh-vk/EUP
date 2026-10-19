"""
IncuBrix Session Runner CLI tool.
Runs a scripted YAML session file or directory against the HTTP API and writes all results to one folder.
Conforms to Assessment Brief page 2 and Integration Standard Point 10.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
import yaml


def run_session_file(session_path: str, output_dir: str, api_base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    api_base = api_base_url.rstrip("/")
    os.makedirs(output_dir, exist_ok=True)

    with open(session_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    video_input = data.get("video")
    steps = data.get("steps", [])

    print(f"\n[RUNNER] Starting session: {session_path}")
    print(f"[RUNNER] Target API: {api_base}")
    print(f"[RUNNER] Source video: {video_input}")

    client = httpx.Client(base_url=api_base, timeout=120.0)

    # 1. Initialize project
    init_key = f"init_{uuid.uuid4().hex[:8]}"
    create_payload = {}
    files = {}

    if video_input and os.path.isfile(video_input):
        files["video_file"] = (os.path.basename(video_input), open(video_input, "rb"), "video/mp4")
    elif video_input:
        create_payload["video_url"] = video_input

    headers = {"Idempotency-Key": init_key}
    if files:
        resp = client.post("/api/v1/projects", data=create_payload, files=files, headers=headers)
    else:
        resp = client.post("/api/v1/projects", data=create_payload, headers=headers)

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create project: {resp.status_code} - {resp.text}")

    project_data = resp.json()
    project_id = project_data["project_id"]
    print(f"[RUNNER] Created project: {project_id} (hash: {project_data['timeline_hash'][:12]}...)")

    results_steps: List[Dict[str, Any]] = []
    final_video_path: Optional[str] = None
    final_manifest_path: Optional[str] = None

    for idx, step in enumerate(steps, 1):
        say_text = step.get("say", "")
        answer_text = step.get("answer", "")
        print(f"\n[RUNNER] Step {idx}: say: '{say_text}'")

        # Check if step is a render command
        if say_text.strip().lower() == "render":
            render_key = f"render_{uuid.uuid4().hex[:8]}"
            r_resp = client.post(
                f"/api/v1/projects/{project_id}/render",
                json={},
                headers={"Idempotency-Key": render_key},
            )
            if r_resp.status_code != 202:
                raise RuntimeError(f"Render submission failed: {r_resp.status_code} - {r_resp.text}")

            job_data = r_resp.json()
            job_id = job_data["job_id"]
            print(f"[RUNNER] Render job submitted: {job_id}. Polling progress...")

            # Poll job
            job_result = None
            while True:
                time.sleep(0.5)
                poll_resp = client.get(f"/api/v1/jobs/{job_id}")
                p_data = poll_resp.json()
                status = p_data.get("status")
                progress = p_data.get("progress", 0)
                print(f"  > Job {job_id}: {status} ({progress}%)")

                if status == "succeeded":
                    job_result = p_data.get("result", {})
                    break
                elif status == "failed":
                    raise RuntimeError(f"Render job failed: {p_data.get('error')}")

            # Download final video and manifest
            video_url = job_result.get("output_video_url")
            manifest_url = job_result.get("manifest_url")

            final_video_path = os.path.join(output_dir, "rendered_video.mp4")
            v_get = client.get(video_url)
            with open(final_video_path, "wb") as vf:
                vf.write(v_get.content)

            if manifest_url:
                final_manifest_path = os.path.join(output_dir, "manifest.json")
                m_get = client.get(manifest_url)
                with open(final_manifest_path, "wb") as mf:
                    mf.write(m_get.content)

            step_record = {
                "step": idx,
                "say": say_text,
                "status": "applied",
                "operations": ["render"],
                "summary": f"Rendered output video successfully ({job_result.get('duration_s')}s).",
                "question": None,
                "options": None,
                "timeline_hash": job_result.get("timeline_hash", ""),
                "duration_s": job_result.get("duration_s", 0.0),
            }
            results_steps.append(step_record)
            continue

        # Regular instruction step
        step_key = f"step_{idx}_{uuid.uuid4().hex[:8]}"
        inst_resp = client.post(
            f"/api/v1/projects/{project_id}/instructions",
            json={"say": say_text},
            headers={"Idempotency-Key": step_key},
        )
        if inst_resp.status_code != 200:
            raise RuntimeError(f"Instruction failed: {inst_resp.status_code} - {inst_resp.text}")

        res_data = inst_resp.json()
        print(f"  > Status: {res_data.get('status')} - Summary: {res_data.get('summary')}")

        # If system asked for clarification and the test has an answer:
        if res_data.get("status") == "needs_clarification" and answer_text:
            print(f"  > Clarification Question: {res_data.get('question')}")
            print(f"  > Replying with Answer: '{answer_text}'")

            ans_key = f"ans_{idx}_{uuid.uuid4().hex[:8]}"
            ans_resp = client.post(
                f"/api/v1/projects/{project_id}/instructions",
                json={"answer": answer_text},
                headers={"Idempotency-Key": ans_key},
            )
            ans_data = ans_resp.json()
            print(f"  > Answer Status: {ans_data.get('status')} - Summary: {ans_data.get('summary')}")

            # Record combined step record with initial question and follow-up answer
            step_record = {
                "step": idx,
                "say": say_text,
                "answer": answer_text,
                "status": ans_data.get("status"),
                "operations": ans_data.get("operations", []),
                "summary": ans_data.get("summary", ""),
                "question": res_data.get("question"),
                "options": res_data.get("options"),
                "timeline_hash": ans_data.get("timeline_hash", ""),
                "duration_s": ans_data.get("duration_s", 0.0),
            }
            results_steps.append(step_record)
        else:
            step_record = {
                "step": idx,
                "say": say_text,
                "status": res_data.get("status"),
                "operations": res_data.get("operations", []),
                "summary": res_data.get("summary", ""),
                "question": res_data.get("question"),
                "options": res_data.get("options"),
                "timeline_hash": res_data.get("timeline_hash", ""),
                "duration_s": res_data.get("duration_s", 0.0),
            }
            results_steps.append(step_record)

    # Fetch final project timeline
    proj_resp = client.get(f"/api/v1/projects/{project_id}")
    final_timeline = proj_resp.json().get("timeline", {})

    # Save outputs to output_dir
    results_path = os.path.join(output_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "session_file": os.path.basename(session_path),
                "project_id": project_id,
                "steps": results_steps,
                "final_timeline_hash": final_timeline.get("timeline_hash"),
                "final_duration_s": final_timeline.get("duration_s") or (final_timeline.get("total_duration_ticks", 0) / 1000.0),
            },
            f,
            indent=2,
        )

    timeline_path = os.path.join(output_dir, "final_timeline.json")
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(final_timeline, f, indent=2)

    print(f"\n[RUNNER] Session complete!")
    print(f"[RUNNER] Results written to: {results_path}")
    print(f"[RUNNER] Final timeline: {timeline_path}")
    if final_video_path:
        print(f"[RUNNER] Final video: {final_video_path}")

    return {
        "results_path": results_path,
        "timeline_path": timeline_path,
        "video_path": final_video_path,
        "manifest_path": final_manifest_path,
    }


def main():
    parser = argparse.ArgumentParser(description="IncuBrix Scripted Session Runner")
    parser.add_argument("input_path", help="Path to YAML session file or folder of session files")
    parser.add_argument("--output-dir", default="session_results", help="Directory to save session outputs")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Base URL of IncuBrix HTTP service")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input_path)
    if os.path.isfile(input_path):
        run_session_file(input_path, args.output_dir, args.api_url)
    elif os.path.isdir(input_path):
        yaml_files = sorted(list(Path(input_path).glob("*.yaml")) + list(Path(input_path).glob("*.yml")))
        if not yaml_files:
            print(f"No YAML files found in {input_path}")
            sys.exit(1)
        for yf in yaml_files:
            sub_out = os.path.join(args.output_dir, yf.stem)
            run_session_file(str(yf), sub_out, args.api_url)
    else:
        print(f"Error: {input_path} is neither a file nor a directory.")
        sys.exit(1)


if __name__ == "__main__":
    main()
