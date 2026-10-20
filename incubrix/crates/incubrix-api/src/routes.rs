//! The routes. Each is described for OpenAPI with `utoipa`; `openapi.yaml`
//! is generated from these annotations, and a test checks the file matches
//! the running service.

use std::path::{Path as FsPath, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use axum::body::to_bytes;
use axum::extract::{FromRequest, Multipart, Path, Request, State};
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{Extension, Json};
use incubrix_core::time::to_secs_ms;
use incubrix_media::transcribe::RawTranscript;
use incubrix_media::{intake, FixtureTranscriber, Transcriber};
use incubrix_nlu::intent::Intent;
use incubrix_nlu::{Action, Reply};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use utoipa::{OpenApi, ToSchema};

use crate::db::{Job, JobStatus};
use crate::error::{ApiError, ErrorBody};
use crate::jobs::{self, Output};
use crate::manifest::{manifest, parser_model};
use crate::{AppState, CorrelationId};

type S = State<Arc<AppState>>;
type R<T> = Result<T, ApiError>;

// ---- schemas ----------------------------------------------------------------

/// `GET /health`.
#[derive(Serialize, ToSchema)]
pub struct Health {
    /// Always "ok" while the process runs.
    pub status: String,
    /// Service version.
    pub version: String,
}

/// `GET /ready`.
#[derive(Serialize, ToSchema)]
pub struct Ready {
    /// All checks passed.
    pub ready: bool,
    /// Each dependency.
    #[schema(value_type = Object)]
    pub checks: Value,
}

/// Start work: a job was accepted.
#[derive(Serialize, ToSchema)]
pub struct Accepted {
    /// Poll `GET /api/v1/jobs/{job_id}`.
    pub job_id: String,
    /// The project the job belongs to, if any.
    pub project_id: Option<String>,
    /// Where to poll.
    pub status_url: String,
}

/// A new project from a video URL (JSON body).
#[derive(Default, Deserialize, ToSchema)]
pub struct CreateProject {
    /// http(s) URL of an MP4 or MOV.
    pub video_url: Option<String>,
    /// Recorded words (`{"words": [{text, start, end, confidence}]}`, microseconds),
    /// used instead of speech recognition.
    #[schema(value_type = Object)]
    pub transcript: Option<Value>,
    /// Told when intake ends (HMAC-SHA256 signed).
    pub callback_url: Option<String>,
}

/// A new project from an upload (multipart form).
#[derive(ToSchema)]
#[allow(dead_code)]
pub struct CreateProjectForm {
    /// The MP4 or MOV file.
    #[schema(value_type = String, format = Binary)]
    pub video: Vec<u8>,
    /// Recorded words as JSON text (optional).
    pub transcript: Option<String>,
    /// Told when intake ends.
    pub callback_url: Option<String>,
}

/// One instruction in plain English.
#[derive(Deserialize, ToSchema)]
pub struct Instruction {
    /// What the user typed, e.g. "Cut the first 30 seconds".
    pub say: String,
}

/// The reply to the waiting question.
#[derive(Deserialize, ToSchema)]
pub struct Answer {
    /// E.g. "the second one", "all", or an option's own words.
    pub answer: String,
}

/// Optional body for a render.
#[derive(Deserialize, ToSchema, Default)]
pub struct RenderRequest {
    /// Told when the render ends.
    pub callback_url: Option<String>,
}

/// A scripted session to play (JSON body).
#[derive(Deserialize, ToSchema)]
pub struct SessionRequest {
    /// The session: an object, or YAML text, in the brief's format
    /// (`video`, `steps: [{say, answer}]`).
    #[schema(value_type = Object)]
    pub session: Value,
    /// Overrides the session's `video`.
    pub video_url: Option<String>,
    /// Recorded words for the video.
    #[schema(value_type = Object)]
    pub transcript: Option<Value>,
    /// Recorded speaker turns.
    #[schema(value_type = Object)]
    pub speakers: Option<Value>,
    /// Told when the session ends.
    pub callback_url: Option<String>,
}

/// An editing answer: applied, needs_clarification or rejected.
#[derive(Serialize, ToSchema)]
#[allow(dead_code)]
pub struct OutcomeDoc {
    /// `applied` | `needs_clarification` | `rejected`.
    pub status: String,
    /// What was done, one line each.
    pub operations: Vec<String>,
    /// Before/after, or the reason.
    pub summary: String,
    /// The question, when one is asked.
    pub question: Option<String>,
    /// Its options.
    pub options: Vec<String>,
    /// Consequences worth knowing.
    pub warnings: Vec<String>,
    /// Always "current": typed times are current playback time.
    pub time_policy: String,
    /// Hash of the timeline after the step.
    pub timeline_hash: String,
    /// Edited length after the step, seconds.
    pub duration_s: f64,
    /// The undo step recorded, if any.
    pub tx: Option<u32>,
    /// Reason code of a rejection.
    pub code: Option<String>,
    /// The project.
    pub project_id: String,
    /// What the caller should do next ("render"), if anything.
    pub action: Option<String>,
    /// Models, settings, timings, licences.
    #[schema(value_type = Object)]
    pub manifest: Value,
}

/// A project's state.
#[derive(Serialize, ToSchema)]
pub struct ProjectSummary {
    /// Id.
    pub project_id: String,
    /// Intake finished.
    pub ready: bool,
    /// Edited length, seconds.
    pub duration_s: Option<f64>,
    /// Source length, seconds.
    pub original_duration_s: Option<f64>,
    /// Current timeline hash.
    pub timeline_hash: Option<String>,
    /// Active edits.
    pub edits: usize,
    /// Captions.
    pub captions: usize,
    /// Words in the transcript.
    pub words: usize,
    /// The question waiting for an answer.
    pub pending_question: Option<String>,
    /// Its options.
    pub options: Vec<String>,
    /// Intake warnings.
    pub warnings: Vec<String>,
}

#[derive(OpenApi)]
#[openapi(
    info(
        title = "IncuBrix editing engine",
        version = "1.0.0",
        description = "Prompt-based video editing: plain-English instructions become exact, reversible edits on a timeline that is replayed on the untouched source. Every instruction answers applied, needs_clarification or rejected; times are read as current playback time. Slow work runs as jobs (202 + job_id). Every POST accepts an Idempotency-Key. Errors are {\"error\": {code, message, retryable, details}}.",
        license(name = "MIT OR Apache-2.0")
    ),
    servers((url = "http://localhost:8080", description = "docker compose")),
    paths(health, ready, create_project, get_project, instruct, answer, undo, redo, timeline, history, otio, render, run_session, get_job, file),
    components(schemas(Health, Ready, Accepted, CreateProject, CreateProjectForm, Instruction, Answer, RenderRequest, SessionRequest, OutcomeDoc, ProjectSummary, Job, JobStatus, ErrorBody)),
    tags(
        (name = "service", description = "Health and readiness"),
        (name = "projects", description = "Videos taken in for editing"),
        (name = "editing", description = "Instructions, answers, undo and redo"),
        (name = "jobs", description = "Background work: intake, render, sessions")
    )
)]
pub struct ApiDoc;

