//! Phase 6: rendering from the timeline only, checked after every render:
//! length and A/V start within one frame of the timeline, source untouched.
//!
//! Videos are made by ffmpeg in the test (test pattern + tone); the test is
//! skipped, with a message, where ffmpeg is not installed.

use std::path::{Path, PathBuf};
use std::process::Command;

use incubrix_core::{secs, Anchor, CaptionStyle, CutReason, Op, Project, SrcRange, StylePatch};
use incubrix_media::probe::ffmpeg_bin;
use incubrix_media::render::{render, verify, RenderOptions};
use incubrix_media::{intake, FixtureTranscriber};

fn scratch(name: &str) -> PathBuf {
    let d = Path::new(env!("CARGO_TARGET_TMPDIR")).join(name);
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/media")
}

/// A test video: pattern + 440 Hz tone, at 29.97 fps.
fn make_video(dir: &Path, name: &str, seconds: u32) -> Option<PathBuf> {
    let out = dir.join(name);
    let ok = Command::new(ffmpeg_bin())
        .args(["-v", "error", "-y", "-f", "lavfi", "-i"])
        .arg(format!(
            "testsrc=size=160x90:rate=30000/1001:duration={seconds}"
        ))
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
        eprintln!("ffmpeg not available: skipping render test");
    }
    ok.then_some(out)
}

fn make_music(dir: &Path) -> PathBuf {
    let out = dir.join("bed.m4a");
    Command::new(ffmpeg_bin())
        .args([
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=3",
            "-c:a",
            "aac",
        ])
        .arg(&out)
        .status()
        .unwrap();
    out
}

/// The single-speaker fixture's words on a 12 s test video.
fn project(dir: &Path) -> Option<Project> {
    let video = make_video(dir, "talk.mp4", 12)?;
    let t = FixtureTranscriber::new(fixtures().join("single_speaker.words.json"));
    Some(intake(&video, &t, None, None).unwrap().into_project())
}

fn cut(a: f64, b: f64) -> Op {
    Op::Cut {
        ranges: vec![SrcRange::new(secs(a), secs(b)).unwrap()],
        reason: CutReason::User,
    }
}

fn words(first: &str, last: &str) -> Anchor {
    Anchor::Words {
        first: first.into(),
        last: last.into(),
    }
}

#[test]
fn an_untouched_timeline_renders_to_its_own_length() {
    let dir = scratch("render-plain");
    let Some(p) = project(&dir) else { return };
    let r = render(&p, &dir.join("out.mp4"), &RenderOptions::default()).unwrap();
    eprintln!("{:?}", r.check);
    assert!(r.check.ok, "{:?}", r.check);
    assert!(r.check.length_diff_frames <= 1.0, "{:?}", r.check);
    assert!(r.check.av_offset_frames <= 1.0, "{:?}", r.check);
    assert!(r.source_unchanged);
}

#[test]
fn every_kind_of_edit_renders_within_one_frame() {
    let dir = scratch("render-mix");
    let Some(mut p) = project(&dir) else { return };
    let music = make_music(&dir);
    p.apply("cut", vec![cut(9.0, 10.5)]).unwrap();
    p.apply(
        "speed",
        vec![Op::Speed {
            range: SrcRange::new(secs(4.0), secs(6.0)).unwrap(),
            speed: 2000,
        }],
    )
    .unwrap();
    p.apply(
        "caption",
        vec![Op::AddCaption {
            id: "cap_1".into(),
            anchor: words("w00003", "w00006"),
            text: "Welcome!".into(),
            style: CaptionStyle::default(),
        }],
    )
    .unwrap();
    p.apply(
        "style",
        vec![Op::StyleCaption {
            id: "cap_1".into(),
            patch: StylePatch {
                color: Some("#FF0000".into()),
                position: Some("top".into()),
                ..Default::default()
            },
        }],
    )
    .unwrap();
    p.apply(
        "mute",
        vec![Op::Mute {
            id: "mute_1".into(),
            anchor: words("w00000", "w00001"),
        }],
    )
    .unwrap();
    p.apply(
        "bleep",
        vec![Op::Bleep {
            id: "bleep_1".into(),
            anchor: words("w00012", "w00012"),
        }],
    )
    .unwrap();
    p.apply(
        "music",
        vec![Op::AddMusic {
            id: "music_1".into(),
            path: music.to_string_lossy().into(),
            volume_db: -18,
            duck_db: 12,
        }],
    )
    .unwrap();
    let expected = p.timeline().timeline.duration;
    let r = render(&p, &dir.join("out.mp4"), &RenderOptions::default()).unwrap();
    eprintln!("{:?}", r.check);
    assert!(r.check.ok, "{:?}", r.check);
    assert_eq!(r.check.expected_us, expected);
    assert!(r.source_unchanged);
    assert!(r.burned_captions == 1, "{r:?}");
}

#[test]
fn extreme_speeds_and_many_cuts_stay_in_sync() {
    let dir = scratch("render-many");
    let Some(mut p) = project(&dir) else { return };
    p.apply(
        "speeds",
        vec![
            Op::Speed {
                range: SrcRange::new(secs(0.0), secs(2.0)).unwrap(),
                speed: 4000,
            },
            Op::Speed {
                range: SrcRange::new(secs(2.0), secs(3.0)).unwrap(),
                speed: 250,
            },
        ],
    )
    .unwrap();
    // 20 small cuts, none on a frame boundary.
    let ranges: Vec<SrcRange> = (0..20)
        .map(|i| {
            let a = 3.5 + i as f64 * 0.4;
            SrcRange::new(secs(a + 0.013), secs(a + 0.171)).unwrap()
        })
        .collect();
    p.apply(
        "many",
        vec![Op::Cut {
            ranges,
            reason: CutReason::Silence,
        }],
    )
    .unwrap();
    let r = render(&p, &dir.join("out.mp4"), &RenderOptions::default()).unwrap();
    eprintln!("{:?}", r.check);
    assert!(r.check.ok, "{:?}", r.check);
    assert!(
        r.check.length_diff_frames <= 1.0 && r.check.av_offset_frames <= 1.0,
        "{:?}",
        r.check
    );
}

#[test]
fn verify_fails_loudly_on_a_wrong_length() {
    let dir = scratch("render-wrong");
    let Some(video) = make_video(&dir, "ten.mp4", 10) else {
        return;
    };
    // Claim the timeline is 11 s: the 10 s file is 30 frames short.
    let c = verify(&video, secs(11.0), (30000, 1001), true).unwrap();
    assert!(!c.ok);
    assert!(c.length_diff_frames > 25.0, "{c:?}");
    assert!(c.problems.iter().any(|p| p.contains("length")), "{c:?}");
}
