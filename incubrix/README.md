# IncuBrix Engine (Rust)

The prompt-based video editing engine for IncuBrix Assessment 2. Licensed
MIT OR Apache-2.0. It never depends on Concat's AGPL `concat-*` crates;
Concat (in `../src`) uses this engine, not the other way round.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Workspace, CI, rules | done |
| 2 | Core model: anchors, projection, hash | done |
| 3 | Operations, undo/redo, selective restore, validation | done |
| 4 | Intake, transcript, diarization | done |
| 5 | Instruction understanding (rules + LLM + mock) | done |
| 6 | Rendering (ffmpeg), A/V checks, OTIO | done |
| 7 | Session runner, 40+ scenarios | done |
| 8 | HTTP service, Integration Standard | next |
| 9 | Concat AI tab, in-process | started early: the tab runs the engine (REPORT.md) |
| 10 | Outstanding level, metrics, evidence | |

The full plan is `../docs/RUST_ENGINE_PLAN.md`.

## How it works

- **The source is never touched.** A `Project` holds the original, its
  transcript and a list of transactions (one per instruction). The timeline
  is always re-derived by replaying the active transactions.
- **Edits belong to content.** Captions, mutes and bleeps store word ids.
  Cuts, speed changes and reorders store source spans. Playback times are
  computed by projection every time, so a caption on "welcome to the
  channel" stays on those words through any cut, speed change, reorder,
  undo or restore.
- **Time policy: current.** A time the user types ("from 1:00 to 1:30") is
  read as the current edited playback time and pinned to the source content
  shown there at that moment (`resolve.rs`).
- **Deterministic.** Integer microseconds, no floats in the model; `timeline_hash`
  is SHA-256 of the canonical timeline JSON.
- **One instruction = one undo.** A new edit clears redo. `Restore { tx }`
  switches one earlier edit off and keeps everything after it.

### Documented rules

| Situation | Rule |
|---|---|
| A caption's words are all cut | Caption is hidden, the user is told; restoring the cut brings it back. |
| Part of a caption's words are cut | Caption shows over the words that remain; the user is told. |
| A caption on sped-up content | Stays on screen at least 0.7 s. |
| Overlapping speed changes | The later one wins on the overlap. |
| Speed outside 0.25x-4x | Rejected (`SPEED_OUT_OF_RANGE`). |
| An edit that removes everything | Rejected (`WOULD_REMOVE_EVERYTHING`), nothing changes. |
| The same edit twice | Accepted, nothing changes, no undo step recorded. |
| Multi-part instruction with an impossible part | Nothing applies (all-or-nothing). |
| Caption on words already cut | Rejected, naming the edit that cut them. |
| Filler inside a bleep | Kept; the user is told. |
| Low-confidence filler | Kept and flagged, never cut blindly. |
| "like" | A filler only when it stands apart (pauses both sides) or is doubled. |
| Silence removal | Keeps protected pauses; pads speech so no word is clipped. |
| A moved section's target is gone | It plays last; the user is told. |

## Layout

