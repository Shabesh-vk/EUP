"""
API Routes for Sessions, Steps, Jobs, Render, and Health.
All routes reside strictly under /api/v1/ (Integration Standard 2).
"""

from __future__ import annotations
import uuid
import asyncio
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Header, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from ..core.models import Transcript, StepResponse
from ..core.timeline_engine import TimelineEngine
from ..ai.brain import VideoEditingBrain
from ..render.renderer import FFmpegRenderer
from ..render.otio_export import export_timeline_to_otio
from .jobs import (
    create_job,
    get_job,
    update_job_progress,
    complete_job,
    generate_output_manifest,
    JobStatus,
)
from .config import settings
from .middleware import IDEMPOTENCY_CACHE, format_api_error
from ..runner.session_runner import load_or_create_transcript

router = APIRouter()

# Active Sessions store: session_id -> { "engine": TimelineEngine, "brain": VideoEditingBrain }
SESSIONS: Dict[str, Dict[str, Any]] = {}


class CreateSessionRequest(BaseModel):
    video_url: str = Field(..., description="URL or local path to video file")
    transcript: Optional[Transcript] = Field(default=None, description="Optional custom word transcript")


class CreateSessionResponse(BaseModel):
    session_id: str
    video_url: str
    duration_s: float
    timeline_hash: str


class StepRequest(BaseModel):
    say: str = Field(..., description="Creator plain-language instruction")
    answer: Optional[str] = Field(default=None, description="Optional reply if resolving a clarification")
    pending_clarification: Optional[Dict[str, Any]] = Field(default=None)


class RenderRequest(BaseModel):
    callback_url: Optional[str] = None


# -------------------------------------------------------------
# Health & Readiness Endpoints (Integration Standard 8)
# -------------------------------------------------------------
@router.get("/health", tags=["Health"])
def health():
    return {"status": "healthy", "version": settings.app_version}


@router.get("/ready", tags=["Health"])
def ready():
    return {
        "status": "ready",
        "llm_provider": settings.llm_provider,
        "s3_endpoint": settings.s3_endpoint_url,
    }


# -------------------------------------------------------------
# Sessions API (/api/v1/sessions)
# -------------------------------------------------------------
@router.post("/sessions", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED, tags=["Sessions"])
def create_session(
    payload: CreateSessionRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    session_id = f"sess_{uuid.uuid4().hex[:10]}"
    transcript = payload.transcript or load_or_create_transcript(payload.video_url)
    engine = TimelineEngine(transcript, source_video_url=payload.video_url)
    brain = VideoEditingBrain()

    SESSIONS[session_id] = {
        "engine": engine,
        "brain": brain,
        "video_url": payload.video_url,
        "pending_clarification": None,
    }

    resp = CreateSessionResponse(
        session_id=session_id,
        video_url=payload.video_url,
        duration_s=engine.get_current_duration(),
        timeline_hash=engine.get_timeline_hash(),
    )

    if idempotency_key:
        IDEMPOTENCY_CACHE[idempotency_key] = (201, resp.model_dump())

    return resp


@router.get("/sessions/{session_id}/timeline", tags=["Sessions"])
def get_session_timeline(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        return format_api_error("SESSION_NOT_FOUND", f"Session {session_id} does not exist", status_code=404)
    return session["engine"].timeline.model_dump()


@router.post("/sessions/{session_id}/steps", response_model=StepResponse, tags=["Sessions"])
def execute_step(
    session_id: str,
    payload: StepRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    session = SESSIONS.get(session_id)
    if not session:
        return format_api_error("SESSION_NOT_FOUND", f"Session {session_id} does not exist", status_code=404)

    engine: TimelineEngine = session["engine"]
    brain: VideoEditingBrain = session["brain"]
    pending = payload.pending_clarification or session.get("pending_clarification")

    res: StepResponse = brain.process_instruction(
        instruction=payload.say,
        engine=engine,
        answer=payload.answer,
        pending_clarification=pending,
    )

    if res.status == "needs_clarification" and res.clarification:
        session["pending_clarification"] = res.clarification.model_dump()
    else:
        session["pending_clarification"] = None

    if idempotency_key:
        IDEMPOTENCY_CACHE[idempotency_key] = (200, res.model_dump())

    return res


# -------------------------------------------------------------
# Background Jobs & Rendering (Integration Standards 3 & 7)
# -------------------------------------------------------------
@router.post("/sessions/{session_id}/render", status_code=status.HTTP_202_ACCEPTED, tags=["Jobs"])
def render_session(
    session_id: str,
    payload: RenderRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    session = SESSIONS.get(session_id)
    if not session:
        return format_api_error("SESSION_NOT_FOUND", f"Session {session_id} does not exist", status_code=404)

    job = create_job(payload.callback_url)

    # Launch background rendering task
    background_tasks.add_task(
        _render_worker,
        job.job_id,
        session["engine"],
        session["video_url"],
        payload.callback_url,
    )

    resp_data = {
        "job_id": job.job_id,
        "status": "queued",
        "progress": 0,
        "links": {"status_url": f"/api/v1/jobs/{job.job_id}"},
    }

    if idempotency_key:
        IDEMPOTENCY_CACHE[idempotency_key] = (202, resp_data)

    return resp_data


@router.get("/jobs/{job_id}", response_model=JobStatus, tags=["Jobs"])
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return format_api_error("JOB_NOT_FOUND", f"Job {job_id} does not exist", status_code=404)
    return job


async def _render_worker(job_id: str, engine: TimelineEngine, video_url: str, callback_url: Optional[str]):
    update_job_progress(job_id, 10, "running")
    await asyncio.sleep(0.1)

    renderer = FFmpegRenderer()
    out_dir = f"./output/renders/{job_id}"
    out_file = f"{out_dir}/rendered.mp4"
    otio_file = f"{out_dir}/timeline.otio"

    update_job_progress(job_id, 40, "running")
    # Export OTIO
    export_timeline_to_otio(engine.timeline, otio_file)

    update_job_progress(job_id, 70, "running")
    render_manifest = renderer.render(engine.timeline, video_url, out_file)

    manifest = generate_output_manifest(
        duration_s=engine.get_current_duration(),
        models_used=[{"type": "llm", "provider": settings.llm_provider, "version": "1.0.0"}],
    )

    update_job_progress(job_id, 90, "running")
    complete_job(
        job_id=job_id,
        result_links={
            "video_url": f"/download/{job_id}/rendered.mp4",
            "otio_url": f"/download/{job_id}/timeline.otio",
            "timeline_json": f"/download/{job_id}/timeline.json",
        },
        manifest=manifest,
        callback_url=callback_url,
        webhook_secret=settings.webhook_secret,
    )
