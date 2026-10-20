//! Every setting comes from the environment (Integration Standard point 6).
//! `.env.example` lists them all with their defaults.

use std::path::PathBuf;

/// Where results are stored.
#[derive(Clone, Debug, PartialEq)]
pub enum StorageConfig {
    /// A folder on disk, served by the API itself (development and tests).
    Local,
    /// An S3-compatible bucket (SeaweedFS in docker compose); links are presigned.
    S3 {
        /// Where the API reaches the store, e.g. `http://s3:9000`.
        endpoint: String,
        /// Where clients reach it; presigned links are signed for this host.
        public_endpoint: String,
        /// Bucket name.
        bucket: String,
        /// Region (SeaweedFS and MinIO ignore it).
        region: String,
        /// Access key.
        access_key: String,
        /// Secret key.
        secret_key: String,
    },
}

/// The service's settings.
#[derive(Clone, Debug)]
pub struct Config {
    /// Address to listen on.
    pub bind: String,
    /// Where the database, uploads and working files live.
    pub data_dir: PathBuf,
    /// Base URL clients use to reach this API (for links in local storage mode).
    pub public_url: String,
    /// Result storage.
    pub storage: StorageConfig,
    /// Lifetime of presigned links, seconds.
    pub link_ttl_s: u64,
    /// Secret for signing job callbacks (HMAC-SHA256); callbacks are unsigned when empty.
    pub callback_secret: String,
    /// ggml whisper model for speech recognition (needs the `whisper` feature).
    pub whisper_model: Option<PathBuf>,
    /// Largest accepted upload, bytes.
    pub max_upload_bytes: usize,
    /// When set, `/api/v1` needs `Authorization: Bearer <token>`.
    pub api_token: Option<String>,
    /// Requests per minute per client; 0 turns the limit off.
    pub rate_limit_per_minute: u32,
    /// Take the client from `X-Forwarded-For` (only behind a proxy you run).
    pub trust_forwarded: bool,
}

fn var(k: &str) -> Option<String> {
    std::env::var(k).ok().filter(|v| !v.trim().is_empty())
}

impl Config {
    /// Reads the environment.
    pub fn from_env() -> Self {
        let storage = match var("STORAGE")
            .unwrap_or_else(|| "local".into())
            .to_lowercase()
            .as_str()
        {
            "s3" | "minio" => {
                let endpoint = var("S3_ENDPOINT").unwrap_or_else(|| "http://localhost:9000".into());
                StorageConfig::S3 {
                    public_endpoint: var("S3_PUBLIC_ENDPOINT").unwrap_or_else(|| endpoint.clone()),
                    endpoint,
                    bucket: var("S3_BUCKET").unwrap_or_else(|| "incubrix".into()),
                    region: var("S3_REGION").unwrap_or_else(|| "us-east-1".into()),
                    access_key: var("S3_ACCESS_KEY").unwrap_or_else(|| "incubrix".into()),
                    secret_key: var("S3_SECRET_KEY").unwrap_or_else(|| "incubrix-secret".into()),
                }
            }
            _ => StorageConfig::Local,
        };
        let bind = var("API_BIND").unwrap_or_else(|| "0.0.0.0:8080".into());
        Self {
            public_url: var("PUBLIC_URL").unwrap_or_else(|| {
                format!(
                    "http://localhost:{}",
                    bind.rsplit(':').next().unwrap_or("8080")
                )
            }),
            bind,
            data_dir: PathBuf::from(var("DATA_DIR").unwrap_or_else(|| "./data".into())),
            storage,
            link_ttl_s: var("LINK_TTL_SECONDS")
                .and_then(|v| v.parse().ok())
                .unwrap_or(3600),
            callback_secret: var("CALLBACK_SECRET").unwrap_or_default(),
            whisper_model: var("WHISPER_MODEL").map(PathBuf::from),
            max_upload_bytes: var("MAX_UPLOAD_MB")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(2048)
                * 1024
                * 1024,
            api_token: var("API_TOKEN"),
            rate_limit_per_minute: var("RATE_LIMIT_PER_MINUTE")
                .and_then(|v| v.parse().ok())
                .unwrap_or(120),
            trust_forwarded: var("TRUST_FORWARDED").is_some_and(|v| v == "1" || v == "true"),
        }
    }

    /// Settings for tests: everything under `dir`, local storage.
    pub fn for_tests(dir: PathBuf) -> Self {
        Self {
            bind: "127.0.0.1:0".into(),
            data_dir: dir,
            public_url: "http://localhost".into(),
            storage: StorageConfig::Local,
            link_ttl_s: 3600,
            callback_secret: "test-secret".into(),
            whisper_model: None,
            max_upload_bytes: 512 * 1024 * 1024,
            api_token: None,
            rate_limit_per_minute: 0,
            trust_forwarded: false,
        }
    }
}
