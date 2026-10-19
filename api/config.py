"""
Configuration settings for the IncuBrix service.
All settings load from environment variables with safe defaults.
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IncuBrix Prompt-Based Editing Engine"
    api_v1_prefix: str = "/api/v1"
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    storage_dir: str = "storage_data"
    storage_public_url: str = "http://localhost:8000/api/v1/storage"

    max_upload_size_mb: int = 500
    stt_provider: str = "mock"  # "mock", "whisper", "deepgram"
    nlu_provider: str = "rule_based"  # "rule_based", "openai", "gemini"

    webhook_signing_secret: str = "incubrix_secret_key_123"
    job_timeout_seconds: int = 300

    time_policy: str = "current_edited_time"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")



settings = Settings()

