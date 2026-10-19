"""
Background job management supporting status polling, signed HMAC webhooks,
and persistent database state. Integration Standard Point 3.
"""

from __future__ import annotations
import hmac
import hashlib
import json
import threading
import time
import uuid
from typing import Dict, Any, Optional, Literal, Callable
import httpx
from pydantic import BaseModel, Field

from .config import settings
from .middleware import logger
from db.database import db


class JobInfo(BaseModel):
    job_id: str
    job_type: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int = Field(ge=0, le=100, default=0)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    created_at: float
    completed_at: Optional[float] = None


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, JobInfo] = {}
        self._lock = threading.Lock()

    def create_job(self, job_type: str, callback_url: Optional[str] = None) -> JobInfo:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = time.time()
        job = JobInfo(
            job_id=job_id,
            job_type=job_type,
            status="queued",
            progress=0,
            created_at=now,
        )
        with self._lock:
            self._jobs[job_id] = job
        try:
            db.save_job(job_id, job_type, "queued", 0, now)
        except Exception:
            pass
        return job

    def get_job(self, job_id: str) -> Optional[JobInfo]:
        with self._lock:
            if job_id in self._jobs:
                return self._jobs[job_id]
        
        # Check persistent database
        try:
            row = db.get_job(job_id)
            if row:
                job = JobInfo(
                    job_id=row["job_id"],
                    job_type=row["job_type"],
                    status=row["status"],
                    progress=row["progress"],
                    result=row["result"],
                    error=row["error"],
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                )
                with self._lock:
                    self._jobs[job_id] = job
                return job
        except Exception:
            pass

        return None

    def update_progress(self, job_id: str, progress: int, status: Optional[str] = None):
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.progress = max(0, min(100, progress))
                if status:
                    job.status = status
                try:
                    db.save_job(
                        job.job_id,
                        job.job_type,
                        job.status,
                        job.progress,
                        job.created_at,
                        result=job.result,
                        error=job.error,
                        completed_at=job.completed_at,
                    )
                except Exception:
                    pass

    def complete_job(self, job_id: str, result: Dict[str, Any], callback_url: Optional[str] = None):
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = "succeeded"
                job.progress = 100
                job.result = result
                job.completed_at = time.time()
                try:
                    db.save_job(
                        job.job_id,
                        job.job_type,
                        job.status,
                        job.progress,
                        job.created_at,
                        result=job.result,
                        error=job.error,
                        completed_at=job.completed_at,
                    )
                except Exception:
                    pass

        if callback_url:
            self._dispatch_webhook(job_id, callback_url, result)

    def fail_job(self, job_id: str, error_detail: Dict[str, Any], callback_url: Optional[str] = None):
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error = error_detail
                job.completed_at = time.time()
                try:
                    db.save_job(
                        job.job_id,
                        job.job_type,
                        job.status,
                        job.progress,
                        job.created_at,
                        result=job.result,
                        error=job.error,
                        completed_at=job.completed_at,
                    )
                except Exception:
                    pass

        if callback_url:
            self._dispatch_webhook(job_id, callback_url, {"error": error_detail})

    def _dispatch_webhook(self, job_id: str, callback_url: str, payload: Dict[str, Any]):
        """Dispatch signed HMAC-SHA256 webhook to optional callback URL."""
        def _send():
            try:
                body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
                signature = hmac.new(
                    settings.webhook_signing_secret.encode("utf-8"),
                    body_bytes,
                    hashlib.sha256,
                ).hexdigest()
                headers = {
                    "Content-Type": "application/json",
                    "X-IncuBrix-Signature": f"sha256={signature}",
                    "X-Job-Id": job_id,
                }
                with httpx.Client(timeout=10.0) as client:
                    client.post(callback_url, content=body_bytes, headers=headers)
            except Exception as e:
                logger.error(f"Failed to deliver callback for job {job_id}: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def submit_background_task(
        self,
        job_type: str,
        task_fn: Callable[..., Dict[str, Any]],
        callback_url: Optional[str] = None,
        *args,
        **kwargs,
    ) -> JobInfo:
        job = self.create_job(job_type, callback_url=callback_url)

        def _runner():
            self.update_progress(job.job_id, 10, status="running")
            try:
                result = task_fn(job.job_id, *args, **kwargs)
                self.complete_job(job.job_id, result, callback_url=callback_url)
            except Exception as e:
                logger.error(f"Job {job.job_id} encountered error: {e}")
                self.fail_job(job.job_id, {"code": "TASK_FAILED", "message": str(e)}, callback_url=callback_url)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        return job


job_manager = JobManager()
