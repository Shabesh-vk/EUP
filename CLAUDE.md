# Working on this repository

This repo holds two things:

- `src/` - **EUP**, a Rust + Slint desktop video editor (AGPL-3.0); a renamed fork of
  Concat (upstream jub0t/Concat).
- `incubrix/` - **our IncuBrix editing engine** (MIT OR Apache-2.0), the submission for
  IncuBrix Assessment 2 (prompt-based video editing). Plan: `docs/RUST_ENGINE_PLAN.md`.

The Python files at the root (`api/`, `core/`, `nlu/`, `engine/`, `session_runner.py`, ...)
are the earlier Python engine. Treat them as a reference for behaviour only.

## Rules for the engine (`incubrix/`)

1. Never add a dependency on any `eup-*` crate (licence). EUP may depend on `incubrix-*`.
2. The source file is never modified. Timelines are derived by replaying the history.
3. Overlays store content anchors (word ids); structural edits store source spans.
   Never store a playback time in an `Op`.
4. Time policy is "current": typed times are current playback time, projected at once (`resolve.rs`).
5. No floating point in the timeline model; integer microseconds. Deterministic output only.
6. An AI model may only produce structured intents. All timeline logic is plain Rust.
7. One instruction = one transaction = one undo step.
8. Every instruction returns exactly one of applied / needs_clarification / rejected.

## How to work

- Do one phase of `docs/RUST_ENGINE_PLAN.md` at a time.
- Write tests first for the phase's "Done when". Run `cd incubrix && cargo test --workspace`
  and `cargo clippy --workspace -- -D warnings` until green.
- Update the status table in `incubrix/README.md` and add a note to `REPORT.md`.
- Do not touch `src/` (EUP) unless the phase says so. EUP builds with
  `.\run_ui.ps1 -Rebuild` on Windows and takes minutes.
