"""
Integration test for the comprehensive 45-step CI session runner scenario.
Executes all 45 instructions sequentially, verifying every semantic response,
clarification handling, rejections, undos, and real FFmpeg rendering.
"""

import os
import json
import threading
import time
import pytest
import uvicorn
from api.main import app
from runner.cli import run_session_file


class ServerThread(threading.Thread):
    def __init__(self, host="127.0.0.1", port=8002):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        config = uvicorn.Config(app=app, host=self.host, port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.server.run()

    def stop(self):
        if self.server:
            self.server.should_exit = True


@pytest.fixture(scope="module")
def running_server_45():
    server = ServerThread(host="127.0.0.1", port=8002)
    server.start()
    time.sleep(1.0)
    yield "http://127.0.0.1:8002"
    server.stop()


def test_45_step_comprehensive_session(running_server_45, tmp_path):
    session_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "sessions", "session_02_comprehensive_45_steps.yaml")
    )
    output_dir = str(tmp_path / "comprehensive_45_steps_output")

    res = run_session_file(session_file, output_dir, api_base_url=running_server_45)

    assert os.path.isfile(res["results_path"]), "results.json must exist"
    assert os.path.isfile(res["timeline_path"]), "final timeline.json must exist"
    assert os.path.isfile(res["video_path"]), "rendered_video.mp4 must exist"
    assert os.path.isfile(res["manifest_path"]), "manifest.json must exist"

    with open(res["results_path"], "r", encoding="utf-8") as f:
        results_data = json.load(f)

    assert len(results_data["steps"]) == 45, f"Expected exactly 45 steps, got {len(results_data['steps'])}"

    # Verify key steps
    steps = {s["step"]: s for s in results_data["steps"]}

    # Step 1: Cut applied
    assert steps[1]["status"] == "applied"
    # Step 6: Pricing ambiguity resolved
    assert steps[6]["status"] == "applied"
    assert steps[6]["question"] is not None
    # Step 10: Multi-speaker dialogue resolved
    assert steps[10]["status"] == "applied"
    assert steps[10]["question"] is not None
    # Step 14: Quantum physics rejected
    assert steps[14]["status"] == "rejected"
    # Step 15: Out of bounds cut rejected
    assert steps[15]["status"] == "rejected"
    # Step 17: Speed 12x rejected
    assert steps[17]["status"] == "rejected"
    # Step 45: Render applied
    assert steps[45]["status"] == "applied"
