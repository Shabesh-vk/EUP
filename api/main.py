"""
FastAPI HTTP application for the IncuBrix Prompt-Based Video Editing Engine.
Implements the 10 Integration Standard points.
"""

from __future__ import annotations
import json
import os
import shutil
import time
import uuid
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, Response, status, Header, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


from core.schema import Timeline, SourceMedia, ClipSegment, Transcript, EffectsCollection
from core.engine import TimelineEngine, EngineResponse
from core.canonicalizer import compute_timeline_hash
from media.inspector import inspect_media_file, compute_file_sha256
from media.renderer import render_timeline
from storage.storage import get_storage
from stt.factory import get_transcription_adapter

from .config import settings
from .errors import IncuBrixException, incubrix_exception_handler, general_exception_handler
from .middleware import CorrelationIdMiddleware, logger
from .idempotency import idempotency_store
from .jobs import job_manager, JobInfo
from .manifest import generate_output_manifest
from .projects_store import project_store, ProjectRecord
from nlu.dispatcher import process_instruction
from nlu.llm_adapter import get_model_status
from core.schema import AutoEditPlan
from db.database import db

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Exception handlers
app.add_exception_handler(IncuBrixException, incubrix_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Middlewares
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],

    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Integration Standard Point 8: Health & Ready Endpoints
# -----------------------------------------------------------------------------

@app.get("/health", tags=["System"])
@app.get("/api/v1/health", tags=["System"])
async def health_check():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/ready", tags=["System"])
async def readiness_check():
    # Verify storage writable
    storage = get_storage()
    if not os.path.isdir(storage.base_dir):
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "storage_not_ready"})
    return {"status": "ready", "engine": "online"}


@app.get("/api/v1/model/status", tags=["System"])
async def model_status_endpoint():
    """
    Integration Standard & NLU status: report model connectivity, active provider,
    and availability separately from API service health.
    """
    return get_model_status()


class ModelConfigRequest(BaseModel):
    provider: str  # "ollama" | "gemini" | "semantic_rule"
    model: Optional[str] = None
    host: Optional[str] = None


@app.post("/api/v1/model/configure", tags=["System"])
async def configure_model_endpoint(payload: ModelConfigRequest):
    from nlu.llm_adapter import set_active_llm_adapter
    if payload.host:
        os.environ["OLLAMA_HOST"] = payload.host
    if payload.model:
        os.environ["OLLAMA_MODEL"] = payload.model
    os.environ["NLU_PROVIDER"] = payload.provider.lower()
    set_active_llm_adapter(payload.provider, model=payload.model)
    return get_model_status()


# -----------------------------------------------------------------------------
# Storage Asset Route (Integration Standard Point 7: Files in, files out)
# -----------------------------------------------------------------------------

@app.api_route("/api/v1/storage/{filename}", methods=["GET", "HEAD"], tags=["Storage"])
async def get_storage_file(filename: str):
    storage = get_storage()
    local_path = storage.get_local_path(filename)
    if not os.path.isfile(local_path):
        raise IncuBrixException(
            code="NOT_FOUND",
            message=f"Requested asset '{filename}' does not exist in storage.",
            status_code=404,
        )
    return FileResponse(local_path)


# -----------------------------------------------------------------------------
# Integration Standard Point 3: Background Jobs API
# -----------------------------------------------------------------------------

@app.get("/api/v1/jobs/{job_id}", tags=["Jobs"])
async def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise IncuBrixException(
            code="JOB_NOT_FOUND",
            message=f"Job '{job_id}' not found.",
            status_code=404,
        )
    return job.model_dump(mode="json")


# -----------------------------------------------------------------------------
# Projects API
# -----------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    video_url: Optional[str] = None


