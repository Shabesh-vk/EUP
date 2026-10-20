//! A public deployment: an optional access token and a per-client rate limit.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use incubrix_api::config::Config;
use incubrix_api::{app, AppState};
use serde_json::Value;
use tower::ServiceExt;

fn service(token: Option<&str>, per_minute: u32) -> axum::Router {
    let dir = std::env::temp_dir().join(format!("incubrix-guard-{}", uuid::Uuid::new_v4()));
    let mut cfg = Config::for_tests(dir);
    cfg.api_token = token.map(str::to_owned);
    cfg.rate_limit_per_minute = per_minute;
    app(Arc::new(AppState::new(cfg).unwrap()))
}

async fn get(
    app: &axum::Router,
    path: &str,
    token: Option<&str>,
) -> (StatusCode, Value, Option<String>) {
    let mut req = Request::get(path);
    if let Some(t) = token {
        req = req.header("authorization", format!("Bearer {t}"));
    }
    let resp = app
        .clone()
        .oneshot(req.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = resp.status();
    let retry = resp
        .headers()
        .get("retry-after")
        .and_then(|v| v.to_str().ok())
        .map(str::to_owned);
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or_default(),
        retry,
    )
}

#[tokio::test]
async fn token_guards_the_api_but_not_health_or_the_document() {
    let app = service(Some("s3cret"), 0);
    let (s, v, _) = get(&app, "/api/v1/jobs/job_x", None).await;
    assert_eq!(s, StatusCode::UNAUTHORIZED);
    assert_eq!(v["error"]["code"], "UNAUTHORIZED");
    let (s, _, _) = get(&app, "/api/v1/jobs/job_x", Some("wrong")).await;
    assert_eq!(s, StatusCode::UNAUTHORIZED);
    let (s, v, _) = get(&app, "/api/v1/jobs/job_x", Some("s3cret")).await;
    assert_eq!(
        (s, v["error"]["code"].as_str()),
        (StatusCode::NOT_FOUND, Some("JOB_NOT_FOUND"))
    );
    for open in ["/health", "/ready", "/api/v1/openapi.json"] {
        let (s, _, _) = get(&app, open, None).await;
        assert_ne!(s, StatusCode::UNAUTHORIZED, "{open}");
    }
}

#[tokio::test]
async fn rate_limit_answers_429_with_retry_after() {
    let app = service(None, 3);
    for _ in 0..3 {
        let (s, _, _) = get(&app, "/api/v1/jobs/job_x", None).await;
        assert_eq!(s, StatusCode::NOT_FOUND);
    }
    let (s, v, retry) = get(&app, "/api/v1/jobs/job_x", None).await;
    assert_eq!(s, StatusCode::TOO_MANY_REQUESTS);
    assert_eq!(v["error"]["code"], "RATE_LIMITED");
    let secs: u64 = retry.unwrap().parse().unwrap();
    assert!((1..=60).contains(&secs));
    // Health checks are never limited.
    let (s, _, _) = get(&app, "/health", None).await;
    assert_eq!(s, StatusCode::OK);
}
