# SOURCES.md — Disclosures & Licenses

In accordance with IncuBrix Engineering Assessment 2 specification ("1. Disclose everything. List every model, API, library, dataset and media source in SOURCES.md"), this document details every model, library, and media asset used within the IncuBrix Prompt-Based Video Editing Engine.

All dependencies and assets adhere to Rule 2 ("Commercially usable. Everything in your default path, and everything it outputs, must be licensed for commercial use."). No AGPL or research-only code is included in the default shipped engine.

---

## 1. Machine Learning Models

| Model | Provider / Architecture | Version / Size | License | Commercial Use | Purpose |
|---|---|---|---|---|---|
| **Faster-Whisper** | OpenAI Whisper / Systran CTranslate2 | `base` / `small` | Apache 2.0 / MIT | Yes | Word-level speech transcription and timestamping |
| **Qwen 2.5** | Alibaba Cloud / Ollama | `1.5B` / `7B` | Apache 2.0 | Yes | Natural language prompt intent and entity translation |
| **Rule-Based Mock Adapter** | Internal IncuBrix Engine | `1.0.0` | Apache 2.0 | Yes | Deterministic, zero-dependency parser for automated test runs |

---

## 2. Core Libraries and Frameworks

| Library | Version | License | Link | Purpose |
|---|---|---|---|---|
| **FastAPI** | `>=0.110.0` | MIT | [FastAPI](https://github.com/tiangolo/fastapi) | Async HTTP API service, OpenAPI 3.1 generation |
| **Uvicorn** | `>=0.28.0` | BSD-3-Clause | [Uvicorn](https://github.com/encode/uvicorn) | High-performance ASGI web server |
| **Pydantic** | `>=2.6.0` | MIT | [Pydantic](https://github.com/pydantic/pydantic) | Data modeling, validation, and serialization |
| **OpenTimelineIO** | `>=0.15.0` | Apache 2.0 | [OTIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | Professional NLE interchange format export |
| **Boto3 / Botocore** | `>=1.34.0` | Apache 2.0 | [Boto3](https://github.com/boto/boto3) | S3 / MinIO compatible object storage integration |
| **PyYAML** | `>=6.0.1` | MIT | [PyYAML](https://github.com/yaml/pyyaml) | Session configuration file parsing |
| **HTTPX** | `>=0.27.0` | BSD-3-Clause | [HTTPX](https://github.com/encode/httpx) | HTTP client for signed webhooks and API testing |
| **Pytest / Pytest-Asyncio** | `>=8.0.0` | MIT | [Pytest](https://github.com/pytest-dev/pytest) | Automated unit, integration, and scenario testing |

---

## 3. Media Processing Software

| Tool | Version | License | Purpose |
|---|---|---|---|
| **FFmpeg** | `9.0.1` / `7+` | LGPL 2.1+ / GPL 2.0+ (commercial compatible build) | Frame-accurate audio/video clipping, speed PTS scaling, captions, ducking |
| **FFprobe** | `9.0.1` | LGPL 2.1+ | Media duration, fps, resolution, and audio stream analysis |

---

## 4. Test Media & Datasets

- **Synthetic Test Patterns**: Generated deterministically using FFmpeg `lavfi` (`testsrc`, `sine`) under public domain / CC0 equivalent.
- **Voice / Spoken Words**: Synthetic audio and frame-accurate word alignments designed specifically for multi-speaker, pricing, filler, and silence tests.