/// The OpenAPI document as YAML (what `openapi.yaml` holds).
pub fn openapi_yaml() -> String {
    ApiDoc::openapi().to_yaml().unwrap_or_default()
}

// ---- service -------------------------------------------------------------------

/// Liveness.
#[utoipa::path(get, path = "/health", tag = "service", responses((status = 200, body = Health)))]
pub async fn health() -> Json<Health> {
    Json(Health {
        status: "ok".into(),
        version: env!("CARGO_PKG_VERSION").into(),
    })
}

fn tool_ok(bin: &str) -> bool {
    std::process::Command::new(bin)
        .arg("-version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Readiness: database, store, ffmpeg.
#[utoipa::path(get, path = "/ready", tag = "service", responses((status = 200, body = Ready), (status = 503, body = Ready)))]
pub async fn ready(State(state): S) -> Response {
    let db = state.db.ping();
    let store = state.storage.ready().await;
    let ffmpeg = tool_ok(&incubrix_media::probe::ffmpeg_bin())
        && tool_ok(&incubrix_media::probe::ffprobe_bin());
    let ok = db && store && ffmpeg;
    let body = Ready {
        ready: ok,
        checks: json!({"database": db, "storage": store, "ffmpeg": ffmpeg, "speech_recognition": state.transcriber.is_some()}),
    };
    let status = if ok {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (status, Json(body)).into_response()
}

/// The OpenAPI document as JSON.
pub async fn openapi_json() -> Json<Value> {
    Json(serde_json::to_value(ApiDoc::openapi()).unwrap_or(Value::Null))
}

/// Unknown routes get the same error shape as everything else.
pub async fn not_found() -> ApiError {
    ApiError::not_found("ROUTE_NOT_FOUND", "no such route; see /api/v1/openapi.json")
}

// ---- helpers -------------------------------------------------------------------

fn new_id(prefix: &str) -> String {
    format!("{prefix}_{}", uuid::Uuid::new_v4().simple())
}

fn accepted(job_id: String, project_id: Option<String>) -> Response {
    let body = Accepted {
        status_url: format!("/api/v1/jobs/{job_id}"),
        job_id,
        project_id,
    };
    (StatusCode::ACCEPTED, Json(body)).into_response()
}

fn video_ext(name: &str) -> R<String> {
    let clean = name.split(['?', '#']).next().unwrap_or(name);
    let ext = FsPath::new(clean)
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if matches!(ext.as_str(), "mp4" | "mov" | "m4v") {
        Ok(ext)
    } else {
        Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "UNSUPPORTED_FORMAT",
            format!("only MP4 and MOV are accepted, not '{clean}'"),
        ))
    }
}

fn download(url: &str, to: &FsPath, limit: usize) -> R<()> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err(ApiError::bad(
            "VALIDATION_ERROR",
            "video_url must be http(s)",
        ));
    }
    let resp = ureq::get(url)
        .timeout(std::time::Duration::from_secs(600))
        .call()
        .map_err(|e| {
            ApiError::new(
                StatusCode::BAD_GATEWAY,
                "DOWNLOAD_FAILED",
                format!("cannot download {url}: {e}"),
            )
        })?;
    let mut f = std::fs::File::create(to).map_err(|e| ApiError::internal(e.to_string()))?;
    let n = std::io::copy(
        &mut std::io::Read::take(resp.into_reader(), limit as u64 + 1),
        &mut f,
    )
    .map_err(|e| ApiError::new(StatusCode::BAD_GATEWAY, "DOWNLOAD_FAILED", e.to_string()))?;
    if n as usize > limit {
        return Err(ApiError::new(
            StatusCode::PAYLOAD_TOO_LARGE,
            "PAYLOAD_TOO_LARGE",
            "the video is larger than MAX_UPLOAD_MB",
        ));
    }
    Ok(())
}

