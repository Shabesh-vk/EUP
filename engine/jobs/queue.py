"""Asynchronous background job queue and idempotency manager.

Adheres to Integration Standards:
- #3: Background jobs: Anything slower than 2 seconds runs as a job:
  POST returns 202 with job_id; GET /api/v1/jobs/{job_id} returns status, progress (0-100), result links.
- #4: Safe retries: Idempotency-Key header on every POST returns identical job without duplicate work.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, Awaitable
from engine.logging_config import logger, job_id_ctx
from engine.jobs.webhooks import dispatch_webhook


class Job:
    """Represents an asynchronous background job."""

    def __init__(
        self,
        job_id: str,
        idempotency_key: Optional[str] = None,
        callback_url: Optional[str] = None
    ):
        self.job_id = job_id
        self.idempotency_key = idempotency_key
        self.callback_url = callback_url
        self.status = "queued"  # queued, running, succeeded, failed
        self.progress = 0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None

    def update_progress(self, progress: int, status: Optional[str] = None):
        self.progress = max(0, min(100, progress))
        if status:
            self.status = status
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def complete(self, result: Dict[str, Any]):
        self.status = "succeeded"
        self.progress = 100
        self.result = result
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if self.callback_url:
            dispatch_webhook(self.callback_url, self.to_dict())

    def fail(self, code: str, message: str, details: Optional[Any] = None, retryable: bool = False):
        self.status = "failed"
        self.error = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details
        }
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if self.callback_url:
            dispatch_webhook(self.callback_url, self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error
        }


class JobManager:
    """In-memory asynchronous background job manager with idempotency tracking."""

    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.idempotency_map: Dict[str, str] = {}  # idempotency_key -> job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Job]:
        job_id = self.idempotency_map.get(idempotency_key)
        return self.jobs.get(job_id) if job_id else None

    def create_job(
        self,
        idempotency_key: Optional[str] = None,
        callback_url: Optional[str] = None
    ) -> Job:
        """Returns existing job if idempotency_key matches, otherwise creates new job."""
        if idempotency_key and idempotency_key in self.idempotency_map:
            existing_job_id = self.idempotency_map[idempotency_key]
            logger.info(f"Idempotent hit for key '{idempotency_key}', returning job '{existing_job_id}'")
            return self.jobs[existing_job_id]

        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, idempotency_key=idempotency_key, callback_url=callback_url)
        self.jobs[job_id] = job

        if idempotency_key:
            self.idempotency_map[idempotency_key] = job_id

        return job

    def run_job_async(
        self,
        job: Job,
        coro_func: Callable[[Job], Awaitable[Dict[str, Any]]]
    ):
        """Dispatches job execution to the background event loop."""
        async def _wrapper():
            token = job_id_ctx.set(job.job_id)
            job.update_progress(5, status="running")
            try:
                result = await coro_func(job)
                job.complete(result)
            except Exception as e:
                logger.exception(f"Job {job.job_id} encountered an error: {e}")
                job.fail(
                    code="JOB_EXECUTION_ERROR",
                    message=str(e),
                    retryable=False
                )
            finally:
                job_id_ctx.reset(token)

        asyncio.create_task(_wrapper())


# Global JobManager singleton
job_manager = JobManager()
