//! `incubrix-api` - the IncuBrix editing engine over HTTP.
//!
//! ```text
//! incubrix-api              serve (settings from the environment, see .env.example)
//! incubrix-api --openapi    print the OpenAPI document (YAML) and exit
//! ```

use std::sync::Arc;

use incubrix_api::config::Config;
use incubrix_api::{app, routes, AppState};

#[tokio::main]
async fn main() {
    if std::env::args().any(|a| a == "--openapi") {
        print!("{}", routes::openapi_yaml());
        return;
    }
    // JSON logs: timestamp, level, message and fields (job_id, correlation_id).
    tracing_subscriber::fmt()
        .json()
        .with_current_span(true)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_env("LOG_LEVEL")
                .unwrap_or_else(|_| "info".into()),
        )
        .init();
    let cfg = Config::from_env();
    let bind = cfg.bind.clone();
    let state = match AppState::new(cfg) {
        Ok(s) => Arc::new(s),
        Err(e) => {
            tracing::error!(code = %e.detail.code, error = %e.detail.message, "cannot start");
            std::process::exit(1);
        }
    };
    tracing::info!(
        bind = %bind,
        speech_recognition = state.transcriber.is_some(),
        "incubrix-api listening"
    );
    let listener = tokio::net::TcpListener::bind(&bind)
        .await
        .expect("bind API_BIND");
    let service = app(state).into_make_service_with_connect_info::<std::net::SocketAddr>();
    axum::serve(listener, service)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .expect("serve");
}
