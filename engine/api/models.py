"""FastAPI Pydantic schemas adhering to the Integration Standard.

Enforces:
- #5: Clear errors: {"error": {"code": "...", "message": "...", "retryable": bool, "details": ...}}
- UPPER_SNAKE_CASE error codes
- Standardized request and response structures
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Standardized error structure (Integration Standard #5)."""
    code: str = Field(..., description="UPPER_SNAKE_CASE error code")
    message: str = Field(..., description="Human-readable explanation")
    retryable: bool = Field(default=False, description="Whether retrying the request might succeed")
    details: Optional[Any] = Field(default=None, description="Optional extra debug information")


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "incubrix-editing-engine"
    version: str = "1.0.0"


class StepRequest(BaseModel):
    say: str = Field(..., description="The user instruction prompt")
    answer: Optional[str] = Field(default=None, description="Reply used if the system asked a question")


class StepResponse(BaseModel):
    status: Literal["applied", "needs_clarification", "rejected"]
    operations: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    question: Optional[str] = None
    options: Optional[List[str]] = None
    reason: Optional[str] = None
    timeline_hash: Optional[str] = None
    duration_s: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    video_url_or_path: str = Field(..., description="URL or local path of the video to edit")
    time_policy: Optional[Literal["current", "original"]] = "current"


class SessionInfoResponse(BaseModel):
    session_id: str
    source_media_id: str
    duration_s: float
    fps: float
    time_policy: str
    timeline_hash: str


class CreateJobRequest(BaseModel):
    job_type: Literal["render", "transcribe", "session_run"]
    session_id: Optional[str] = None
    video_url_or_path: Optional[str] = None
    steps: Optional[List[StepRequest]] = None
    callback_url: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int = Field(..., ge=0, le=100)
    created_at: str
    updated_at: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[ErrorDetail] = None
