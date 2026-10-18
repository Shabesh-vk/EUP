"""
Configuration management for IncuBrix API Service.
Integration Standard 6: All settings, paths, model names and limits come from environment variables.
"""

import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "IncuBrix Video Editing Engine"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    # Storage (S3 / MinIO)
    s3_endpoint_url: str = Field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"))
    s3_access_key: str = Field(default_factory=lambda: os.getenv("S3_ACCESS_KEY", "minioadmin"))
    s3_secret_key: str = Field(default_factory=lambda: os.getenv("S3_SECRET_KEY", "minioadmin"))
    s3_bucket: str = Field(default_factory=lambda: os.getenv("S3_BUCKET", "incubrix-outputs"))

    # AI Model Settings
    llm_provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    llm_model: str = Field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    llm_api_key: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))

    # Limits
    max_video_duration_s: float = Field(default_factory=lambda: float(os.getenv("MAX_VIDEO_DURATION_S", "7200.0")))
    max_upload_size_mb: int = Field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_SIZE_MB", "2048")))

    # Webhook signature secret
    webhook_secret: str = Field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "incubrix_secret_key_123"))


settings = Settings()
