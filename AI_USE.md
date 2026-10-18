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
