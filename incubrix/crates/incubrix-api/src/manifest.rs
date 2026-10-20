//! The output manifest every result carries (Integration Standard point 9):
//! what produced it, with which settings, how long it took, what it cost,
//! what to watch out for, and under which licences.

use serde_json::{json, Value};

/// Licences of everything that touches a result.
pub fn licences() -> Value {
    json!([
        {"component": "incubrix (this service)", "licence": "MIT OR Apache-2.0"},
        {"component": "ffmpeg / ffprobe", "licence": "LGPL-2.1-or-later; GPL-2.0-or-later when built with libx264 (the image's build)", "use": "separate program, called as a process"},
        {"component": "x264", "licence": "GPL-2.0-or-later", "use": "inside ffmpeg"},
        {"component": "whisper.cpp", "licence": "MIT", "use": "speech recognition (whisper feature)"},
        {"component": "Whisper model weights", "licence": "MIT"},
        {"component": "SQLite", "licence": "Public domain"},
        {"component": "SeaweedFS", "licence": "Apache-2.0", "use": "S3 store in docker compose, separate service over HTTP"}
    ])
}

/// A manifest. `models` names who read the words and who heard the speech.
pub fn manifest(
    models: Vec<Value>,
    settings: Value,
    timings_ms: Value,
    warnings: &[String],
) -> Value {
    json!({
        "engine": {"name": "incubrix", "version": env!("CARGO_PKG_VERSION")},
        "models": models,
        "settings": settings,
        "seed": 0,
        "deterministic": true,
        "timings_ms": timings_ms,
        // Rules, local recognition and local models cost nothing per call; a
        // hosted model's cost is reported by its provider, not estimated here.
        "cost_estimate_usd": 0.0,
        "warnings": warnings,
        "licences": licences(),
    })
}

/// The instruction reader as a model entry.
pub fn parser_model(name: &str) -> Value {
    let kind = if name.starts_with("llm:") || name.contains("llm:") {
        "language model"
    } else {
        "rules"
    };
    json!({"role": "instruction_reader", "name": name, "kind": kind})
}
