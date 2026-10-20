//! The service's own records in SQLite: jobs, projects and idempotency keys.
//! Short synchronous calls behind a mutex - every call is a single row.

use std::path::Path;
use std::sync::Mutex;

use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;

/// A job's state (Integration Standard point 3).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    /// Waiting to start.
    Queued,
    /// Working.
    Running,
    /// Done; see `result`.
    Succeeded,
    /// Failed; see `error`.
    Failed,
}

impl JobStatus {
    fn as_str(self) -> &'static str {
        match self {
            JobStatus::Queued => "queued",
            JobStatus::Running => "running",
            JobStatus::Succeeded => "succeeded",
            JobStatus::Failed => "failed",
        }
    }

    fn parse(s: &str) -> Self {
        match s {
            "running" => JobStatus::Running,
            "succeeded" => JobStatus::Succeeded,
            "failed" => JobStatus::Failed,
            _ => JobStatus::Queued,
        }
    }
}

/// A background job.
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct Job {
    /// Id.
    pub job_id: String,
    /// `intake`, `render` or `session`.
    pub kind: String,
    /// Where it is.
    pub status: JobStatus,
    /// 0 to 100.
    pub progress: u8,
    /// The project it belongs to.
    pub project_id: Option<String>,
    /// Links and figures when it succeeded.
    #[schema(value_type = Object)]
    pub result: Option<Value>,
    /// The error when it failed (same shape as an error response's `error`).
    #[schema(value_type = Object)]
    pub error: Option<Value>,
    /// What produced the result: models, settings, timings, licences.
    #[schema(value_type = Object)]
    pub manifest: Option<Value>,
    /// Seconds since the epoch.
    pub created_at: u64,
    /// Seconds since the epoch.
    pub updated_at: u64,
}

/// A stored idempotent response.
#[derive(Clone, Debug)]
pub struct Remembered {
    /// Hash of method, path and body of the first request.
    pub fingerprint: String,
    /// Status sent.
    pub status: u16,
    /// Body sent.
    pub body: Value,
}

/// The database.
pub struct Db {
    conn: Mutex<Connection>,
}

fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

