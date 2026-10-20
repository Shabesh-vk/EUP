# IncuBrix engine - phase notes

Running notes per phase of `../docs/RUST_ENGINE_PLAN.md`. (The root
`REPORT.md` still has unresolved merge-conflict markers from the Python
engine; these notes are kept here until it is cleaned up.)

## Phase 4 - Intake, transcript, diarization

- New crate `incubrix-media`: `probe()` (ffprobe JSON parsed straight to
  integer microseconds; exact rational fps; VFR when base and average
  rates differ by more than 0.1 %; MP4/MOV only, `UNSUPPORTED_FORMAT`
  otherwise; `NO_VIDEO_STREAM`), source SHA-256 and `verify_unchanged`.
- `Transcriber` trait + `FixtureTranscriber`; `clean_words` sorts, clamps,
  trims overlaps, keeps punctuation on the word that ended just before it,
  numbers words `w00000...`, and flags low-confidence words (< 0.5).
- `Diarizer` trait + `FixtureDiarizer`; `assign_speakers` (most overlap
  wins, labels `S1`, `S2` by first appearance) warns on overlapping speech
  and likely speaker-label swaps; labels are never silently changed.
- `TranscriptCache` keyed by source hash + recogniser (+ diarizer).
- `WhisperRs` and `SherpaOnnx` adapters behind features `whisper` and
  `sherpa`. They type-check against whisper-rs 0.16 and sherpa-onnx 1.13
  but have **not been run**: no models are on this machine. CI uses the
  fixture adapters only.
- Done when: `tests/intake.rs` - a single-speaker and a two-speaker test
  video (made by ffmpeg in the test) go through intake with hash, fps,
  audio and a cache hit on the second run; the fixture adapters reproduce
  `fixtures/media/*.transcript.json` byte for byte; no-audio, VFR and
  non-MP4 cases fail or warn clearly. The video part skips (with a
  message) where ffmpeg is missing; CI now installs it.
- Deviation: the test videos carry a tone, not speech, so the words come
  from recorded recogniser output rather than a live recogniser run.

## Phase 5 - Understanding instructions

- New crate `incubrix-nlu`: `Intent` schema (`schema/intent.schema.json`),
  `Parser` trait, adapters `rules` (default), `llm` (Anthropic / OpenAI /
  Ollama, temperature 0, schema in the prompt, answers cached by SHA-256 of
  provider + model + prompt + context), `mock`; `parser_from_env()` reads
  `NLU_PROVIDER`.
- `Session` resolves intents in plain code: current-time policy for typed
  times; several matches give `needs_clarification` with timestamped
  options and an "All" option where it makes sense; meaning-based matches
  (synonym table) are always shown first; "that caption" uses the last
  caption talked about, else the only one (stated as an assumption), else
  asks; vague goals ask with concrete options; multi-part instructions
  resolve on a staged copy and commit as one transaction, or are rejected
  naming the failing part.
- Core change: `Project::apply` now validates each op against the timeline
  the earlier ops of the same transaction left, so "cut 10 s, then caption
  what is at 0:05" works as one transaction. `Outcome` gained an optional
  `code` (UPPER_SNAKE_CASE) for rejections.
- Documented choices: the same typed cut sent twice asks (under the
  current-time policy it would hit different content); "undo the
  second-to-last cut but keep the music" restores that cut and re-adds any
  music it carried; low-confidence words are never bleeped without asking.
- Done when: `tests/hard_cases.rs` covers every row of the brief's hard-case
  list plus the Outstanding ambiguity and conflict items (22 tests), and
  `tests/worked_example.rs` runs the 8 steps from typed words, 3 times with
  identical hashes. All with the rules parser and fixture transcripts.
- Not done: the LLM adapter is only tested through its cache (no API key in
  CI); semantic search uses a synonym table, not embeddings.

## Concat AI tab (part of Phase 9, done early on request)