@app.post("/api/v1/projects", status_code=status.HTTP_201_CREATED, tags=["Projects"])
@app.post("/api/v1/projects/create", status_code=status.HTTP_201_CREATED, tags=["Projects"])
async def create_project(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    video_file: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    video_url: Optional[str] = Form(None),
    transcription_mode: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
):
    uploaded = video_file or file

    if idempotency_key:
        body_bytes = (video_url or "").encode("utf-8") + (uploaded.filename.encode("utf-8") if uploaded and uploaded.filename else b"")
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    storage = get_storage()
    project_id = project_id or f"proj_{uuid.uuid4().hex[:8]}"

    # Save media locally
    target_filename = f"{project_id}_source.mp4"
    local_target_path = storage.get_local_path(target_filename)

    if uploaded and getattr(uploaded, "filename", None):
        with open(local_target_path, "wb") as f:
            shutil.copyfileobj(uploaded.file, f)
    elif video_url:
        # Download video URL or copy local path
        if os.path.isfile(video_url):
            shutil.copy2(video_url, local_target_path)
        else:
            import httpx
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(video_url)
                if resp.status_code != 200:
                    raise IncuBrixException(
                        code="DOWNLOAD_FAILED",
                        message=f"Failed to fetch video from URL: HTTP {resp.status_code}",
                        status_code=400,
                    )
                with open(local_target_path, "wb") as f:
                    f.write(resp.content)
    else:
        # Default fixture media
        fixture_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "test_interview.mp4"))
        if not os.path.isfile(fixture_path):
            from scripts.generate_fixtures import generate_test_video
            generate_test_video(fixture_path, duration_s=60.0)
        shutil.copy2(fixture_path, local_target_path)

    # Inspect media file
    source_media, inspection = inspect_media_file(local_target_path, media_id=f"media_{project_id}")
    if uploaded and getattr(uploaded, "filename", None):
        source_media.filename = uploaded.filename

    # Build initial transcript using selected STT adapter
    selected_stt_mode = transcription_mode or settings.stt_provider
    adapter = get_transcription_adapter(selected_stt_mode)
    transcript = adapter.transcribe(
        local_target_path,
        language="auto",
        timebase=1000,
        duration_ticks=source_media.duration_ticks,
    )
    # Filter words within video duration
    valid_words = [w for w in transcript.words if w.end_ticks <= source_media.duration_ticks]
    transcript.words = valid_words

    # Initial segment covering whole video
    init_seg = ClipSegment(
        segment_id="seg_001",
        source_start_ticks=0,
        source_end_ticks=source_media.duration_ticks,
        speed_ratio=1.0,
    )

    timeline = Timeline(
        schema_version="1.0.0",
        project_id=project_id,
        timebase=1000,
        source_media=source_media,
        transcript=transcript,
        segments=[init_seg],
        effects=EffectsCollection(),
        transactions=[],
        timeline_hash="",
    )
    timeline.timeline_hash = compute_timeline_hash(timeline)

    # Store project
    record = ProjectRecord(project_id=project_id, timeline=timeline, source_filepath=local_target_path)
    project_store.save(record)

    response_data = {
        "project_id": project_id,
        "timeline_hash": timeline.timeline_hash,
        "duration_s": timeline.total_duration_seconds,
        "source_media": source_media.model_dump(mode="json"),
        "transcript_words_count": len(transcript.words),
    }

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 201, response_data)

    return JSONResponse(status_code=201, content=response_data)


@app.get("/api/v1/media", tags=["Media"])
@app.get("/api/v1/projects", tags=["Projects"])
async def list_media_and_projects():
    records = project_store.list_all()
    items = []
    for r in records:
        source_media = r.timeline.source_media
        filename = source_media.filename if source_media else os.path.basename(r.source_filepath)
        size_bytes = 0
        if r.source_filepath and os.path.isfile(r.source_filepath):
            size_bytes = os.path.getsize(r.source_filepath)
        
        items.append({
            "project_id": r.project_id,
            "filename": filename,
            "duration_s": r.timeline.total_duration_seconds,
            "source_duration_s": (source_media.duration_ticks / 1000.0) if source_media and source_media.duration_ticks else r.timeline.total_duration_seconds,
            "resolution": f"{source_media.width}x{source_media.height}" if source_media and source_media.width else "1280x720",
            "fps": source_media.fps if source_media else 30.0,
            "size_bytes": size_bytes,
            "source_url": f"/api/v1/projects/{r.project_id}/source-media",
            "timeline_hash": r.timeline.timeline_hash,
            "segments_count": len(r.timeline.segments),
            "captions_count": len(r.timeline.effects.captions),
            "sha256": source_media.sha256_hash if source_media else "",
        })
    return {"media": items, "projects": items}


@app.get("/api/v1/projects/{project_id}", tags=["Projects"])
async def get_project(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )
    return {
        "project_id": record.project_id,
        "timeline_hash": record.timeline.timeline_hash,
        "duration_s": record.timeline.total_duration_seconds,
        "timeline": record.timeline.model_dump(mode="json"),
    }


