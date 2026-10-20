# IncuBrix Engine in Rust, inside Concat — Build Plan

This file is the working plan for building the IncuBrix Assessment 2 engine
(prompt-based video editing) in Rust, wired into the Concat editor. It is
written for Claude (or any coding agent) to execute **one phase at a time**.
Put it at `docs/RUST_ENGINE_PLAN.md` and point `CLAUDE.md` at it.

---

## 0. Decisions that shape everything

### 0.1 Where the engine lives

```
N:\Concat\
├── incubrix\                  ← NEW Cargo workspace, MIT/Apache-2.0, our code
│   ├── crates\
│   │   ├── incubrix-core       timeline model, anchors, projection, ops, history, hash
│   │   ├── incubrix-nlu        instruction → structured ops (rule parser + LLM adapters + mock)
│   │   ├── incubrix-media      probe, transcript (whisper-rs), diarization, render (ffmpeg), OTIO
│   │   ├── incubrix-api        axum HTTP service: /api/v1, jobs, idempotency, MinIO, logs
│   │   └── incubrix-cli        session-runner + batch-runner
│   ├── fixtures\               test videos, golden transcripts, session YAMLs, expected results
│   ├── openapi.yaml
│   ├── Dockerfile, docker-compose.yml, .env.example
│   └── README.md, REPORT.md, SOURCES.md, AI_USE.md
├── src\                       ← Concat (AGPL) — the desktop UI, untouched except the AI tab
│   └── crates\concat          depends on incubrix-core + incubrix-nlu by path
└── legacy-python\             ← current Python engine, kept only as a reference/oracle
```

**Why a separate workspace and not `src/crates/*`:**
- **Licence.** The brief says *"Avoid AGPL code in the shipped service."* Concat is AGPL-3.0.
  The `incubrix` crates must **never depend on any `concat-*` crate**. Concat may depend on
  them (an AGPL app may use MIT code), never the reverse. The shipped Docker service builds
  only `incubrix/`, so no AGPL code is in it.
- **Docker.** The service image builds without Slint, Skia, wgpu or the window.
- **Speed.** `cargo test` in `incubrix/` runs in seconds; Concat's build takes minutes.

"Inside Concat" therefore means: **the Concat app runs the engine in-process** (no HTTP,
no Python) through its AI tab, and the same engine is also served over HTTP for IncuBrix.

### 0.2 Non-negotiable rules (from the brief's must-haves)

1. **The source is never touched.** History = untouched original + ordered list of
   transactions. The timeline is always *derived* by replaying active transactions.
2. **Edits belong to content.** Captions, mutes, bleeps and effects store **word ids**
   (anchors), never playback times. Playback times are computed by projection.
3. **Deterministic.** All timeline logic is ordinary Rust. An LLM may only turn text into
   an `Intent` JSON. Time is integer ticks (e.g. 1/48000 s, or `Rational`), never `f64`
   inside the model. `timeline_hash` = SHA-256 of canonical JSON (sorted keys, no
   timestamps/session ids/URLs).
4. **Three answers only:** `applied` | `needs_clarification` | `rejected`. Never guess on
   anything destructive.
5. **One time policy, stated everywhere.** Policy = **current playback time** ("at 1:20" means
   what the user sees now), projected immediately to source coordinates and stored as anchors.
   Every response carries `"time_policy": "current"`.
6. **One instruction = one undo step.** A new edit clears redo.
7. **Render matches the timeline:** A/V within 1 frame, length within 1 frame.

### 0.3 Reuse what exists

- The Python engine (`core/engine.py`, `nlu/dispatcher.py`) and `test_pack/` outputs are the
  **reference behaviour**. Port the rules; turn its outputs into golden fixtures.
- Concat already ships `whisper-rs` and `sherpa-onnx` builds on this machine
  (`sherpa-libs`, `ffmpeg-dev`, `onnxruntime-*`). Reuse the *libraries* directly
  (MIT/Apache) — not through `eup-speech`.

