# SOURCES.md - Disclosures and Licensing Information

This document details every model, library, API, dataset, and media source utilized in the **IncuBrix Prompt-Based Video Editing Engine**, confirming commercial usability and absence of AGPL code in the shipped service.

---

## 1. Libraries and Frameworks

| Library / Tool | Version | License | Commercial Use | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **FastAPI** | `>=0.110.0` | MIT | Yes | Asynchronous HTTP API Service (`/api/v1/`) |
| **Uvicorn** | `>=0.28.0` | BSD-3-Clause | Yes | ASGI Web Server |
| **Pydantic** | `>=2.6.0` | MIT | Yes | Data validation and JSON Schema generation |
| **OpenTimelineIO** | `>=0.16.0` | Apache-2.0 | Yes | Open Interchange Timeline Format Export |
| **FFmpeg** | `7.0+` | LGPL-2.1+ | Yes | Video trimming, speed modification, audio ducking, rendering |
| **Structlog** | `>=24.1.0` | Apache-2.0 / MIT | Yes | Structured JSON logging with Correlation IDs |
| **Boto3** | `>=1.34.0` | Apache-2.0 | Yes | S3/MinIO compatible artifact storage |
| **PyYAML** | `>=6.0.1` | MIT | Yes | Session configuration parsing |
| **HTTPX** | `>=0.27.0` | BSD-3-Clause | Yes | Webhooks and swappable LLM network client |
| **Pytest** | `>=8.0.0` | MIT | Yes | Automated testing framework (57 test suite) |

> [!NOTE]
> **License Compliance (Rule 2)**: All libraries in the default runtime path use permissive licenses (MIT, Apache 2.0, BSD). **Zero AGPL code is included in the shipped Docker service.**

---

## 2. AI Models and Speech-To-Text

| Component | Default Model | License | Provider / Source | Cost per Unit |
| :--- | :--- | :--- | :--- | :--- |
| **AI Video Editing Brain** | `MockLLMAdapter` (Default) | Apache-2.0 | Native Deterministic Engine | \$0.00 / min |
| **AI Video Editing Brain** (Live) | `gpt-4o-mini` (Swappable) | Commercial API | OpenAI API | ~\$0.0005 / min |
| **Speech-to-Text** | Whisper Large v3 | MIT | OpenAI / Faster-Whisper | \$0.00 (Self-hosted) |

---

## 3. Media and Datasets

- **Test Footage**: Public domain royalty-free CC0 talking-head samples.
- **Audio Assets**: CC0 Royalty-Free dialogue and background music samples.
- **Transcripts**: Synthetic word-level alignment generated for the 8-step worked example and 45-scenario test suite.
