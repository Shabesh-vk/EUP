//! The numbers the brief's Metrics tab asks for, measured, not estimated.
//!
//! - Instruction latency on a 5-minute and a 60-minute interview (median and
//!   slowest, transcription and rendering excluded).
//! - Determinism: every scenario played 3 times, final hashes compared.
//! - Clarification quality: ambiguous instructions that asked or stated an
//!   assumption, versus guessed.
//! - Word clipping: 20 cuts at awkward times, each edge checked against the
//!   words it lands near.
//! - Render accuracy (with a real video, when ffmpeg is installed).
//! - Cost per minute of video.

use std::path::Path;
use std::time::Instant;

use incubrix_core::{secs, Project, SourceInfo, Status, Transcript, Us, Word};
use incubrix_nlu::{RulesParser, Session};
use serde::Serialize;

use crate::{run, RunOptions};

/// Latency on one video length.
#[derive(Clone, Debug, Serialize)]
pub struct Latency {
    /// Video length, minutes.
    pub minutes: u32,
    /// Words in its transcript.
    pub words: usize,
    /// Instructions timed.
    pub instructions: usize,
    /// Median response, milliseconds.
    pub median_ms: f64,
    /// Slowest response, milliseconds.
    pub slowest_ms: f64,
    /// The slowest instruction.
    pub slowest: String,
    /// Every instruction and its time.
    pub each: Vec<(String, f64)>,
}

/// One render measured against its timeline.
#[derive(Clone, Debug, Serialize)]
pub struct RenderMeasure {
    /// What was rendered.
    pub session: String,
    /// |rendered length - timeline length|, frames.
    pub length_diff_frames: f64,
    /// Largest audio/video start offset, frames.
    pub av_offset_frames: f64,
}

/// Everything, as written to `metrics.json`.
#[derive(Clone, Debug, Serialize)]
pub struct Metrics {
    /// 5- and 60-minute latency.
    pub latency: Vec<Latency>,
    /// Sessions played 3 times.
    pub determinism_sessions: usize,
    /// Of those, how many gave the same hashes every time (percent).
    pub determinism_percent: f64,
    /// Ambiguous instructions found in the scenarios.
    pub ambiguous: usize,
    /// Of those, asked a question.
    pub asked: usize,
    /// Of those, applied while stating an assumption.
    pub stated_assumption: usize,
    /// Of those, had one candidate and named it in the reply.
    pub named_single: usize,
    /// Of those, refused with a reason.
    pub refused: usize,
    /// Of those, applied silently (a guess).
    pub guessed: usize,
    /// The ambiguous instructions and what happened.
    pub ambiguous_each: Vec<(String, String)>,
    /// Cuts checked for clipped words.
    pub cuts_checked: usize,
    /// Cut edges inside a word.
    pub clipped_words: usize,
    /// Renders measured (empty without ffmpeg).
    pub renders: Vec<RenderMeasure>,
    /// Largest length difference across renders, frames.
    pub worst_length_diff_frames: Option<f64>,
    /// Largest A/V offset across renders, frames.
    pub worst_av_offset_frames: Option<f64>,
    /// Speech-to-text cost per minute (local whisper).
    pub stt_cost_per_minute_usd: f64,
    /// Language-model cost per minute (rules parser; an LLM is optional).
    pub llm_cost_per_minute_usd: f64,
}

/// Instructions whose meaning is open: each must ask or state an assumption.
const AMBIGUOUS: &[&str] = &[
    "make it shorter",
    "remove the boring bit",
    "put back what i removed",
    "make that caption red",
    "remove the part about pricing",
    "make it bigger",
    "change the caption to",
    "remove the caption",
    "speed up 10x",
    "bleep the swearing",
];

/// Lines an interview might have; topic words appear again and again, so a
/// long video has many matches for "pricing" and "welcome".
const LINES: &[&str] = &[
    "Hi everyone and welcome to the channel",
    "Today we are talking about how small teams ship video faster",
    "Our pricing starts at ten dollars a month for each seat",
    "The cost goes down when you pay for a whole year up front",
    "Let me show you how the editor handles a long interview",
    "um so the first thing you notice is the timeline",
    "Every caption stays on the words it was written for",
    "If you cut a sentence the caption goes with it",
    "That is the key idea behind the whole design",
    "Thanks for watching and see you in the next one",
];

