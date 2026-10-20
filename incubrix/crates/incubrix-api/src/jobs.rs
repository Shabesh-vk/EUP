//! Background jobs (Integration Standard point 3): anything that can take
//! more than two seconds - intake, render, a whole session - answers `202`
//! with a `job_id` at once and runs here. `GET /api/v1/jobs/{id}` shows
//! status, progress 0-100 and result links; a `callback_url` is told when
//! the job ends, signed with HMAC-SHA256 in `X-IncuBrix-Signature`.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::Sha256;
use tracing::Instrument;

use crate::db::JobStatus;
use crate::error::ApiError;
use crate::AppState;

/// What a job's work hands back.
pub struct Output {
    /// The result body (links are added to it).
    pub result: Value,
    /// Files to store: (key, local path, field in `result.links`).
    pub files: Vec<(String, PathBuf, String)>,
    /// The manifest, before timings are added.
    pub manifest: Value,
}

/// What a running job can do.
#[derive(Clone)]
pub struct Ctx {
    state: Arc<AppState>,
    /// The job.
    pub job_id: String,
}

impl Ctx {
    /// Reports progress (0-100).
    pub fn progress(&self, p: u8) {
        self.state
            .db
            .progress(&self.job_id, JobStatus::Running, p.min(99));
    }

    /// The service state.
    pub fn state(&self) -> &AppState {
        &self.state
    }
}

/// Starts `work` in the background as job `job_id` (already recorded).
pub fn spawn<F>(state: Arc<AppState>, job_id: String, correlation_id: String, work: F)
where
    F: FnOnce(&Ctx) -> Result<Output, ApiError> + Send + 'static,
{
    let span = tracing::info_span!("job", job_id = %job_id, correlation_id = %correlation_id);
    tokio::spawn(async move {
        let started = Instant::now();
        state.db.progress(&job_id, JobStatus::Running, 1);
        tracing::info!(job_id = %job_id, correlation_id = %correlation_id, "job started");
        let ctx = Ctx { state: state.clone(), job_id: job_id.clone() };
        let worked = tokio::task::spawn_blocking(move || work(&ctx))
            .await
            .unwrap_or_else(|e| Err(ApiError::internal(format!("the job stopped unexpectedly: {e}"))));
        let finished = match worked {
            Ok(mut out) => {
                // Files out: store each, put its link in the result.
                let mut links = serde_json::Map::new();
                // Keys too: links expire, so GET /jobs/{id} signs new ones.
                let mut keys = serde_json::Map::new();
                let mut failed = None;
                for (key, path, field) in &out.files {
                    if !path.is_file() {
                        continue;
                    }
                    match state.storage.put_file(key, path).await {
                        Ok(()) => match state.storage.link(key).await {
                            Ok(url) => {
                                links.insert(field.clone(), json!(url));
                                keys.insert(field.clone(), json!(key));
                            }
                            Err(e) => failed = Some(e),
                        },
                        Err(e) => failed = Some(e),
                    }
                }
                match failed {
                    Some(e) => Err(e),
                    None => {
                        out.result["links"] = Value::Object(links);
                        out.result["files"] = Value::Object(keys);
                        Ok(out)
                    }
                }
            }
            Err(e) => Err(e),
        };
        let total_ms = started.elapsed().as_millis() as u64;
        match finished {
            Ok(out) => {
                let mut manifest = out.manifest;
                manifest["timings_ms"]["total"] = json!(total_ms);
                state.db.finish(&job_id, Ok(out.result), &manifest);
                tracing::info!(job_id = %job_id, correlation_id = %correlation_id, ms = total_ms, "job succeeded");
            }
            Err(e) => {
                let manifest = crate::manifest::manifest(vec![], json!({}), json!({"total": total_ms}), &[]);
                state.db.finish(&job_id, Err(json!(e.detail)), &manifest);
                tracing::warn!(job_id = %job_id, correlation_id = %correlation_id, code = %e.detail.code, error = %e.detail.message, "job failed");
            }
        }
        if let (Some(url), Some(job)) = (state.db.callback(&job_id), state.db.job(&job_id)) {
            let secret = state.cfg.callback_secret.clone();
            let body = serde_json::to_string(&job).unwrap_or_default();
            let cid = correlation_id.clone();
            let _ = tokio::task::spawn_blocking(move || callback(&url, &secret, &body, &cid)).await;
        }
    }.instrument(span));
}

/// `sha256=<hex>` of HMAC-SHA256(secret, body).
pub fn signature(secret: &str, body: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("any key length");
    mac.update(body.as_bytes());
    format!("sha256={}", hex::encode(mac.finalize().into_bytes()))
}

/// Tells the caller the job ended; three tries, backing off.
fn callback(url: &str, secret: &str, body: &str, correlation_id: &str) {
    for attempt in 0..3 {
        let mut req = ureq::post(url)
            .set("content-type", "application/json")
            .set("X-Correlation-Id", correlation_id)
            .timeout(std::time::Duration::from_secs(10));
        if !secret.is_empty() {
            req = req.set("X-IncuBrix-Signature", &signature(secret, body));
        }
        match req.send_string(body) {
            Ok(_) => {
                tracing::info!(url, "callback delivered");
                return;
            }
            Err(e) => {
                tracing::warn!(url, attempt, error = %e, "callback failed");
                std::thread::sleep(std::time::Duration::from_millis(500 * (1 << attempt)));
            }
        }
    }
}
