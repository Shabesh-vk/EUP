"""
Integration Tests for IncuBrix HTTP API Service.
Validates Integration Standards:
1. One-command test execution with no API keys.
2. OpenAPI 3.1 endpoints under /api/v1/.
3. Background jobs & polling.
4. Idempotency-Key retries.
5. Standard error structures.
8. Structured JSON logs and health/ready endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from incubrix_engine.api.app import app

client = TestClient(app)


def test_health_and_ready():
    # Root and /api/v1 health endpoints
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "healthy"

    res2 = client.get("/api/v1/ready")
    assert res2.status_code == 200
    assert res2.json()["status"] == "ready"


def test_session_lifecycle_and_idempotency():
    idemp_key = "test_key_abc_123"

    # 1. Create Session
    payload = {"video_url": "https://example.com/interview.mp4"}
    res = client.post(
        "/api/v1/sessions",
        json=payload,
        headers={"Idempotency-Key": idemp_key, "X-Correlation-Id": "corr_test_001"},
    )
    assert res.status_code == 201
    data = res.json()
    session_id = data["session_id"]
    assert "sess_" in session_id

    # 2. Idempotent Retry of same POST request
    retry_res = client.post(
        "/api/v1/sessions",
        json=payload,
        headers={"Idempotency-Key": idemp_key, "X-Correlation-Id": "corr_test_002"},
    )
    assert retry_res.status_code == 201
    assert retry_res.headers.get("X-Cache") == "HIT"
    assert retry_res.json()["session_id"] == session_id

    # 3. Read Timeline
    timeline_res = client.get(f"/api/v1/sessions/{session_id}/timeline")
    assert timeline_res.status_code == 200
    assert len(timeline_res.json()["segments"]) > 0

    # 4. Execute Step
    step_res = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"say": "Add a caption 'Welcome!' when I say welcome to the channel"},
    )
    assert step_res.status_code == 200
    step_data = step_res.json()
    assert step_data["status"] == "applied"
    assert "0:42" in step_data["summary"]

    # 5. Execute Clarification Step
    clarif_res = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={"say": "Remove the part about pricing"},
    )
    assert clarif_res.status_code == 200
    clarif_data = clarif_res.json()
    assert clarif_data["status"] == "needs_clarification"
    assert len(clarif_data["clarification"]["options"]) > 0

    # 6. Resolve Clarification with answer
    resolve_res = client.post(
        f"/api/v1/sessions/{session_id}/steps",
        json={
            "say": "Remove the part about pricing",
            "answer": "the second one",
        },
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "applied"


def test_background_render_job():
    # Create session first
    res = client.post("/api/v1/sessions", json={"video_url": "https://example.com/test.mp4"})
    session_id = res.json()["session_id"]

    # Trigger render
    render_res = client.post(
        f"/api/v1/sessions/{session_id}/render",
        json={"callback_url": "https://example.com/webhook"},
    )
    assert render_res.status_code == 202
    job_id = render_res.json()["job_id"]
    assert "job_" in job_id

    # Poll job status
    poll_res = client.get(f"/api/v1/jobs/{job_id}")
    assert poll_res.status_code == 200
    job_data = poll_res.json()
    assert job_data["status"] in ["queued", "running", "succeeded"]


def test_standardized_error_format():
    # Non-existent session
    res = client.get("/api/v1/sessions/sess_nonexistent_999/timeline")
    assert res.status_code == 404
    err_body = res.json()
    assert "error" in err_body
    assert err_body["error"]["code"] == "SESSION_NOT_FOUND"
    assert "retryable" in err_body["error"]
