//! Errors as JSON: `{"error": {"code", "message", "retryable", "details"}}`
//! (Integration Standard point 5). Codes are UPPER_SNAKE_CASE and listed in
//! the README.
//!
//! An editing answer of `rejected` is not an error: it is a normal `200`
//! with the engine's outcome. Errors are for requests the service cannot
//! take at all.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::Serialize;
use serde_json::{json, Value};
use utoipa::ToSchema;

/// The error body.
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct ErrorBody {
    /// The error.
    pub error: ErrorDetail,
}

/// One error.
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct ErrorDetail {
    /// UPPER_SNAKE_CASE code.
    pub code: String,
    /// For people.
    pub message: String,
    /// Whether the same request may succeed later.
    pub retryable: bool,
    /// Anything that helps (field names, limits).
    #[schema(value_type = Object)]
    pub details: Value,
}

/// An error the API returns.
#[derive(Clone, Debug)]
pub struct ApiError {
    /// HTTP status.
    pub status: StatusCode,
    /// The body's error.
    pub detail: ErrorDetail,
}

impl ApiError {
    /// An error with no details.
    pub fn new(status: StatusCode, code: &str, message: impl Into<String>) -> Self {
        let retryable = status.is_server_error() || status == StatusCode::TOO_MANY_REQUESTS;
        Self {
            status,
            detail: ErrorDetail {
                code: code.into(),
                message: message.into(),
                retryable,
                details: json!({}),
            },
        }
    }

    /// Adds details.
    pub fn with(mut self, details: Value) -> Self {
        self.detail.details = details;
        self
    }

    /// 400.
    pub fn bad(code: &str, message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, code, message)
    }

    /// 404.
    pub fn not_found(code: &str, message: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, code, message)
    }

    /// 500, retryable.
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL", message)
    }

    /// The body as JSON.
    pub fn body(&self) -> Value {
        json!({"error": self.detail})
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(self.body())).into_response()
    }
}

impl From<incubrix_media::MediaError> for ApiError {
    fn from(e: incubrix_media::MediaError) -> Self {
        let status = match e {
            incubrix_media::MediaError::Unsupported(_) | incubrix_media::MediaError::NoVideo => {
                StatusCode::UNPROCESSABLE_ENTITY
            }
            incubrix_media::MediaError::BadData(_) => StatusCode::UNPROCESSABLE_ENTITY,
            _ => StatusCode::INTERNAL_SERVER_ERROR,
        };
        Self::new(status, e.code(), e.to_string())
    }
}

/// Every code the API returns, for the README and the OpenAPI description.
pub const CODES: &[(&str, &str)] = &[
    (
        "VALIDATION_ERROR",
        "The request body or a parameter is malformed.",
    ),
    ("ROUTE_NOT_FOUND", "No such route."),
    (
        "UNAUTHORIZED",
        "API_TOKEN is set and the request has no matching Bearer token.",
    ),
    (
        "RATE_LIMITED",
        "Too many requests from this client; retry after Retry-After seconds.",
    ),
    ("PROJECT_NOT_FOUND", "No project with that id."),
    (
        "PROJECT_NOT_READY",
        "The project's intake job has not finished.",
    ),
    ("JOB_NOT_FOUND", "No job with that id."),
    ("FILE_NOT_FOUND", "No stored file with that key."),
    (
        "IDEMPOTENCY_KEY_REUSED",
        "The Idempotency-Key was used with a different request.",
    ),
    (
        "PAYLOAD_TOO_LARGE",
        "The upload is larger than MAX_UPLOAD_MB.",
    ),
    ("DOWNLOAD_FAILED", "The video URL could not be fetched."),
    (
        "NO_TRANSCRIBER",
        "No transcript was given and no speech model is configured.",
    ),
    ("UNSUPPORTED_FORMAT", "Only MP4 and MOV are accepted."),
    ("NO_VIDEO_STREAM", "The file has no picture."),
    ("MEDIA_TOOL_FAILED", "ffmpeg or ffprobe failed."),
    (
        "RENDER_MISMATCH",
        "A render failed its length or A/V check.",
    ),
    ("SOURCE_CHANGED", "The source file changed since intake."),
    ("STORAGE_UNAVAILABLE", "The result store cannot be reached."),
    ("INTERNAL", "Anything else; retryable."),
];
