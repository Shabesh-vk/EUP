//! `incubrix` - the session runner.
//!
//! ```text
//! incubrix session run <session.yaml> [--out DIR] [--no-render] [--parser rules|auto]
//! incubrix batch run <folder|session.yaml> [--out DIR] [--no-render] [--parser rules|auto]
//! incubrix check <folder|session.yaml>... [--parser rules|auto]
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
  incubrix batch run <folder|session.yaml> [--out DIR] [--no-render] [--parser rules|auto]
  incubrix check <folder|session.yaml>... [--parser rules|auto]";

struct Args {
    paths: Vec<PathBuf>,
    out: Option<PathBuf>,
    render: bool,
    parser: String,
}

fn parse(args: &[String], default_parser: &str) -> Result<Args, String> {
    let mut a = Args {
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

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
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
                if let Err(e) = run_one(path, &a, out) {
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
