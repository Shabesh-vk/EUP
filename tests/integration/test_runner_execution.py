"""
End-to-end integration test running the CLI Session Runner against the HTTP API server.
Verifies reproduction of the 8-step worked example through the full runner toolchain.
"""

import os
import shutil
import threading
import time
import pytest
import uvicorn
from api.main import app
from runner.cli import run_session_file


class ServerThread(threading.Thread):
    def __init__(self, host="127.0.0.1", port=8001):
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
def running_server():
    server = ServerThread(host="127.0.0.1", port=8001)
    server.start()
    # Wait for server to start
    time.sleep(1.0)
    yield "http://127.0.0.1:8001"
    server.stop()


def test_session_runner_worked_example_end_to_end(running_server, tmp_path):
    session_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "sessions", "session_01_worked_example.yaml")
    )
    output_dir = str(tmp_path / "session_worked_example_output")

    # Run CLI runner against the live server
    res = run_session_file(session_file, output_dir, api_base_url=running_server)

    assert os.path.isfile(res["results_path"])
    assert os.path.isfile(res["timeline_path"])
    assert os.path.isfile(res["video_path"])
    assert os.path.isfile(res["manifest_path"])

    import json
    with open(res["results_path"], "r", encoding="utf-8") as f:
        results_data = json.load(f)

    steps = results_data["steps"]
    assert len(steps) == 8

    # Step 1: Add caption Welcome!
    assert steps[0]["status"] == "applied"
    assert "Welcome!" in steps[0]["summary"]

    # Step 2: Cut first 30s
    assert steps[1]["status"] == "applied"
    assert "30.0s shorter" in steps[1]["summary"]

    # Step 3: Remove pricing (disambiguated with 'the second one')
    assert steps[2]["status"] == "applied"
    assert "pricing" in steps[2]["question"].lower()
    assert "shorter" in steps[2]["summary"].lower()


    # Step 4: Speed up 1:00-1:30 by 2x
    assert steps[3]["status"] == "applied"
    assert "speed_range" in steps[3]["operations"]

    # Step 5: Restore intro
    assert steps[4]["status"] == "applied"
    assert "restore" in steps[4]["summary"].lower() or "intro" in steps[4]["summary"].lower()

    # Step 6: Undo
    assert steps[5]["status"] == "applied"
    assert "undo" in steps[5]["operations"]

    # Step 7: Make caption red
    assert steps[6]["status"] == "applied"
    assert "red" in steps[6]["summary"].lower()

    # Step 8: Render
    assert steps[7]["status"] == "applied"
    assert "render" in steps[7]["operations"]
    assert steps[7]["duration_s"] > 0
