//! Phase 8 "done when": a test for each of the ten Integration Standard
//! points, against the real router with a real video (made by ffmpeg),
//! real jobs, a real render, and a real HTTP listener for callbacks.
//! Storage is local here; docker compose runs the same service on an S3 store (SeaweedFS).

use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use incubrix_api::config::Config;
use incubrix_api::{app, routes, AppState};
use serde_json::{json, Value};
use tower::ServiceExt;

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures")
}

fn tmp(name: &str) -> PathBuf {
    let d = Path::new(env!("CARGO_TARGET_TMPDIR")).join(name);
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn video(dir: &Path, seconds: u32) -> Option<PathBuf> {
    let out = dir.join("talk.mp4");
    let ok = Command::new(incubrix_media::probe::ffmpeg_bin())
        .args(["-v", "error", "-y", "-f", "lavfi", "-i"])
        .arg(format!("testsrc=size=160x90:rate=25:duration={seconds}"))
        .args(["-f", "lavfi", "-i"])
        .arg(format!("sine=frequency=440:duration={seconds}"))
        .args([
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ])
        .arg(&out)
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !ok {
        eprintln!("ffmpeg not available: skipping");
    }
    ok.then_some(out)
}

struct Api {
    app: axum::Router,
}

impl Api {
    fn new(dir: &Path) -> Self {
        let state = Arc::new(AppState::new(Config::for_tests(dir.join("data"))).unwrap());
        Self { app: app(state) }
    }

    async fn call(&self, req: Request<Body>) -> (StatusCode, axum::http::HeaderMap, Vec<u8>) {
        let resp = self.app.clone().oneshot(req).await.unwrap();
        let status = resp.status();
        let headers = resp.headers().clone();
        let body = resp
            .into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .to_vec();
        (status, headers, body)
    }

    async fn json(
        &self,
        method: &str,
        path: &str,
        body: Option<Value>,
        key: Option<&str>,
    ) -> (StatusCode, Value) {
        let mut b = Request::builder().method(method).uri(path);
        if let Some(k) = key {
            b = b.header("Idempotency-Key", k);
        }
        let req = match body {
            Some(v) => b
                .header("content-type", "application/json")
                .body(Body::from(v.to_string()))
                .unwrap(),
            None => b.body(Body::empty()).unwrap(),
        };
        let (s, _, bytes) = self.call(req).await;
        (s, serde_json::from_slice(&bytes).unwrap_or(Value::Null))
    }

    async fn wait(&self, job: &str) -> Value {
        for _ in 0..600 {
            let (_, j) = self
                .json("GET", &format!("/api/v1/jobs/{job}"), None, None)
                .await;
            if j["status"] == "succeeded" || j["status"] == "failed" {
                return j;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        panic!("job {job} did not finish");
    }
}

/// A multipart body with a video file and text fields.
fn multipart(video: &Path, fields: &[(&str, &str)]) -> (String, Vec<u8>) {
    let boundary = "----incubrix-test-boundary";
    let mut body = Vec::new();
    for (k, v) in fields {
        write!(
            body,
            "--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        )
        .unwrap();
    }
    write!(body, "--{boundary}\r\nContent-Disposition: form-data; name=\"video\"; filename=\"talk.mp4\"\r\nContent-Type: video/mp4\r\n\r\n").unwrap();
    body.extend(std::fs::read(video).unwrap());
    write!(body, "\r\n--{boundary}--\r\n").unwrap();
    (format!("multipart/form-data; boundary={boundary}"), body)
}

/// Requests a test server received: (headers, body).
type Seen = Arc<Mutex<Vec<(Vec<(String, String)>, String)>>>;

/// A tiny HTTP server: serves `file` at any GET, records any POST.
fn http_server(file: Option<PathBuf>) -> (String, Seen) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = seen.clone();
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut s) = stream else { continue };
            let mut buf = Vec::new();
            let mut tmp = [0u8; 65536];
            // Read the head, then the body by Content-Length.
            let head_end = loop {
                let n = s.read(&mut tmp).unwrap_or(0);
                if n == 0 {
                    break None;
                }
                buf.extend_from_slice(&tmp[..n]);
                if let Some(i) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    break Some(i + 4);
                }
            };
            let Some(head_end) = head_end else { continue };
            let head = String::from_utf8_lossy(&buf[..head_end]).to_string();
            let headers: Vec<(String, String)> = head
                .lines()
                .skip(1)
                .filter_map(|l| l.split_once(':'))
                .map(|(k, v)| (k.trim().to_lowercase(), v.trim().to_owned()))
                .collect();
            let len: usize = headers
                .iter()
                .find(|(k, _)| k == "content-length")
                .and_then(|(_, v)| v.parse().ok())
                .unwrap_or(0);
            while buf.len() < head_end + len {
                let n = s.read(&mut tmp).unwrap_or(0);
                if n == 0 {
                    break;
                }
                buf.extend_from_slice(&tmp[..n]);
            }
            if head.starts_with("POST") {
                log.lock().unwrap().push((
                    headers,
                    String::from_utf8_lossy(&buf[head_end..]).to_string(),
                ));
                let _ = s.write_all(
                    b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\nconnection: close\r\n\r\n",
                );
            } else if let Some(f) = &file {
                let bytes = std::fs::read(f).unwrap();
                let _ = write!(s, "HTTP/1.1 200 OK\r\ncontent-type: video/mp4\r\ncontent-length: {}\r\nconnection: close\r\n\r\n", bytes.len());
                let _ = s.write_all(&bytes);
            }
        }
    });
    (url, seen)
}

