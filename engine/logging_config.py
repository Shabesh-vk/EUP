"""Structured JSON logging configuration adhering to Integration Standard #8.

Outputs logs in machine-readable JSON format with timestamp, level, job_id,
and X-Correlation-Id extracted from context variables.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Optional

# Context variables to track correlation_id and job_id per request/task
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
job_id_ctx: ContextVar[Optional[str]] = ContextVar("job_id", default=None)


class JSONFormatter(logging.Formatter):
    """Custom log formatter producing structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or correlation_id_ctx.get(),
            "job_id": getattr(record, "job_id", None) or job_id_ctx.get(),
        }

        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include custom extra attributes if provided
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_entry.update(record.extra_data)

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configures the root logger with the JSON formatter."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    # Avoid duplicate handlers if already configured
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(JSONFormatter())

    return logging.getLogger("incubrix.engine")


# Default module logger
logger = setup_logging()
