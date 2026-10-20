//! The IncuBrix editing engine as an HTTP service.
//!
//! Every route is under `/api/v1/` and is described by the OpenAPI document
//! generated from this code (`openapi.yaml`). Slow work - intake,
//! rendering, whole sessions - runs as background jobs; instructions are
//! answered at once. See the README for the Integration Standard points.

pub mod config;
pub mod db;
pub mod error;
pub mod jobs;
pub mod manifest;
pub mod routes;
pub mod storage;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use axum::body::{to_bytes, Body};
use axum::extract::{DefaultBodyLimit, Request, State};
use axum::http::{HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::Router;
use incubrix_nlu::{Parser, RulesParser, Session};
use sha2::{Digest, Sha256};

use crate::config::Config;
use crate::db::Db;
use crate::error::ApiError;
use crate::storage::Storage;

/// One open editing conversation.
pub type SharedSession = Arc<Mutex<Session>>;

/// Everything the handlers share.
pub struct AppState {
    /// Settings.
    pub cfg: Config,
    /// Jobs, projects, idempotency keys.
    pub db: Db,
    /// Result files.
    pub storage: Storage,
    /// Conversations in memory, by project id (rebuilt from the database).
    pub sessions: Mutex<HashMap<String, SharedSession>>,
    /// Requests with an Idempotency-Key in flight, so a retry waits for the first.
    pub in_flight: Mutex<HashMap<String, Arc<tokio::sync::Mutex<()>>>>,
    /// Hears speech, when a model is configured.
    pub transcriber: Option<incubrix_cli::SharedTranscriber>,
    /// Requests per client in the current minute: (minute, count).
    pub rate: Mutex<HashMap<String, (u64, u32)>>,
}

impl AppState {
    /// Opens the database and the store.
    pub fn new(cfg: Config) -> Result<Self, ApiError> {
        std::fs::create_dir_all(&cfg.data_dir).map_err(|e| ApiError::internal(e.to_string()))?;
        let db = Db::open(&cfg.data_dir.join("incubrix.sqlite"))
            .map_err(|e| ApiError::internal(e.to_string()))?;
        let storage = Storage::new(&cfg)?;
        let transcriber = transcriber(&cfg);
        Ok(Self {
            cfg,
            db,
            storage,
            sessions: Mutex::new(HashMap::new()),
            in_flight: Mutex::new(HashMap::new()),
            transcriber,
            rate: Mutex::new(HashMap::new()),
        })
    }

    /// Where a project's files live.
    pub fn project_dir(&self, id: &str) -> PathBuf {
        self.cfg.data_dir.join("projects").join(id)
    }

    /// The parser the service uses: deterministic rules unless
    /// `NLU_PROVIDER` asks for a model.
    pub fn parser(&self) -> Box<dyn Parser> {
        match std::env::var("NLU_PROVIDER") {
            Ok(p) if !p.trim().is_empty() => incubrix_nlu::parser_from_env(),
            _ => Box::new(RulesParser),
        }
    }

    /// The conversation on a project, from memory or the database.
    pub fn session(&self, id: &str) -> Result<SharedSession, ApiError> {
        if let Some(s) = self
            .sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(id)
        {
            return Ok(s.clone());
        }
        let (ready, project, _) = self.db.project(id).ok_or_else(|| {
            ApiError::not_found("PROJECT_NOT_FOUND", format!("there is no project {id}"))
        })?;
        let project = match (ready, project) {
            (true, Some(p)) => {
                serde_json::from_value(p).map_err(|e| ApiError::internal(e.to_string()))?
            }
            _ => {
                return Err(ApiError::new(
                    StatusCode::CONFLICT,
                    "PROJECT_NOT_READY",
                    "the project is still being taken in; check its intake job",
                ))
            }
        };
        let s = Arc::new(Mutex::new(Session::new(project, self.parser())));
        self.sessions
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(id.to_owned(), s.clone());
        Ok(s)
    }
}

#[cfg(feature = "whisper")]
fn transcriber(cfg: &Config) -> Option<incubrix_cli::SharedTranscriber> {
    let model = cfg.whisper_model.as_ref().filter(|m| m.is_file())?;
    Some(Arc::new(incubrix_media::whisper::WhisperRs::new(
        model,
        Some("en".into()),
    )))
}

#[cfg(not(feature = "whisper"))]
fn transcriber(_cfg: &Config) -> Option<incubrix_cli::SharedTranscriber> {
    None
}

/// `X-Correlation-Id`: taken from the request or made up, put on the
/// response and on every log line of the request (point 8).
/// Access token and rate limit for a public deployment. Health, readiness,
/// the API document and result links (unguessable keys) stay open.
async fn guard(State(state): State<Arc<AppState>>, req: Request, next: Next) -> Response {
    let path = req.uri().path();
    let open = !path.starts_with("/api/v1/")
        || path == "/api/v1/openapi.json"
        || path.starts_with("/api/v1/files/");
    if open {
        return next.run(req).await;
    }
    if let Some(token) = &state.cfg.api_token {
        let given = req
            .headers()
            .get(axum::http::header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "));
        if given != Some(token.as_str()) {
            return ApiError::new(
                StatusCode::UNAUTHORIZED,
                "UNAUTHORIZED",
                "send Authorization: Bearer <API_TOKEN>",
            )
            .into_response();
        }
    }
    let limit = state.cfg.rate_limit_per_minute;
    if limit > 0 {
        let forwarded = state
            .cfg
            .trust_forwarded
            .then(|| req.headers().get("x-forwarded-for"))
            .flatten()
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.split(',').next())
            .map(|v| v.trim().to_owned());
        let client = forwarded
            .or_else(|| {
                req.extensions()
                    .get::<axum::extract::ConnectInfo<std::net::SocketAddr>>()
                    .map(|c| c.0.ip().to_string())
            })
            .unwrap_or_else(|| "local".into());
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let minute = now / 60;
        let over = {
            let mut rate = state.rate.lock().unwrap_or_else(|e| e.into_inner());
            rate.retain(|_, (m, _)| *m == minute);
            let entry = rate.entry(client).or_insert((minute, 0));
            entry.1 += 1;
            entry.1 > limit
        };
        if over {
            let mut resp = ApiError::new(
                StatusCode::TOO_MANY_REQUESTS,
                "RATE_LIMITED",
                format!("more than {limit} requests this minute"),
            )
            .into_response();
            if let Ok(v) = HeaderValue::from_str(&(60 - now % 60).to_string()) {
                resp.headers_mut().insert("retry-after", v);
            }
            return resp;
        }
    }
    next.run(req).await
}

async fn correlation(mut req: Request, next: Next) -> Response {
    let id = req
        .headers()
        .get("x-correlation-id")
        .and_then(|v| v.to_str().ok())
        .filter(|v| !v.is_empty() && v.len() <= 128)
        .map(str::to_owned)
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    req.extensions_mut().insert(CorrelationId(id.clone()));
    let (method, path) = (req.method().clone(), req.uri().path().to_owned());
    let started = std::time::Instant::now();
    let mut resp = next.run(req).await;
    tracing::info!(
        correlation_id = %id,
        method = %method,
        path = %path,
        status = resp.status().as_u16(),
        ms = started.elapsed().as_millis() as u64,
        "request"
    );
    if let Ok(v) = HeaderValue::from_str(&id) {
        resp.headers_mut().insert("x-correlation-id", v);
    }
    resp
}

/// The request's correlation id.
#[derive(Clone, Debug)]
pub struct CorrelationId(pub String);

/// `Idempotency-Key` on a POST (point 4): the same key with the same
/// request gets the first response again, and the work is never repeated;
/// the same key with a different request is refused.
async fn idempotency(State(state): State<Arc<AppState>>, req: Request, next: Next) -> Response {
    let key = req
        .headers()
        .get("idempotency-key")
        .and_then(|v| v.to_str().ok())
        .map(str::to_owned);
    let (Some(key), true) = (key, req.method() == Method::POST) else {
        return next.run(req).await;
    };
    let (parts, body) = req.into_parts();
    let Ok(bytes) = to_bytes(body, state.cfg.max_upload_bytes).await else {
        return ApiError::new(
            StatusCode::PAYLOAD_TOO_LARGE,
            "PAYLOAD_TOO_LARGE",
            "the request is larger than MAX_UPLOAD_MB",
        )
        .into_response();
    };
    let mut h = Sha256::new();
    h.update(parts.method.as_str());
    h.update(parts.uri.path());
    h.update(&bytes);
    let fingerprint = hex::encode(h.finalize());

    // One request per key at a time: a retry waits for the first to finish.
    let lock = state
        .in_flight
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .entry(key.clone())
        .or_insert_with(|| Arc::new(tokio::sync::Mutex::new(())))
        .clone();
    let _guard = lock.lock().await;
    if let Some(r) = state.db.remembered(&key) {
        if r.fingerprint != fingerprint {
            return ApiError::new(
                StatusCode::CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "this Idempotency-Key was already used with a different request",
            )
            .with(serde_json::json!({"key": key}))
            .into_response();
        }
        let mut resp = (
            StatusCode::from_u16(r.status).unwrap_or(StatusCode::OK),
            axum::Json(r.body),
        )
            .into_response();
        resp.headers_mut()
            .insert("idempotent-replayed", HeaderValue::from_static("true"));
        return resp;
    }
    let resp = next
        .run(Request::from_parts(parts, Body::from(bytes)))
        .await;
    let status = resp.status();
    let (rparts, rbody) = resp.into_parts();
    let rbytes = to_bytes(rbody, usize::MAX).await.unwrap_or_default();
    // Server errors are not remembered: a retry should get a fresh try.
    if !status.is_server_error() {
        if let Ok(v) = serde_json::from_slice::<serde_json::Value>(&rbytes) {
            state.db.remember(&key, &fingerprint, status.as_u16(), &v);
        }
    }
    Response::from_parts(rparts, Body::from(rbytes))
}

/// The service's router.
pub fn app(state: Arc<AppState>) -> Router {
    let limit = state.cfg.max_upload_bytes;
    Router::new()
        .route("/health", get(routes::health))
        .route("/ready", get(routes::ready))
        .route("/api/v1/openapi.json", get(routes::openapi_json))
        .route("/api/v1/projects", post(routes::create_project))
        .route("/api/v1/projects/{id}", get(routes::get_project))
        .route("/api/v1/projects/{id}/instructions", post(routes::instruct))
        .route("/api/v1/projects/{id}/answers", post(routes::answer))
        .route("/api/v1/projects/{id}/undo", post(routes::undo))
        .route("/api/v1/projects/{id}/redo", post(routes::redo))
        .route("/api/v1/projects/{id}/timeline", get(routes::timeline))
        .route("/api/v1/projects/{id}/history", get(routes::history))
        .route("/api/v1/projects/{id}/otio", get(routes::otio))
        .route("/api/v1/projects/{id}/renders", post(routes::render))
        .route("/api/v1/sessions", post(routes::run_session))
        .route("/api/v1/jobs/{id}", get(routes::get_job))
        .route("/api/v1/files/{*key}", get(routes::file))
        .fallback(routes::not_found)
        .layer(middleware::from_fn_with_state(state.clone(), idempotency))
        .layer(middleware::from_fn_with_state(state.clone(), guard))
        .layer(middleware::from_fn(correlation))
        .layer(DefaultBodyLimit::max(limit))
        .with_state(state)
}