fn words() -> String {
    std::fs::read_to_string(fixtures().join("media/single_speaker.words.json")).unwrap()
}

/// Uploads the video with recorded words; returns the ready project id.
async fn ready_project(api: &Api, video: &Path) -> String {
    let (ct, body) = multipart(video, &[("transcript", &words())]);
    let req = Request::post("/api/v1/projects")
        .header("content-type", ct)
        .body(Body::from(body))
        .unwrap();
    let (s, _, b) = api.call(req).await;
    assert_eq!(s, StatusCode::ACCEPTED);
    let v: Value = serde_json::from_slice(&b).unwrap();
    let job = api.wait(v["job_id"].as_str().unwrap()).await;
    assert_eq!(job["status"], "succeeded", "{job}");
    v["project_id"].as_str().unwrap().to_owned()
}

// Point 1 (the test half): the whole flow runs in one test command, no keys.
// Point 3: jobs answer 202 + job_id; status, progress, result links; callback signed.
#[tokio::test(flavor = "multi_thread")]
async fn p3_jobs_progress_links_and_signed_callback() {
    let dir = tmp("api-jobs");
    let Some(v) = video(&dir, 12) else { return };
    let api = Api::new(&dir);
    let (hook, seen) = http_server(None);
    let (ct, body) = multipart(
        &v,
        &[
            ("transcript", &words()),
            ("callback_url", &format!("{hook}/done")),
        ],
    );
    let req = Request::post("/api/v1/projects")
        .header("content-type", ct)
        .body(Body::from(body))
        .unwrap();
    let (s, _, b) = api.call(req).await;
    assert_eq!(s, StatusCode::ACCEPTED);
    let acc: Value = serde_json::from_slice(&b).unwrap();
    assert!(acc["status_url"]
        .as_str()
        .unwrap()
        .starts_with("/api/v1/jobs/"));
    let job = api.wait(acc["job_id"].as_str().unwrap()).await;
    assert_eq!(job["status"], "succeeded", "{job}");
    assert_eq!(job["progress"], 100);
    assert_eq!(job["result"]["words"], 18);
    assert_eq!(job["result"]["source_sha256"].as_str().unwrap().len(), 64);

    // The callback arrives, signed with HMAC-SHA256 over the body.
    for _ in 0..50 {
        if !seen.lock().unwrap().is_empty() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let (headers, body) = seen.lock().unwrap()[0].clone();
    let sig = headers
        .iter()
        .find(|(k, _)| k == "x-incubrix-signature")
        .map(|(_, v)| v.clone())
        .unwrap();
    assert_eq!(sig, incubrix_api::jobs::signature("test-secret", &body));
    assert!(body.contains("\"status\":\"succeeded\""));
}

// Point 7: files in (upload or URL) and out (stored, returned as links).
#[tokio::test(flavor = "multi_thread")]
async fn p7_url_in_render_out_as_a_link() {
    let dir = tmp("api-files");
    let Some(v) = video(&dir, 12) else { return };
    let api = Api::new(&dir);
    let (server, _) = http_server(Some(v.clone()));
    let transcript: Value = serde_json::from_str(&words()).unwrap();
    let (s, acc) = api
        .json(
            "POST",
            "/api/v1/projects",
            Some(json!({"video_url": format!("{server}/talk.mp4"), "transcript": transcript})),
            None,
        )
        .await;
    assert_eq!(s, StatusCode::ACCEPTED, "{acc}");
    let job = api.wait(acc["job_id"].as_str().unwrap()).await;
    assert_eq!(job["status"], "succeeded", "{job}");
    let pid = acc["project_id"].as_str().unwrap();
    let (_, o) = api
        .json(
            "POST",
            &format!("/api/v1/projects/{pid}/instructions"),
            Some(json!({"say": "cut the first 2 seconds"})),
            None,
        )
        .await;
    assert_eq!(o["status"], "applied", "{o}");

    let (s, acc) = api
        .json(
            "POST",
            &format!("/api/v1/projects/{pid}/renders"),
            None,
            None,
        )
        .await;
    assert_eq!(s, StatusCode::ACCEPTED);
    let job = api.wait(acc["job_id"].as_str().unwrap()).await;
    assert_eq!(job["status"], "succeeded", "{job}");
    assert_eq!(job["result"]["check"]["ok"], true);
    assert!(
        job["result"]["check"]["length_diff_frames"]
            .as_f64()
            .unwrap()
            <= 1.0
    );
    assert_eq!(job["result"]["source_unchanged"], true);
    let link = job["result"]["links"]["video"].as_str().unwrap();
    let path = link.trim_start_matches("http://localhost");
    let (s, h, bytes) = api
        .call(Request::get(path).body(Body::empty()).unwrap())
        .await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(h["content-type"], "video/mp4");
    assert!(bytes.len() > 1000);
    assert!(job["result"]["links"]["otio"].is_string());
}

// Point 4: the same Idempotency-Key never repeats work.
#[tokio::test(flavor = "multi_thread")]
async fn p4_idempotency_key() {
    let dir = tmp("api-idem");
    let Some(v) = video(&dir, 12) else { return };
    let api = Api::new(&dir);
    let pid = ready_project(&api, &v).await;
    let path = format!("/api/v1/projects/{pid}/instructions");

    let (s1, a) = api
        .json(
            "POST",
            &path,
            Some(json!({"say": "cut the first 2 seconds"})),
            Some("k-1"),
        )
        .await;
    let (s2, b) = api
        .json(
            "POST",
            &path,
            Some(json!({"say": "cut the first 2 seconds"})),
            Some("k-1"),
        )
        .await;
    assert_eq!((s1, s2), (StatusCode::OK, StatusCode::OK));
    assert_eq!(a, b, "the same response");
    let (_, p) = api
        .json("GET", &format!("/api/v1/projects/{pid}"), None, None)
        .await;
    assert_eq!(p["edits"], 1, "the cut was made once, not twice");
    assert_eq!(p["duration_s"], 10.0);

    let (s, e) = api
        .json(
            "POST",
            &path,
            Some(json!({"say": "cut the last 2 seconds"})),
            Some("k-1"),
        )
        .await;
    assert_eq!(s, StatusCode::CONFLICT);
    assert_eq!(e["error"]["code"], "IDEMPOTENCY_KEY_REUSED");

    // A job: the same key gives the same job, and only one render runs.
    let r = format!("/api/v1/projects/{pid}/renders");
    let (_, j1) = api.json("POST", &r, None, Some("render-1")).await;
    let (_, j2) = api.json("POST", &r, None, Some("render-1")).await;
    assert_eq!(j1["job_id"], j2["job_id"]);
    api.wait(j1["job_id"].as_str().unwrap()).await;
    let renders = std::fs::read_dir(dir.join("data/projects").join(&pid).join("renders"))
        .unwrap()
        .count();
    assert_eq!(renders, 1);
}

// Point 5: errors are JSON with code, message, retryable, details.
#[tokio::test(flavor = "multi_thread")]
async fn p5_errors_have_one_shape() {
    let dir = tmp("api-errors");
    let api = Api::new(&dir);
    let check = |s: StatusCode, v: &Value, status: u16, code: &str| {
        assert_eq!(s.as_u16(), status, "{v}");
        let e = &v["error"];
        assert_eq!(e["code"], code, "{v}");
        assert!(
            e["message"].is_string() && e["retryable"].is_boolean() && e["details"].is_object(),
            "{v}"
        );
    };
    let (s, v) = api
        .json(
            "POST",
            "/api/v1/projects/nope/instructions",
            Some(json!({"say": "cut"})),
            None,
        )
        .await;
    check(s, &v, 404, "PROJECT_NOT_FOUND");
    let (s, v) = api.json("GET", "/api/v1/jobs/nope", None, None).await;
    check(s, &v, 404, "JOB_NOT_FOUND");
    let (s, v) = api.json("GET", "/api/v1/nothing-here", None, None).await;
    check(s, &v, 404, "ROUTE_NOT_FOUND");
    let (s, v) = api
        .json(
            "POST",
            "/api/v1/projects",
            Some(json!({"video_url": "http://x/clip.mkv", "transcript": {"words": []}})),
            None,
        )
        .await;
    check(s, &v, 422, "UNSUPPORTED_FORMAT");
    let (s, v) = api
        .json(
            "POST",
            "/api/v1/projects",
            Some(json!({"video_url": "http://x/clip.mp4"})),
            None,
        )
        .await;
    check(s, &v, 422, "NO_TRANSCRIBER");
    let (s, v) = api
        .json("POST", "/api/v1/projects", Some(json!({})), None)
        .await;
    check(s, &v, 400, "VALIDATION_ERROR");
    assert_eq!(v["error"]["retryable"], false);
    let (s, v) = api
        .json(
            "POST",
            "/api/v1/sessions",
            Some(json!({"session": {"source": {"duration_s": 10}, "steps": []}})),
            None,
        )
        .await;
    check(s, &v, 400, "VALIDATION_ERROR");
}

// Point 8: correlation id on every response; health and readiness.
#[tokio::test(flavor = "multi_thread")]
async fn p8_correlation_id_health_ready() {
    let dir = tmp("api-health");
    let api = Api::new(&dir);
    let req = Request::get("/health")
        .header("X-Correlation-Id", "abc-123")
        .body(Body::empty())
        .unwrap();
    let (s, h, b) = api.call(req).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(h["x-correlation-id"], "abc-123");
    assert_eq!(serde_json::from_slice::<Value>(&b).unwrap()["status"], "ok");
    let (_, h, _) = api
        .call(Request::get("/health").body(Body::empty()).unwrap())
        .await;
    assert_eq!(
        h["x-correlation-id"].len(),
        36,
        "one is made up when none is sent"
    );
    let (s, v) = api.json("GET", "/ready", None, None).await;
    assert_eq!(s, StatusCode::OK, "{v}");
    assert_eq!(v["checks"]["database"], true);
    assert_eq!(v["checks"]["storage"], true);
}

// Point 9: every result carries a manifest. Editing works over HTTP.
#[tokio::test(flavor = "multi_thread")]
async fn p9_manifest_and_editing_over_http() {
    let dir = tmp("api-edit");
    let Some(v) = video(&dir, 12) else { return };
    let api = Api::new(&dir);
    let pid = ready_project(&api, &v).await;
    let base = format!("/api/v1/projects/{pid}");
    let (_, o) = api
        .json(
            "POST",
            &format!("{base}/instructions"),
            Some(json!({"say": "Add a caption 'Welcome!' when I say welcome to the channel"})),
            None,
        )
        .await;
    assert_eq!(o["status"], "applied", "{o}");
    assert_eq!(o["time_policy"], "current");
    let m = &o["manifest"];
    for k in [
        "engine",
        "models",
        "settings",
        "seed",
        "timings_ms",
        "cost_estimate_usd",
        "warnings",
        "licences",
    ] {
        assert!(m.get(k).is_some(), "manifest lacks {k}: {m}");
    }
    let (_, o) = api
        .json(
            "POST",
            &format!("{base}/instructions"),
            Some(json!({"say": "remove the part about pricing"})),
            None,
        )
        .await;
    assert_eq!(o["status"], "needs_clarification", "{o}");
    assert_eq!(o["options"].as_array().unwrap().len(), 3);
    let (_, o) = api
        .json(
            "POST",
            &format!("{base}/answers"),
            Some(json!({"answer": "the second one"})),
            None,
        )
        .await;
    assert_eq!(o["status"], "applied", "{o}");
    let (_, u) = api.json("POST", &format!("{base}/undo"), None, None).await;
    assert_eq!(u["status"], "applied");
    let (_, r) = api.json("POST", &format!("{base}/redo"), None, None).await;
    assert_eq!(
        r["timeline_hash"], o["timeline_hash"],
        "redo restores the same timeline"
    );
    let (s, t) = api
        .json("GET", &format!("{base}/timeline"), None, None)
        .await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(t["captions"].as_array().unwrap().len(), 1);
    let (_, h) = api
        .json("GET", &format!("{base}/history"), None, None)
        .await;
    assert_eq!(h["txs"].as_array().unwrap().len(), 2);
    let (_, x) = api.json("GET", &format!("{base}/otio"), None, None).await;
    assert_eq!(x["OTIO_SCHEMA"], "Timeline.1");
    let (s, v) = api
        .json(
            "POST",
            &format!("{base}/instructions"),
            Some(json!({})),
            None,
        )
        .await;
    assert_eq!(
        (s, v["error"]["code"].as_str()),
        (StatusCode::BAD_REQUEST, Some("VALIDATION_ERROR"))
    );
}

// Point 10 (service side): a scripted session as a job, results.json out.
#[tokio::test(flavor = "multi_thread")]
async fn p10_session_job_writes_results() {
    let dir = tmp("api-session");
    let api = Api::new(&dir);
    let session =
        std::fs::read_to_string(fixtures().join("sessions/01_worked_example.yaml")).unwrap();
    let (s, acc) = api
        .json(
            "POST",
            "/api/v1/sessions",
            Some(json!({"session": session})),
            Some("s-1"),
        )
        .await;
    assert_eq!(s, StatusCode::ACCEPTED, "{acc}");
    let job = api.wait(acc["job_id"].as_str().unwrap()).await;
    assert_eq!(job["status"], "succeeded", "{job}");
    let durations: Vec<f64> = job["result"]["steps"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| s["duration_s"].as_f64().unwrap())
        .collect();
    assert_eq!(
        durations,
        [240.0, 210.0, 208.0, 193.0, 223.0, 193.0, 193.0, 193.0]
    );
    // Keys are kept so links are signed afresh each time the job is read.
    let jid = acc["job_id"].as_str().unwrap();
    assert_eq!(
        job["result"]["files"]["results"],
        format!("sessions/{jid}/results.json")
    );
    let link = job["result"]["links"]["results"]
        .as_str()
        .unwrap()
        .trim_start_matches("http://localhost")
        .to_owned();
    let (s, _, b) = api
        .call(Request::get(link).body(Body::empty()).unwrap())
        .await;
    assert_eq!(s, StatusCode::OK);
    let results: Value = serde_json::from_slice(&b).unwrap();
    assert_eq!(results["steps"][2]["options"].as_array().unwrap().len(), 4);

    // A session naming a file on the caller's disk is refused up front;
    // sent with the file's contents, it plays.
    let session =
        std::fs::read_to_string(fixtures().join("sessions/41_two_speakers_old_job.yaml")).unwrap();
    let (s, v) = api
        .json(
            "POST",
            "/api/v1/sessions",
            Some(json!({"session": session})),
            None,
        )
        .await;
    assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY, "{v}");
    assert_eq!(v["error"]["code"], "VALIDATION_ERROR");
    assert_eq!(v["error"]["details"]["field"], "transcript");
    let transcript: Value = serde_json::from_str(
        &std::fs::read_to_string(fixtures().join("media/two_speakers.transcript.json")).unwrap(),
    )
    .unwrap();
    let (s, acc) = api
        .json(
            "POST",
            "/api/v1/sessions",
            Some(json!({"session": session, "transcript": transcript})),
            None,
        )
        .await;
    assert_eq!(s, StatusCode::ACCEPTED, "{acc}");
    let job = api.wait(acc["job_id"].as_str().unwrap()).await;
    assert_eq!(job["status"], "succeeded", "{job}");
}

