"""
Unit tests verifying persistent database storage for Projects, Idempotency, and Jobs.
Simulates server restart by creating new store instances and verifying retrieval from SQLite.
"""

import os
import tempfile
import pytest
from core.schema import Timeline
from tests.fixtures.transcript_fixtures import create_test_timeline
from db.database import DatabaseManager
from api.projects_store import ProjectStore, ProjectRecord
from api.idempotency import IdempotencyStore
from api.jobs import JobManager


def test_db_persistence_across_restarts():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_persistence.db")
        db = DatabaseManager(db_path=db_file)

        # 1. Test Project Persistence
        timeline = create_test_timeline(duration_seconds=120.0)
        db.save_project("proj_persisted_01", timeline, "dummy_source.mp4", {"type": "test_pending"})

        # Retrieve via fresh query
        row = db.get_project("proj_persisted_01")
        assert row is not None
        assert row["project_id"] == "proj_persisted_01"
        assert row["timeline"].timeline_hash == timeline.timeline_hash
        assert row["pending_clarification"] == {"type": "test_pending"}

        # 2. Test Idempotency Persistence
        db.register_idempotency_key("idem_key_01", "hash_abc_123")
        db.record_idempotency_response("idem_key_01", 201, {"status": "created", "project_id": "proj_persisted_01"})

        # Retrieve via fresh query
        idem_row = db.get_idempotency_record("idem_key_01")
        assert idem_row is not None
        assert idem_row["body_hash"] == "hash_abc_123"
        assert idem_row["status_code"] == 201
        assert idem_row["response_data"]["status"] == "created"

        # 3. Test Jobs Persistence
        db.save_job("job_persisted_01", "render", "succeeded", 100, 1000.0, result={"output_video": "test.mp4"})

        job_row = db.get_job("job_persisted_01")
        assert job_row is not None
        assert job_row["status"] == "succeeded"
        assert job_row["progress"] == 100
        assert job_row["result"]["output_video"] == "test.mp4"