/// Recorded words as a file the fixture transcriber reads.
fn write_transcript(v: &Value, to: &FsPath) -> R<()> {
    let words = if v.is_array() {
        json!({"words": v})
    } else {
        v.clone()
    };
    // A recogniser's `{words}`, or the engine's own transcript (words with
    // ids), bare or inside `{"transcript": ...}` as the CLI writes it.
    let inner = words.get("transcript").unwrap_or(&words);
    let checked = if inner["words"].get(0).is_some_and(|w| w.get("id").is_some()) {
        serde_json::from_value::<incubrix_core::Transcript>(inner.clone()).map(|_| ())
    } else {
        serde_json::from_value::<RawTranscript>(words.clone()).map(|_| ())
    };
    checked.map_err(|e| {
        ApiError::bad("VALIDATION_ERROR", format!("transcript: {e}"))
            .with(json!({"field": "transcript"}))
    })?;
    std::fs::write(to, words.to_string()).map_err(|e| ApiError::internal(e.to_string()))
}

struct Form {
    video: Option<(String, PathBuf)>,
    fields: std::collections::HashMap<String, String>,
}

/// Reads a multipart form, writing a `video` part to `dir`.
async fn read_form(req: Request, state: &AppState, dir: &FsPath) -> R<Form> {
    let mut mp = Multipart::from_request(req, &())
        .await
        .map_err(|e| ApiError::bad("VALIDATION_ERROR", e.to_string()))?;
    let mut form = Form {
        video: None,
        fields: Default::default(),
    };
    while let Some(mut field) = mp
        .next_field()
        .await
        .map_err(|e| ApiError::bad("VALIDATION_ERROR", e.to_string()))?
    {
        let name = field.name().unwrap_or_default().to_owned();
        if name == "video" {
            let file_name = field.file_name().unwrap_or("video.mp4").to_owned();
            let ext = video_ext(&file_name)?;
            std::fs::create_dir_all(dir).map_err(|e| ApiError::internal(e.to_string()))?;
            let path = dir.join(format!("source.{ext}"));
            let mut out = tokio::fs::File::create(&path)
                .await
                .map_err(|e| ApiError::internal(e.to_string()))?;
            let mut written = 0usize;
            while let Some(chunk) = field
                .chunk()
                .await
                .map_err(|e| ApiError::bad("VALIDATION_ERROR", e.to_string()))?
            {
                written += chunk.len();
                if written > state.cfg.max_upload_bytes {
                    return Err(ApiError::new(
                        StatusCode::PAYLOAD_TOO_LARGE,
                        "PAYLOAD_TOO_LARGE",
                        "the upload is larger than MAX_UPLOAD_MB",
                    ));
                }
                tokio::io::AsyncWriteExt::write_all(&mut out, &chunk)
                    .await
                    .map_err(|e| ApiError::internal(e.to_string()))?;
            }
            form.video = Some((file_name, path));
        } else {
            let text = field
                .text()
                .await
                .map_err(|e| ApiError::bad("VALIDATION_ERROR", e.to_string()))?;
            form.fields.insert(name, text);
        }
    }
    Ok(form)
}

fn is_multipart(req: &Request) -> bool {
    req.headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.starts_with("multipart/form-data"))
}

async fn json_body<T: for<'de> Deserialize<'de> + Default>(
    req: Request,
    allow_empty: bool,
) -> R<T> {
    let bytes = to_bytes(req.into_body(), 16 * 1024 * 1024)
        .await
        .map_err(|e| ApiError::bad("VALIDATION_ERROR", e.to_string()))?;
    if bytes.is_empty() && allow_empty {
        return Ok(T::default());
    }
    serde_json::from_slice(&bytes)
        .map_err(|e| ApiError::bad("VALIDATION_ERROR", format!("body: {e}")))
}

fn transcriber_name(state: &AppState, provided: bool) -> String {
    if provided {
        "recorded transcript (supplied with the request)".into()
    } else if state.transcriber.is_some() {
        state
            .cfg
            .whisper_model
            .as_ref()
            .and_then(|m| m.file_stem())
            .map(|s| format!("whisper.cpp {}", s.to_string_lossy()))
            .unwrap_or_default()
    } else {
        "none".into()
    }
}