---

## Phase plan

Each phase ends with: tests green, a commit, and a short note appended to `REPORT.md`.
Do not start a phase until the previous one's "Done when" is true.

### Phase 1 — Skeleton and repo hygiene (½ day)

- Fix the merge-conflict markers in the root `README.md`.
- Move the Python engine to `legacy-python/` (keep it runnable for comparison).
- Create the `incubrix/` workspace with the five crates, `rust-toolchain.toml`, MIT licence,
  `cargo fmt`/`clippy` config, a GitHub Actions workflow running `cargo test --workspace`.
- Write `CLAUDE.md` at the repo root: the rules in §0.2, the crate map, "never depend on
  concat-*", how to run tests.

**Done when:** `cd incubrix && cargo test --workspace` passes in CI with empty crates.

### Phase 2 — Core model, anchors, projection, hash (1 day) · Must-haves 1, 2, 4, 7

`incubrix-core`:
- `Transcript { words: Vec<Word> }`, `Word { id, text, start, end, speaker, confidence }`
  (source ticks).
- `Source { path, sha256, duration, fps (rational, VFR flag), has_audio }`.
- `Timeline` (derived): ordered `Segment { source_start, source_end, speed }` +
  `Caption { id, anchor: WordSpan, text, style }`, `Mute/Bleep { anchor }`,
  `Music { path, duck }`, `ProtectedPause { anchor }`.
- `Projection`: source → playback and playback → source maps across cuts, reorders and
  speed changes; anchor → playback range (or `None` when its words are cut).
- Rules: a caption whose words are all cut is hidden and reported; a partial cut keeps the
  surviving words (documented rule); sped-up captions get a minimum on-screen time of 0.7 s.
- `timeline_hash()` with canonical serialisation.
- JSON Schema of the timeline generated with `schemars` → `timeline.schema.json`.

**Done when:** unit tests prove: caption on "welcome to the channel" at 0:42 → after cutting
0–30 s it plays at 0:12; after restore it is at 0:42 again; hash identical over 3 runs.

### Phase 3 — Operations and history (1 day) · Must-have 6, Advanced "conflicts"

- `Op` enum: `Cut`, `KeepOnly`, `Reorder`, `Speed`, `Mute`, `Bleep`, `AddCaption`,
  `StyleCaption`, `AutoCaption`, `RemoveFillers`, `RemoveSilences{min}`, `AddMusic{duck}`.
- `History { base, transactions: Vec<Tx>, cursor }`: `apply(Vec<Op>)` as one transaction
  (all-or-nothing), `undo`, `redo`, `restore(tx_id)` (selective: re-insert that span, keep
  later independent edits), `replay() -> Timeline`.
- Validation → `rejected` with a reason: out of range, whole-video cut, speed outside
  0.25×–4× (so "10x" is rejected or clamped with a warning — pick one and document it),
  contradicts tx N.
- Conflict rules: the same cut twice is idempotent (second says "already removed");
  overlapping speed changes → the latest one wins on the overlap (documented); protected
  pauses survive silence removal; filler removal never cuts into a bleeped word.

**Done when:** a table-driven test of ≥ 20 op/undo/restore sequences matches expected
timelines; steps 1–7 of the brief's worked example pass at the core level (ops given directly).

### Phase 4 — Intake, transcript, diarization (1 day) · Advanced "two speakers", Outstanding "imperfect data"

`incubrix-media`:
- `probe()` via `ffprobe -show_streams -of json` (duration, rational fps, VFR detection,
  audio presence). MP4/MOV only; clear error otherwise.
- Source SHA-256 at intake and after every render.
- `Transcriber` trait: `WhisperRs` (word timestamps, confidence), `Fixture` (reads golden JSON
  for tests and CI — **no API keys, no models needed in CI**).
- `Diarizer` trait: `SherpaOnnx` speaker diarization (Apache-2.0), `Fixture`. Warnings for
  overlapping speech and likely speaker-label swaps.
