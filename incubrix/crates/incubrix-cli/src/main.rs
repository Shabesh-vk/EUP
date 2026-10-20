//! `incubrix` - the session runner.
//!
//! ```text
//! incubrix session run <session.yaml> [--out DIR] [--no-render] [--parser rules|auto]
//! incubrix batch run <folder|session.yaml> [--out DIR] [--no-render] [--parser rules|auto]
//! incubrix check <folder|session.yaml>... [--parser rules|auto]
//! incubrix metrics [<scenario folder>] [--out DIR] [--no-render]
//! ```
//!
//! `check` plays every session three times, compares each step's
//! `timeline_hash` across the runs, and checks the `expect:` blocks. It
//! uses the deterministic rules parser unless told otherwise.

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use incubrix_cli::{check, load, run, RunOptions};
use incubrix_nlu::{parser_from_env, Parser, RulesParser};

const USAGE: &str = "usage:
  incubrix session run <session.yaml> [--out DIR] [--no-render] [--parser rules|auto]
  incubrix batch run <folder|session.yaml> [--out DIR] [--no-render] [--parser rules|auto] [--api URL]
  incubrix check <folder|session.yaml>... [--parser rules|auto]
  incubrix metrics [<scenario folder>] [--out DIR] [--no-render]";

struct Args {
    paths: Vec<PathBuf>,
    out: Option<PathBuf>,
    render: bool,
    parser: String,
    /// Run sessions on a running service instead of in this process.
    api: Option<String>,
}

fn parse(args: &[String], default_parser: &str) -> Result<Args, String> {
    let mut a = Args {
        api: None,
        paths: vec![],
        out: None,
        render: true,
        parser: default_parser.into(),
    };
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--out" => {
                i += 1;
                a.out = Some(PathBuf::from(args.get(i).ok_or("--out needs a folder")?));
            }
            "--no-render" => a.render = false,
            "--api" => {
                i += 1;
                a.api = Some(
                    args.get(i)
                        .ok_or("--api needs the service URL")?
                        .trim_end_matches('/')
                        .to_owned(),
                );
            }
            "--parser" => {
                i += 1;
                a.parser = args.get(i).ok_or("--parser needs rules or auto")?.clone();
            }
            s if s.starts_with("--") => return Err(format!("unknown option {s}")),
            s => a.paths.push(PathBuf::from(s)),
        }
        i += 1;
    }
    if a.paths.is_empty() {
        return Err("no session file given".into());
    }
    Ok(a)
}

fn parser(name: &str) -> Box<dyn Parser> {
    match name {
        "rules" => Box::new(RulesParser),
        _ => parser_from_env(),
    }
}

/// Session files under each path, sorted.
fn sessions(paths: &[PathBuf]) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for p in paths {
        if p.is_dir() {
            let mut found: Vec<PathBuf> = std::fs::read_dir(p)
                .map(|d| d.filter_map(Result::ok).map(|e| e.path()).collect())
                .unwrap_or_default();
            found
                .retain(|f| matches!(f.extension().and_then(|e| e.to_str()), Some("yaml" | "yml")));
            found.sort();
            out.extend(found);
        } else {
            out.push(p.clone());
        }
    }
    out
}

fn run_one(path: &Path, a: &Args, out: Option<PathBuf>) -> Result<(), String> {
    let opts = RunOptions {
        out: out.clone(),
        render: a.render,
        ..Default::default()
    };
    let (results, _) = run(path, parser(&a.parser), &opts).map_err(|e| e.to_string())?;
    for s in &results.steps {
        let status = serde_json::to_value(s.status)
            .ok()
            .and_then(|v| v.as_str().map(str::to_owned))
            .unwrap_or_default();
        println!(
            "  {:>2}. {:<20} {:>8.3}s  {}",
            s.step, status, s.duration_s, s.say
        );
    }
    if let Some(out) = out {
        println!("  -> {}", out.join("results.json").display());
    }
    Ok(())
}

