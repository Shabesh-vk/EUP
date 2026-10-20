//! Files out (Integration Standard point 7): results go to an S3-compatible
//! store - SeaweedFS in docker compose - and come back as presigned links. In
//! local mode (development, tests) they go to a folder and the API serves
//! them at `/api/v1/files/{key}`.

use std::path::Path;
use std::sync::Arc;
use std::time::Duration;

use axum::http::Method;
use object_store::aws::{AmazonS3, AmazonS3Builder};
use object_store::local::LocalFileSystem;
use object_store::path::Path as Key;
use object_store::signer::Signer;
use object_store::{ObjectStore, PutPayload, WriteMultipart};
use tokio::io::AsyncReadExt;

use crate::config::{Config, StorageConfig};
use crate::error::ApiError;

/// Where results are kept.
pub struct Storage {
    store: Arc<dyn ObjectStore>,
    /// Signs links for the public endpoint (S3 mode only).
    signer: Option<AmazonS3>,
    public_url: String,
    ttl: Duration,
}

fn unavailable(e: impl std::fmt::Display) -> ApiError {
    ApiError::new(
        axum::http::StatusCode::SERVICE_UNAVAILABLE,
        "STORAGE_UNAVAILABLE",
        format!("the result store cannot be reached: {e}"),
    )
}

fn s3(
    endpoint: &str,
    bucket: &str,
    region: &str,
    key: &str,
    secret: &str,
) -> object_store::Result<AmazonS3> {
    AmazonS3Builder::new()
        .with_endpoint(endpoint)
        .with_bucket_name(bucket)
        .with_region(region)
        .with_access_key_id(key)
        .with_secret_access_key(secret)
        .with_allow_http(true)
        .with_virtual_hosted_style_request(false)
        .build()
}

impl Storage {
    /// The store the configuration names.
    pub fn new(cfg: &Config) -> Result<Self, ApiError> {
        let ttl = Duration::from_secs(cfg.link_ttl_s);
        match &cfg.storage {
            StorageConfig::Local => {
                let dir = cfg.data_dir.join("files");
                std::fs::create_dir_all(&dir).map_err(unavailable)?;
                Ok(Self {
                    store: Arc::new(LocalFileSystem::new_with_prefix(&dir).map_err(unavailable)?),
                    signer: None,
                    public_url: cfg.public_url.trim_end_matches('/').to_owned(),
                    ttl,
                })
            }
            StorageConfig::S3 {
                endpoint,
                public_endpoint,
                bucket,
                region,
                access_key,
                secret_key,
            } => Ok(Self {
                store: Arc::new(
                    s3(endpoint, bucket, region, access_key, secret_key).map_err(unavailable)?,
                ),
                signer: Some(
                    s3(public_endpoint, bucket, region, access_key, secret_key)
                        .map_err(unavailable)?,
                ),
                public_url: cfg.public_url.trim_end_matches('/').to_owned(),
                ttl,
            }),
        }
    }

    /// Whether the store answers.
    pub async fn ready(&self) -> bool {
        self.store.list_with_delimiter(None).await.is_ok()
    }

    /// Stores bytes under `key`.
    pub async fn put_bytes(&self, key: &str, bytes: Vec<u8>) -> Result<(), ApiError> {
        self.store
            .put(&Key::from(key), PutPayload::from(bytes))
            .await
            .map_err(unavailable)?;
        Ok(())
    }

    /// Stores a file under `key`, in parts so a large video never sits in memory.
    pub async fn put_file(&self, key: &str, path: &Path) -> Result<(), ApiError> {
        let upload = self
            .store
            .put_multipart(&Key::from(key))
            .await
            .map_err(unavailable)?;
        let mut w = WriteMultipart::new(upload);
        let mut f = tokio::fs::File::open(path)
            .await
            .map_err(|e| ApiError::internal(e.to_string()))?;
        let mut buf = vec![0u8; 8 * 1024 * 1024];
        loop {
            let n = f
                .read(&mut buf)
                .await
                .map_err(|e| ApiError::internal(e.to_string()))?;
            if n == 0 {
                break;
            }
            w.write(&buf[..n]);
        }
        w.finish().await.map_err(unavailable)?;
        Ok(())
    }

    /// A link a client can download `key` from.
    pub async fn link(&self, key: &str) -> Result<String, ApiError> {
        match &self.signer {
            Some(s) => Ok(s
                .signed_url(Method::GET, &Key::from(key), self.ttl)
                .await
                .map_err(unavailable)?
                .to_string()),
            None => Ok(format!("{}/api/v1/files/{key}", self.public_url)),
        }
    }

    /// A stored file's bytes (local mode's download route).
    pub async fn get(&self, key: &str) -> Option<bytes::Bytes> {
        self.store
            .get(&Key::from(key))
            .await
            .ok()?
            .bytes()
            .await
            .ok()
    }
}
