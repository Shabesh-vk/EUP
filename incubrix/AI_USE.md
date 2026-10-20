# AI use

How AI tools were used to build the IncuBrix engine (`incubrix/`) and its
Concat integration.

## Coding assistant

| Tool | Model | Used for |
|---|---|---|
| Claude Code (desktop app) | Claude Opus 5.5 | Writing most of the Rust code and tests, under my direction, phase by phase from `docs/RUST_ENGINE_PLAN.md` |

How it was used:

- **I set the design and the rules.** The plan, the eight engine rules in
  `CLAUDE.md` (content anchors, integer microseconds, history replay, one
  instruction = one transaction, three answers) and the order of the phases
  came first. Each phase began with tests for its "Done when".
- **The assistant wrote code and ran it.** It ran tests, clippy, the scenario
  checker, the Docker stack and the desktop app. It read the failures and fixed
  them. Commits carry a `Co-Authored-By: Claude` line.
- **Measured, not claimed.** The metrics come from `incubrix metrics`, which
  measures them. Problems it found were fixed in the engine, not in the
  numbers. For example, auto-captioning a 60-minute video took 124 s because
  each caption replayed the history; replay is now lazy and it takes about
  0.4 s.
- **I review and can explain every part**: the anchor model, the projection,
  selective restore, the parser and the service.

Earlier work: the Python engine at the repository root (reference only) was
built with Google Antigravity (Gemini). See `../AI_USE.md`.

## AI inside the product

- An optional language model (Claude, OpenAI or a local Ollama model) reads a
  request into a structured intent. It cannot touch the timeline: the intent
  is validated, then resolved and applied by plain Rust (rule 6). Without a
  model, the rules parser does the same job deterministically. Tests, the
  scenarios and the metrics all use the rules parser.
- Speech recognition is whisper.cpp, run locally. Diarization (optional) is
  sherpa-onnx.

See `SOURCES.md` for models and licences.
