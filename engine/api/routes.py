"""FastAPI v1 API routes implementing the IncuBrix Editing Engine interface.

All endpoints adhere to Integration Standards:
- /api/v1/ routes
- Background jobs with 202 response
- Idempotency-Key handling
- Structured JSON responses
- Download links from storage
"""

import uuid
from pathlib import Path
from typing import Dict, Optional, Any
from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import FileResponse, JSONResponse

from engine.api.models import (
    HealthResponse,
    StepRequest,
    StepResponse,
    CreateSessionRequest,
    SessionInfoResponse,
    CreateJobRequest,
    JobStatusResponse,
    ErrorResponse
)
from engine.core.timeline import Timeline
from engine.core.otio_export import export_to_otio
from engine.parser.nl_parser import InstructionEngine
from engine.media.probe import probe_media_file
from engine.media.transcriber import get_transcriber
from engine.media.renderer import render_timeline_video
from engine.storage.s3_minio import get_storage
from engine.jobs.queue import job_manager, Job
from engine.config import settings
from engine.logging_config import logger

router = APIRouter()

# In-memory session store: session_id -> { "timeline": Timeline, "engine": InstructionEngine }
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}


# -----------------------------------------------------------------------------
# Health & Readiness
# -----------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health():
    """Liveness probe returning 200 OK."""
    return HealthResponse(status="ok", service="incubrix-editing-engine", version="1.0.0")


@router.get("/ready", response_model=HealthResponse, tags=["Health"])
async def get_ready():
    """Readiness probe confirming engine is prepared to process tasks."""
    return HealthResponse(status="ready", service="incubrix-editing-engine", version="1.0.0")


# -----------------------------------------------------------------------------
# Sessions & Interactive Steps
# -----------------------------------------------------------------------------

@router.post(
    "/api/v1/sessions",
    response_model=SessionInfoResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Sessions"]
)
async def create_session(req: CreateSessionRequest):
    """Initializes a new editing session for a video."""
    storage = get_storage()
    local_path = f"./storage_data/temp_{uuid.uuid4().hex[:8]}.mp4"

    try:
        source_file = storage.fetch_file(req.video_url_or_path, local_path)
    except Exception:
        # If fetch fails, use path directly
        source_file = req.video_url_or_path

    source_media = probe_media_file(source_file)
    transcriber = get_transcriber()
    transcript, warnings = transcriber.transcribe(source_file)

    timeline = Timeline(
        source=source_media,
        transcript=transcript,
        time_policy=req.time_policy or settings.DEFAULT_TIME_POLICY
    )
    engine = InstructionEngine(timeline=timeline)

    session_id = str(uuid.uuid4())
    ACTIVE_SESSIONS[session_id] = {
        "timeline": timeline,
        "engine": engine,
        "source_file": source_file,
        "warnings": warnings
    }

    return SessionInfoResponse(
        session_id=session_id,
        source_media_id=source_media.media_id,
        duration_s=timeline.total_duration,
        fps=source_media.fps,
        time_policy=timeline.time_policy,
        timeline_hash=timeline.timeline_hash
    )


@router.get(
    "/api/v1/sessions/{session_id}",
    response_model=SessionInfoResponse,
    tags=["Sessions"]
)
async def get_session(session_id: str):
    """Retrieves metadata of an active session."""
    session = ACTIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} does not exist."}
        )
    tl: Timeline = session["timeline"]
    return SessionInfoResponse(
        session_id=session_id,
        source_media_id=tl.source.media_id,
        duration_s=tl.total_duration,
        fps=tl.source.fps,
        time_policy=tl.time_policy,
        timeline_hash=tl.timeline_hash
    )


@router.post(
    "/api/v1/sessions/{session_id}/step",
    response_model=StepResponse,
    tags=["Sessions"]
)
async def execute_step(session_id: str, step: StepRequest):
    """Executes a single natural language editing instruction on the session timeline."""
    session = ACTIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found."}
        )

    engine: InstructionEngine = session["engine"]
    result = engine.execute_instruction(step.say, answer=step.answer)

    return StepResponse(
        status=result.status,
        operations=result.operations,
        summary=result.summary,
        question=result.question,
        options=result.options,
        reason=result.reason,
        timeline_hash=result.timeline_hash,
        duration_s=result.duration_s,
        warnings=result.warnings
    )


# -----------------------------------------------------------------------------
# Background Jobs
# -----------------------------------------------------------------------------

