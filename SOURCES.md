<<<<<<< HEAD
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
=======
# Sources & Dependency Licenses

This document discloses all models, APIs, libraries, datasets, and media sources used in the IncuBrix Prompt-Based Video Editing Engine, along with their commercial licensing status.

## 1. Libraries and Frameworks

| Library / Tool | Version | License | Commercial Permissibility | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | 3.11.9 | Python Software Foundation (PSF) | Yes | Standard runtime |
| **FastAPI** | 0.143.3 | MIT | Yes | Web framework |
| **Pydantic** | 2.14.1 | MIT | Yes | Schema validation and data modeling |
| **Starlette** | 1.8.0 | BSD-3-Clause | Yes | ASGI toolkit |
| **Uvicorn** | 0.54.0 | BSD-3-Clause | Yes | ASGI server |
| **HTTPX** | 0.28.1 | BSD-3-Clause | Yes | HTTP client for webhooks and runner |
| **PyYAML** | 6.0.3 | MIT | Yes | YAML parsing for scripted test sessions |
| **jsonschema** | 4.26.0 | MIT | Yes | JSON Schema Draft 2020-12 validation |
| **pytest** | 9.1.1 | MIT | Yes | Automated test runner |
| **OpenTimelineIO** | 0.17.0+ | Apache 2.0 | Yes | NLE interchange format export |
| **React** | 18.3.1 | MIT | Yes | Web UI frontend framework |
| **React-DOM** | 18.3.1 | MIT | Yes | DOM renderer for React |
| **Lucide-React**| 0.453.0 | ISC | Yes | Icon set for web UI |
| **Vite** | 5.4.10 | MIT | Yes | Frontend build tool and bundler |
| **FFmpeg / FFprobe** | 9.0.1 | LGPL v2.1+ / GPL v3 (separate binary) | Yes | Standalone external executable subprocess. Production Docker build uses LGPL v2.1+ build flags without non-free or GPL-only codecs. |

---

## 2. Models and Speech-to-Text Services

| Model / Service | Provider | License | Mode | Cost Estimate |
| :--- | :--- | :--- | :--- | :--- |
| **Mock STT Adapter** | Internal / IncuBrix | Proprietary / MIT | Default test mode (Zero credentials required) | $0.00 / min |
| **faster-whisper** | Systran / OpenAI | MIT (OpenAI Whisper open weights) | Local execution | ~$0.00 / min (compute only) |
| **Deepgram Nova-2** | Deepgram Inc. | Commercial SaaS API | Cloud adapter (Optional via config) | ~$0.0043 / min |
| **Whisper API** | OpenAI | Commercial SaaS API | Cloud adapter (Optional via config) | ~$0.0060 / min |

---

## 3. Storage Systems & Licensing Notice

| System | License | Deployment Strategy |
| :--- | :--- | :--- |
| **Local File Storage** | Proprietary / Apache 2.0 | Default in tests and single-container deployments |
| **MinIO** | AGPL v3 | Permitted in Docker Compose by assessment brief. Isolated behind standard S3 network protocol; no proprietary code links against MinIO libraries. |
| **SeaweedFS / S3** | Apache 2.0 | Fully compatible drop-in replacement for strict AGPL-free enterprise deployments. |

---

## 4. Test Media and Datasets

- `tests/fixtures/test_interview.mp4`: Synthetic audio/video media generated deterministically using FFmpeg filtergraph primitives (`testsrc`, `sine` synthesizer, `drawtext`). 100% free of third-party copyright, commercial rights reserved.
- `tests/fixtures/test_music.mp3`: Synthetic audio generated via FFmpeg sine wave synthesizer.
- All transcripts and dialog lines are original synthetic prompt test cases.
>>>>>>> 18d551fd02fc30603ac5339893e00ef8d9a870b2
