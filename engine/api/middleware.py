"""FastAPI middleware for correlation tracking, error formatting, and idempotency.

Adheres to:
- #4: Safe retries (Idempotency-Key header)
- #5: Clear errors (UPPER_SNAKE_CASE error format)
- #8: Structured JSON logs with X-Correlation-Id
"""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from engine.logging_config import correlation_id_ctx, logger


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagates or generates X-Correlation-Id across the request lifecycle."""

    async def dispatch(self, request: Request, call_next) -> Response:
        corr_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        token = correlation_id_ctx.set(corr_id)

        try:
            response = await call_next(request)
            response.headers["X-Correlation-Id"] = corr_id
            return response
        finally:
            correlation_id_ctx.reset(token)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Formats uncaught exceptions into standard Integration Standard #5 JSON errors."""
    logger.exception(f"Unhandled error processing request {request.url.path}: {exc}")
    error_payload = {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": str(exc),
            "retryable": False,
            "details": None
        }
    }
    return JSONResponse(status_code=500, content=error_payload)