// ---- projects -------------------------------------------------------------------

/// Take in a video: upload (multipart `video`) or `video_url`. Probing,
/// hashing and speech recognition run as a job.
#[utoipa::path(
    post, path = "/api/v1/projects", tag = "projects",
    params(("Idempotency-Key" = Option<String>, Header, description = "Same key + same request = same job, never repeated work")),
    request_body(content(
        (CreateProject = "application/json"),
        (CreateProjectForm = "multipart/form-data")
    )),
    responses(
        (status = 202, body = Accepted),
        (status = 400, body = ErrorBody), (status = 409, body = ErrorBody),
        (status = 413, body = ErrorBody), (status = 422, body = ErrorBody)
    )
)]
pub async fn create_project(
    State(state): S,
    Extension(cid): Extension<CorrelationId>,
    req: Request,
) -> R<Response> {
    let project_id = new_id("prj");
    let dir = state.project_dir(&project_id);
    std::fs::create_dir_all(&dir).map_err(|e| ApiError::internal(e.to_string()))?;
    let (video, url, transcript, callback) = if is_multipart(&req) {
        let form = read_form(req, &state, &dir).await?;
        let transcript = match form.fields.get("transcript") {
            Some(t) => Some(
                serde_json::from_str::<Value>(t)
                    .map_err(|e| ApiError::bad("VALIDATION_ERROR", format!("transcript: {e}")))?,
            ),
            None => None,
        };
        (
            form.video.map(|v| v.1),
            None,
            transcript,
            form.fields.get("callback_url").cloned(),
        )
    } else {
        let body: CreateProject = json_body(req, false).await?;
        (None, body.video_url, body.transcript, body.callback_url)
    };
    let source = match (&video, &url) {
        (Some(p), _) => p.clone(),
        (None, Some(u)) => dir.join(format!("source.{}", video_ext(u)?)),
        (None, None) => {
            return Err(
                ApiError::bad("VALIDATION_ERROR", "send a `video` file or a `video_url`")
                    .with(json!({"fields": ["video", "video_url"]})),
            )
        }
    };
    let words = dir.join("transcript.json");
    if let Some(t) = &transcript {
        write_transcript(t, &words)?;
    } else if state.transcriber.is_none() {
        return Err(ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, "NO_TRANSCRIBER", "no transcript was sent and no speech model is configured (set WHISPER_MODEL in an image built with speech recognition)"));
    }

    let job_id = new_id("job");
    state
        .db
        .create_project(&project_id, &source.to_string_lossy());
    state
        .db
        .create_job(&job_id, "intake", Some(&project_id), callback.as_deref());
    let st = state.clone();
    let pid = project_id.clone();
    let provided = transcript.is_some();
    jobs::spawn(state.clone(), job_id.clone(), cid.0, move |ctx| {
        let started = Instant::now();
        if let Some(u) = &url {
            download(u, &source, st.cfg.max_upload_bytes)?;
        }
        ctx.progress(30);
        let fixture;
        let t: &dyn Transcriber = if provided {
            fixture = FixtureTranscriber::new(&words);
            &fixture
        } else {
            st.transcriber.as_deref().expect("checked above")
        };
        let taken = intake(&source, t, None, None)?;
        ctx.progress(90);
        let warnings = taken.warnings.clone();
        let project = taken.into_project();
        let words_n = project.transcript.words.len();
        let mut speakers: Vec<&str> = project
            .transcript
            .words
            .iter()
            .map(|w| w.speaker.as_str())
            .collect();
        speakers.sort();
        speakers.dedup();
        let result = json!({
            "project_id": pid,
            "duration_s": to_secs_ms(project.source.duration),
            "fps": format!("{}/{}", project.source.fps_num, project.source.fps_den),
            "variable_frame_rate": project.source.variable_frame_rate,
            "has_audio": project.source.has_audio,
            "source_sha256": project.source.sha256,
            "words": words_n,
            "speakers": speakers,
            "warnings": warnings,
        });
        st.db.save_project(
            &pid,
            &serde_json::to_value(&project).unwrap_or(Value::Null),
            &warnings,
        );
        Ok(Output {
            result,
            files: vec![],
            manifest: manifest(
                vec![
                    json!({"role": "speech_recognition", "name": transcriber_name(&st, provided)}),
                ],
                json!({"formats": ["mp4", "mov"]}),
                json!({"intake": started.elapsed().as_millis() as u64}),
                &warnings,
            ),
        })
    });
    Ok(accepted(job_id, Some(project_id)))
}

/// A project's state.
#[utoipa::path(get, path = "/api/v1/projects/{id}", tag = "projects", params(("id" = String, Path)),
    responses((status = 200, body = ProjectSummary), (status = 404, body = ErrorBody)))]
