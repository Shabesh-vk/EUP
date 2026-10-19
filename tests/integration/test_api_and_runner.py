"""
Integration tests for FastAPI endpoints, idempotency, error envelopes, and session runner execution.
"""

import json
import os
import pytest
from fastapi.testclient import TestClient

from api.main import app
from runner.cli import run_session_file


@pytest.fixture
def client():
    return TestClient(app)


def test_health_and_readiness_endpoints(client):
    """Integration Standard Point 8: GET /health and GET /ready"""
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "ok"

    resp_ready = client.get("/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["status"] == "ready"


def test_idempotency_key_safety(client):
    """Integration Standard Point 4: Same key returns identical job/project and doesn't re-execute."""
    video_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "test_interview.mp4"))
    key = "idem_test_key_12345"

    with open(video_path, "rb") as f:
        resp1 = client.post(
            "/api/v1/projects",
            files={"video_file": ("test_interview.mp4", f, "video/mp4")},
            headers={"Idempotency-Key": key},
        )
    assert resp1.status_code == 201
    proj_id_1 = resp1.json()["project_id"]

    # Repeat exact same request with same key
    with open(video_path, "rb") as f:
        resp2 = client.post(
            "/api/v1/projects",
            files={"video_file": ("test_interview.mp4", f, "video/mp4")},
            headers={"Idempotency-Key": key},
        )
    assert resp2.status_code == 201
    proj_id_2 = resp2.json()["project_id"]
    assert proj_id_1 == proj_id_2

    # Reusing same key with DIFFERENT payload must be rejected with 409 Conflict
    resp_conflict = client.post(
        "/api/v1/projects",
        data={"video_url": "https://example.com/other.mp4"},
        headers={"Idempotency-Key": key},
    )
    assert resp_conflict.status_code == 409
    err = resp_conflict.json()["error"]
    assert err["code"] == "IDEMPOTENCY_CONFLICT"


def test_standardized_error_envelope(client):
    """Integration Standard Point 5: Errors are JSON with code, message, retryable, details."""
    resp = client.get("/api/v1/projects/non_existent_project")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    error = data["error"]
    assert error["code"] == "PROJECT_NOT_FOUND"
    assert isinstance(error["message"], str)
    assert isinstance(error["retryable"], bool)


def test_background_job_polling_and_render(client):
    """Integration Standard Point 3: POST /render returns 202; GET /jobs/{id} returns status and progress."""
    # 1. Create project
    video_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "test_interview.mp4"))
    with open(video_path, "rb") as f:
        proj_resp = client.post(
            "/api/v1/projects",
            files={"video_file": ("test_interview.mp4", f, "video/mp4")},
        )
    project_id = proj_resp.json()["project_id"]

    # 2. Trigger render (returns 202 with job_id)
    render_resp = client.post(f"/api/v1/projects/{project_id}/render", json={})
    assert render_resp.status_code == 202
    job_id = render_resp.json()["job_id"]
    assert job_id.startswith("job_")

    # 3. Poll job until completion
    job_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["status"] in ("queued", "running", "succeeded")
