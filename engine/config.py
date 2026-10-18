"""Configuration management for the IncuBrix Video Editing Engine.

All configuration is loaded from environment variables or .env files,
fulfilling Integration Standard #6 (no hard-coded paths, models, or secrets).
"""

from typing import Literal
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # Storage settings
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_DIR: str = "./storage_data"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "incubrix-videos"
    S3_REGION: str = "us-east-1"
    S3_SECURE: bool = False

    # Media & FFmpeg
    FFMPEG_PATH: str = "ffmpeg"
    FFPROBE_PATH: str = "ffprobe"
    DEFAULT_FPS: float = 30.0
    MIN_CAPTION_DURATION_S: float = 0.70  # Brief: sped-up captions keep a readable minimum (~0.7s)
    DEFAULT_SILENCE_THRESHOLD_S: float = 1.0  # Gaps > N sec considered silence
    SILENCE_KEEP_DURATION_S: float = 0.20  # Keep 200ms natural pause when trimming silence
    SNAP_SILENCE_PADDING_S: float = 0.05  # Snapping buffer to avoid cutting into word audio

    # Transcription (STT)
    STT_PROVIDER: Literal["faster-whisper", "mock"] = "mock"
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_DEVICE: str = "auto"
    WHISPER_COMPUTE_TYPE: str = "default"

    # Language Model (LLM)
    LLM_PROVIDER: Literal["ollama", "mock"] = "mock"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:1.5b"
    LLM_TEMPERATURE: float = 0.0

    # Timeline policy
    # Brief #7: "When a user says 'at 1:20' after earlier cuts, your system uses
    # one stated policy (original time or current time), everywhere, and says which one in its answer."
    DEFAULT_TIME_POLICY: Literal["current", "original"] = "original"

    # Background Jobs & Webhooks
    JOB_TIMEOUT_S: int = 600
    MAX_CONCURRENT_JOBS: int = 4
    WEBHOOK_SECRET: str = "incubrix-secret-key-change-in-prod"

    # Costs per unit (reported in manifests and metrics)
    COST_PER_MINUTE_STT_USD: float = 0.006  # e.g., Whisper API equivalent / compute amortized
    COST_PER_1K_LLM_TOKENS_USD: float = 0.0002  # Local Qwen2.5 or self-hosted API amortized


# Singleton settings instance
settings = Settings()