@app.get("/api/v1/projects/{project_id}/timeline", tags=["Projects"])
async def get_project_timeline(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )
    return JSONResponse(status_code=200, content=record.timeline.model_dump(mode="json"))


@app.get("/api/v1/projects/{project_id}/transcript", tags=["Projects"])
async def get_project_transcript(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )
    return record.timeline.transcript.model_dump(mode="json")


@app.post("/api/v1/projects/{project_id}/transcribe", tags=["Projects"])
async def transcribe_project(
    project_id: str,
    mode: str = Query("auto", description="Transcription mode: 'real' (faster-whisper), 'mock', or 'auto'"),
):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )
    storage = get_storage()
    target_filename = f"{project_id}_source.mp4"
    local_path = storage.get_local_path(target_filename)
    if not os.path.isfile(local_path) and getattr(record, "source_filepath", None) and os.path.isfile(record.source_filepath):
        local_path = record.source_filepath
    if not os.path.isfile(local_path):
        raise IncuBrixException(
            code="MEDIA_NOT_FOUND",
            message="Source media file not found for transcription.",
            status_code=404,
        )

    adapter = get_transcription_adapter(mode)
    transcript = adapter.transcribe(
        local_path,
        language="en",
        timebase=1000,
        duration_ticks=record.timeline.source_media.duration_ticks,
    )
    valid_words = [w for w in transcript.words if w.end_ticks <= record.timeline.source_media.duration_ticks]
    transcript.words = valid_words

    record.timeline.transcript = transcript
    engine = TimelineEngine(record.timeline)
    engine._sync_effects_anchoring()
    engine.recompute_hash()
    project_store.save(record)

    return {
        "status": "ok",
        "project_id": project_id,
        "transcript_words_count": len(valid_words),
        "is_mock": transcript.is_mock,
        "language": transcript.language,
        "timeline_hash": record.timeline.timeline_hash,
    }


