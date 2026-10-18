"""
Main FastAPI Application for IncuBrix Editing Engine.
Compliant with OpenAPI 3.1 and all IncuBrix Integration Standards.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yaml
from pathlib import Path

from .config import settings
from .middleware import IncuBrixMiddleware
from .routes import router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="IncuBrix Prompt-Based Video Editing Engine API. Translates human instructions to content-anchored edits.",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.openapi_version = "3.1.0"

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom IncuBrix middleware for logging, idempotency, correlation ID
app.add_middleware(IncuBrixMiddleware)

# Mount routes under /api/v1 and root health/ready
app.include_router(router, prefix=settings.api_prefix)
app.include_router(router)  # Also expose /health and /ready at root


def export_openapi_yaml(output_path: str = "n:/Concat/openapi.yaml") -> str:
    """Exports OpenAPI 3.1 specification to YAML (Integration Standard 2)."""
    schema = app.openapi()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)
    return str(path)


if __name__ == "__main__":
    export_openapi_yaml()
    print("Exported openapi.yaml successfully.")
