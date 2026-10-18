"""FastAPI application initialization for IncuBrix Editing Engine.

Configured with:
- OpenAPI 3.1 documentation at /docs and /openapi.json
- Structured Correlation ID logging middleware
- Standardized error handlers
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from engine.api.routes import router
from engine.api.middleware import CorrelationIdMiddleware
from engine.config import settings


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    app = FastAPI(
        title="IncuBrix Prompt-Based Video Editing Engine",
        description="Containerized, deterministic prompt-based video editing engine following the Golden Timeline Rule.",
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Correlation ID middleware
    app.add_middleware(CorrelationIdMiddleware)

    # Include routes
    app.include_router(router)

    # Standardized 500 error handler
    @app.exception_handler(Exception)
    async def standard_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": str(exc),
                    "retryable": False,
                    "details": None
                }
            }
        )

    return app


app = create_app()
