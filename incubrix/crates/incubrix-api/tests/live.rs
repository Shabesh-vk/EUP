//! End to end against the running stack (`docker compose run --rm test`):
//! the real API container, a real S3 store, real speech recognition, presigned
//! links fetched like a client would. Skipped when `API_URL` is not set.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use serde_json::{json, Value};

fn api() -> Option<String> {
    std::env::var("API_URL").ok().filter(|v| !v.is_empty())
}

fn post(url: &str, body: Value, key: Option<&str>) -> (u16, Value) {
    let mut req = ureq::post(url).set("content-type", "application/json");
    if let Some(k) = key {
        req = req.set("Idempotency-Key", k);
    }
    match req.send_string(&body.to_string()) {
        Ok(r) => (r.status(), json_of(r)),
        Err(ureq::Error::Status(c, r)) => (c, json_of(r)),
        Err(e) => panic!("{url}: {e}"),
    }
}

fn json_of(r: ureq::Response) -> Value {
    serde_json::from_str(&r.into_string().unwrap_or_default()).unwrap_or(Value::Null)
}

fn get(url: &str) -> Value {
    json_of(ureq::get(url).call().unwrap())
}

fn wait(base: &str, job: &str) -> Value {
    for _ in 0..1200 {
        let j = get(&format!("{base}/api/v1/jobs/{job}"));
        if j["status"] == "succeeded" || j["status"] == "failed" {
            return j;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    panic!("job {job} did not finish");
}

fn video(dir: &Path) -> PathBuf {
    let out = dir.join("live.mp4");
    let ok = Command::new("ffmpeg")
        .args([
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=25:duration=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
        ])
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
        .unwrap();
    assert!(ok.success());
    out
}

fn upload(base: &str, file: &Path, fields: &[(&str, &str)]) -> Value {
    let boundary = "----incubrix-live";
    let mut body = Vec::new();
    for (k, v) in fields {
        write!(
            body,
            "--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        )
        .unwrap();
    }
    write!(body, "--{boundary}\r\nContent-Disposition: form-data; name=\"video\"; filename=\"live.mp4\"\r\nContent-Type: video/mp4\r\n\r\n").unwrap();
    body.extend(std::fs::read(file).unwrap());
    write!(body, "\r\n--{boundary}--\r\n").unwrap();
    let r = ureq::post(&format!("{base}/api/v1/projects"))
        .set(
            "content-type",
            &format!("multipart/form-data; boundary={boundary}"),
        )
        .send_bytes(&body)
        .unwrap();
    assert_eq!(r.status(), 202);
    json_of(r)
}

#[test]
fn live_stack_end_to_end() {
    let Some(base) = api() else {
        eprintln!(
            "API_URL not set: the live end-to-end test runs in `docker compose run --rm test`"
        );
        return;
    };
    let dir = std::env::temp_dir().join("incubrix-live");
    std::fs::create_dir_all(&dir).unwrap();

    // Ready: database, S3 store, ffmpeg, speech recognition.
    let ready = get(&format!("{base}/ready"));
    assert_eq!(ready["ready"], true, "{ready}");
    assert_eq!(ready["checks"]["speech_recognition"], true, "{ready}");

    // A callback listener in this container.
    let hook = TcpListener::bind("0.0.0.0:0").unwrap();
    let port = hook.local_addr().unwrap().port();
    let host = std::env::var("CALLBACK_HOST").unwrap_or_else(|_| "localhost".into());
    let got = std::thread::spawn(move || {
        let (mut s, _) = hook.accept().unwrap();
        s.set_read_timeout(Some(Duration::from_secs(5))).ok();
        let mut buf = vec![0u8; 1 << 20];
        let n = s.read(&mut buf).unwrap_or(0);
        let _ = s.write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n");
        String::from_utf8_lossy(&buf[..n]).to_string()
    });

    // Upload with no transcript: the service hears the speech itself.
    let v = video(&dir);
    let acc = upload(
        &base,
        &v,
        &[("callback_url", &format!("http://{host}:{port}/hook"))],
    );
    let job = wait(&base, acc["job_id"].as_str().unwrap());
    assert_eq!(job["status"], "succeeded", "{job}");
    assert!(
        job["manifest"]["models"][0]["name"]
            .as_str()
            .unwrap()
            .contains("whisper"),
        "{job}"
    );
    let callback = got.join().unwrap();
    assert!(
        callback
            .to_lowercase()
            .contains("x-incubrix-signature: sha256="),
        "{callback}"
    );

    // Edit, with an Idempotency-Key retried.
    let pid = acc["project_id"].as_str().unwrap();
    let say = format!("{base}/api/v1/projects/{pid}/instructions");
    // One key per project, so rerunning against the same stack never reuses it.
    let key = format!("live-{pid}");
    let (s1, a) = post(&say, json!({"say": "cut the first 2 seconds"}), Some(&key));
    let (s2, b) = post(&say, json!({"say": "cut the first 2 seconds"}), Some(&key));
    assert_eq!((s1, s2), (200, 200));
    assert_eq!(a, b);
    assert_eq!(a["duration_s"], 8.0);

    // Render: a presigned S3 link, downloaded like a client would.
    let (s, r) = post(
        &format!("{base}/api/v1/projects/{pid}/renders"),
        json!({}),
        None,
    );
    assert_eq!(s, 202);
    let job = wait(&base, r["job_id"].as_str().unwrap());
    assert_eq!(job["status"], "succeeded", "{job}");
    assert_eq!(job["result"]["check"]["ok"], true);
    let link = job["result"]["links"]["video"].as_str().unwrap();
    assert!(link.contains("X-Amz-Signature="), "presigned: {link}");
    let mut bytes = Vec::new();
    ureq::get(link)
        .call()
        .unwrap()
        .into_reader()
        .read_to_end(&mut bytes)
        .unwrap();
    let out = dir.join("rendered.mp4");
    std::fs::write(&out, &bytes).unwrap();
    let probe = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
        ])
        .arg(&out)
        .output()
        .unwrap();
    let secs: f64 = String::from_utf8_lossy(&probe.stdout)
        .trim()
        .parse()
        .unwrap();
    assert!((secs - 8.0).abs() < 0.05, "rendered {secs} s");

    // The batch runner against the API (point 10).
    // Tests run in the crate folder; the fixtures are at the workspace root.
    let sessions = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/sessions");
    let batch = Command::new("incubrix")
        .args(["batch", "run"])
        .arg(sessions.join("01_worked_example.yaml"))
        .arg(sessions.join("41_two_speakers_old_job.yaml"))
        .args(["--api", &base, "--out"])
        .arg(dir.join("batch"))
        .output()
        .unwrap();
    let text = String::from_utf8_lossy(&batch.stdout);
    assert!(
        batch.status.success(),
        "{text}\n{}",
        String::from_utf8_lossy(&batch.stderr)
    );
    let results: Value = serde_json::from_str(
        &std::fs::read_to_string(dir.join("batch/01_worked_example/results.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(results["steps"][7]["duration_s"], 193.0);
    println!("live end-to-end passed: intake with whisper, idempotent edit, presigned render, signed callback, batch runner");
}