@router.post(
    "/api/v1/jobs",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Jobs"]
)
async def create_job(
    req: CreateJobRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """Enqueues an asynchronous background job (> 2s tasks), returning 202 with job_id."""
    existing_job = job_manager.get_by_idempotency_key(idempotency_key) if idempotency_key else None
    if existing_job:
        response.status_code = status.HTTP_200_OK
        return JobStatusResponse(**existing_job.to_dict())

    job = job_manager.create_job(idempotency_key=idempotency_key, callback_url=req.callback_url)

    async def _run_job_task(j: Job) -> Dict[str, Any]:
        storage = get_storage()

        if req.job_type == "render":
            session = ACTIVE_SESSIONS.get(req.session_id or "")
            if not session:
                raise ValueError(f"Session {req.session_id} not found.")

            tl: Timeline = session["timeline"]
            out_filename = f"render_{j.job_id}.mp4"
            local_render_path = f"./storage_data/{out_filename}"

            def _on_prog(p: int):
                j.update_progress(p)

            rendered_path, manifest = render_timeline_video(
                timeline=tl,
                output_path=local_render_path,
                progress_callback=_on_prog
            )

            download_url = storage.save_file(rendered_path, out_filename)
            return {
                "download_url": download_url,
                "timeline_hash": tl.timeline_hash,
                "duration_s": tl.total_duration,
                "manifest": manifest
            }

        elif req.job_type == "session_run":
            # Play a scripted session
            source_file = req.video_url_or_path or "./sample.mp4"
            source_media = probe_media_file(source_file)
            transcriber = get_transcriber()
            transcript, _ = transcriber.transcribe(source_file)
            tl = Timeline(source=source_media, transcript=transcript)
            eng = InstructionEngine(timeline=tl)

            step_results = []
            steps = req.steps or []
            total_steps = len(steps)

            for idx, s in enumerate(steps):
                res = eng.execute_instruction(s.say, answer=s.answer)
                step_results.append(res.model_dump())
                j.update_progress(int(((idx + 1) / max(1, total_steps)) * 80))

            # Auto-render final video
            out_filename = f"session_{j.job_id}.mp4"
            local_render_path = f"./storage_data/{out_filename}"
            rendered_path, manifest = render_timeline_video(tl, local_render_path)
            download_url = storage.save_file(rendered_path, out_filename)

            j.update_progress(100)
            return {
                "step_results": step_results,
                "download_url": download_url,
                "timeline_hash": tl.timeline_hash,
                "duration_s": tl.total_duration,
                "manifest": manifest
            }

        return {"message": "Job completed successfully."}

    job_manager.run_job_async(job, _run_job_task)
    return JobStatusResponse(**job.to_dict())


@router.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Jobs"]
)
async def get_job_status(job_id: str):
    """Retrieves progress and status of a background job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": f"Job {job_id} does not exist."}
        )
    return JobStatusResponse(**job.to_dict())


# -----------------------------------------------------------------------------
# Timeline & OpenTimelineIO
# -----------------------------------------------------------------------------

@router.get("/api/v1/timeline/{session_id}", tags=["Timeline"])
async def get_timeline_data(session_id: str):
    """Returns the full timeline data structure and resolved state."""
    session = ACTIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found."}
        )
    tl: Timeline = session["timeline"]
    resolved_caps, _ = tl.get_resolved_captions()
    resolved_effs = tl.get_resolved_audio_effects()

    return {
        "timeline_hash": tl.timeline_hash,
        "total_duration_s": tl.total_duration,
        "time_policy": tl.time_policy,
        "clips": [c.model_dump() for c in tl.clips],
        "captions": [c.model_dump() for c in resolved_caps],
        "effects": [e.model_dump() for e in resolved_effs],
        "history": [h.model_dump() for h in tl.history]
    }


@router.post("/api/v1/timeline/{session_id}/otio", tags=["Timeline"])
async def export_otio(session_id: str):
    """Exports the timeline to OpenTimelineIO (.otio) format."""
    session = ACTIVE_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found."}
        )
    tl: Timeline = session["timeline"]
    otio_filename = f"export_{session_id}.otio"
    local_otio_path = f"./storage_data/{otio_filename}"
    export_to_otio(tl, local_otio_path)

    storage = get_storage()
    download_url = storage.save_file(local_otio_path, otio_filename)
    return {"otio_download_url": download_url}


# -----------------------------------------------------------------------------
# Storage Download Link
# -----------------------------------------------------------------------------

@router.get("/api/v1/storage/download/{filename:path}", tags=["Storage"])
async def download_storage_file(filename: str):
    """Serves files stored in local storage."""
    file_path = Path(settings.STORAGE_LOCAL_DIR) / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": "FILE_NOT_FOUND", "message": f"File '{filename}' not found in storage."}
        )
    return FileResponse(path=str(file_path), filename=file_path.name)
