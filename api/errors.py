"""
Standardized error envelopes and exceptions conforming to IncuBrix Integration Standard Point 5.
Format: {"error": {"code": UPPER_SNAKE_CASE, "message": str, "retryable": bool, "details": any}}
"""

from typing import Any, Optional, Dict
from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Optional[Any] = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class IncuBrixException(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        retryable: bool = False,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details

    def to_envelope(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            }
        }


async def incubrix_exception_handler(request: Request, exc: IncuBrixException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": str(exc),
                "retryable": True,
                "details": {"type": type(exc).__name__},
            }
        },
    )