/// A synthetic interview `minutes` long: 0.3 s words, 0.1 s gaps, a 1.2 s
/// pause between lines, two speakers taking turns.
pub fn interview(minutes: u32) -> Transcript {
    let end = secs(minutes as f64 * 60.0);
    let mut words = Vec::new();
    let mut at = secs(1.0);
    let mut line = 0usize;
    while at < end - secs(10.0) {
        let speaker = if (line / 3).is_multiple_of(2) {
            "S1"
        } else {
            "S2"
        };
        for w in LINES[line % LINES.len()].split_whitespace() {
            words.push(Word {
                id: format!("w{:06}", words.len()),
                text: w.to_owned(),
                start: at,
                end: at + 300_000,
                speaker: speaker.to_owned(),
                confidence: 0.95,
            });
            at += 400_000;
        }
        at += 1_200_000;
        line += 1;
    }
    Transcript { words }
}

/// Instructions timed on each length (answers follow questions).
const TIMED: &[(&str, Option<&str>)] = &[
    (
        "Add a caption 'Welcome!' when I say welcome to the channel",
        Some("the first one"),
    ),
    ("Cut the first 30 seconds", None),
    ("Remove the part about pricing", Some("the first one")),
    ("Speed up from 1:00 to 1:30 by 2x", None),
    ("Actually, put the intro back", None),
    ("Undo", None),
    ("redo", None),
    ("Make that caption red", None),
    ("remove the ums", None),
    ("remove silences longer than 1 second", None),
    ("cut 2:00 to 2:10", None),
    ("slow down 3:00 to 3:10 by 2x", None),
    ("add a caption 'Late' at 4:00", None),
    ("bleep the word dollars", None),
    ("move 0:40 to 0:50 to the end", None),
    ("keep only 1:00 to 4:30", None),
    ("put back what I removed", Some("all of it")),
    ("auto-caption the whole video", None),
    ("how long is my video now?", None),
    ("undo", None),
];

fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}

/// Times every instruction in `TIMED` on an interview `minutes` long.
pub fn latency(minutes: u32) -> Latency {
    let transcript = interview(minutes);
    let words = transcript.words.len();
    let source = SourceInfo::with_duration(secs(minutes as f64 * 60.0));
    let mut session = Session::new(Project::new(source, transcript), Box::new(RulesParser));
    let mut each = Vec::new();
    for (say, answer) in TIMED {
        let t = Instant::now();
        let reply = session.say(say);
        each.push((say.to_string(), ms(t)));
        if let (Status::NeedsClarification, Some(a)) = (reply.outcome.status, answer) {
            let t = Instant::now();
            session.answer(a);
            each.push((format!("{say} -> {a}"), ms(t)));
        }
    }
    let mut times: Vec<f64> = each.iter().map(|e| e.1).collect();
    times.sort_by(f64::total_cmp);
    let median = if times.is_empty() {
        0.0
    } else if !times.len().is_multiple_of(2) {
        times[times.len() / 2]
    } else {
        (times[times.len() / 2 - 1] + times[times.len() / 2]) / 2.0
    };
    let (slowest, slowest_ms) = each
        .iter()
        .max_by(|a, b| a.1.total_cmp(&b.1))
        .cloned()
        .unwrap_or_default();
    Latency {
        minutes,
        words,
        instructions: each.len(),
        median_ms: median,
        slowest_ms,
        slowest,
        each,
    }
}

/// 20 cuts at times that fall inside words; counts edges left inside one.
pub fn word_clipping() -> (usize, usize) {
    let transcript = interview(5);
    let source = SourceInfo::with_duration(secs(300.0));
    let mut clipped = 0;
    let cuts = 20;
    for k in 0..cuts {
        // 0.13 s past a whole second lands mid-word for most lines.
        let a = 10 + k * 13;
        let say = format!(
            "cut {}:{:02}.13 to {}:{:02}.47",
            a / 60,
            a % 60,
            (a + 4) / 60,
            (a + 4) % 60
        );
        let mut session = Session::new(
            Project::new(source.clone(), transcript.clone()),
            Box::new(RulesParser),
        );
        session.say(&say);
        let tl = session.project.timeline().timeline;
        for s in &tl.segments {
            for edge in [s.source.start, s.source.end] {
                if inside_a_word(&transcript, edge) {
                    clipped += 1;
                }
            }
        }
    }
    (cuts as usize, clipped)
}

fn inside_a_word(t: &Transcript, at: Us) -> bool {
    t.words.iter().any(|w| w.start < at && at < w.end)
}