- Detectors: filler words (um, uh; "like" only when a filler — context rule plus
  optional LLM check), silences longer than N s, low-confidence words (flag, never bleep blindly).
- Cache transcripts by source hash.

**Done when:** a single-speaker and a two-speaker test video produce transcripts with word
ids, speakers and confidences; the fixture transcriber reproduces them byte-for-byte.

### Phase 5 — Understanding instructions (1½ days) · Must-have 3, Advanced "ambiguity"

`incubrix-nlu`:
- `Intent` schema (JSON, `schemars`): op kind + target (time range | word query | semantic
  query | reference like "that caption" / "the second one") + params.
- `Parser` trait with three adapters selected by `NLU_PROVIDER`:
  - `rules` (default, deterministic): regex grammar for times ("80 seconds", "a minute twenty",
    "1:00 to 1:30", "the last 10 seconds"), common verbs, references, multi-part splitting.
  - `llm`: Claude/OpenAI/Ollama over HTTP, temperature 0, JSON-schema-constrained output,
    **responses cached by hash(prompt + context)** so reruns are identical.
  - `mock`: canned intents for tests.
- `Resolver` (plain code): intent → concrete ops on the current timeline.
  - Several matches ("pricing" said 3×, "thanks" said 4×) → `needs_clarification` with
    timestamped options; the next `answer` resolves the pending question.
  - Semantic search ("pricing" finds "cost"): embedding adapter or a synonym table fallback;
    show matches before cutting.
  - "that caption", "make it bigger" with no caption → clarify or reject with the reason.
  - "remove the boring bit" → clarify with candidates; never guess.
  - Multi-part: all-or-nothing, or report exactly which parts applied.
- Response: `{status, operations, summary, question, options, warnings, time_policy,
  timeline_hash, duration_s}`.

**Done when:** every row of the brief's "Hard cases" list has a passing test with the
`rules` + `fixture` adapters.

### Phase 6 — Rendering and export (1 day) · Must-have 5, Outstanding "export"

- Render from the timeline only, as a separate step: an ffmpeg filtergraph
  (`trim/atrim`, `setpts/atempo`, `concat`, ASS subtitles for captions, `volume=0` for mutes,
  sine for bleeps, `sidechaincompress` for music ducking). CFR output at the source rate
  (VFR input → `fps` filter, with a warning).
- Verify after every render with ffprobe: length vs timeline ≤ 1 frame, A/V start offset
  ≤ 1 frame; source hash unchanged. Fail loudly otherwise.
- Cuts snap to the nearest silence within ±150 ms so no word is clipped.
- OpenTimelineIO export (`.otio` JSON written directly; schema is simple).

**Done when:** the worked example's step 8 render passes the frame checks; the OTIO file opens
in DaVinci Resolve.

### Phase 7 — Session runner and the test suite (1 day) · Core level, Outstanding "proof"

`incubrix-cli`:
- `incubrix session run session.yaml --out dir/` → `results.json` (per step: status,
  operations, summary, question, options, timeline_hash, duration_s) + final timeline +
  video. Uses `answer:` when the engine asks.
- `incubrix batch run <folder|file> --api <url> --out dir/` (Integration point 10).
- ≥ 40 scripted scenarios in `fixtures/sessions/` with expected results, run in CI;
  determinism test runs each 3× and compares hashes.

**Done when:** the brief's 8-step worked example reproduces exactly on our test video, and all
40+ scenarios pass in CI.

### Phase 8 — The HTTP service and the Integration Standard (1½ days) · 20 marks

`incubrix-api` (axum + tokio, `utoipa` for OpenAPI 3.1):
1. `docker compose up` → api + MinIO (+ sqlite volume). `make test` / one command runs unit,
   integration and an end-to-end test with no API keys. `.env.example` lists every setting.
