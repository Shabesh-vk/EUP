//! Phase 6 "done when": the brief's worked example, typed as words on a real
//! 4-minute video, ends with step 8 - render - and the render passes the
//! frame checks: length and A/V start within one frame, source untouched.

mod common;

use std::path::Path;
use std::process::Command;

use incubrix_core::{Project, Status};
use incubrix_media::probe::{ffmpeg_bin, probe};
use incubrix_media::render::{render, RenderOptions};
use incubrix_nlu::{Action, RulesParser, Session};

#[test]
fn step_8_render_matches_the_timeline() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("worked-render");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let video = dir.join("talk.mp4");
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
    let source = probe(&video).unwrap().source;
    let mut s = Session::new(
        Project::new(source, common::worked().project.transcript),
        Box::new(RulesParser),
    );

    for step in [
        "Add a caption 'Welcome!' when I say welcome to the channel",
        "Cut the first 30 seconds",
        "Remove the part about pricing",
    ] {
        s.say(step);
    }
    assert_eq!(s.answer("the second one").outcome.status, Status::Applied);
    for step in [
        "Speed up from 1:00 to 1:30 by 2x",
        "Actually, put the intro back",
        "Undo",
        "Make that caption red",
    ] {
        assert_eq!(s.say(step).outcome.status, Status::Applied, "{step}");
    }
    let r = s.say("render");
    assert_eq!(r.action, Some(Action::Render));

    let out = dir.join("step8.mp4");
    let report = render(&s.project, &out, &RenderOptions::default()).unwrap();
    eprintln!("{:?}", report.check);
    assert!(report.check.ok, "{:?}", report.check);
    // 193 s, within a frame: some ffmpeg builds pad the AAC track by ~7 ms,
    // which makes the generated source itself a little over 240 s.
    assert!(
        (report.check.expected_us - 193_000_000).abs() < report.check.frame_us,
        "{}",
        report.check.expected_us
    );
    assert!(report.check.length_diff_frames <= 1.0);
    assert!(report.check.av_offset_frames <= 1.0);
    assert!(report.source_unchanged);
    assert_eq!(report.burned_captions, 1, "the red Welcome! caption");
}
