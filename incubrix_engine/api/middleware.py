"""
API Middleware for Structured Logging, Error Formatting, and Idempotency.
Integration Standards 4, 5, 8.
"""

from __future__ import annotations
import uuid
import time
import json
import logging
from typing import Callable, Dict, Any, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import structlog

# Set up structured JSON logger
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

# In-memory Idempotency Cache: Idempotency-Key -> (status_code, body_dict)
IDEMPOTENCY_CACHE: Dict[str, Tuple[int, Dict[str, Any]]] = {}


class IncuBrixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Correlation ID
        corr_id = request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
        request.state.correlation_id = corr_id

        # 2. Idempotency Check on POST requests (Integration Standard 4)
        idemp_key = request.headers.get("Idempotency-Key")
        if request.method == "POST" and idemp_key:
            if idemp_key in IDEMPOTENCY_CACHE:
                cached_status, cached_body = IDEMPOTENCY_CACHE[idemp_key]
                logger.info(
                    "idempotency_cache_hit",
                    idempotency_key=idemp_key,
                    correlation_id=corr_id,
                )
                res = JSONResponse(status_code=cached_status, content=cached_body)
                res.headers["X-Correlation-Id"] = corr_id
                res.headers["X-Cache"] = "HIT"
                return res

        start_time = time.time()
        try:
            response: Response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            response.headers["X-Correlation-Id"] = corr_id

            logger.info(
                "http_request_finished",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
                correlation_id=corr_id,
            )
            return response

        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "unhandled_server_error",
                method=request.method,
                path=request.url.path,
                error=str(exc),
                duration_ms=round(duration_ms, 2),
                correlation_id=corr_id,
            )
            return JSONResponse(
                status_code=500,
                headers={"X-Correlation-Id": corr_id},
                content={
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An unexpected internal server error occurred.",
                        "retryable": True,
                        "details": str(exc),
                    }
                },
            )


def format_api_error(code: str, message: str, retryable: bool = False, details: Any = None, status_code: int = 400) -> JSONResponse:
    """Standardized IncuBrix error JSON response (Integration Standard 5)."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details,
            }
        },
    )
