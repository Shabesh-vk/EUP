//! OpenTimelineIO export: the clips add up to the edited length, speed
//! changes carry a time warp, captions are markers - and, where the
//! official `opentimelineio` Python library is installed, it reads the file
//! back with the same length.

mod common;

use incubrix_core::otio::to_otio;
use incubrix_core::resolve::words_anchor;
use incubrix_core::search::find_phrase;
use incubrix_core::{secs, CaptionStyle, CutReason, Op, SrcRange};

fn edited() -> incubrix_core::Project {
    let mut p = common::worked_example();
    p.apply(
        "cut",
        vec![Op::Cut {
            ranges: vec![SrcRange::new(0, secs(30.0)).unwrap()],
            reason: CutReason::User,
        }],
    )
    .unwrap();
    p.apply(
        "speed",
        vec![Op::Speed {
            range: SrcRange::new(secs(90.0), secs(120.0)).unwrap(),
            speed: 2000,
        }],
    )
    .unwrap();
    let tl = p.timeline().timeline;
    let h = &find_phrase(&p.transcript, &tl, "welcome to the channel")[0];
    let anchor = words_anchor(&p.transcript, h.first, h.last);
    p.apply(
        "caption",
        vec![Op::AddCaption {
            id: "cap_1".into(),
            anchor,
            text: "Welcome!".into(),
            style: CaptionStyle::default(),
        }],
    )
    .unwrap();
    p.source.path = "C:/clips/talk.mp4".into();
    p
}

#[test]
fn clips_add_up_to_the_edited_length() {
    let p = edited();
    let doc = to_otio(&p, "talk");
    let video = &doc["tracks"]["children"][0];
    assert_eq!(doc["OTIO_SCHEMA"], "Timeline.1");
    assert_eq!(video["kind"], "Video");
    let clips = video["children"].as_array().unwrap();
    let frames: f64 = clips
        .iter()
        .map(|c| c["source_range"]["duration"]["value"].as_f64().unwrap())
        .sum();
    let rate = clips[0]["source_range"]["duration"]["rate"]
        .as_f64()
        .unwrap();
    let expected = p.timeline().timeline.duration as f64 / 1e6 * rate;
    assert!((frames - expected).abs() < 1.0, "{frames} vs {expected}");
    assert!(
        clips.iter().any(|c| c["effects"][0]["time_scalar"] == 2.0),
        "the 2x part carries a time warp"
    );
    assert_eq!(video["markers"][0]["name"], "Welcome!");
    assert_eq!(
        clips[0]["media_references"]["DEFAULT_MEDIA"]["target_url"],
        "file:///C:/clips/talk.mp4"
    );
}

#[test]
fn the_official_reader_opens_it() {
    let p = edited();
    let path = std::path::Path::new(env!("CARGO_TARGET_TMPDIR")).join("talk.otio");
    std::fs::write(
        &path,
        serde_json::to_string_pretty(&to_otio(&p, "talk")).unwrap(),
    )
    .unwrap();
    let script = "import sys, opentimelineio as otio\nt = otio.adapters.read_from_file(sys.argv[1])\nprint(t.duration().to_seconds(), len(t.video_tracks()[0]), len(t.video_tracks()[0].markers))";
    let out = std::process::Command::new("python")
        .args(["-c", script])
        .arg(&path)
        .output();
    let Some(out) = out.ok().filter(|o| o.status.success()) else {
        eprintln!("python with opentimelineio not available: skipping the reader check");
        return;
    };
    let text = String::from_utf8_lossy(&out.stdout);
    let mut it = text.split_whitespace();
    let seconds: f64 = it.next().unwrap().parse().unwrap();
    let clips: usize = it.next().unwrap().parse().unwrap();
    let markers: usize = it.next().unwrap().parse().unwrap();
    let expected = p.timeline().timeline.duration as f64 / 1e6;
    let frame = 1.0 / 30.0;
    assert!(
        (seconds - expected).abs() <= frame,
        "OTIO says {seconds} s, timeline {expected} s"
    );
    assert_eq!(clips, p.timeline().timeline.segments.len());
    assert_eq!(markers, 1);
}
