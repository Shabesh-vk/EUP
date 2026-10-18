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
docker compose run --rm test-runner

# 6. Run Session Runner on Worked Example
python session_runner.py test_pack/worked_example.yaml --output-dir test_pack/worked_example_output

# 7. Run Batch Runner on all test sessions
python batch_runner.py test_pack/scenarios --output-dir test_pack/batch_results
```

---

## Running Locally Without Docker

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows or source venv/bin/activate on Linux

# Install dependencies
pip install -r requirements.txt

# Run all 79 automated tests
pytest -v tests/

# Start API server
uvicorn engine.api.app:app --host 0.0.0.0 --port 8000
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
| `S3_BUCKET` | `incubrix-videos` | Target bucket for rendered outputs. |
| `WEBHOOK_SECRET` | `incubrix_secret_key_123` | HMAC-SHA256 signature secret for webhooks. |
| `DEFAULT_TIME_POLICY` | `original` | Default clock policy (`original` or `current`). |

---

## Deliverables & Documentation Index

- **OpenAPI 3.1 Contract**: [`openapi.yaml`](openapi.yaml)
- **Timeline JSON Schema**: [`timeline_schema.json`](timeline_schema.json) & [`schema/timeline.schema.json`](schema/timeline.schema.json)
- **Schema Explanation**: [`schema/TIMELINE_SCHEMA_EXPLANATION.md`](schema/TIMELINE_SCHEMA_EXPLANATION.md)
- **Technical Report**: [`REPORT.md`](REPORT.md)
- **License & Sources**: [`SOURCES.md`](SOURCES.md)
- **AI Tooling Disclosure**: [`AI_USE.md`](AI_USE.md)
- **Test Pack**: [`tests/`](tests/) (79 automated tests)
- **Sample Session**: [`test_pack/worked_example.yaml`](test_pack/worked_example.yaml)
- **Batch Test Scenarios**: [`test_pack/scenarios/`](test_pack/scenarios/) (16 scenario suites)