/// Every scenario 3 times; the share with identical hashes, and how the
/// ambiguous instructions were handled.
fn scenarios(dir: &Path) -> (usize, usize, Vec<(String, String)>) {
    let mut files: Vec<_> = std::fs::read_dir(dir)
        .map(|d| d.filter_map(Result::ok).map(|e| e.path()).collect())
        .unwrap_or_default();
    files.retain(|f| f.extension().is_some_and(|e| e == "yaml"));
    files.sort();
    let mut same = 0;
    let mut ambiguous = Vec::new();
    for f in &files {
        let runs: Vec<_> = (0..3)
            .filter_map(|_| run(f, Box::new(RulesParser), &RunOptions::default()).ok())
            .map(|(r, _)| r)
            .collect();
        let hashes: Vec<Vec<&String>> = runs
            .iter()
            .map(|r| r.steps.iter().map(|s| &s.timeline_hash).collect())
            .collect();
        if runs.len() == 3 && hashes.windows(2).all(|w| w[0] == w[1]) {
            same += 1;
        }
        let Some(r) = runs.first() else { continue };
        for s in &r.steps {
            let said = s.say.to_lowercase();
            if !AMBIGUOUS.iter().any(|a| said.starts_with(a)) {
                continue;
            }
            // The runner records the status after the answer, so a step
            // that was answered is one that asked.
            let how = match s.status {
                _ if s.answer.is_some() || s.question.is_some() => "asked",
                Status::NeedsClarification => "asked",
                _ if stated(s) => "stated an assumption",
                Status::Rejected => "refused with a reason",
                // One candidate (one caption, one listed word), named in the reply.
                Status::Applied if s.summary.contains('\'') => "one candidate, named in the reply",
                _ => "guessed",
            };
            ambiguous.push((s.say.clone(), how.to_owned()));
        }
    }
    (files.len(), same, ambiguous)
}

fn stated(s: &crate::StepResult) -> bool {
    let text = format!("{} {}", s.summary, s.warnings.join(" ")).to_lowercase();
    [
        "assum",
        "i took",
        "i used",
        "the last",
        "the only",
        "most recent",
        "i picked",
    ]
    .iter()
    .any(|k| text.contains(k))
}

/// Renders a few sessions on a generated 4-minute video and measures them.
fn renders(work: &Path) -> Vec<RenderMeasure> {
    use std::process::Command;
    let video = work.join("interview.mp4");
    let made = Command::new(incubrix_media::probe::ffmpeg_bin())
        .args(["-y", "-v", "error", "-f", "lavfi", "-i"])
        .arg("testsrc=size=160x90:rate=30000/1001:duration=240")
        .args(["-f", "lavfi", "-i", "sine=frequency=440:duration=240"])
        .args([
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
        ])
        .args(["-c:a", "aac", "-shortest"])
        .arg(&video)
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !made {
        return vec![];
    }
    let words: Vec<_> = interview(4)
        .words
        .into_iter()
        .map(|w| {
            serde_json::json!({"text": w.text, "start": w.start,
                "end": w.end, "confidence": w.confidence, "speaker": w.speaker})
        })
        .collect();
    let _ = std::fs::write(
        work.join("interview.words.json"),
        serde_json::json!({ "words": words }).to_string(),
    );
    let sessions: &[(&str, &str)] = &[
        (
            "worked example",
            "- say: \"Add a caption 'Welcome!' when I say welcome to the channel\"\n  answer: \"the first one\"\n\
             - say: \"Cut the first 30 seconds\"\n\
             - say: \"Remove the part about pricing\"\n  answer: \"the first one\"\n\
             - say: \"Speed up from 1:00 to 1:30 by 2x\"\n\
             - say: \"Actually, put the intro back\"\n- say: \"Undo\"\n\
             - say: \"Make that caption red\"\n- say: \"render\"\n",
        ),
        (
            "slow motion and captions",
            "- say: \"slow down 0:10 to 0:20 by 2x\"\n- say: \"auto-caption the whole video\"\n- say: \"render\"\n",
        ),
        (
            "many cuts",
            "- say: \"cut 0:10 to 0:20\"\n- say: \"cut 1:00 to 1:10\"\n- say: \"remove silences longer than 1 second\"\n- say: \"render\"\n",
        ),
        (
            "bleep and speed",
            "- say: \"bleep the word dollars\"\n- say: \"speed up 2:00 to 2:30 by 3x\"\n- say: \"render\"\n",
        ),
    ];
    let mut out = Vec::new();
    for (i, (name, steps)) in sessions.iter().enumerate() {
        let file = work.join(format!("render{i}.yaml"));
        let _ = std::fs::write(
            &file,
            format!("video: interview.mp4\ntranscript: interview.words.json\nsteps:\n{steps}"),
        );
        let opts = RunOptions {
            out: Some(work.join(format!("render{i}"))),
            render: true,
            ..Default::default()
        };
        let (r, session) = match run(&file, Box::new(RulesParser), &opts) {
            Ok(x) => x,
            Err(e) => {
                eprintln!("render {name}: {e}");
                continue;
            }
        };
        let Some(v) = r.steps.iter().rev().find_map(|s| s.video.clone()) else {
            let why = r
                .steps
                .last()
                .map(|s| s.summary.clone())
                .unwrap_or_default();
            eprintln!("render {name}: no video ({why})");
            continue;
        };
        let expected = session.project.timeline().timeline.duration;
        if let Ok(c) = incubrix_media::render::verify(Path::new(&v), expected, (30000, 1001), true)
        {
            out.push(RenderMeasure {
                session: name.to_string(),
                length_diff_frames: c.length_diff_frames.abs(),
                av_offset_frames: c.av_offset_frames.abs(),
            });
        }
    }
    out
}

