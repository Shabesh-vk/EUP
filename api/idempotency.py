"""
Idempotency management implementing safe retries (Integration Standard Point 4).
Persists idempotency keys and cached response payloads to SQLite database.
"""

from __future__ import annotations
import hashlib
import json
from typing import Dict, Any, Optional
from fastapi.responses import JSONResponse
from .errors import IncuBrixException
from db.database import db


class IdempotencyRecord:
    def __init__(self, key: str, body_hash: str, status_code: Optional[int] = None, response_data: Optional[Dict[str, Any]] = None, job_id: Optional[str] = None):
        self.key = key
        self.body_hash = body_hash
        self.status_code = status_code
        self.response_data = response_data
        self.job_id = job_id


class IdempotencyStore:
    def __init__(self):
        self._records: Dict[str, IdempotencyRecord] = {}

    def check_or_register(self, key: str, body_bytes: bytes) -> Optional[JSONResponse]:
        """
        Check if idempotency key exists:
        - If not, registers it and returns None.
        - If yes with same body: returns cached response if completed.
        - If yes with different body: raises 409 Conflict.
        """
        body_hash = hashlib.sha256(body_bytes).hexdigest()

        # Check memory cache first
        record = self._records.get(key)
        if not record:
            # Query persistent DB
            db_row = db.get_idempotency_record(key)
            if db_row:
                record = IdempotencyRecord(
                    key=db_row["key"],
                    body_hash=db_row["body_hash"],
                    status_code=db_row["status_code"],
                    response_data=db_row["response_data"],
                    job_id=db_row["job_id"],
                )
                self._records[key] = record

        if record:
            if record.body_hash != body_hash:
                raise IncuBrixException(
                    code="IDEMPOTENCY_CONFLICT",
                    message="Idempotency-Key was previously used with a different request body.",
                    status_code=409,
                    retryable=False,
                )
            # Same request payload retried
            if record.response_data is not None and record.status_code is not None:
                return JSONResponse(status_code=record.status_code, content=record.response_data)
        else:
            self._records[key] = IdempotencyRecord(key=key, body_hash=body_hash)
            db.register_idempotency_key(key, body_hash)

        return None

    def record_response(self, key: str, status_code: int, response_data: Dict[str, Any], job_id: Optional[str] = None):
        if key in self._records:
            self._records[key].status_code = status_code
            self._records[key].response_data = response_data
            self._records[key].job_id = job_id
        db.record_idempotency_response(key, status_code, response_data, job_id=job_id)


idempotency_store = IdempotencyStore()
