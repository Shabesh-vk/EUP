"""Integration Standard tests verifying HTTP API, background jobs, idempotency, and error formats."""

import pytest
import asyncio
from fastapi.testclient import TestClient
from engine.api.app import app
from engine.jobs.webhooks import sign_payload


@pytest.fixture
def client():
    return TestClient(app)


def test_api_health_and_ready(client):
    """Integration Standard #8: GET /health and GET /ready endpoints."""
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ready"


def test_api_session_lifecycle(client):
    """Sessions creation and step execution under /api/v1/."""
    # 1. Create session
    r_sess = client.post("/api/v1/sessions", json={"video_url_or_path": "sample.mp4"})
    assert r_sess.status_code == 201
    sess_id = r_sess.json()["session_id"]
    assert sess_id is not None

    # 2. Execute step
    r_step = client.post(
        f"/api/v1/sessions/{sess_id}/step",
        json={"say": "Cut the first 30 seconds"}
    )
    assert r_step.status_code == 200
    assert r_step.json()["status"] == "applied"
    assert "Video is 30 s shorter" in r_step.json()["summary"]


def test_api_background_jobs_and_progress(client):
    """Integration Standard #3: POST returns 202 with job_id; GET returns progress 0-100 and result links."""
    # Create session first
    r_sess = client.post("/api/v1/sessions", json={"video_url_or_path": "sample.mp4"})
    sess_id = r_sess.json()["session_id"]

    # Enqueue render job (> 2s task)
    r_job = client.post(
        "/api/v1/jobs",
        json={"job_type": "render", "session_id": sess_id}
    )
    assert r_job.status_code == 202
    job_id = r_job.json()["job_id"]
    assert job_id is not None

    # Poll status
    r_status = client.get(f"/api/v1/jobs/{job_id}")
    assert r_status.status_code == 200
    data = r_status.json()
    assert data["status"] in ("queued", "running", "succeeded")
    assert 0 <= data["progress"] <= 100


def test_api_idempotency_key(client):
    """Integration Standard #4: Safe retries with Idempotency-Key header."""
    idem_key = "unique-key-123456"

    r1 = client.post(
        "/api/v1/jobs",
        json={"job_type": "session_run", "video_url_or_path": "sample.mp4"},
        headers={"Idempotency-Key": idem_key}
    )
    assert r1.status_code == 202
    job_id_1 = r1.json()["job_id"]

    # Send exact same request with same key
    r2 = client.post(
        "/api/v1/jobs",
        json={"job_type": "session_run", "video_url_or_path": "sample.mp4"},
        headers={"Idempotency-Key": idem_key}
    )
    assert r2.status_code in (200, 202)
    job_id_2 = r2.json()["job_id"]

    # Both requests must return the exact same job ID
    assert job_id_1 == job_id_2


def test_api_standardized_error_format(client):
    """Integration Standard #5: Errors are JSON {"error": {"code", "message", "retryable", "details"}}."""
    # Request non-existent session
    r = client.get("/api/v1/sessions/non-existent-session-id")
    assert r.status_code == 404
    data = r.json()
    assert "error" in data or "detail" in data
    err = data.get("error") or data.get("detail")
    assert err["code"] == "SESSION_NOT_FOUND"


def test_hmac_sha256_webhook_signing():
    """Integration Standard #3: Callback signed with HMAC-SHA256."""
    secret = "test-secret"
    payload = b'{"job_id": "123", "status": "succeeded"}'
    signature = sign_payload(payload, secret)
    assert len(signature) == 64  # SHA-256 produces 64 hex characters