pub async fn get_project(State(state): S, Path(id): Path<String>) -> R<Json<ProjectSummary>> {
    let (ready, _, warnings) = state.db.project(&id).ok_or_else(|| {
        ApiError::not_found("PROJECT_NOT_FOUND", format!("there is no project {id}"))
    })?;
    if !ready {
        return Ok(Json(ProjectSummary {
            project_id: id,
            ready: false,
            duration_s: None,
            original_duration_s: None,
            timeline_hash: None,
            edits: 0,
            captions: 0,
            words: 0,
            pending_question: None,
            options: vec![],
            warnings,
        }));
    }
    let s = state.session(&id)?;
    let s = s.lock().unwrap_or_else(|e| e.into_inner());
    let tl = s.project.timeline().timeline;
    let (q, o) = s
        .pending()
        .map(|(q, o)| (Some(q.to_owned()), o))
        .unwrap_or((None, vec![]));
    Ok(Json(ProjectSummary {
        project_id: id,
        ready: true,
        duration_s: Some(to_secs_ms(tl.duration)),
        original_duration_s: Some(to_secs_ms(s.project.source.duration)),
        timeline_hash: Some(s.project.hash()),
        edits: s.project.active().len(),
        captions: tl.captions.len(),
        words: s.project.transcript.words.len(),
        pending_question: q,
        options: o,
        warnings,
    }))
}

/// Runs one step of the conversation on a worker thread, saves the project,
/// and answers with the outcome and its manifest.
async fn step(
    state: Arc<AppState>,
    id: String,
    f: impl FnOnce(&mut incubrix_nlu::Session) -> Reply + Send + 'static,
) -> R<Json<Value>> {
    let s = state.session(&id)?;
    let st = state.clone();
    let pid = id.clone();
    let out = tokio::task::spawn_blocking(move || {
        let started = Instant::now();
        let mut s = s.lock().unwrap_or_else(|e| e.into_inner());
        let reply = f(&mut s);
        let ms = started.elapsed().as_millis() as u64;
        let warnings = st.db.project(&pid).map(|p| p.2).unwrap_or_default();
        st.db.save_project(
            &pid,
            &serde_json::to_value(&s.project).unwrap_or(Value::Null),
            &warnings,
        );
        let mut v = serde_json::to_value(&reply.outcome).unwrap_or(Value::Null);
        v["project_id"] = json!(pid);
        v["action"] = match reply.action {
            Some(Action::Render) => json!("render"),
            None => Value::Null,
        };
        v["manifest"] = manifest(
            vec![parser_model(&s.parser_name())],
            json!({"time_policy": "current", "reader": reply.reader}),
            json!({"instruction": ms}),
            &reply.outcome.warnings,
        );
        v
    })
    .await
    .map_err(|e| ApiError::internal(e.to_string()))?;
    Ok(Json(out))
}

/// Send one instruction in plain English. Answers at once (the engine
/// takes milliseconds) with applied, needs_clarification or rejected.
#[utoipa::path(post, path = "/api/v1/projects/{id}/instructions", tag = "editing", params(("id" = String, Path)),
    request_body = Instruction,
    responses((status = 200, body = OutcomeDoc), (status = 404, body = ErrorBody), (status = 409, body = ErrorBody)))]
pub async fn instruct(State(state): S, Path(id): Path<String>, req: Request) -> R<Json<Value>> {
    let body: Instruction = json_body::<InstructionOpt>(req, false).await?.into()?;
    step(state, id, move |s| s.say(&body.say)).await
}

#[derive(Default, Deserialize)]
struct InstructionOpt {
    say: Option<String>,
}

impl InstructionOpt {
    fn into(self) -> R<Instruction> {
        match self.say.filter(|s| !s.trim().is_empty()) {
            Some(say) => Ok(Instruction { say }),
            None => Err(ApiError::bad("VALIDATION_ERROR", "`say` is required")
                .with(json!({"field": "say"}))),
        }
    }
}

#[derive(Default, Deserialize)]
struct AnswerOpt {
    answer: Option<String>,
}

/// Answer the waiting question.
#[utoipa::path(post, path = "/api/v1/projects/{id}/answers", tag = "editing", params(("id" = String, Path)),
    request_body = Answer,
    responses((status = 200, body = OutcomeDoc), (status = 404, body = ErrorBody)))]
pub async fn answer(State(state): S, Path(id): Path<String>, req: Request) -> R<Json<Value>> {
    let body: AnswerOpt = json_body(req, false).await?;
    let answer = body
        .answer
        .filter(|a| !a.trim().is_empty())
        .ok_or_else(|| {
            ApiError::bad("VALIDATION_ERROR", "`answer` is required")
                .with(json!({"field": "answer"}))
        })?;
    step(state, id, move |s| s.answer(&answer)).await
}

/// Undo the last instruction.
#[utoipa::path(post, path = "/api/v1/projects/{id}/undo", tag = "editing", params(("id" = String, Path)),
    responses((status = 200, body = OutcomeDoc), (status = 404, body = ErrorBody)))]
pub async fn undo(State(state): S, Path(id): Path<String>) -> R<Json<Value>> {
    step(state, id, |s| s.run("undo", Intent::Undo { steps: 1 })).await
}

