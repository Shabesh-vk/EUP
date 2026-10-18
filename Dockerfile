# IncuBrix Prompt-Based Video Editing Engine
# Integration Standard 1: One-command container start & tests
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies: FFmpeg and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and schemas
COPY incubrix_engine/ incubrix_engine/
COPY sessions/ sessions/
COPY schema/ schema/
COPY openapi.yaml .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "incubrix_engine.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