/// The request for `POST /api/v1/sessions`: the session text, with the
/// local files it names (`transcript`, `speakers`) sent along, since the
/// server cannot read the caller's disk.
fn remote_body(path: &Path, text: &str) -> Result<serde_json::Value, String> {
    let yaml: serde_yaml::Value =
        serde_yaml::from_str(text).map_err(|e| format!("{}: {e}", path.display()))?;
    let base = path.parent().unwrap_or(Path::new("."));
    let mut body = serde_json::json!({ "session": text });
    for field in ["transcript", "speakers"] {
        let Some(named) = yaml.get(field).and_then(|v| v.as_str()) else {
            continue;
        };
        if named.contains("://") {
            continue;
        }
        let file = base.join(named);
        let contents =
            std::fs::read_to_string(&file).map_err(|e| format!("{}: {e}", file.display()))?;
        body[field] =
            serde_json::from_str(&contents).map_err(|e| format!("{}: {e}", file.display()))?;
    }
    if let Some(video) = yaml.get("video").and_then(|v| v.as_str()) {
        if !video.contains("://") {
            return Err(format!(
                "{}: `video` is a local file; the API takes videos as URLs here                  (upload with POST /api/v1/sessions multipart instead)",
                path.display()
            ));
        }
    }
    Ok(body)
}

