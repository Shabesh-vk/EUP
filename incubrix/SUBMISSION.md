# Submission form answers

Each row of the IncuBrix Submission Form, with a link to its proof. Copy
these into the Excel form. Paths are relative to `incubrix/`. Run everything
with `docker compose run --rm test`, or `cargo test --workspace` plus
`cargo run -p incubrix-cli -- check fixtures/sessions`.

Anything not proven is marked Partial or No.

## Must-haves

| # | Must-have | Met | Evidence |
|---|---|---|---|
| 1 | Never damage the original | Yes | History replayed on the untouched source: `crates/incubrix-core/src/history.rs`. The source SHA-256 is checked before and after render (`source_unchanged`): `crates/incubrix-media/src/render.rs`, `crates/incubrix-nlu/tests/render_worked_example.rs`. `results.json` records `source_sha256`. |
| 2 | Edits stick to content | Yes | Word-id anchors (`Anchor` in `crates/incubrix-core/src/model.rs`). Tests: `crates/incubrix-core/tests/hard_cases.rs` (caption hidden and back on restore, reorder then mute, partial cut). Scenarios 18, 45, 46. Rendered frames checked in `crates/incubrix-media/tests/render.rs`. |
| 3 | Three-way answers | Yes | `crates/incubrix-core/src/outcome.rs`; `every_answer_has_one_of_three_statuses_and_the_policy` in `crates/incubrix-nlu/tests/hard_cases.rs`; every step of the 47 scenarios. |
| 4 | Predictable | Yes | `timeline_hash` (SHA-256 of canonical JSON, integer microseconds): `crates/incubrix-core/src/hash.rs`. `incubrix check` runs every session 3 times: 100% identical (`metrics/METRICS.md`). The model only outputs an intent (`crates/incubrix-nlu/src/intent.rs`); resolver and timeline are plain Rust. |
| 5 | Render matches the timeline | Yes | `verify` measures length and A/V offset in frames: `crates/incubrix-media/src/render.rs`. Tests: `every_kind_of_edit_renders_within_one_frame`, `extreme_speeds_and_many_cuts_stay_in_sync`. Metrics: worst length difference 0.49 frames, A/V offset 0 frames over 4 renders. |
| 6 | All operations, undo/redo, restore | Yes | Scenarios 02-33; `undo_redo_and_new_edit_clears_redo`, `restore_rules` in `crates/incubrix-core/tests/hard_cases.rs`. |
| 7 | A clear time policy | Yes | Policy "current" (`crates/incubrix-core/src/resolve.rs`), stated in every answer (`time_policy`) and in summaries ("Times are read as the current edited playback time"). Scenario 01 step 4. |
| 8 | Integration Standard, session runner, live demo | Partial | Standard: see below. Session runner: `incubrix session run`, `batch run`, `check`. **Live demo: not deployed yet** (needs a cloud account). The container is ready (`Dockerfile`, `docker-compose.yml`, token and rate limit built in). |

## Levels

| Level | Item | Met | Evidence |
|---|---|---|---|
| Core | All must-haves pass | Partial | All except the live demo URL (must-have 8). |
| Core | Worked example on own test video | Yes | `fixtures/sessions/01_worked_example.yaml`; on a real rendered video: `worked_example_on_a_real_video_writes_results_and_renders` (`crates/incubrix-cli/tests/scenarios.rs`), lengths 240, 210, 208, 193, 223, 193, 193, 193 s, pricing question with options. |
| Advanced | One single-speaker and one two-speaker video | Yes | `crates/incubrix-media/tests/intake.rs` (`single_speaker_transcript_matches_golden`, `two_speaker_transcript_matches_golden`); scenarios 41, 42. |
| Outstanding | Edits that shift each other | Yes | `caption_hidden_when_its_sentence_is_cut_and_back_when_restored` (user told by a warning), `partial_cut_keeps_the_caption_on_the_remaining_words` (rule: the caption stays on its remaining words), `sped_up_caption_keeps_a_readable_minimum` (0.7 s). |
| Outstanding | Ambiguity and references | Yes | Scenarios 33-38, `vague_requests_ask_with_options`, `that_caption_with_several_captions_asks`, `meaning_based_match_is_shown_before_cutting` ("pricing" finds "cost"). Metrics: 14 open instructions, 0 guessed. |
| Outstanding | Conflicts | Yes | Scenarios 03, 10, 11, 26, 39, 40; `same_cut_twice_is_safe`, `overlapping_speed_changes_latest_wins` (documented: the later one wins), `multi_part_instruction_is_all_or_nothing`, `deliberate_pause_survives_silence_removal`. |
| Outstanding | Two speakers | Yes | Scenario 41; `guest_lines_about_old_job_and_the_hosts_question`. |
| Outstanding | Imperfect data | Yes | Snap to silence (`snap_to_silence`, 150 ms; metrics: 0 of 20 cuts clip a word, automatic check). `low_confidence_words_are_not_bleeped_blindly`. `phone_video_with_variable_frame_rate_is_flagged`. `no_audio_works_and_says_so`. Overlap and label-swap warnings: scenario 42, `two_speaker_phone_video_with_music`. |
| Outstanding | Scale (60 min, < 3 s) | Yes | `crates/incubrix-cli/tests/scale.rs` (release build, in CI). Metrics: 60-minute video, median 107 ms, slowest 434 ms. |
| Outstanding | Export to OpenTimelineIO | Yes | `crates/incubrix-core/src/otio.rs`; `crates/incubrix-core/tests/otio.rs` opens the file with Python opentimelineio 0.18.1. `GET /api/v1/projects/{id}/otio`. |
| Outstanding | Proof: 40+ scripted scenarios in CI | Yes | 47 scenarios in `fixtures/sessions/`, checked 3 times each by `incubrix check` in `.github/workflows/incubrix.yml`. |

