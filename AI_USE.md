<<<<<<< HEAD
# AI_USE.md - AI Coding Assistance Disclosure

This document discloses all AI tools and models utilized during the design, implementation, and testing of the **IncuBrix Prompt-Based Video Editing Engine**.

---

## 1. AI Coding Assistants Used

| Tool / Assistant | Model / Engine | Purpose & Scope of Use |
| :--- | :--- | :--- |
| **Google Antigravity** | Gemini 3.8 Flash (High) | Pair programming, architecture design, test suite formulation, schema validation, and documentation generation. |

---

## 2. Details of Contributions

1. **Architecture & Content-Anchored Mathematical Model**:
   - Designed the dynamic projection equations mapping immutable source word coordinates to variable timeline intervals without clock corruption.
   - Formulated the selective restoration algorithm (non-destructive history replay excluding specific past steps).

2. **Codebase Implementation**:
   - `engine/core/models.py` & `engine/core/timeline.py`: Data structures and deterministic state machine.
   - `engine/parser/nl_parser.py` & `engine/parser/llm_adapter.py`: Prompt parsing, three-way answer logic, ambiguity detection.
   - `engine/media/renderer.py` & `engine/core/otio_export.py`: FFmpeg filtergraph generator and OpenTimelineIO exporter.
   - `engine/api/app.py`: FastAPI OpenAPI 3.1 endpoints, background jobs, idempotency middleware.

3. **Test Automation**:
   - Created the 79-test automated test suite, verifying:
     - The canonical 8-step worked example verbatim.
     - 100% determinism (`timeline_hash` invariance across 3 runs).
     - 8 Hard Cases from the IncuBrix Brief.
     - 45 automated scripted scenarios for CI verification.
     - Complete async background jobs, idempotency keys, and HMAC-SHA256 webhooks.

4. **Review & Verification**:
   - All code logic was executed, tested, and validated locally against Python 3.11 and FFmpeg 9.0.
=======
# AI Use Disclosure

This document discloses all AI tools, models, and assistants utilized during the design, development, and testing of the IncuBrix Prompt-Based Video Editing Engine, in full accordance with the assessment requirements.

## 1. AI Coding Assistants

| Tool / Assistant | Provider | Role & Tasks Performed |
| :--- | :--- | :--- |
| **Antigravity AI Agent** | Google DeepMind | Pair programming, architecture scaffolding, test suite development, FFmpeg filtergraph construction, and CI automation. |

## 2. Models Used for Natural Language Understanding & Prompts

| Model | Purpose | Usage Mode |
| :--- | :--- | :--- |
| **Internal Rule-Based Parser** | Deterministic translation of common video editing instructions (Cut, Speed, Caption, Mute, Bleep, Silence, Filler, Restore) | Default in-engine mode for 100% reproducible tests without external API dependencies. |
| **OpenAI / Claude / Gemini API Adapter** | Natural language disambiguation and semantic search (e.g. matching "pricing" with "cost") | Pluggable cloud adapter behind `nlu_provider` configuration. |

## 3. Speech-to-Text Models

| Model | Purpose | Usage Mode |
| :--- | :--- | :--- |
| **Deterministic Mock STT** | Word-level timing, confidence scores, and multi-speaker assignment for tests | Default for credential-free CI and local offline execution. |
| **Whisper (base.en / tiny.en)** | Real transcription on unfamiliar uploaded MP4/MOV videos | Enabled via `STT_PROVIDER=whisper` (MIT license). |
>>>>>>> 18d551fd02fc30603ac5339893e00ef8d9a870b2