/// Plays a session on the HTTP service: `POST /api/v1/sessions` with an
/// Idempotency-Key from what is sent (a rerun never repeats the
/// work), waits for the job, and downloads its results.
fn run_remote(path: &Path, api: &str, out: Option<PathBuf>) -> Result<(), String> {
    use sha2::{Digest, Sha256};
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let json = |r: ureq::Response| -> serde_json::Value {
        serde_json::from_str(&r.into_string().unwrap_or_default()).unwrap_or_default()
    };
    let body = remote_body(path, &text)?.to_string();
    // From everything sent, so a changed transcript is new work.
    let key = format!("batch-{:x}", Sha256::digest(body.as_bytes()));
    let accepted = match ureq::post(&format!("{api}/api/v1/sessions"))
        .set("content-type", "application/json")
        .set("Idempotency-Key", &key)
        .send_string(&body)
    {
        Ok(r) => json(r),
        Err(ureq::Error::Status(code, r)) => return Err(format!("{code}: {}", json(r)["error"])),
        Err(e) => return Err(e.to_string()),
    };
    let job_id = accepted["job_id"]
        .as_str()
        .ok_or("no job_id in the reply")?
        .to_owned();
    let job = loop {
        let j = json(
            ureq::get(&format!("{api}/api/v1/jobs/{job_id}"))
                .call()
                .map_err(|e| e.to_string())?,
        );
        match j["status"].as_str() {
            Some("succeeded") | Some("failed") => break j,
            _ => std::thread::sleep(std::time::Duration::from_millis(500)),
        }
    };
    if job["status"] != "succeeded" {
        return Err(format!("job {job_id} failed: {}", job["error"]));
    }
    for s in job["result"]["steps"].as_array().into_iter().flatten() {
        println!(
            "  {:>2}. {:<20} {:>8.3}s  {}",
            s["step"],
            s["status"].as_str().unwrap_or(""),
            s["duration_s"].as_f64().unwrap_or(0.0),
            s["say"].as_str().unwrap_or("")
        );
    }
    if let Some(out) = out {
        std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
        for (field, file) in [
            ("results", "results.json"),
            ("timeline", "timeline.json"),
            ("history", "history.json"),
            ("otio", "timeline.otio"),
            ("video", "video.mp4"),
        ] {
            if let Some(url) = job["result"]["links"][field].as_str() {
                let mut bytes = Vec::new();
                let r = ureq::get(url).call().map_err(|e| format!("{field}: {e}"))?;
                std::io::Read::read_to_end(&mut r.into_reader(), &mut bytes)
                    .map_err(|e| e.to_string())?;
                std::fs::write(out.join(file), bytes).map_err(|e| e.to_string())?;
            }
        }
        println!("  -> {}", out.join("results.json").display());
    }
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("metrics") {
        return metrics(&args[1..]);
    }
    let (cmd, rest) = match args.first().map(String::as_str) {
        Some("session") | Some("batch") if args.get(1).map(String::as_str) == Some("run") => {
            (args[0].as_str(), &args[2..])
        }
        Some("check") => ("check", &args[1..]),
        _ => {
            eprintln!("{USAGE}");
            return ExitCode::from(2);
        }
    };
    let a = match parse(rest, if cmd == "check" { "rules" } else { "auto" }) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    match cmd {
        "session" => {
            let path = &a.paths[0];
            println!("{}", path.display());
            match run_one(path, &a, a.out.clone()) {
                Ok(()) => ExitCode::SUCCESS,
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::FAILURE
                }
            }
        }
        "batch" => {
            let mut failed = 0;
            let files = sessions(&a.paths);
            for path in &files {
                println!("{}", path.display());
                let stem = path
                    .file_stem()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default();
                let out = a.out.as_ref().map(|o| o.join(&stem));
                let ran = match &a.api {
                    Some(api) => run_remote(path, api, out),
                    None => run_one(path, &a, out),
                };
                if let Err(e) = ran {
                    eprintln!("  error: {e}");
                    failed += 1;
                }
            }
            println!("{} sessions, {failed} failed to run", files.len());
            if failed == 0 {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
        _ => {
            let files = sessions(&a.paths);
            let mut bad = 0;
            for path in &files {
                let outcome = (|| -> Result<Vec<String>, String> {
                    let file = load(path).map_err(|e| e.to_string())?;
                    let opts = RunOptions {
                        out: None,
                        render: false,
                        ..Default::default()
                    };
                    let (first, session) =
                        run(path, parser(&a.parser), &opts).map_err(|e| e.to_string())?;
                    let mut problems = check(&file, &first, &session);
                    for k in 2..=3 {
                        let (again, _) =
                            run(path, parser(&a.parser), &opts).map_err(|e| e.to_string())?;
                        let a_hashes: Vec<_> =
                            first.steps.iter().map(|s| &s.timeline_hash).collect();
                        let b_hashes: Vec<_> =
                            again.steps.iter().map(|s| &s.timeline_hash).collect();
                        if a_hashes != b_hashes {
                            problems.push(format!("run {k} gave different timeline hashes"));
                        }
                    }
                    Ok(problems)
                })();
                match outcome {
                    Ok(p) if p.is_empty() => println!("ok    {}", path.display()),
                    Ok(p) => {
                        bad += 1;
                        println!("FAIL  {}", path.display());
                        for line in p {
                            println!("      {line}");
                        }
                    }
                    Err(e) => {
                        bad += 1;
                        println!("ERROR {}: {e}", path.display());
                    }
                }
            }
            println!(
                "{} sessions, {} passed, {bad} failed (each run 3 times)",
                files.len(),
                files.len() - bad
            );
            if bad == 0 {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            }
        }
    }
}

/// `incubrix metrics`: measures the Metrics tab's numbers and writes
/// `metrics.json` and `METRICS.md`.
fn metrics(args: &[String]) -> ExitCode {
    let mut folder = incubrix_cli::metrics::fixtures();
    let mut out = PathBuf::from("metrics");
    let mut render = true;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--out" => {
                i += 1;
                match args.get(i) {
                    Some(o) => out = PathBuf::from(o),
                    None => {
                        eprintln!("--out needs a folder");
                        return ExitCode::from(2);
                    }
                }
            }
            "--no-render" => render = false,
            s => folder = PathBuf::from(s),
        }
        i += 1;
    }
    let m = incubrix_cli::metrics::measure(&folder, &out.join("work"), render);
    let md = incubrix_cli::metrics::markdown(&m);
    let written = std::fs::create_dir_all(&out)
        .and_then(|_| {
            std::fs::write(
                out.join("metrics.json"),
                serde_json::to_string_pretty(&m).unwrap_or_default(),
            )
        })
        .and_then(|_| std::fs::write(out.join("METRICS.md"), &md));
    print!("{md}");
    match written {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