```
crates/incubrix-core/src
  time.rs       integer time, source and playback ranges
  model.rs      source info, transcript, anchors, caption style
  ops.rs        every edit as data
  timeline.rs   the derived timeline and source<->playback projection
  history.rs    transactions, undo/redo, restore, validation, replay
  resolve.rs    the time policy
  search.rs     finding phrases in the transcript
  detect.rs     fillers, silences, caption chunks
  outcome.rs    applied / needs_clarification / rejected
  hash.rs       timeline_hash
  otio.rs       OpenTimelineIO export
crates/incubrix-media/src
  probe.rs      ffprobe: exact duration and fps, VFR, audio; MP4/MOV only
  hash.rs       source SHA-256 at intake and after renders
  transcribe.rs Transcriber trait, recogniser cleanup, fixture adapter
  diarize.rs    Diarizer trait, speaker labels, overlap and swap warnings
  cache.rs      transcripts cached by source hash
  intake.rs     all of the above in one call
  render.rs     the timeline to MP4 with ffmpeg, then checked (length, A/V, source hash)
  whisper.rs    whisper.cpp adapter (feature whisper)
  sherpa.rs     sherpa-onnx diarization adapter (feature sherpa)

crates/incubrix-nlu/src
  intent.rs     the Intent schema: the only thing a parser may produce
  rules.rs      the default deterministic parser
  llm.rs        Claude / OpenAI / Ollama parser, temperature 0, cached
  mock.rs       canned intents for tests
  times.rs      "80 seconds", "a minute twenty", "1:00 to 1:30"
  semantic.rs   sentences, stems, synonyms ("pricing" finds "cost")
  answer.rs     reading "the second one", "all", "no"
  session.rs    the resolver: intents to ops, questions, all-or-nothing

crates/incubrix-cli/src
  lib.rs        session files, the runner, results.json, expectation checks
  main.rs       `incubrix session run | batch run | check`

fixtures/sessions/  47 scripted scenarios with expected results

schema/         generated JSON Schemas (timeline, project, op, outcome, intent)
```

## Commands

```sh
cargo test --workspace                          # all tests
cargo clippy --workspace -- -D warnings         # lints
cargo run -p incubrix-cli -- check fixtures/sessions             # 47 scenarios, 3 runs each
cargo run -p incubrix-cli -- session run my.yaml --out results/  # one session: results.json, timeline, render
cargo run -p incubrix-core --example schema     # regenerate schema/*.json
cargo run -p incubrix-nlu --example schema      # regenerate schema/intent.schema.json
UPDATE_GOLDEN=1 cargo test -p incubrix-media    # rewrite media golden files (review the diff)
cargo check -p incubrix-media --features whisper,sherpa   # real recogniser adapters
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `NLU_PROVIDER` | `rules` | `rules`, `anthropic`, `openai`, `ollama`, `mock` |
| `NLU_MODEL` | per provider | model for the LLM parser |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | - | keys for the LLM parser |
| `OLLAMA_URL` / `NLU_BASE_URL` | - | where the LLM parser sends requests |
| `NLU_CACHE_DIR` | `.incubrix-cache/nlu` | cached LLM answers (reruns need no network) |
| `FFPROBE` / `FFMPEG` | on `PATH` | media tools for intake |

## Error codes

Edits: `WOULD_REMOVE_EVERYTHING`, `OUT_OF_RANGE`, `SPEED_OUT_OF_RANGE`, `UNKNOWN_WORD`,
`UNKNOWN_CAPTION`, `UNKNOWN_EDIT`, `CONTRADICTS_EARLIER_EDIT`, `INVALID_EDIT`,
`UNKNOWN_INSTRUCTION`, `NOT_FOUND`, `CONTENT_REMOVED`, `NO_CAPTION`, `NO_MUSIC`,
`NO_PAUSE`, `NO_SUCH_SPEAKER`, `NO_TRANSCRIPT`, `NOTHING_TO_UNDO`, `NOTHING_TO_REDO`,
`NOTHING_TO_RESTORE`, `NOTHING_TO_ANSWER`, `NEEDS_A_SPAN`, `CANNOT_COMBINE`, `CANCELLED`,
`MUSIC_PATH_MISSING`, `CAPTION_PLACE_MISSING`, `EMPTY_CAPTION`, `LOW_CONFIDENCE_ONLY`,
`SPANS_A_CUT`, `ALREADY_THERE`, `NOTHING_TO_CHANGE`, `NOTHING_REFERRED_TO`, `NOTHING_THERE`.
Intake: `UNSUPPORTED_FORMAT`, `NO_VIDEO_STREAM`, `MEDIA_TOOL_FAILED`, `IO_ERROR`,
`BAD_MEDIA_DATA`, `SOURCE_CHANGED`.
