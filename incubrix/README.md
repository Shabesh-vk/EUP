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
| 8 | HTTP service, Integration Standard | done (public demo deploy pending) |
| 9 | Concat AI tab, in-process | done |
| 10 | Outstanding level, metrics, evidence | done (`metrics/METRICS.md`, `SUBMISSION.md`) |

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
cargo run -p incubrix-nlu --example intent_schema      # regenerate schema/intent.schema.json
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

## The HTTP service (Integration Standard)

```sh
docker compose up                # API on http://localhost:8080, S3 store (SeaweedFS) on :9000
docker compose run --rm test     # every test: unit, integration, 47 scenarios, end to end on the live stack
```

No API key is needed for either. Settings: `.env.example` (copy to `.env`).

| # | Point | Where |
|---|---|---|
| 1 | One-command start and test | `docker-compose.yml` (api + S3 store (SeaweedFS) + bucket init + `test` profile), `.env.example` |
| 2 | Documented HTTP API | `openapi.yaml` (OpenAPI 3.1, generated by `incubrix-api --openapi`; test `p2_openapi_matches_the_running_service`), also served at `/api/v1/openapi.json` |
| 3 | Background jobs | intake, renders and sessions answer `202 {job_id}`; `GET /api/v1/jobs/{id}` → status, progress, result links; `callback_url` signed with HMAC-SHA256 in `X-IncuBrix-Signature: sha256=…` |
| 4 | Safe retries | `Idempotency-Key` on every POST: same key + same request → the stored response (header `Idempotent-Replayed: true`), work never repeated; same key + different request → `409 IDEMPOTENCY_KEY_REUSED` |
| 5 | Clear errors | `{"error": {code, message, retryable, details}}`, codes below |
| 6 | Configuration | environment only (`config.rs`) |
| 7 | Files in, files out | upload (multipart `video`) or `video_url` in; results to S3 (SeaweedFS in compose), returned as presigned links |
| 8 | Logs and health | JSON logs (timestamp, level, `job_id`, `correlation_id`); `X-Correlation-Id` echoed or created; `/health`, `/ready` (database, store, ffmpeg) |
| 9 | Output manifest | every outcome and job result: engine version, models, settings, seed, timings, cost, warnings, licences |
| 10 | Batch runner | `incubrix batch run <folder> --api http://localhost:8080 --out results/` |

Routes (all under `/api/v1/` except health): `POST /projects` · `GET /projects/{id}` ·
`POST /projects/{id}/instructions` `{say}` · `POST /projects/{id}/answers` `{answer}` ·
`POST /projects/{id}/undo` · `POST /projects/{id}/redo` · `GET /projects/{id}/timeline` ·
`GET /projects/{id}/history` · `GET /projects/{id}/otio` · `POST /projects/{id}/renders` ·
`POST /sessions` · `GET /jobs/{id}` · `GET /files/{key}` (local storage mode).

Instructions are answered synchronously: the rules reader and the engine take
milliseconds (measured in the logs' `ms`). With `NLU_PROVIDER` set to a hosted
model an instruction can take longer than two seconds; that is opt-in.

### API error codes

`VALIDATION_ERROR`, `ROUTE_NOT_FOUND`, `PROJECT_NOT_FOUND`, `PROJECT_NOT_READY`, `JOB_NOT_FOUND`,
`FILE_NOT_FOUND`, `UNAUTHORIZED`, `RATE_LIMITED` (retry after `Retry-After`), `IDEMPOTENCY_KEY_REUSED`, `PAYLOAD_TOO_LARGE`, `DOWNLOAD_FAILED`,
`NO_TRANSCRIBER`, `UNSUPPORTED_FORMAT`, `NO_VIDEO_STREAM`, `MEDIA_TOOL_FAILED`,
`RENDER_MISMATCH`, `SOURCE_CHANGED`, `STORAGE_UNAVAILABLE`, `INTERNAL` (retryable).
An editing answer of `rejected` is not an HTTP error: it is a `200` with the
engine's own code (listed above under Error codes).

### Public deployment

The same container runs anywhere Docker runs. For a public URL set:

| Setting | What it does |
|---|---|
| `API_TOKEN` | `/api/v1` needs `Authorization: Bearer <token>` (`401 UNAUTHORIZED` otherwise). `/health`, `/ready`, `/api/v1/openapi.json` and result links stay open. |
| `RATE_LIMIT_PER_MINUTE` | Requests per client per minute (default 120): `429 RATE_LIMITED` with `Retry-After`. |
| `TRUST_FORWARDED` | Behind your own proxy, take the client from `X-Forwarded-For`. |
| `S3_*`, `PUBLIC_URL` | Any S3-compatible bucket, and the address clients use. |

Cold start: the image is 957 MB (ffmpeg and the whisper model included); a
stopped container answers `/ready` 7.1 s after start (measured with
docker compose on Windows).

## Metrics

```sh
cargo run --release -p incubrix-cli -- metrics --out metrics
```

This measures what the brief's Metrics tab asks for and writes
`metrics/METRICS.md` and `metrics/metrics.json`: latency on a 5-minute and a
60-minute interview, render accuracy (needs ffmpeg), determinism over the 47
scenarios, clarification quality, word clipping over 20 cuts, and cost. CI
runs it and keeps `METRICS.md` as an artifact; `tests/scale.rs` fails the
build if any instruction on 60 minutes takes 3 s or more.

Evidence for every claim: `SUBMISSION.md`. Sources and licences: `SOURCES.md`.
AI use: `AI_USE.md`.