## Integration Standard

| # | Point | Met | Evidence |
|---|---|---|---|
| 1 | One-command start and test | Yes | `docker compose up`; `docker compose run --rm test` (workspace tests, 47 scenarios, live end-to-end test). |
| 2 | API contract | Yes | `openapi.yaml` (OpenAPI 3.1, generated from the handlers); `p2_openapi_matches_the_running_service`. |
| 3 | Jobs | Yes | 202 + `job_id`, `GET /api/v1/jobs/{id}` (status, progress, links), HMAC-SHA256 callback: `p3_jobs_progress_links_and_signed_callback`; live test. |
| 4 | Idempotency | Yes | `p4_idempotency_key`; live test retries an instruction. |
| 5 | Clear errors | Yes | One shape, 19 codes (`crates/incubrix-api/src/error.rs`); `p5_errors_have_one_shape`. |
| 6 | Configuration | Yes | `.env.example`; `crates/incubrix-api/src/config.rs`. No paths or keys in code. |
| 7 | Files in, files out | Yes | Upload or URL in; results to S3 (SeaweedFS in compose) as presigned links: `p7_url_in_render_out_as_a_link`, live test downloads a presigned link. |
| 8 | Logs and health | Yes | JSON logs with `job_id` and `correlation_id`; `/health`, `/ready`: `p8_correlation_id_health_ready`. |
| 9 | Output manifest | Yes | `crates/incubrix-api/src/manifest.rs`; `p9_manifest_and_editing_over_http`. |
| 10 | Batch runner | Yes | `incubrix batch run <folder> --api URL`; `p10_session_job_writes_results`; live test runs it against the stack. |

## Hard cases

| Case | Result | Evidence |
|---|---|---|
| Caption added, its sentence cut, cut restored | Caption hidden with a warning, comes back on restore | Scenario 18, 46 |
| Section reordered, then a word in it muted | The mute follows the word | Scenario 45 |
| Filler removal into a bleeped word | Bleeped filler left alone, said so | Scenario 24 |
| "Remove 0:30-0:40" twice | Second time asks (already cut) | Scenario 03 |
| Caption at 5:00 on a shorter video | Rejected with the video's length | `caption_past_the_end_is_rejected` |
| "80 seconds", "a minute twenty", "the last 10 seconds" | Read correctly | Scenarios 04, 05 |
| "Undo the second-to-last cut but keep the music" | That cut restored, music kept | Scenario 32 |
| "Make it bigger" with no caption | Rejected: no caption exists | Scenario 17 |
| "Remove everything after I say thanks" (4 times) | Asks which, with 4 options | Scenario 35 |
| "Speed up 10x", "cut everything" | Rejected, nothing changed | Scenarios 10, 11 |
| Three-part instruction, one part impossible | Nothing applied; says which part failed | Scenario 39 |
| Two speakers with label swap, overlap, music | Warnings for swap and overlap | Scenario 42, `two_speaker_phone_video_with_music` |
| Phone video, variable frame rate | Flagged at intake; the render is constant fps and its report says so | `phone_video_with_variable_frame_rate_is_flagged` (probe of a real iPhone clip); render branch in `crates/incubrix-media/src/render.rs`. No test renders a real VFR file yet. |

## Metrics

From `metrics/METRICS.md` (`cargo run --release -p incubrix-cli -- metrics`).

| Metric | Value |
|---|---|
| Instruction latency, 5-minute video | median 1.7 ms, slowest 12.9 ms |
| Instruction latency, 60-minute video | median 107 ms, slowest 434 ms |
| Render accuracy | largest length difference 0.49 frames, largest A/V offset 0 frames (4 renders) |
| Determinism | 100% (47 sessions x 3 runs) |
| Clarification quality | 14 open instructions: 6 asked, 1 stated an assumption, 5 had one candidate and named it, 2 refused with a reason, 0 guessed |
| Word clipping | 0 of 20 cuts. This is an automatic check of cut edges against word timings, not a listening check: **listen to 20 cuts before submitting.** |
| Cost | $0.00 per minute: local whisper and the rules parser. With an optional cloud LLM, its provider's price per request. |

## Still to do before submitting

- Deploy the container and put the URL (and `API_TOKEN`) in the form.
- Record the demo video.
- Do the listening check of 20 cuts.
- Give the reviewer access to the GitHub repository.