// Point 2: openapi.yaml is generated from the code and matches the service.
#[tokio::test(flavor = "multi_thread")]
async fn p2_openapi_matches_the_running_service() {
    let generated = routes::openapi_yaml();
    let file = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../openapi.yaml");
    if std::env::var_os("UPDATE_OPENAPI").is_some() {
        std::fs::write(&file, &generated).unwrap();
    }
    let committed = std::fs::read_to_string(&file).expect("incubrix/openapi.yaml");
    assert_eq!(
        committed.replace("\r\n", "\n"),
        generated,
        "openapi.yaml is stale: run with UPDATE_OPENAPI=1"
    );
    assert!(generated.starts_with("openapi: 3.1"), "OpenAPI 3.1");

    // Every documented route exists on the router (no ROUTE_NOT_FOUND, no 405).
    let dir = tmp("api-openapi");
    let api = Api::new(&dir);
    let doc: Value = serde_yaml::from_str(&generated).unwrap();
    let mut n = 0;
    for (path, item) in doc["paths"].as_object().unwrap() {
        for method in item.as_object().unwrap().keys() {
            let p = path.replace("{id}", "x").replace("{key}", "x");
            let req = Request::builder()
                .method(method.to_uppercase().as_str())
                .uri(&p)
                .body(Body::empty())
                .unwrap();
            let (s, _, b) = api.call(req).await;
            let v: Value = serde_json::from_slice(&b).unwrap_or(Value::Null);
            assert_ne!(s, StatusCode::METHOD_NOT_ALLOWED, "{method} {path}");
            assert_ne!(v["error"]["code"], "ROUTE_NOT_FOUND", "{method} {path}");
            n += 1;
            if path != "/health" && path != "/ready" {
                assert!(path.starts_with("/api/v1/"), "{path} is under /api/v1/");
            }
        }
    }
    assert!(n >= 15, "{n} operations");
}
