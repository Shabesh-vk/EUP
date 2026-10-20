//! Phase 7 "done when": every scripted scenario in `fixtures/sessions`
//! meets its expected results, three runs give the same timeline hashes,
//! and the worked example plays on a real video through to the render.

use std::path::{Path, PathBuf};
use std::process::Command;

use incubrix_cli::{check, load, run, RunOptions};
use incubrix_media::probe::ffmpeg_bin;
use incubrix_nlu::RulesParser;

fn sessions_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/sessions")
}

fn all_sessions() -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(sessions_dir())
        .unwrap()
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "yaml"))
        .collect();
    v.sort();
    v
}

#[test]
fn at_least_forty_scenarios_meet_their_expectations() {
    let files = all_sessions();
    assert!(files.len() >= 40, "only {} scenarios", files.len());
    let mut failures = Vec::new();
    for path in &files {
        let file = load(path).unwrap();
        let (results, session) = run(path, Box::new(RulesParser), &RunOptions::default()).unwrap();
        for f in check(&file, &results, &session) {
            failures.push(format!(
                "{}: {f}",
                path.file_name().unwrap().to_string_lossy()
            ));
        }
        // Every step got one of the three answers and the policy.
        assert!(results.steps.iter().all(|s| !s.timeline_hash.is_empty()));
        assert_eq!(results.time_policy, "current");
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn every_scenario_gives_the_same_hashes_three_times() {
    for path in all_sessions() {
        let hashes = || -> Vec<String> {
            let (r, _) = run(&path, Box::new(RulesParser), &RunOptions::default()).unwrap();
            r.steps.into_iter().map(|s| s.timeline_hash).collect()
        };
        let a = hashes();
        assert_eq!(a, hashes(), "{}", path.display());
        assert_eq!(a, hashes(), "{}", path.display());
    }
}

#[test]
fn a_wrong_expectation_is_reported() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("wrong-expect");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("wrong.yaml");
    std::fs::write(
        &path,
        "source:\n  duration_s: 60\nsteps:\n  - say: \"cut the first 10 seconds\"\n    expect:\n      status: \"applied\"\n      duration_s: 55.0\n",
    )
    .unwrap();
    let file = load(&path).unwrap();
    let (results, session) = run(&path, Box::new(RulesParser), &RunOptions::default()).unwrap();
    let f = check(&file, &results, &session);
    assert_eq!(f.len(), 1, "{f:?}");
    assert!(f[0].contains("duration 50 s, expected 55 s"), "{f:?}");
}

/// The worked example as the brief runs it: a session file naming a video,
/// played by the runner, with `results.json`, the timeline and the render
/// written out.
#[test]
fn worked_example_on_a_real_video_writes_results_and_renders() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("worked-session");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let video = dir.join("interview.mp4");
    let made = Command::new(ffmpeg_bin())
        .args([
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=30000/1001:duration=240",
        ])
        .args(["-f", "lavfi", "-i", "sine=frequency=440:duration=240"])
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
        .arg(&video)
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !made {
        eprintln!("ffmpeg not available: skipping");
        return;
    }
    // The words of the worked example's video, as a recogniser would give them.
    let script = load(&sessions_dir().join("01_worked_example.yaml")).unwrap();
    let words = incubrix_cli::synthetic_transcript(&script.source.unwrap().lines);
    std::fs::write(
        dir.join("interview.words.json"),
        serde_json::to_string(&words).unwrap(),
    )
    .unwrap();
    std::fs::write(
        dir.join("session.yaml"),
        "video: interview.mp4\ntranscript: interview.words.json\nsteps:\n\
         - say: \"Add a caption 'Welcome!' when I say welcome to the channel\"\n\
         - say: \"Cut the first 30 seconds\"\n\
         - say: \"Remove the part about pricing\"\n  answer: \"the second one\"\n\
         - say: \"Speed up from 1:00 to 1:30 by 2x\"\n\
         - say: \"Actually, put the intro back\"\n\
         - say: \"Undo\"\n\
         - say: \"Make that caption red\"\n\
         - say: \"render\"\n",
    )
    .unwrap();
    let out = dir.join("out");
    let opts = RunOptions {
        out: Some(out.clone()),
        render: true,
    };
    let (results, _) = run(&dir.join("session.yaml"), Box::new(RulesParser), &opts).unwrap();

    let durations: Vec<f64> = results.steps.iter().map(|s| s.duration_s).collect();
    assert_eq!(
        durations,
        [240.0, 210.0, 208.0, 193.0, 223.0, 193.0, 193.0, 193.0]
    );
    assert!(results.steps[2]
        .question
        .as_deref()
        .unwrap()
        .contains("mentioned 3 times"));
    assert_eq!(results.source_sha256.len(), 64);
    let render = &results.steps[7];
    assert!(render.video.is_some(), "{render:?}");
    assert!(
        render
            .warnings
            .iter()
            .any(|w| w.starts_with("Render checked")),
        "{:?}",
        render.warnings
    );
    for f in [
        "results.json",
        "timeline.json",
        "history.json",
        "timeline.otio",
        "render_step8.mp4",
    ] {
        assert!(out.join(f).is_file(), "{f} written");
    }
    // results.json carries the brief's fields for every step.
    let json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(out.join("results.json")).unwrap()).unwrap();
    for step in json["steps"].as_array().unwrap() {
        for key in [
            "status",
            "operations",
            "summary",
            "question",
            "options",
            "timeline_hash",
            "duration_s",
        ] {
            assert!(step.get(key).is_some(), "missing {key}");
        }
    }
}
