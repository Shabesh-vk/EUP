# Sources

Everything the IncuBrix engine (`incubrix/`) uses: models, services, crates,
tools, data and media, with licences. The engine itself is MIT OR Apache-2.0.

## Licence boundary

The engine never depends on EUP (`src/`, AGPL-3.0; a renamed fork of
Concat). EUP is only the
desktop demo, and it depends on the engine (`incubrix-core`, `incubrix-nlu`,
and `incubrix-cli` for one test), never the other way round. The HTTP service,
the CLI and every test run without EUP.

## Models

| Model | Licence | Used for | Where |
|---|---|---|---|
| whisper.cpp `ggml-tiny.en` (OpenAI Whisper weights, converted by ggerganov) | MIT | Speech to words with timings, in the Docker image | `Dockerfile` downloads it from huggingface.co/ggerganov/whisper.cpp; `incubrix-media` feature `whisper` |
| pyannote segmentation + a speaker-embedding model via sherpa-onnx | MIT (pyannote), Apache-2.0 (sherpa-onnx; per-model licences in its model zoo) | Speaker turns (optional; tests use recorded turns) | `incubrix-media` feature `sherpa` |
| Claude (`claude-opus-5-5`, Anthropic API) | Commercial API | Optional: reads a request into a structured intent | `incubrix-nlu/src/llm.rs`, only with `NLU_PROVIDER=anthropic` and a key |
| OpenAI `gpt-4o-mini` | Commercial API | Optional, same role | `NLU_PROVIDER=openai` |
| Ollama local models (`llama3.1`, `qwen2.5`, `llama3`, `mistral`, whichever is installed) | Per model (Llama 3.1 Community, Apache-2.0 for Qwen 2.5 / Mistral) | Optional, same role, offline | `NLU_PROVIDER=ollama` |

A model may only produce a structured intent (JSON validated against
`schema/intent.schema.json`). Every timeline change is plain Rust. The default,
and everything in the tests and the metrics, is the deterministic rules parser.

## Services and tools (separate processes, not linked)

| Tool | Licence | Used for |
|---|---|---|
| FFmpeg / ffprobe | LGPL-2.1+ / GPL (distribution build) | Probe, render, verify, test media |
| SeaweedFS 4.48 (`chrislusf/seaweedfs`) | Apache-2.0 | S3-compatible store in docker compose |
| OpenTimelineIO 0.18.1 (Python) | Apache-2.0 | Tests only: opens our `.otio` exports |
| Docker, docker compose | Apache-2.0 | Packaging |

## Rust crates (direct dependencies)

| Crate | Licence | Used for |
|---|---|---|
| serde, serde_json, serde_yaml | MIT OR Apache-2.0 | Data formats |
| sha2, hmac, hex | MIT OR Apache-2.0 | Hashes, callback signatures |
| thiserror | MIT OR Apache-2.0 | Errors |
| schemars | MIT | JSON Schemas (`schema/`) |
| regex | MIT OR Apache-2.0 | Rules parser |
| ureq | MIT OR Apache-2.0 | HTTP client (LLM adapters, downloads, batch runner) |
| axum, tower | MIT | HTTP service |
| tokio | MIT | Async runtime |
| utoipa | MIT OR Apache-2.0 | OpenAPI document from the code |
| uuid | MIT OR Apache-2.0 | Ids |
| rusqlite (bundled SQLite) | MIT (SQLite: public domain) | Jobs, projects, idempotency keys |
| object_store | MIT OR Apache-2.0 | S3 and local storage, presigned links |
| bytes, url | MIT (OR Apache-2.0) | Plumbing |
| tracing, tracing-subscriber | MIT | JSON logs |
| whisper-rs (optional) | Unlicense | whisper.cpp bindings |
| sherpa-onnx (optional) | Apache-2.0 | Diarization bindings |
| http-body-util (tests) | MIT | Test helpers |

`cargo tree` lists the transitive crates; all are permissive (MIT, Apache-2.0,
BSD, ISC, Unicode, Zlib).

## Data and media

| Item | Source | Licence |
|---|---|---|
| `fixtures/media/*` transcripts and speaker turns | Written for this project | MIT OR Apache-2.0 |
| `fixtures/sessions/*.yaml` (47 scenarios) | Written for this project; the worked example and hard cases follow the IncuBrix brief | MIT OR Apache-2.0 |
| Test videos | Generated at test time by FFmpeg (`testsrc`, `sine`) | None needed |
| 5- and 60-minute interviews in `incubrix metrics` | Generated from a fixed list of sentences | None needed |

No third-party datasets or downloaded media are used.