- The hard-coded tab (fake hashes, string matching, canned summaries) is
  replaced by one that shows the engine's real answers: status, summary,
  operations, warnings, the question with clickable options, hash, length,
  edit history with per-edit Restore, and captions.
- `src/crates/concat/src/panes/ai.rs` runs `incubrix_nlu::Session` in
  process and, after every change, rebuilds the engine-managed clips on the
  Concat timeline in one gesture (one Ctrl+Z): a clip per segment
  (in-point, length, speed, muted where a mute or bleep lands) and a title
  per caption at its projected time.
- Word-based edits use Concat's transcriber; its output is phrase-level, so
  word times are spread inside each phrase (the tab says so).
- Known gaps: Ctrl+Z in Concat is not mirrored into the engine (editing the
  managed clips by hand starts a new AI session, with a notice); bleeps are
  muted in the preview, not toned; rendering goes through Concat's Export.

## AI models read plain English (Phase 5 follow-up)

- `AutoParser` (the default from `parser_from_env()`): an AI model reads the
  words first when one is set up; the built-in rules are the backup when the
  model is unreachable, refuses, or does not understand. With no model set
  up, the rules work alone as before.
- Model selection, in order: `NLU_PROVIDER` (`anthropic`, `openai`, `ollama`,
  `rules`, `mock`); else `ANTHROPIC_API_KEY` (Claude, default model
  `claude-opus-5-5`); else `OPENAI_API_KEY`; else a local Ollama server with
  a model pulled (probed once per run at `127.0.0.1:11434`).
- Claude is called over raw HTTP (no official Rust SDK): no `temperature`
  (current models reject it), `output_config.effort: "low"`, server-side
  `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`), thinking
  blocks skipped when reading the text, `stop_reason: "refusal"` handled.
- The prompt is a compact cheat-sheet of every intent shape plus examples
  (the raw recursive JSON Schema was too much for small local models).
  Times the user said are converted by the engine (`times::mentions`) and
  handed to the model as `times_in_ms`: models are unreliable at that
  arithmetic. A malformed answer gets one correction round; answers are
  cached by hash, so reruns need no network and give the same result.
- Free-form replies to a question ("the one about teams") go to the model
  when the plain matcher cannot read them; the matcher no longer reads "the
  one about X" as option 1.
- Tests: `tests/ai_model.rs` runs the whole path against a local stand-in
  for the Messages API (request shape, correction round, refusal, rules
  backup, free-form answer, cache). Live check on this machine with Ollama
  `llama3.1:8b` (`cargo run -p incubrix-nlu --example ask`), about 0.3-1.5 s
  per sentence: the runs showed three misreadings - "half minute" as 60 s,
  unrequested style fields, "the captions" as one caption - each fixed in
  the prompt or with `times_in_ms` and re-checked. This is a spot check of
  about 20 sentences, not a measured accuracy.
  Not tested live: Claude and OpenAI (no API key here).
- Concat: the AI tab reads on a worker thread (the window stays responsive),
  says whether the AI is on and which model, and its buttons (Undo, Redo,
  Restore) bypass the model.

## Conversation (talk intent)

- New intent `talk` (topics greeting, thanks, help, status, history,
  smalltalk). The engine answers from its own state - file name, current
  and original length, change list, caption count - so a reply never
  carries a model's guess about the video. Only small talk uses words a
  model wrote (`reply`, capped at 280 characters). Talk changes nothing and
  records no undo step (`status: applied`, `tx: null`, `code: "TALK"`).
- Rules recognise common greetings, thanks, help and status/history
  questions; a greeting in front of a request ("hi, can u cut the first
  30 seconds") is treated as courtesy and the request is applied.
- The AI prompt gained the talk shapes and examples; live check with
  `llama3.1:8b`: 8 of 8 sample messages classified as expected (spot check).
- Tests: `tests/talk.rs` (4).
- Concat chat: warmer replies ("Done! ... The video is now 4:05.3 (2.7 s
  shorter). I've moved the preview to 0:02 so you can see it. What's next?"),
  doubled punctuation after quotes fixed, user bubbles sized to their words,
  replies with an AI avatar.

## Phase 6 - Rendering and export

- `incubrix-media::render`: one ffmpeg run built from the timeline only -
  `trim`/`atrim` per segment, `setpts` and chained `atempo` for speed,
  `concat`, mutes as `volume=0` over their playback spans, bleeps as a
  1 kHz `aevalsrc` tone, music looped and ducked with `sidechaincompress`
  keyed on the speech, captions burned in from a generated ASS file.
  Output is H.264/AAC at the source's frame rate, constant (a variable-rate
  source is resampled, with a warning).