impl Db {
    /// Opens (and creates) the database at `path`.
    pub fn open(path: &Path) -> rusqlite::Result<Self> {
        let conn = Connection::open(path)?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL,
                project_id TEXT, result TEXT, error TEXT, manifest TEXT, callback_url TEXT,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, project TEXT, source_path TEXT, ready INTEGER NOT NULL DEFAULT 0,
                warnings TEXT, created_at INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS idempotency (
                key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status INTEGER NOT NULL, body TEXT NOT NULL,
                created_at INTEGER NOT NULL);",
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    fn c(&self) -> std::sync::MutexGuard<'_, Connection> {
        self.conn.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Whether the database answers.
    pub fn ping(&self) -> bool {
        self.c()
            .query_row("SELECT 1", [], |r| r.get::<_, i64>(0))
            .is_ok()
    }

    /// Records a new queued job.
    pub fn create_job(
        &self,
        id: &str,
        kind: &str,
        project_id: Option<&str>,
        callback: Option<&str>,
    ) {
        let t = now() as i64;
        let _ = self.c().execute(
            "INSERT INTO jobs (id, kind, status, progress, project_id, callback_url, created_at, updated_at) VALUES (?1, ?2, 'queued', 0, ?3, ?4, ?5, ?5)",
            params![id, kind, project_id, callback, t],
        );
    }

    /// Moves a job along.
    pub fn progress(&self, id: &str, status: JobStatus, progress: u8) {
        let _ = self.c().execute(
            "UPDATE jobs SET status = ?2, progress = ?3, updated_at = ?4 WHERE id = ?1",
            params![id, status.as_str(), progress as i64, now() as i64],
        );
    }

    /// Ends a job.
    pub fn finish(&self, id: &str, result: Result<Value, Value>, manifest: &Value) {
        let (status, ok, err) = match &result {
            Ok(v) => ("succeeded", Some(v.to_string()), None),
            Err(e) => ("failed", None, Some(e.to_string())),
        };
        let _ = self.c().execute(
            "UPDATE jobs SET status = ?2, progress = ?3, result = ?4, error = ?5, manifest = ?6, updated_at = ?7 WHERE id = ?1",
            params![id, status, if ok.is_some() { 100 } else { 0 }, ok, err, manifest.to_string(), now() as i64],
        );
    }

    /// The job's callback URL, if one was given.
    pub fn callback(&self, id: &str) -> Option<String> {
        self.c()
            .query_row("SELECT callback_url FROM jobs WHERE id = ?1", [id], |r| {
                r.get::<_, Option<String>>(0)
            })
            .ok()
            .flatten()
    }

    /// A job.
    pub fn job(&self, id: &str) -> Option<Job> {
        let parse = |s: Option<String>| s.and_then(|s| serde_json::from_str(&s).ok());
        self.c()
            .query_row(
                "SELECT id, kind, status, progress, project_id, result, error, manifest, created_at, updated_at FROM jobs WHERE id = ?1",
                [id],
                |r| {
                    Ok(Job {
                        job_id: r.get(0)?,
                        kind: r.get(1)?,
                        status: JobStatus::parse(&r.get::<_, String>(2)?),
                        progress: r.get::<_, i64>(3)? as u8,
                        project_id: r.get(4)?,
                        result: parse(r.get(5)?),
                        error: parse(r.get(6)?),
                        manifest: parse(r.get(7)?),
                        created_at: r.get::<_, i64>(8)? as u64,
                        updated_at: r.get::<_, i64>(9)? as u64,
                    })
                },
            )
            .optional()
            .ok()
            .flatten()
    }

    /// Records a project being taken in.
    pub fn create_project(&self, id: &str, source_path: &str) {
        let _ = self.c().execute(
            "INSERT INTO projects (id, source_path, ready, created_at) VALUES (?1, ?2, 0, ?3)",
            params![id, source_path, now() as i64],
        );
    }

    /// Stores a project's edit (after intake and after every change).
    pub fn save_project(&self, id: &str, project: &Value, warnings: &[String]) {
        let _ = self.c().execute(
            "UPDATE projects SET project = ?2, ready = 1, warnings = ?3 WHERE id = ?1",
            params![
                id,
                project.to_string(),
                serde_json::to_string(warnings).unwrap_or_default()
            ],
        );
    }

    /// A project: (ready, project json, intake warnings).
    pub fn project(&self, id: &str) -> Option<(bool, Option<Value>, Vec<String>)> {
        self.c()
            .query_row(
                "SELECT ready, project, warnings FROM projects WHERE id = ?1",
                [id],
                |r| {
                    Ok((
                        r.get::<_, i64>(0)? != 0,
                        r.get::<_, Option<String>>(1)?
                            .and_then(|s| serde_json::from_str(&s).ok()),
                        r.get::<_, Option<String>>(2)?
                            .and_then(|s| serde_json::from_str(&s).ok())
                            .unwrap_or_default(),
                    ))
                },
            )
            .optional()
            .ok()
            .flatten()
    }

    /// The response stored for an idempotency key.
    pub fn remembered(&self, key: &str) -> Option<Remembered> {
        self.c()
            .query_row(
                "SELECT fingerprint, status, body FROM idempotency WHERE key = ?1",
                [key],
                |r| {
                    Ok(Remembered {
                        fingerprint: r.get(0)?,
                        status: r.get::<_, i64>(1)? as u16,
                        body: serde_json::from_str(&r.get::<_, String>(2)?).unwrap_or(Value::Null),
                    })
                },
            )
            .optional()
            .ok()
            .flatten()
    }

    /// Stores the response for an idempotency key; the first one wins.
    pub fn remember(&self, key: &str, fingerprint: &str, status: u16, body: &Value) {
        let _ = self.c().execute(
            "INSERT OR IGNORE INTO idempotency (key, fingerprint, status, body, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![key, fingerprint, status as i64, body.to_string(), now() as i64],
        );
    }
}