/// Redo the instruction last undone.
#[utoipa::path(post, path = "/api/v1/projects/{id}/redo", tag = "editing", params(("id" = String, Path)),
    responses((status = 200, body = OutcomeDoc), (status = 404, body = ErrorBody)))]
pub async fn redo(State(state): S, Path(id): Path<String>) -> R<Json<Value>> {
    step(state, id, |s| s.run("redo", Intent::Redo { steps: 1 })).await
}

/// The edited timeline (JSON Schema: `schema/timeline.schema.json`).
#[utoipa::path(get, path = "/api/v1/projects/{id}/timeline", tag = "projects", params(("id" = String, Path)),
    responses((status = 200, description = "The timeline", body = Object), (status = 404, body = ErrorBody)))]
pub async fn timeline(State(state): S, Path(id): Path<String>) -> R<Json<Value>> {
    let s = state.session(&id)?;
    let s = s.lock().unwrap_or_else(|e| e.into_inner());
    Ok(Json(
        serde_json::to_value(s.project.timeline().timeline).unwrap_or(Value::Null),
    ))
}

/// The untouched source's facts and every transaction on it.
#[utoipa::path(get, path = "/api/v1/projects/{id}/history", tag = "projects", params(("id" = String, Path)),
    responses((status = 200, description = "The project: source, transcript, history", body = Object), (status = 404, body = ErrorBody)))]
pub async fn history(State(state): S, Path(id): Path<String>) -> R<Json<Value>> {
    let s = state.session(&id)?;
    let s = s.lock().unwrap_or_else(|e| e.into_inner());
    Ok(Json(
        serde_json::to_value(&s.project).unwrap_or(Value::Null),
    ))
}

/// The timeline as OpenTimelineIO.
#[utoipa::path(get, path = "/api/v1/projects/{id}/otio", tag = "projects", params(("id" = String, Path)),
    responses((status = 200, description = "OTIO Timeline.1 JSON", body = Object), (status = 404, body = ErrorBody)))]
pub async fn otio(State(state): S, Path(id): Path<String>) -> R<Json<Value>> {
    let s = state.session(&id)?;
    let s = s.lock().unwrap_or_else(|e| e.into_inner());
    Ok(Json(incubrix_core::otio::to_otio(&s.project, &id)))
}

/// Render the current timeline (a job). The result links to the video,
/// the timeline and the OTIO file, with the frame checks.
#[utoipa::path(post, path = "/api/v1/projects/{id}/renders", tag = "jobs", params(("id" = String, Path),
        ("Idempotency-Key" = Option<String>, Header, description = "Same key + same request = same job")),
    request_body(content = RenderRequest, description = "Optional"),
    responses((status = 202, body = Accepted), (status = 404, body = ErrorBody), (status = 409, body = ErrorBody)))]
pub async fn render(
    State(state): S,
    Extension(cid): Extension<CorrelationId>,
    Path(id): Path<String>,
    req: Request,
) -> R<Response> {
    let body: RenderRequestOpt = json_body(req, true).await?;
    let s = state.session(&id)?;
    let job_id = new_id("job");
    state
        .db
        .create_job(&job_id, "render", Some(&id), body.callback_url.as_deref());
    let dir = state.project_dir(&id).join("renders").join(&job_id);
    let jid = job_id.clone();
    let pid = id.clone();
    jobs::spawn(state.clone(), job_id.clone(), cid.0, move |ctx| {
        std::fs::create_dir_all(&dir).map_err(|e| ApiError::internal(e.to_string()))?;
        let project = s.lock().unwrap_or_else(|e| e.into_inner()).project.clone();
        ctx.progress(5);
        let video = dir.join("video.mp4");
        let opts = incubrix_media::render::RenderOptions::default();
        let report = incubrix_media::render::render(&project, &video, &opts)?;
        let tl = project.timeline().timeline;
        std::fs::write(
            dir.join("timeline.json"),
            serde_json::to_string_pretty(&tl).unwrap_or_default(),
        )
        .ok();
        std::fs::write(
            dir.join("timeline.otio"),
            incubrix_core::otio::to_otio(&project, &pid).to_string(),
        )
        .ok();
        let key = |f: &str| format!("renders/{jid}/{f}");
        Ok(Output {
            result: json!({
                "project_id": pid,
                "duration_s": to_secs_ms(tl.duration),
                "timeline_hash": incubrix_core::timeline_hash(&tl),
                "check": {
                    "length_diff_frames": report.check.length_diff_frames,
                    "av_offset_frames": report.check.av_offset_frames,
                    "av_length_diff_frames": report.check.av_length_diff_frames,
                    "ok": report.check.ok,
                },
                "source_unchanged": report.source_unchanged,
                "source_sha256": report.source_sha256,
                "captions_burned": report.burned_captions,
            }),
            files: vec![
                (key("video.mp4"), video, "video".into()),
                (
                    key("timeline.json"),
                    dir.join("timeline.json"),
                    "timeline".into(),
                ),
                (
                    key("timeline.otio"),
                    dir.join("timeline.otio"),
                    "otio".into(),
                ),
            ],
            manifest: manifest(
                vec![json!({"role": "encoder", "name": "ffmpeg libx264 + aac"})],
                json!({"crf": opts.crf, "preset": opts.preset, "frame_rate": format!("{}/{}", project.source.fps_num, project.source.fps_den), "constant_frame_rate": true}),
                json!({"render": (report.seconds * 1000.0) as u64}),
                &report.warnings,
            ),
        })
    });
    Ok(accepted(job_id, Some(id)))
}