2. `openapi.yaml` generated from code, all routes under `/api/v1/`, tested against the server.
3. Jobs: transcription and render return `202 {job_id}`; `GET /api/v1/jobs/{id}` → status,
   progress 0–100, result links; optional callback signed with HMAC-SHA256 in
   `X-IncuBrix-Signature`.
4. `Idempotency-Key` on every POST (stored key → same job, never double work).
5. Errors `{"error":{code,message,retryable,details}}`, UPPER_SNAKE_CASE codes listed in README.
6. All config from env (`config` crate); no hard-coded paths or keys.
7. Upload or URL in; outputs to MinIO, returned as presigned links.
8. `tracing` JSON logs with timestamp, level, job_id, `X-Correlation-Id`; `/health`, `/ready`.
9. Output manifest on every result: models/providers + versions, settings, seed, timings,
   cost estimate, warnings, licences.
10. Batch runner (Phase 7).
- Deploy the container for the live demo (Fly.io / Render / a VM) and keep it up.

**Done when:** a checklist test hits each of the 10 points against the running compose stack.

### Phase 9 — Concat integration (1 day) · the editor demo

- `src/crates/eup/Cargo.toml`: path deps on `incubrix-core`, `incubrix-nlu`.
- Replace `ai_apply_prompt`, `ai_cut_range`, `ai_speed_range`, `ai_restore_intro` in
  `studio.rs` with an `AiSession` holding the engine `History` for the open project.
- Transcription runs on a worker; progress shown in the tab.
- `apply_engine_timeline(&Timeline)`: remove the AI-managed clips and rebuild them as **one
  `Command::Batch`** — `AddClip` per segment (`source_start`, duration = len / speed) +
  `SetClipSpeed`, `AddTextClip` per visible caption at its projected time, mutes as volume 0.
  So preview and Export show the real result and Ctrl+Z is one step.
- `ai-conversation.slint`: delete the hard-coded string matches and fake summaries; show the
  real `status`, `summary`, warnings, and clarification `options` as buttons that send
  `answer`.
- Optional switch: talk to the HTTP service instead of in-process (`INCUBRIX_API_URL`).
- Rebuild with `.\run_ui.ps1 -Rebuild`.

**Done when:** typing the 8 worked-example prompts in the Concat AI tab changes the timeline,
preview and exported file exactly as the session runner does.

### Phase 10 — Outstanding level, metrics, evidence (1 day)

- Performance: a 60-minute fixture transcript; each instruction < 3 s (benchmark with
  `criterion`, report median and slowest).
- Metrics tab: latency (5-min and 60-min), largest A/V offset and length diff in frames,
  determinism %, clarification count vs guesses, word-clipping check (20 cuts), cost per minute.
- `SOURCES.md` (every model, crate, dataset, media and its licence — note Concat is AGPL and
  only used as the desktop demo, not in the service), `AI_USE.md`, `REPORT.md`.
- Fill the Submission Form with a link to evidence for every claim; mark anything unproven as
  Partial or No.
- Rehearse the live session: architecture walkthrough, predict-and-run, debugging from logs,
  adding a new op ("zoom in on the speaker") test-first.

---

## Suggested schedule (adjust to the real deadline)

| Day | Phases |
|---|---|
| 1 | 1, 2 |
| 2 | 3 |
| 3 | 4 |
| 4–5 | 5 |
| 6 | 6, 7 |
| 7–8 | 8 (and deploy) |
| 9 | 9 |
| 10 | 10 |

If time runs short, cut Phase 9 (the Concat tab) before anything in Phases 2–8: the marks
come from the service, the session runner and the evidence, not from the desktop UI.

## How to hand a phase to Claude

> Read `docs/RUST_ENGINE_PLAN.md` and `CLAUDE.md`. Do **Phase N** only. Write tests first
> for the "Done when" criteria, implement, run `cargo test --workspace` in `incubrix/`, fix
> until green, then commit with message `phase N: <summary>` and append what was done and
> any deviations to `REPORT.md`. Do not touch `src/` unless the phase says so.