- Sync by construction: every cut point is snapped to the source's frame
  grid and picture and sound are cut at the same points, so they cannot
  drift apart across many cuts; both streams are then padded or trimmed to
  exactly the timeline's length.
- `render::verify` measures every render with ffprobe and fails loudly
  (`RENDER_MISMATCH`) if the length is more than one frame off the timeline,
  or sound and picture start or end more than one frame apart. The source
  is hashed before and after (`SOURCE_CHANGED` if it differs).
- Typed cut points that land inside a word snap to the nearer edge of that
  word within 150 ms (`resolve::snap_to_silence`); farther than that they
  stay, with a warning that the word may be clipped.
- `incubrix-core::otio`: OpenTimelineIO export (Timeline.1, Clip.2 per
  segment with LinearTimeWarp for speed, markers for captions, mutes and
  bleeps). Verified by reading it back with the official
  `opentimelineio` 0.18.1 library (length, clip and marker counts).
- Done when: `tests/render_worked_example.rs` types the brief's 8 steps on
  a real 4-minute video and renders step 8: timeline 193.000 s, render
  192.993 s (0.22 frames), A/V start offset 0 frames, source unchanged, one
  caption burned in. A frame at 0:12.5 of the render shows source 0:42
  (where "welcome to the channel" is said) with the red caption; at 0:15
  it is gone. Other render tests: every edit kind together, 4x and 0.25x
  speeds with 20 off-grid cuts (0.11 frames), and a deliberately wrong
  length that must fail.
- Not done: the file has not been opened in DaVinci Resolve (not installed
  here); music ducking depth is approximate (a compressor, not a fixed
  gain); bleeps and mutes in the Concat preview are still mutes only.

## Phase 7 - Session runner and the test suite

- New crate `incubrix-cli`, binary `incubrix`:
  `session run <file> --out DIR` plays a session in the brief's format
  (`video`, `steps` with `say` and `answer`) and writes `results.json`
  (per step: status, operations, summary, question, options,
  timeline_hash, duration_s, plus warnings and code), `timeline.json`,
  `history.json`, `timeline.otio`, and the render for a "render" step.
  `batch run <folder>` does the same for every session in a folder (the
  `--api` mode belongs to Phase 8). `check <folder>` plays every session
  three times, compares the hashes and checks the `expect:` blocks.
- Session-file extensions (optional): `transcript:` (recorded words),
  `speakers:` (turns), `source:` (a length and spoken lines, so engine-only
  scenarios need no video), `expect:` per step.
- 47 scenarios in `fixtures/sessions/`: every operation in the brief, every
  hard-case row, ambiguity and references, conflicts, two speakers, low
  confidence, conversation. Expected values were worked out by hand before
  the first run (e.g. 2.9 s after silence removal, 7.4 s with a protected
  pause, 9.3 s for the guest's lines); all 47 pass, 3 runs each with the
  same hashes. A planted wrong expectation is reported (test).
- Done when: the worked example as a session file naming a real 4-minute
  video reproduces exactly (240, 210, 208, 193, 223, 193, 193, 193 s; the
  pricing question with 4 options) and step 8 renders at 0.22 frames off
  the timeline with A/V offset 0. CI runs `incubrix check fixtures/sessions`.
- Not done: videos given as URLs are downloaded but not cached by hash;
  speech recognition in the runner needs `transcript:` (whisper adapter
  not wired to the CLI yet).