#[derive(Default, Deserialize)]
struct RenderRequestOpt {
    callback_url: Option<String>,
}

/// Play a scripted session (the batch runner's call): every step's answer
/// in `results.json`, plus the final timeline, history, OTIO and, for a
/// "render" step, the video.
#[utoipa::path(post, path = "/api/v1/sessions", tag = "jobs",
    params(("Idempotency-Key" = Option<String>, Header, description = "Same key + same request = same job")),
    request_body(content = SessionRequest, content_type = "application/json"),
    responses((status = 202, body = Accepted), (status = 400, body = ErrorBody), (status = 422, body = ErrorBody)))]
pub async fn run_session(
    State(state): S,
    Extension(cid): Extension<CorrelationId>,
    req: Request,
) -> R<Response> {
    let job_id = new_id("job");
    let dir = state.cfg.data_dir.join("sessions").join(&job_id);
    std::fs::create_dir_all(&dir).map_err(|e| ApiError::internal(e.to_string()))?;
    let (mut session, video_url, transcript, speakers, callback, uploaded) = if is_multipart(&req) {
        let form = read_form(req, &state, &dir).await?;
        let text =
            form.fields.get("session").cloned().ok_or_else(|| {
                ApiError::bad("VALIDATION_ERROR", "the `session` field is required")
            })?;
        let session: Value = serde_yaml::from_str(&text)
            .map_err(|e| ApiError::bad("VALIDATION_ERROR", format!("session: {e}")))?;
        let json_field = |name: &str| -> R<Option<Value>> {
            form.fields
                .get(name)
                .map(|t| {
                    serde_json::from_str::<Value>(t)
                        .map_err(|e| ApiError::bad("VALIDATION_ERROR", format!("{name}: {e}")))
                })
                .transpose()
        };
        let transcript = json_field("transcript")?;
        let speakers = json_field("speakers")?;
        (
            session,
            form.fields.get("video_url").cloned(),
            transcript,
            speakers,
            form.fields.get("callback_url").cloned(),
            form.video.map(|v| v.1),
        )
    } else {
        let body: SessionRequestOpt = json_body(req, false).await?;
        let session = match body.session {
            Some(Value::String(yaml)) => serde_yaml::from_str(&yaml)
                .map_err(|e| ApiError::bad("VALIDATION_ERROR", format!("session: {e}")))?,
            Some(v @ Value::Object(_)) => v,
            _ => {
                return Err(ApiError::bad(
                    "VALIDATION_ERROR",
                    "`session` is required (an object or YAML text)",
                )
                .with(json!({"field": "session"})))
            }
        };
        (
            session,
            body.video_url,
            body.transcript,
            body.speakers,
            body.callback_url,
            None,
        )
    };
    if let Some(p) = &uploaded {
        session["video"] = json!(p.to_string_lossy());
    } else if let Some(u) = video_url {
        session["video"] = json!(u);
    }
    if let Some(t) = &transcript {
        write_transcript(t, &dir.join("transcript.json"))?;
        session["transcript"] = json!(dir.join("transcript.json").to_string_lossy());
    }
    if let Some(t) = &speakers {
        std::fs::write(dir.join("speakers.json"), t.to_string())
            .map_err(|e| ApiError::internal(e.to_string()))?;
        session["speakers"] = json!(dir.join("speakers.json").to_string_lossy());
    }
    // Files the session names must be here: a path on the caller's machine
    // means the caller forgot to send the file.
    for field in ["video", "transcript", "speakers"] {
        let Some(named) = session.get(field).and_then(Value::as_str) else {
            continue;
        };
        if named.contains("://") || dir.join(named).exists() {
            continue;
        }
        let how = if field == "video" {
            "upload it as the `video` part or give `video_url`"
        } else {
            "send its contents in the request's field of the same name"
        };
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            format!("the session's `{field}` names {named}, which is not on the server; {how}"),
        )
        .with(json!({"field": field})));
    }
    let described = session.get("source").is_some();
    if !described && session.get("transcript").is_none() && state.transcriber.is_none() {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "NO_TRANSCRIBER",
            "the session has no transcript and no speech model is configured",
        ));
    }
    let file: incubrix_cli::SessionFile = serde_json::from_value::<Value>(session.clone())
        .ok()
        .and_then(|v| serde_yaml::to_string(&v).ok())
        .and_then(|y| serde_yaml::from_str(&y).ok())
        .ok_or_else(|| {
            ApiError::bad(
                "VALIDATION_ERROR",
                "the session must have `steps: [{say, answer}]` and a `video` (or `source`)",
            )
        })?;
    if file.steps.is_empty() {
        return Err(ApiError::bad(
            "VALIDATION_ERROR",
            "the session has no steps",
        ));
    }
    std::fs::write(
        dir.join("session.yaml"),
        serde_yaml::to_string(&session).unwrap_or_default(),
    )
    .map_err(|e| ApiError::internal(e.to_string()))?;

    state
        .db
        .create_job(&job_id, "session", None, callback.as_deref());
    let st = state.clone();
    let jid = job_id.clone();
    jobs::spawn(state.clone(), job_id.clone(), cid.0, move |ctx| {
        let started = Instant::now();
        ctx.progress(5);
        let out = dir.join("out");
        let opts = incubrix_cli::RunOptions {
            out: Some(out.clone()),
            render: true,
            transcriber: st.transcriber.clone(),
        };
        let (results, _session) = incubrix_cli::run(&dir.join("session.yaml"), st.parser(), &opts)
            .map_err(|e| {
                ApiError::new(
                    StatusCode::UNPROCESSABLE_ENTITY,
                    "VALIDATION_ERROR",
                    e.to_string(),
                )
            })?;
        let key = |f: &str| format!("sessions/{jid}/{f}");
        let mut files = vec![
            (
                key("results.json"),
                out.join("results.json"),
                "results".to_owned(),
            ),
            (
                key("timeline.json"),
                out.join("timeline.json"),
                "timeline".to_owned(),
            ),
            (
                key("history.json"),
                out.join("history.json"),
                "history".to_owned(),
            ),
            (
                key("timeline.otio"),
                out.join("timeline.otio"),
                "otio".to_owned(),
            ),
        ];
        if let Some(v) = results.steps.iter().rev().find_map(|s| s.video.clone()) {
            files.push((key("video.mp4"), PathBuf::from(v), "video".into()));
        }
        let warnings: Vec<String> = results
            .steps
            .iter()
            .flat_map(|s| s.warnings.clone())
            .collect();
        Ok(Output {
            result: json!({
                "steps": results.steps.iter().map(|s| json!({"step": s.step, "say": s.say, "status": s.status, "duration_s": s.duration_s, "timeline_hash": s.timeline_hash})).collect::<Vec<_>>(),
                "final_timeline_hash": results.final_timeline_hash,
                "final_duration_s": results.final_duration_s,
                "source_sha256": results.source_sha256,
                "time_policy": "current",
            }),
            files,
            manifest: manifest(
                vec![parser_model(&results.parser)],
                json!({"time_policy": "current", "render": {"crf": 20, "preset": "veryfast"}}),
                json!({"session": started.elapsed().as_millis() as u64}),
                &warnings,
            ),
        })
    });
    Ok(accepted(job_id, None))
}

