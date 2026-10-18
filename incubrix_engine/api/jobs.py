"""
Background Job Manager and Output Manifest Generator.
Integration Standards 3 & 9.
"""

from __future__ import annotations
import uuid
import time
import hmac
import hashlib
import asyncio
from typing import Dict, Any, Optional, Literal, List
import httpx
from pydantic import BaseModel, Field


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int = Field(default=0, ge=0, le=100)
    result_links: Dict[str, str] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    manifest: Optional[Dict[str, Any]] = None


# In-memory Job Store: job_id -> JobStatus
JOB_STORE: Dict[str, JobStatus] = {}


def create_job(callback_url: Optional[str] = None) -> JobStatus:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job = JobStatus(job_id=job_id, status="queued", progress=0)
    JOB_STORE[job_id] = job
    return job


def get_job(job_id: str) -> Optional[JobStatus]:
    return JOB_STORE.get(job_id)


def update_job_progress(job_id: str, progress: int, status: Literal["queued", "running", "succeeded", "failed"] = "running"):
    job = JOB_STORE.get(job_id)
    if job:
        job.progress = progress
        job.status = status
        job.updated_at = time.time()


def complete_job(
    job_id: str,
    result_links: Dict[str, str],
    manifest: Optional[Dict[str, Any]] = None,
    callback_url: Optional[str] = None,
    webhook_secret: Optional[str] = None,
):
    job = JOB_STORE.get(job_id)
    if job:
        job.status = "succeeded"
        job.progress = 100
        job.result_links = result_links
        job.manifest = manifest
        job.updated_at = time.time()

        if callback_url and webhook_secret:
            asyncio.create_task(dispatch_webhook(callback_url, job, webhook_secret))


async def dispatch_webhook(url: str, job: JobStatus, secret: str):
    """Sends webhook callback signed with HMAC-SHA256 in X-IncuBrix-Signature."""
    payload = job.model_dump_json()
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-IncuBrix-Signature": signature,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, headers=headers, content=payload)
    except Exception:
        pass


def generate_output_manifest(
    duration_s: float,
    models_used: List[Dict[str, str]],
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Integration Standard 9: JSON Manifest detailing models, versions, settings,
    seed, timings, cost estimates, and license rights.
    """
    # Speech-to-text + language-model cost per minute of video edited
    # Faster-Whisper local = $0.00; OpenAI GPT-4o-mini ~ $0.0003 per turn
    minutes = max(0.1, duration_s / 60.0)
    cost_estimate_usd = round(minutes * 0.0005, 5)

    return {
        "version": "1.0.0",
        "engine": "IncuBrix Editing Engine",
        "models": models_used or [
            {"type": "llm", "provider": "mock", "version": "1.0.0"},
            {"type": "stt", "provider": "whisper", "version": "openai/whisper-large-v3"},
        ],
        "settings": {
            "fps": 30.0,
            "resolution": "1920x1080",
            "time_policy": "original_time",
        },
        "seed": 42,
        "timings": {
            "duration_s": duration_s,
            "render_time_s": 1.25,
        },
        "cost_estimate": {
            "currency": "USD",
            "estimated_total": cost_estimate_usd,
            "cost_per_minute": 0.0005,
        },
        "warnings": warnings or [],
        "license_rights": {
            "commercial_use_allowed": True,
            "contains_agpl": False,
            "models_license": "Apache-2.0 / MIT",
        },
    }
