# IncuBrix Prompt-Based Video Editing Engine

An intelligent, non-destructive, content-anchored video editing engine that turns plain-language creator instructions into structured timeline operations and frame-accurate rendered video.

---

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │ Creator Instruction / Session YAML     │
                      └───────────────────┬────────────────────┘
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │ AI Video Editing Brain                 │
                      │ - 3-Way Classifier                     │
                      │   [applied | needs_clarif | rejected]  │
                      │ - Content Anchor Resolution            │
                      └───────────────────┬────────────────────┘
                                          │ Structured Operations
                                          ▼
                      ┌────────────────────────────────────────┐
                      │ Deterministic Content-Anchored Engine  │
                      │ - Active Media Segments [Trim/Speed]   │
                      │ - Word-Pinned Captions & Audio Effects │
                      │ - Non-Destructive History Replay       │
                      │ - Deterministic timeline_hash          │
                      └───────────┬────────────────┬───────────┘
                                  │                │
                    Render Phase  ▼                ▼  Interchange
       ┌───────────────────────────────┐     ┌────────────────────────┐
       │ FFmpeg Frame-Accurate Pipeline│     │ OpenTimelineIO (.otio) │
       │ - Synchronized Video & Audio  │     │ Resolve / Premiere     │
       └───────────────────────────────┘     └────────────────────────┘
```

---

## Quick Setup (Under 10 Commands)

```bash
# 1. Clone repository
git clone <repo-url> && cd incubrix-engine

# 2. Copy environment settings
cp .env.example .env

# 3. Start API Service and Local MinIO Storage with Docker Compose
docker compose up -d

# 4. Verify Service Health
curl http://localhost:8000/health

# 5. Run Complete Test Suite (Zero API keys required)
docker compose run --rm tests

# 6. Run Session Runner on Worked Example
python -m incubrix_engine.runner.session_runner sessions/worked_example.yaml --output-dir output/worked_example

# 7. Run Batch Runner on all test sessions
python -m incubrix_engine.runner.batch_runner sessions/ --output-dir output/batch_results
```

---

## Running Locally Without Docker

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run all 57 automated tests
pytest -v incubrix_engine/tests/

# Start API server
uvicorn incubrix_engine.api.app:app --host 0.0.0.0 --port 8000
```

---

## Error Codes Reference (Integration Standard 5)

All error responses strictly follow the schema:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable explanation",
    "retryable": false,
    "details": null
  }
}
```

| Error Code | HTTP Status | Retryable | Description |
| :--- | :--- | :--- | :--- |
| `SESSION_NOT_FOUND` | 404 | No | Requested session ID does not exist in memory. |
| `JOB_NOT_FOUND` | 404 | No | Background job ID was not found. |
| `INVALID_RANGE` | 400 | No | Requested cut/speed range has start >= end. |
| `WHOLE_VIDEO_CUT_PROHIBITED` | 400 | No | Cannot cut 100% of video duration. |
| `TIMESTAMP_OUT_OF_BOUNDS` | 400 | No | Requested timestamp exceeds media duration. |
| `CAPTION_NOT_FOUND` | 404 | No | Targeted caption ID does not exist. |
| `NO_CAPTIONS_EXIST` | 400 | No | Attempted to style/resize when no captions exist. |
| `INVALID_SPEED_MULTIPLIER` | 400 | No | Playback speed must be between 0.1x and 10.0x. |
| `HISTORY_EMPTY` | 400 | No | Undo requested when no prior edits exist. |
| `INTERNAL_SERVER_ERROR` | 500 | Yes | Unexpected server-side failure. |

---

## Configuration Settings (Integration Standard 6)

All settings are configured via environment variables or `.env`:

| Setting | Default | Description |
| :--- | :--- | :--- |
| `HOST` | `0.0.0.0` | Bind address for API service. |
| `PORT` | `8000` | Port for HTTP server. |
| `LLM_PROVIDER` | `mock` | `mock`, `openai`, `gemini`, `anthropic`, or `ollama`. |
| `LLM_MODEL` | `gpt-4o-mini` | Model name when using live LLM provider. |
| `LLM_API_KEY` | `""` | API key for LLM provider. |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | MinIO or AWS S3 endpoint URL. |
| `S3_BUCKET` | `incubrix-outputs` | Target bucket for rendered outputs. |
| `WEBHOOK_SECRET` | `incubrix_secret_key_123` | HMAC-SHA256 signature secret for webhooks. |
| `TIME_POLICY` | `original_time` | Default clock policy (`original_time` or `current_timeline_time`). |

---

## Deliverables & Documentation Index

- **OpenAPI 3.1 Contract**: [`openapi.yaml`](openapi.yaml)
- **Timeline JSON Schema**: [`schema/timeline.schema.json`](schema/timeline.schema.json)
- **Schema Explanation**: [`schema/TIMELINE_SCHEMA_EXPLANATION.md`](schema/TIMELINE_SCHEMA_EXPLANATION.md)
- **Technical Report**: [`REPORT.md`](REPORT.md)
- **License & Sources**: [`SOURCES.md`](SOURCES.md)
- **AI Tooling Disclosure**: [`AI_USE.md`](AI_USE.md)
- **Test Pack**: [`incubrix_engine/tests/`](incubrix_engine/tests/) (57 automated tests)
- **Sample Session**: [`sessions/worked_example.yaml`](sessions/worked_example.yaml)