/// Measures everything. `sessions` is the scenario folder; `work` holds
/// generated media (renders are skipped when `render` is false).
pub fn measure(sessions: &Path, work: &Path, render: bool) -> Metrics {
    let latency = vec![latency(5), latency(60)];
    let (n, same, ambiguous_each) = scenarios(sessions);
    let count = |k: &str| ambiguous_each.iter().filter(|a| a.1 == k).count();
    let (cuts_checked, clipped_words) = word_clipping();
    let renders = if render {
        let _ = std::fs::create_dir_all(work);
        renders(work)
    } else {
        vec![]
    };
    let worst = |f: fn(&RenderMeasure) -> f64| renders.iter().map(f).reduce(f64::max);
    Metrics {
        latency,
        determinism_sessions: n,
        determinism_percent: if n == 0 {
            0.0
        } else {
            100.0 * same as f64 / n as f64
        },
        ambiguous: ambiguous_each.len(),
        asked: count("asked"),
        stated_assumption: count("stated an assumption"),
        named_single: count("one candidate, named in the reply"),
        refused: count("refused with a reason"),
        guessed: count("guessed"),
        ambiguous_each,
        cuts_checked,
        clipped_words,
        worst_length_diff_frames: worst(|r| r.length_diff_frames),
        worst_av_offset_frames: worst(|r| r.av_offset_frames),
        renders,
        stt_cost_per_minute_usd: 0.0,
        llm_cost_per_minute_usd: 0.0,
    }
}

/// The scenario folder of this checkout (for tests and the default).
pub fn fixtures() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/sessions")
}

/// The Metrics tab as a Markdown table.
pub fn markdown(m: &Metrics) -> String {
    let mut s = String::from(
        "# Metrics

Measured by `incubrix metrics` (release build).

| Metric | Value |
|---|---|
",
    );
    for l in &m.latency {
        s += &format!(
            "| Instruction latency, {}-minute video ({} words, {} instructions) | median {:.1} ms, slowest {:.1} ms (\"{}\") |
",
            l.minutes, l.words, l.instructions, l.median_ms, l.slowest_ms, l.slowest
        );
    }
    match (m.worst_length_diff_frames, m.worst_av_offset_frames) {
        (Some(len), Some(av)) => {
            s += &format!(
                "| Render accuracy ({} renders) | largest length difference {len:.2} frames, largest A/V offset {av:.2} frames |
",
                m.renders.len()
            )
        }
        _ => s += "| Render accuracy | not measured (no ffmpeg, or --no-render) |
",
    }
    s += &format!(
        "| Determinism | {:.0}% of {} sessions identical across 3 runs |
",
        m.determinism_percent, m.determinism_sessions
    );
    s += &format!(
        "| Clarification quality | {} open instructions: {} asked, {} stated an assumption, {} had one candidate and named it, {} refused with a reason, {} guessed |
",
        m.ambiguous, m.asked, m.stated_assumption, m.named_single, m.refused, m.guessed
    );
    s += &format!(
        "| Word clipping | {} of {} cuts' edges inside a word (automatic check against word timings) |
",
        m.clipped_words, m.cuts_checked
    );
    s += &format!(
        "| Cost | speech-to-text ${:.2}/min (local whisper), language model ${:.2}/min (rules parser; an optional LLM is billed by its provider) |
",
        m.stt_cost_per_minute_usd, m.llm_cost_per_minute_usd
    );
    s += "
## Ambiguous instructions

";
    for (say, how) in &m.ambiguous_each {
        s += &format!(
            "- \"{say}\": {how}
"
        );
    }
    for l in &m.latency {
        s += &format!(
            "
## {}-minute video, each instruction

",
            l.minutes
        );
        for (say, t) in &l.each {
            s += &format!(
                "- {t:.1} ms: {say}
"
            );
        }
    }
    s
}
