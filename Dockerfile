# IncuBrix Video Editing Engine Container
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies: FFmpeg, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and specifications
COPY engine/ /app/engine/
COPY tests/ /app/tests/
COPY test_pack/ /app/test_pack/
COPY session_runner.py /app/
COPY batch_runner.py /app/
COPY openapi.yaml /app/
COPY timeline_schema.json /app/
COPY pytest.ini /app/
COPY .env.example /app/.env

# Default storage directories
RUN mkdir -p /app/storage_data /app/test_pack/batch_results

EXPOSE 8000

# Healthcheck probe using the /health endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start FastAPI server with Uvicorn
CMD ["uvicorn", "engine.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
