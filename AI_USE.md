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
   - `incubrix_engine/core/models.py` & `timeline_engine.py`: Data structures and deterministic state machine.
   - `incubrix_engine/ai/brain.py` & `mock_adapter.py`: Prompt parsing, three-way answer logic, ambiguity detection.
   - `incubrix_engine/render/renderer.py` & `otio_export.py`: FFmpeg filtergraph generator and OpenTimelineIO exporter.
   - `incubrix_engine/api/app.py`: FastAPI OpenAPI 3.1 endpoints, background jobs, idempotency middleware.

3. **Test Automation**:
   - Created the 57-test automated test pack, verifying:
     - The canonical 8-step worked example.
     - 100% determinism (`timeline_hash` invariance across 3 runs).
     - 6 Hard Cases from the IncuBrix Brief.
     - 45 automated scripted scenarios for CI verification.

4. **Review & Verification**:
   - All code logic was executed, tested, and validated locally against Python 3.11 and FFmpeg 9.0.
