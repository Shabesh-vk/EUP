"""
Structured JSON logging and X-Correlation-Id middleware.
Conforms to Integration Standard Point 8.
"""

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class StructuredJsonFormatter(logging.Formatter):
    """Format logs as single-line JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "job_id": getattr(record, "job_id", None),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        return json.dumps(log_obj)


def setup_structured_logging():
    logger = logging.getLogger("incubrix")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(handler)
    return logger


logger = setup_structured_logging()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        corr_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        request.state.correlation_id = corr_id

        start_time = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        response.headers["X-Correlation-Id"] = corr_id

        # Log request completion with structured fields
        extra = {"correlation_id": corr_id, "job_id": request.headers.get("X-Job-Id")}
        logger.info(
            f"{request.method} {request.url.path} returned {response.status_code} in {duration_ms}ms",
            extra=extra,
        )

        return response
