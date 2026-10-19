//! Phase 4 "done when": a single-speaker and a two-speaker test video give
//! transcripts with word ids, speakers and confidences, and the fixture
//! adapters reproduce the golden files byte for byte.
//!
//! The test videos are made with ffmpeg (tone + test pattern); the words
//! come from recorded recogniser output, so no model is needed. Set
//! `UPDATE_GOLDEN=1` to rewrite the golden files after a deliberate change.

use std::path::{Path, PathBuf};
use std::process::Command;

use incubrix_core::{secs, SourceInfo};
use incubrix_media::cache::CachedTranscript;
use incubrix_media::intake::transcribe_and_label;
use incubrix_media::probe::{ffmpeg_bin, parse_probe};
use incubrix_media::{intake, FixtureDiarizer, FixtureTranscriber, MediaError, TranscriptCache};

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/media")
}

fn scratch(name: &str) -> PathBuf {
    let d = Path::new(env!("CARGO_TARGET_TMPDIR")).join(name);
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// A 12 s 160x90 test video; `None` when ffmpeg is not installed.
fn make_video(dir: &Path, name: &str, audio: bool) -> Option<PathBuf> {
    let out = dir.join(name);
    let mut cmd = Command::new(ffmpeg_bin());
    cmd.args(["-v", "error", "-y", "-f", "lavfi", "-i"])
        .arg("testsrc=size=160x90:rate=30000/1001:duration=12");
    if audio {
        cmd.args([
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=12",
            "-c:a",
            "aac",
        ]);
    }
    cmd.args(["-c:v", "mpeg4", "-shortest"]).arg(&out);
    match cmd.status() {
        Ok(s) if s.success() => Some(out),
        _ => {
            eprintln!("ffmpeg not available: skipping the video part of this test");
            None
        }
    }
}

fn golden(name: &str, entry: &CachedTranscript) {
    let path = fixtures().join(name);
    let json = serde_json::to_string_pretty(entry).unwrap() + "\n";
    if std::env::var_os("UPDATE_GOLDEN").is_some() {
        std::fs::write(&path, &json).unwrap();
    }
    let want = std::fs::read_to_string(&path).expect("golden file");
    assert_eq!(json, want, "{name} differs from the golden file");
}

fn twelve_seconds() -> SourceInfo {
    SourceInfo::with_duration(secs(12.0))
}

#[test]
fn single_speaker_transcript_matches_golden() {
    let t = FixtureTranscriber::new(fixtures().join("single_speaker.words.json"));
    let (transcript, warnings) =
        transcribe_and_label(Path::new("x.mp4"), &twelve_seconds(), &t, None).unwrap();
    assert!(transcript.words.iter().all(|w| w.speaker == "S1"));
    assert!(transcript.words.iter().any(|w| w.confidence < 0.5));
    assert_eq!(transcript.words[0].id, "w00000");
    assert_eq!(
        transcript.words[1].text, "everyone,",
        "punctuation kept on its word"
    );
    assert!(
        warnings.iter().any(|w| w.contains("'simple.' at 0:07.9")),
        "{warnings:?}"
    );
    golden(
        "single_speaker.transcript.json",
        &CachedTranscript {
            transcript,
            warnings,
        },
    );
}

#[test]
fn two_speaker_transcript_matches_golden() {
    let t = FixtureTranscriber::new(fixtures().join("two_speakers.words.json"));
    let d = FixtureDiarizer::new(fixtures().join("two_speakers.turns.json"));
    let (transcript, warnings) =
        transcribe_and_label(Path::new("x.mp4"), &twelve_seconds(), &t, Some(&d)).unwrap();
    let by = |text: &str| {
        transcript
            .words
            .iter()
            .find(|w| w.text.trim_end_matches(['.', ',', '?']) == text)
            .unwrap()
            .speaker
            .clone()
    };
    assert_eq!(by("before"), "S1", "host asks");
    assert_eq!(by("bank"), "S2", "guest answers");
    assert_eq!(by("Interesting"), "S1");
    assert!(
        warnings
            .iter()
            .any(|w| w.starts_with("Overlapping speech") && w.contains("boring")),
        "{warnings:?}"
    );
    assert!(
        warnings
            .iter()
            .any(|w| w.contains("swap") && w.contains("'hours'")),
        "{warnings:?}"
    );
    golden(
        "two_speakers.transcript.json",
        &CachedTranscript {
            transcript,
            warnings,
        },
    );
}

#[test]
fn fixture_run_is_identical_every_time() {
    let t = FixtureTranscriber::new(fixtures().join("two_speakers.words.json"));
    let d = FixtureDiarizer::new(fixtures().join("two_speakers.turns.json"));
    let run = || transcribe_and_label(Path::new("x.mp4"), &twelve_seconds(), &t, Some(&d)).unwrap();
    let a = run();
    assert_eq!(a, run());
    assert_eq!(a, run());
}

#[test]
fn videos_go_through_intake_with_hash_and_cache() {
    let dir = scratch("intake");
    let Some(single) = make_video(&dir, "single.mp4", true) else {
        return;
    };
    let Some(two) = make_video(&dir, "two.mov", true) else {
        return;
    };
    let cache = TranscriptCache::new(dir.join("cache"));
    let t1 = FixtureTranscriber::new(fixtures().join("single_speaker.words.json"));
    let t2 = FixtureTranscriber::new(fixtures().join("two_speakers.words.json"));
    let d2 = FixtureDiarizer::new(fixtures().join("two_speakers.turns.json"));

    let a = intake(&single, &t1, None, Some(&cache)).unwrap();
    assert_eq!(a.source.sha256.len(), 64);
    assert_eq!((a.source.fps_num, a.source.fps_den), (30000, 1001));
    assert!(a.source.has_audio);
    assert!(
        (a.source.duration - secs(12.0)).abs() < secs(0.1),
        "{}",
        a.source.duration
    );
    assert!(!a.cached);
    assert!(a
        .transcript
        .words
        .iter()
        .all(|w| !w.id.is_empty() && w.speaker == "S1"));

    let b = intake(&two, &t2, Some(&d2), Some(&cache)).unwrap();
    let speakers: std::collections::BTreeSet<_> = b
        .transcript
        .words
        .iter()
        .map(|w| w.speaker.as_str())
        .collect();
    assert_eq!(speakers.into_iter().collect::<Vec<_>>(), ["S1", "S2"]);

    // Second time: from the cache, same words, same source hash.
    let again = intake(&two, &t2, Some(&d2), Some(&cache)).unwrap();
    assert!(again.cached);
    assert_eq!(again.transcript, b.transcript);
    assert_eq!(again.source.sha256, b.source.sha256);
    incubrix_media::hash::verify_unchanged(&two, &b.source.sha256).unwrap();
}

#[test]
fn no_audio_works_and_says_so() {
    let dir = scratch("noaudio");
    let Some(v) = make_video(&dir, "silent.mp4", false) else {
        return;
    };
    let t = FixtureTranscriber::new(fixtures().join("single_speaker.words.json"));
    let i = intake(&v, &t, None, None).unwrap();
    assert!(!i.source.has_audio);
    assert!(i.transcript.words.is_empty());
    assert!(i.warnings.iter().any(|w| w.contains("no sound")));
}

#[test]
fn other_formats_fail_clearly() {
    let t = FixtureTranscriber::new(fixtures().join("single_speaker.words.json"));
    let e = intake(Path::new("talk.mkv"), &t, None, None).unwrap_err();
    assert_eq!(e.code(), "UNSUPPORTED_FORMAT");
    assert!(e.to_string().contains("only MP4 and MOV"));

    let e = parse_probe(
        r#"{"streams":[{"codec_type":"video","r_frame_rate":"25/1","avg_frame_rate":"25/1"}],
            "format":{"format_name":"matroska,webm","duration":"3.0"}}"#,
        "x.mp4",
    )
    .unwrap_err();
    assert!(matches!(e, MediaError::Unsupported(_)));

    let e = parse_probe(
        r#"{"streams":[{"codec_type":"audio"}],"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"3.0"}}"#,
        "x.mp4",
    )
    .unwrap_err();
    assert_eq!(e.code(), "NO_VIDEO_STREAM");
}

#[test]
fn phone_video_with_variable_frame_rate_is_flagged() {
    // Recorded from an iPhone clip: base 30 fps, measured average lower.
    let p = parse_probe(
        r#"{"streams":[{"codec_type":"video","r_frame_rate":"30/1","avg_frame_rate":"2589000/86621","width":1920,"height":1080},
                       {"codec_type":"audio"}],
            "format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"2.887367"}}"#,
        "phone.mov",
    )
    .unwrap();
    assert!(p.source.variable_frame_rate);
    assert_eq!(p.source.duration, 2_887_367);
    assert!(p.warnings.iter().any(|w| w.contains("Variable frame rate")));
}
