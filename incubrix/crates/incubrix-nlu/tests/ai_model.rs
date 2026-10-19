//! The AI-model path end to end, against a local stand-in for the Claude
//! Messages API: plain English in, intent out, resolved by the engine. No
//! API key and no network are needed.

mod common;

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use common::{duration, transcript};
use incubrix_core::{secs, Project, SourceInfo, Status};
use incubrix_nlu::llm::{LlmConfig, LlmParser, Provider};
use incubrix_nlu::{AutoParser, Session};
use serde_json::{json, Value};

/// One request as the server saw it.
#[derive(Clone, Debug)]
struct Seen {
    headers: Vec<(String, String)>,
    body: Value,
}

/// Answers each request with the next reply, in order; records requests.
fn fake_claude(replies: Vec<Value>) -> (String, Arc<Mutex<Vec<Seen>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = Arc::clone(&seen);
    std::thread::spawn(move || {
        for (reply, stream) in replies.into_iter().zip(listener.incoming()) {
            let mut stream = stream.unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut headers = Vec::new();
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            loop {
                line.clear();
                reader.read_line(&mut line).unwrap();
                let l = line.trim_end();
                if l.is_empty() {
                    break;
                }
                if let Some((k, v)) = l.split_once(':') {
                    headers.push((k.trim().to_lowercase(), v.trim().to_owned()));
                }
            }
            let len: usize = headers
                .iter()
                .find(|(k, _)| k == "content-length")
                .map(|(_, v)| v.parse().unwrap())
                .unwrap_or(0);
            let mut body = vec![0u8; len];
            reader.read_exact(&mut body).unwrap();
            log.lock().unwrap().push(Seen {
                headers,
                body: serde_json::from_slice(&body).unwrap(),
            });
            let out = reply.to_string();
            write!(
                stream,
                "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{out}",
                out.len()
            )
            .unwrap();
        }
    });
    (url, seen)
}

/// A Claude reply whose text is `text`, after an (empty) thinking block.
fn claude_says(text: &str) -> Value {
    json!({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": "", "signature": "x"}, {"type": "text", "text": text}],
    })
}

fn cache_dir(name: &str) -> PathBuf {
    let d = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join(name);
    let _ = std::fs::remove_dir_all(&d);
    d
}

fn model(url: &str, cache: PathBuf) -> LlmParser {
    LlmParser::new(LlmConfig {
        provider: Provider::Anthropic,
        model: "claude-opus-5-5".into(),
        api_key: Some("test-key".into()),
        base_url: url.into(),
        cache_dir: cache,
    })
}

fn talk() -> Project {
    Project::new(
        SourceInfo::with_duration(secs(240.0)),
        transcript(&[
            (42.0, "Welcome to the channel."),
            (65.0, "Our pricing is simple."),
            (135.0, "The pricing changed last year."),
            (195.0, "Pricing for teams is different."),
        ]),
    )
}

#[test]
fn plain_english_is_read_by_the_model_and_applied_by_the_engine() {
    let (url, seen) = fake_claude(vec![claude_says(
        r#"{"intent":"cut","target":{"kind":"first","ms":30000}}"#,
    )]);
    let mut s = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(model(&url, cache_dir("ai-plain"))))),
    );
    let r = s.say("could you trim off the opening half minute? it drags");
    assert_eq!(r.outcome.status, Status::Applied, "{:?}", r.outcome);
    assert_eq!(duration(&s), 210.0);
    assert!(r.reader.starts_with("AI model Claude"), "{}", r.reader);
    assert_eq!(s.model_label().as_deref(), Some("Claude (claude-opus-5-5)"));

    // The request is what the current Messages API expects.
    let req = &seen.lock().unwrap()[0];
    let h = |k: &str| {
        req.headers
            .iter()
            .find(|(n, _)| n == k)
            .map(|(_, v)| v.clone())
    };
    assert_eq!(h("x-api-key").as_deref(), Some("test-key"));
    assert_eq!(h("anthropic-version").as_deref(), Some("2023-06-01"));
    assert_eq!(
        h("anthropic-beta").as_deref(),
        Some("server-side-fallback-2026-07-01")
    );
    assert_eq!(req.body["model"], "claude-opus-5-5");
    assert_eq!(req.body["fallbacks"], "default");
    assert_eq!(req.body["output_config"]["effort"], "low");
    assert!(
        req.body.get("temperature").is_none(),
        "current models reject sampling parameters"
    );
    assert!(req.body["system"]
        .as_str()
        .unwrap()
        .contains("\"intent\":\"cut\""));
    let user: Value =
        serde_json::from_str(req.body["messages"][0]["content"].as_str().unwrap()).unwrap();
    assert_eq!(
        user["instruction"],
        "could you trim off the opening half minute? it drags"
    );
    assert_eq!(user["context"]["duration_s"], 240.0);
}