#[derive(Default, Deserialize)]
struct SessionRequestOpt {
    session: Option<Value>,
    video_url: Option<String>,
    transcript: Option<Value>,
    speakers: Option<Value>,
    callback_url: Option<String>,
}

/// A job's status, progress and result links.
#[utoipa::path(get, path = "/api/v1/jobs/{id}", tag = "jobs", params(("id" = String, Path)),
    responses((status = 200, body = Job), (status = 404, body = ErrorBody)))]
pub async fn get_job(State(state): S, Path(id): Path<String>) -> R<Json<Job>> {
    let mut job = state
        .db
        .job(&id)
        .ok_or_else(|| ApiError::not_found("JOB_NOT_FOUND", format!("there is no job {id}")))?;
    // Links are signed when read: a job looked at hours later (or replayed
    // by an Idempotency-Key) still hands out links that work.
    if let Some(result) = job.result.as_mut() {
        let files: Vec<(String, String)> = result["files"]
            .as_object()
            .map(|m| {
                m.iter()
                    .filter_map(|(f, k)| Some((f.clone(), k.as_str()?.to_owned())))
                    .collect()
            })
            .unwrap_or_default();
        for (field, key) in files {
            result["links"][field] = json!(state.storage.link(&key).await?);
        }
    }
    Ok(Json(job))
}

/// A stored file (local storage mode; with S3 the links are presigned).
#[utoipa::path(get, path = "/api/v1/files/{key}", tag = "jobs", params(("key" = String, Path)),
    responses((status = 200, description = "The file", content_type = "application/octet-stream"), (status = 404, body = ErrorBody)))]
pub async fn file(State(state): S, Path(key): Path<String>) -> R<Response> {
    if key.contains("..") {
        return Err(ApiError::not_found("FILE_NOT_FOUND", "no such file"));
    }
    let bytes =
        state.storage.get(&key).await.ok_or_else(|| {
            ApiError::not_found("FILE_NOT_FOUND", format!("no stored file {key}"))
        })?;
    let ct = match FsPath::new(&key).extension().and_then(|e| e.to_str()) {
        Some("mp4") => "video/mp4",
        Some("json") | Some("otio") => "application/json",
        _ => "application/octet-stream",
    };
    Ok(([(header::CONTENT_TYPE, ct)], bytes).into_response())
}