@app.api_route("/api/v1/projects/{project_id}/source-media", methods=["GET", "HEAD"], tags=["Projects"])
async def get_project_source_media(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )
    storage = get_storage()
    target_filename = f"{project_id}_source.mp4"
    local_path = storage.get_local_path(target_filename)
    if not os.path.isfile(local_path) and getattr(record, "source_filepath", None) and os.path.isfile(record.source_filepath):
        local_path = record.source_filepath
    if not os.path.isfile(local_path):
        raise IncuBrixException(
            code="MEDIA_NOT_FOUND",
            message="Source media file not found.",
            status_code=404,
        )
    return FileResponse(
        local_path,
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


class OperationRequest(BaseModel):
    operation_type: str
    details: Dict[str, Any] = Field(default_factory=dict)
    instruction: Optional[str] = None


@app.post("/api/v1/projects/{project_id}/operations", tags=["Operations"])
async def apply_operation(
    project_id: str,
    payload: OperationRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    op_type = payload.operation_type
    details = payload.details
    instruction = payload.instruction or f"Manual edit: {op_type}"

    from core.operations import (
        CutRangeOperation,
        SpeedRangeOperation,
        SplitSegmentOperation,
        DeleteSegmentOperation,
        AddCaptionOperation,
        EditCaptionOperation,
        RemoveFillerWordsOperation,
        RemoveSilenceOperation,
        ReorderSegmentsOperation,
        AddMusicOperation,
    )

    op_instance = None
    if op_type == "split_segment":
        split_ticks = details.get("split_ticks")
        if split_ticks is None and "split_seconds" in details:
            split_ticks = int(round(float(details["split_seconds"]) * 1000))
        op_instance = SplitSegmentOperation(split_ticks=split_ticks, time_domain=details.get("time_domain", "current_edited_time"))
    elif op_type == "delete_segment":
        op_instance = DeleteSegmentOperation(segment_id=details["segment_id"])
    elif op_type == "cut_range":
        start_ticks = details.get("start_ticks")
        if start_ticks is None and "start_seconds" in details:
            start_ticks = int(round(float(details["start_seconds"]) * 1000))
        end_ticks = details.get("end_ticks")
        if end_ticks is None and "end_seconds" in details:
            end_ticks = int(round(float(details["end_seconds"]) * 1000))
        op_instance = CutRangeOperation(start_ticks=start_ticks, end_ticks=end_ticks, time_domain=details.get("time_domain", "current_edited_time"))
    elif op_type == "speed_range":
        start_ticks = details.get("start_ticks")
        if start_ticks is None and "start_seconds" in details:
            start_ticks = int(round(float(details["start_seconds"]) * 1000))
        end_ticks = details.get("end_ticks")
        if end_ticks is None and "end_seconds" in details:
            end_ticks = int(round(float(details["end_seconds"]) * 1000))
        td = details.get("time_domain", "current_edited_time")
        if td == "source":
            td = "source_time"
        op_instance = SpeedRangeOperation(start_ticks=start_ticks, end_ticks=end_ticks, speed_ratio=float(details["speed_ratio"]), time_domain=td)
    elif op_type == "add_caption":
        start_ticks = details.get("source_start_ticks")
        if start_ticks is None and "start_seconds" in details:
            start_ticks = int(round(float(details["start_seconds"]) * 1000))
        end_ticks = details.get("source_end_ticks")
        if end_ticks is None and "end_seconds" in details:
            end_ticks = int(round(float(details["end_seconds"]) * 1000))
        op_instance = AddCaptionOperation(
            text=details["text"],
            source_start_ticks=start_ticks,
            source_end_ticks=end_ticks,
            color=details.get("color", "white"),
            font_size=int(details.get("font_size", 36)),
            position=details.get("position", "bottom"),
        )
    elif op_type == "edit_caption":
        op_instance = EditCaptionOperation(
            caption_id=details.get("caption_id"),
            group_id=details.get("group_id"),
            target=details.get("target"),
            color=details.get("color"),
            font_size=details.get("font_size"),
            font_size_delta=details.get("font_size_delta"),
            position=details.get("position"),
            text=details.get("text"),
        )
    elif op_type == "reorder_segments":
        op_instance = ReorderSegmentsOperation(new_order_segment_ids=details["new_order_segment_ids"])
    elif op_type == "undo":
        from core.operations import UndoOperation
        op_instance = UndoOperation()
    elif op_type == "redo":
        from core.operations import RedoOperation
        op_instance = RedoOperation()
    else:
        raise IncuBrixException(
            code="UNSUPPORTED_OPERATION",
            message=f"Unsupported manual operation type '{op_type}'.",
            status_code=400,
        )

    engine = TimelineEngine(record.timeline)
    res = engine.dispatch_operation(op_instance, instruction=instruction)
    project_store.save(record)

    res_dict = res.model_dump(mode="json")
    db.save_chat_message(
        project_id,
        "assistant",
        res.summary,
        metadata={
            "status": res.status,
            "timeline_hash": res.timeline_hash,
            "duration_s": res.duration_s,
        },
    )

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 200, res_dict)

    return JSONResponse(status_code=200, content=res_dict)


@app.post("/api/v1/projects/{project_id}/undo", tags=["Operations"])
async def project_undo(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(code="PROJECT_NOT_FOUND", message=f"Project '{project_id}' not found.", status_code=404)
    engine = TimelineEngine(record.timeline)
    res = engine.apply_undo()
    project_store.save(record)
    res_dict = res.model_dump(mode="json")
    db.save_chat_message(
        project_id,
        "assistant",
        res.summary,
        metadata={"status": res.status, "timeline_hash": res.timeline_hash, "duration_s": res.duration_s},
    )
    return JSONResponse(status_code=200, content=res_dict)


@app.post("/api/v1/projects/{project_id}/redo", tags=["Operations"])
async def project_redo(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(code="PROJECT_NOT_FOUND", message=f"Project '{project_id}' not found.", status_code=404)
    engine = TimelineEngine(record.timeline)
    res = engine.apply_redo()
    project_store.save(record)
    res_dict = res.model_dump(mode="json")
    db.save_chat_message(
        project_id,
        "assistant",
        res.summary,
        metadata={"status": res.status, "timeline_hash": res.timeline_hash, "duration_s": res.duration_s},
    )
    return JSONResponse(status_code=200, content=res_dict)


@app.post("/api/v1/projects/{project_id}/transactions/{tx_id}/restore", tags=["Operations"])
async def project_restore_transaction(project_id: str, tx_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(code="PROJECT_NOT_FOUND", message=f"Project '{project_id}' not found.", status_code=404)
    engine = TimelineEngine(record.timeline)
    res = engine.apply_restore_transaction(tx_id)
    project_store.save(record)
    res_dict = res.model_dump(mode="json")
    db.save_chat_message(
        project_id,
        "assistant",
        res.summary,
        metadata={"status": res.status, "timeline_hash": res.timeline_hash, "duration_s": res.duration_s},
    )
    return JSONResponse(status_code=200, content=res_dict)


# -----------------------------------------------------------------------------
# Instructions API
# -----------------------------------------------------------------------------

class InstructionRequest(BaseModel):
    say: Optional[str] = None
    answer: Optional[str] = None
    instruction: Optional[str] = None


@app.post("/api/v1/projects/{project_id}/instructions", tags=["Instructions"])
async def apply_instruction(
    project_id: str,
    payload: InstructionRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    prompt_text = payload.say or payload.instruction or payload.answer or ""
    if not prompt_text:
        raise IncuBrixException(
            code="INVALID_REQUEST",
            message="Instruction cannot be empty. Provide 'say' or 'answer'.",
            status_code=400,
        )

    db.save_chat_message(project_id, "user", prompt_text)
    history = db.get_chat_history(project_id)
    engine = TimelineEngine(record.timeline)
    res, updated_pending = process_instruction(engine, prompt_text, record.pending_clarification, chat_history=history)
    record.pending_clarification = updated_pending
    project_store.save(record)

    res_dict = res.model_dump(mode="json")
    db.save_chat_message(
        project_id,
        "assistant",
        res.summary,
        metadata={
            "status": res.status,
            "timeline_hash": res.timeline_hash,
            "duration_s": res.duration_s,
            "question": res.question,
            "options": res.options,
        },
    )

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 200, res_dict)

    return JSONResponse(status_code=200, content=res_dict)


# -----------------------------------------------------------------------------
# Conversational Assistant & Chat Persistence
# -----------------------------------------------------------------------------

class ChatMessageRequest(BaseModel):
    message: str


@app.get("/api/v1/projects/{project_id}/chat", tags=["Chat"])
async def get_project_chat(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )
    messages = db.get_chat_history(project_id)
    return {"project_id": project_id, "messages": messages}


@app.post("/api/v1/projects/{project_id}/chat", tags=["Chat"])
async def post_project_chat(
    project_id: str,
    payload: ChatMessageRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    text = payload.message.strip()
    if not text:
        raise IncuBrixException(
            code="INVALID_REQUEST",
            message="Chat message cannot be empty.",
            status_code=400,
        )

    db.save_chat_message(project_id, "user", text)
    history = db.get_chat_history(project_id)
    engine = TimelineEngine(record.timeline)
    res, updated_pending = process_instruction(engine, text, record.pending_clarification, chat_history=history)
    record.pending_clarification = updated_pending
    project_store.save(record)

    res_dict = res.model_dump(mode="json")
    db.save_chat_message(
        project_id,
        "assistant",
        res.summary,
        metadata={
            "status": res.status,
            "timeline_hash": res.timeline_hash,
            "duration_s": res.duration_s,
            "question": res.question,
            "options": res.options,
        },
    )

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 200, res_dict)

    return JSONResponse(status_code=200, content=res_dict)


# -----------------------------------------------------------------------------
# Structured Selective Restore API
# -----------------------------------------------------------------------------

@app.post("/api/v1/projects/{project_id}/transactions/{tx_id}/restore", tags=["History"])
async def restore_project_transaction(
    project_id: str,
    tx_id: str,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    engine = TimelineEngine(record.timeline)
    success, msg, restored_tx = engine.history.selective_restore(tx_id)
    if not success:
        raise IncuBrixException(
            code="RESTORE_FAILED",
            message=msg,
            status_code=400,
        )

    engine.recompute_hash()
    project_store.save(record)

    response_data = {
        "status": "applied",
        "summary": msg,
        "restored_transaction_id": restored_tx.id if restored_tx else tx_id,
        "timeline_hash": engine.timeline.timeline_hash,
        "duration_s": engine.timeline.total_duration_seconds,
    }

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 200, response_data)

    return JSONResponse(status_code=200, content=response_data)


# -----------------------------------------------------------------------------
# Auto Edit Planning and Application API
# -----------------------------------------------------------------------------

class AutoEditPlanRequest(BaseModel):
    options: Optional[Dict[str, Any]] = None


class AutoEditApplyRequest(BaseModel):
    plan: AutoEditPlan
    excluded_item_ids: Optional[List[str]] = None


@app.post("/api/v1/projects/{project_id}/auto-edit/plan", tags=["AutoEdit"])
async def create_auto_edit_plan(
    project_id: str,
    payload: AutoEditPlanRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    engine = TimelineEngine(record.timeline)
    plan = engine.generate_auto_edit_plan(payload.options)
    plan_dict = plan.model_dump(mode="json")

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 200, plan_dict)

    return JSONResponse(status_code=200, content=plan_dict)


@app.post("/api/v1/projects/{project_id}/auto-edit/apply", tags=["AutoEdit"])
async def apply_auto_edit_plan_endpoint(
    project_id: str,
    payload: AutoEditApplyRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    engine = TimelineEngine(record.timeline)
    res = engine.apply_auto_edit_plan(payload.plan, payload.excluded_item_ids)
    if res.status != "applied":
        raise IncuBrixException(
            code="AUTO_EDIT_FAILED",
            message=res.summary,
            status_code=400,
        )

    project_store.save(record)
    res_dict = res.model_dump(mode="json")

    db.save_chat_message(
        project_id,
        "assistant",
        f"Applied Auto Edit Clean Up preset: {res.summary}",
        metadata={"status": "applied", "timeline_hash": res.timeline_hash},
    )

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 200, res_dict)

    return JSONResponse(status_code=200, content=res_dict)


# -----------------------------------------------------------------------------
# Render API (Background Job with 202 Accepted)
# -----------------------------------------------------------------------------

class RenderRequest(BaseModel):
    callback_url: Optional[str] = None


@app.post("/api/v1/projects/{project_id}/render", status_code=status.HTTP_202_ACCEPTED, tags=["Render"])
async def trigger_render(
    project_id: str,
    payload: RenderRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    body_bytes = await request.body()
    if idempotency_key:
        cached = idempotency_store.check_or_register(idempotency_key, body_bytes)
        if cached:
            return cached

    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    storage = get_storage()
    render_filename = f"{project_id}_rendered.mp4"
    output_path = storage.get_local_path(render_filename)

    def _render_task(job_id: str) -> Dict[str, Any]:
        job_manager.update_progress(job_id, 30, status="running")
        start_time = time.time()

        render_res = render_timeline(
            timeline=record.timeline,
            source_media_path=record.source_filepath,
            output_video_path=output_path,
        )

        job_manager.update_progress(job_id, 80, status="running")
        render_dur = round(time.time() - start_time, 3)

        manifest = generate_output_manifest(
            timeline=record.timeline,
            timings={"render_duration_s": render_dur},
            warnings=render_res.warnings,
        )
        manifest_filename = f"{project_id}_manifest.json"
        storage.save_bytes(manifest_filename, json.dumps(manifest, indent=2).encode("utf-8"))

        return {
            "output_video_url": storage.get_download_url(render_filename),
            "manifest_url": storage.get_download_url(manifest_filename),
            "timeline_hash": render_res.timeline_hash,
            "duration_s": render_res.rendered_duration_s,
            "frame_diff": render_res.frame_diff,
            "is_in_sync": render_res.is_in_sync,
            "manifest": manifest,
        }

    job = job_manager.submit_background_task(
        job_type="render",
        task_fn=_render_task,
        callback_url=payload.callback_url,
    )

    response_data = {
        "job_id": job.job_id,
        "status": "queued",
        "poll_url": f"/api/v1/jobs/{job.job_id}",
    }

    if idempotency_key:
        idempotency_store.record_response(idempotency_key, 202, response_data, job_id=job.job_id)

    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=response_data)


# -----------------------------------------------------------------------------
# Export API (OpenTimelineIO)
# -----------------------------------------------------------------------------

@app.get("/api/v1/projects/{project_id}/export", tags=["Export"])
@app.get("/api/v1/projects/{project_id}/export/otio", tags=["Export"])
async def export_project_otio(project_id: str):
    record = project_store.get(project_id)
    if not record:
        raise IncuBrixException(
            code="PROJECT_NOT_FOUND",
            message=f"Project '{project_id}' not found.",
            status_code=404,
        )

    from core.otio_export import export_timeline_to_otio
    import opentimelineio as otio

    otio_timeline = export_timeline_to_otio(record.timeline)
    otio_json = otio.adapters.write_to_string(otio_timeline, "otio_json")
    return JSONResponse(status_code=200, content=json.loads(otio_json))


# -----------------------------------------------------------------------------
# Static UI Mount (Serves compiled React SPA if present)
# -----------------------------------------------------------------------------

from fastapi.staticfiles import StaticFiles

ui_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ui", "dist"))
if os.path.isdir(ui_dist_path):
    app.mount("/", StaticFiles(directory=ui_dist_path, html=True), name="ui")