#[test]
fn a_malformed_answer_gets_one_correction_round() {
    let (url, seen) = fake_claude(vec![
        claude_says("Sure! I'll cut the first thirty seconds for you."),
        claude_says(r#"{"intent":"cut","target":{"kind":"first","ms":30000}}"#),
    ]);
    let mut s = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(model(&url, cache_dir("ai-fix"))))),
    );
    assert_eq!(
        s.say("chop the start, first 30 secs").outcome.status,
        Status::Applied
    );
    let seen = seen.lock().unwrap();
    assert_eq!(seen.len(), 2);
    let msgs = seen[1].body["messages"].as_array().unwrap();
    assert_eq!(
        msgs.len(),
        3,
        "user, the model's own reply echoed, the correction"
    );
    assert_eq!(msgs[1]["role"], "assistant");
    assert_eq!(
        msgs[1]["content"][0]["type"], "thinking",
        "echoed unchanged"
    );
    assert!(msgs[2]["content"].as_str().unwrap().contains("not valid"));
}

#[test]
fn without_the_model_the_built_in_phrases_still_work() {
    // Nothing listens on this port: the model is unreachable.
    let dead = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", dead.local_addr().unwrap());
    drop(dead);
    let mut s = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(model(&url, cache_dir("ai-dead"))))),
    );
    let r = s.say("Cut the first 30 seconds");
    assert_eq!(r.outcome.status, Status::Applied, "{:?}", r.outcome);
    assert!(r.reader.starts_with("built-in phrases"), "{}", r.reader);
}

#[test]
fn a_refusal_falls_back_to_the_rules() {
    let refused = json!({"type": "message", "stop_reason": "refusal", "content": []});
    let (url, _) = fake_claude(vec![refused]);
    let mut s = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(model(&url, cache_dir("ai-refuse"))))),
    );
    assert_eq!(
        s.say("Cut the first 30 seconds").outcome.status,
        Status::Applied
    );
}

#[test]
fn a_free_form_answer_is_matched_by_the_model() {
    let (url, _) = fake_claude(vec![
        claude_says(r#"{"intent":"cut","target":{"kind":"topic","text":"pricing"}}"#),
        claude_says(r#"{"option": 3}"#),
    ]);
    let mut s = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(model(&url, cache_dir("ai-answer"))))),
    );
    let r = s.say("drop the pricing part").outcome;
    assert_eq!(r.status, Status::NeedsClarification);
    let r = s.say("the one about teams");
    assert_eq!(r.outcome.status, Status::Applied, "{:?}", r.outcome);
    let tl = s.project.timeline().timeline;
    let teams = s
        .project
        .transcript
        .words
        .iter()
        .find(|w| w.text == "teams")
        .unwrap();
    assert_eq!(tl.covered(&teams.range()), 0, "the third mention went");
}

#[test]
fn answers_are_cached_so_a_rerun_needs_no_network() {
    let cache = cache_dir("ai-cache");
    let (url, _) = fake_claude(vec![claude_says(
        r#"{"intent":"speed","target":{"kind":"range","start_ms":60000,"end_ms":90000},"speed":2000}"#,
    )]);
    let text = "play one minute to one thirty twice as fast";
    let mut a = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(model(&url, cache.clone())))),
    );
    let first = a.say(text).outcome;
    assert_eq!(first.status, Status::Applied);

    let dead = TcpListener::bind("127.0.0.1:0").unwrap();
    let gone = format!("http://{}", dead.local_addr().unwrap());
    drop(dead);
    // Same model and prompt, server gone: served from the cache.
    let mut b = Session::new(
        talk(),
        Box::new(AutoParser::new(Some(LlmParser::new(LlmConfig {
            base_url: gone,
            ..model(&url, cache).config().clone()
        })))),
    );
    let again = b.say(text).outcome;
    assert_eq!(again.timeline_hash, first.timeline_hash);
}
