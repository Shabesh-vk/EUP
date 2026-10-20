//! The session runner: plays a scripted editing session and writes every
//! response, in the format the brief asks for.
//!
//! ```yaml
//! video: https://.../interview.mp4      # or a local path
//! steps:
//!   - say: "Add a caption 'Welcome!' when I say welcome to the channel"
//!   - say: "Remove the part about pricing"
//!     answer: "the second one"          # used if the system asks
//!   - say: "render"
//! ```
//!
//! Output (`--out dir`): `results.json` - for each step: status, operations,
//! summary, question, options, timeline_hash, duration_s - plus the final
//! timeline (`timeline.json`), an OpenTimelineIO file, and the rendered
//! video when a step says "render".
//!
//! Optional fields, for tests and CI: `transcript:` (a words file),
//! `speakers:` (speaker turns), `source:` (a length and spoken lines, so a
//! session runs with no video at all), and `expect:` on any step, checked
//! by `incubrix check`.

use std::path::{Path, PathBuf};

use incubrix_core::time::to_secs_ms;
use incubrix_core::{secs, Outcome, Project, SourceInfo, Status, Transcript, Word};
use incubrix_media::render::{render, RenderOptions};
use incubrix_media::transcribe::clean_words;
use incubrix_media::{intake, Diarizer, FixtureDiarizer, FixtureTranscriber};
use incubrix_nlu::{Action, Parser, Session};
use serde::{Deserialize, Serialize};

/// A session file.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionFile {
    /// The video: a local path (relative to the session file) or a URL.
    #[serde(default)]
    pub video: Option<String>,
    /// Recorded words for the video (instead of running a recogniser).
    #[serde(default)]
    pub transcript: Option<String>,
    /// Recorded speaker turns.
    #[serde(default)]
    pub speakers: Option<String>,
    /// A video described instead of supplied: length and spoken lines.
    #[serde(default)]
    pub source: Option<Synthetic>,
    /// What the user types, in order.
    pub steps: Vec<Step>,
}

/// A source with no file: for engine-only sessions.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Synthetic {
    /// Length, seconds.
    pub duration_s: f64,
    /// `[start_s, "S2: words said"]`, 0.4 s per word; `word~0.3` sets a
    /// word's recognition confidence.
    #[serde(default)]
    pub lines: Vec<(f64, String)>,
}

/// One user turn.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Step {
    /// What the user types.
    pub say: String,
    /// The reply if the system asks a question.
    #[serde(default)]
    pub answer: Option<String>,
    /// What the step must produce (checked by `incubrix check`).
    #[serde(default)]
    pub expect: Option<Expect>,
}

/// Expected results for one step. Absent fields are not checked.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Expect {
    /// `applied`, `needs_clarification` or `rejected` (after any answer).
    pub status: Option<String>,
    /// Status of the first reply, before the answer.
    pub asked: Option<bool>,
    /// Edited length after the step, seconds (to the millisecond).
    pub duration_s: Option<f64>,
    /// Number of options offered.
    pub options: Option<usize>,
    /// Reason code of a rejection.
    pub code: Option<String>,
    /// Words the summary must contain.
    pub summary_contains: Option<String>,
    /// Words the question must contain.
    pub question_contains: Option<String>,
    /// Words one of the warnings must contain.
    pub warning_contains: Option<String>,
    /// Captions that exist (shown or hidden).
    pub captions: Option<usize>,
    /// Captions currently on screen somewhere.
    pub captions_shown: Option<usize>,
    /// The timeline hash equals the one after this (1-based) step.
    pub same_timeline_as_step: Option<usize>,
    /// Whether an undo step was recorded.
    pub recorded: Option<bool>,
}

/// One step's response, as written to `results.json`.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct StepResult {
    /// 1-based.
    pub step: usize,
    /// What was typed.
    pub say: String,
    /// The answer given, if a question was asked.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    /// `applied`, `needs_clarification` or `rejected`.
    pub status: Status,
    /// What was done.
    pub operations: Vec<String>,
    /// Before/after, or the reason.
    pub summary: String,
    /// The question asked, if any.
    pub question: Option<String>,
    /// Its options.
    pub options: Vec<String>,
    /// Consequences worth knowing.
    pub warnings: Vec<String>,
    /// Hash of the timeline after the step.
    pub timeline_hash: String,
    /// Edited length after the step, seconds.
    pub duration_s: f64,
    /// Reason code of a rejection.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    /// The undo step recorded, if any.
    pub tx: Option<u32>,
    /// The rendered file, for a render step.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub video: Option<String>,
}

/// The whole run.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Results {
    /// The session file played.
    pub session: String,
    /// Always "current".
    pub time_policy: String,
    /// Who read the words.
    pub parser: String,
    /// Every step.
    pub steps: Vec<StepResult>,
    /// Hash of the final timeline.
    pub final_timeline_hash: String,
    /// Length of the final timeline, seconds.
    pub final_duration_s: f64,
    /// The source's SHA-256 (empty for a described source).
    pub source_sha256: String,
}

/// What can go wrong running a session (not an editing answer: those are
/// results).
#[derive(Debug)]
pub struct RunError(pub String);

impl std::fmt::Display for RunError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for RunError {}

fn err(e: impl std::fmt::Display) -> RunError {
    RunError(e.to_string())
}

/// Reads a session file.
pub fn load(path: &Path) -> Result<SessionFile, RunError> {
    let text =
        std::fs::read_to_string(path).map_err(|e| RunError(format!("{}: {e}", path.display())))?;
    serde_yaml::from_str(&text).map_err(|e| RunError(format!("{}: {e}", path.display())))
}

/// Words laid out from spoken lines: 0.4 s per word.
pub fn synthetic_transcript(lines: &[(f64, String)]) -> Transcript {
    let mut words = Vec::new();
    for (at, line) in lines {
        let (speaker, text) = match line.split_once(": ") {
            Some((s, t)) if s.starts_with('S') && s.len() <= 3 => (s.to_owned(), t),
            _ => ("S1".to_owned(), line.as_str()),
        };
        for (k, w) in text.split_whitespace().enumerate() {
            let (w, conf) = match w.split_once('~') {
                Some((w, c)) => (w, c.parse().unwrap_or(0.95)),
                None => (w, 0.95),
            };
            let start = at + k as f64 * 0.4;
            words.push(Word {
                id: String::new(),
                text: w.to_owned(),
                start: secs(start),
                end: secs(start + 0.4),
                speaker: speaker.clone(),
                confidence: conf,
            });
        }
    }
    words.sort_by_key(|w| w.start);
    for (i, w) in words.iter_mut().enumerate() {
        w.id = format!("w{i:05}");
    }
    Transcript { words }
}

/// A transcript file: a cleaned transcript (`{"words": [...ids...]}` or the
/// cache form `{"transcript": {...}}`) or raw recogniser output.
fn read_transcript(path: &Path, duration: incubrix_core::Us) -> Result<Transcript, RunError> {
    let text =
        std::fs::read_to_string(path).map_err(|e| RunError(format!("{}: {e}", path.display())))?;
    let v: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| RunError(format!("{}: {e}", path.display())))?;
    let inner = if v.get("transcript").is_some() {
        v["transcript"].clone()
    } else {
        v
    };
    if inner["words"].get(0).is_some_and(|w| w.get("id").is_some()) {
        return serde_json::from_value(inner).map_err(err);
    }
    let raw = FixtureTranscriber::new(path);
    let words =
        incubrix_media::Transcriber::transcribe(&raw, path, &SourceInfo::with_duration(duration))
            .map_err(err)?;
    Ok(clean_words(words, duration).0)
}

/// Builds the project a session edits. Relative paths are read from `base`.
pub fn project(file: &SessionFile, base: &Path, work: &Path) -> Result<Project, RunError> {
    let at = |p: &str| -> PathBuf {
        let p = Path::new(p);
        if p.is_absolute() {
            p.to_path_buf()
        } else {
            base.join(p)
        }
    };
    if let Some(src) = &file.source {
        let source = SourceInfo::with_duration(secs(src.duration_s));
        let transcript = match &file.transcript {
            Some(t) => read_transcript(&at(t), source.duration)?,
            None => synthetic_transcript(&src.lines),
        };
        return Ok(Project::new(source, transcript));
    }
    let video = file
        .video
        .as_deref()
        .ok_or_else(|| RunError("the session has no video and no source".into()))?;
    let path = if video.starts_with("http://") || video.starts_with("https://") {
        download(video, work)?
    } else {
        at(video)
    };
    let words = file.transcript.as_deref().map(&at).ok_or_else(|| {
        RunError(
            "no transcript: give `transcript:` (or build with the `whisper` feature and a model)"
                .into(),
        )
    })?;
    let transcriber = FixtureTranscriber::new(words);
    let diarizer = file
        .speakers
        .as_deref()
        .map(|s| FixtureDiarizer::new(at(s)));
    let mut project = intake(
        &path,
        &transcriber,
        diarizer.as_ref().map(|d| d as &dyn Diarizer),
        None,
    )
    .map_err(err)?
    .into_project();
    project
        .transcript
        .words
        .retain(|w| w.start < project.source.duration);
    Ok(project)
}

fn download(url: &str, work: &Path) -> Result<PathBuf, RunError> {
    std::fs::create_dir_all(work).map_err(err)?;
    let name = url
        .rsplit('/')
        .next()
        .filter(|n| !n.is_empty())
        .unwrap_or("video.mp4");
    let name = name.split('?').next().unwrap_or(name);
    let out = work.join(name);
    if out.is_file() {
        return Ok(out);
    }
    let resp = ureq::get(url)
        .call()
        .map_err(|e| RunError(format!("cannot download {url}: {e}")))?;
    let mut file = std::fs::File::create(&out).map_err(err)?;
    std::io::copy(&mut resp.into_reader(), &mut file).map_err(err)?;
    Ok(out)
}

/// What to do besides answering.
#[derive(Clone, Debug, Default)]
pub struct RunOptions {
    /// Where results, timeline and video go; nothing is written when `None`.
    pub out: Option<PathBuf>,
    /// Render on "render" steps (needs a real video).
    pub render: bool,
}

fn result(
    step: usize,
    say: &str,
    answer: Option<String>,
    asked: Option<&Outcome>,
    o: &Outcome,
) -> StepResult {
    StepResult {
        step,
        say: say.to_owned(),
        answer,
        status: o.status,
        operations: o.operations.clone(),
        summary: o.summary.clone(),
        question: asked
            .and_then(|a| a.question.clone())
            .or_else(|| o.question.clone()),
        options: match asked {
            Some(a) => a.options.clone(),
            None => o.options.clone(),
        },
        warnings: o.warnings.clone(),
        timeline_hash: o.timeline_hash.clone(),
        duration_s: o.duration_s,
        code: o.code.clone(),
        tx: o.tx,
        video: None,
    }
}

/// Plays a session file with `parser`.
pub fn run(
    path: &Path,
    parser: Box<dyn Parser>,
    opts: &RunOptions,
) -> Result<(Results, Session), RunError> {
    let file = load(path)?;
    let base = path.parent().unwrap_or(Path::new("."));
    let work = opts
        .out
        .clone()
        .unwrap_or_else(|| std::env::temp_dir().join("incubrix-run"));
    let project = project(&file, base, &work)?;
    let source_sha256 = project.source.sha256.clone();
    let mut session = Session::new(project, parser);
    let mut steps = Vec::new();
    for (i, step) in file.steps.iter().enumerate() {
        let first = session.say(&step.say);
        let mut r = match (&first.outcome.status, &step.answer) {
            (Status::NeedsClarification, Some(answer)) => {
                let then = session.answer(answer);
                result(
                    i + 1,
                    &step.say,
                    Some(answer.clone()),
                    Some(&first.outcome),
                    &then.outcome,
                )
            }
            _ => result(i + 1, &step.say, None, None, &first.outcome),
        };
        if first.action == Some(Action::Render) {
            if let (true, Some(out)) = (
                opts.render && !session.project.source.path.is_empty(),
                &opts.out,
            ) {
                let file = out.join(format!("render_step{}.mp4", i + 1));
                match render(&session.project, &file, &RenderOptions::default()) {
                    Ok(report) => {
                        r.video = Some(file.to_string_lossy().into_owned());
                        r.warnings.extend(report.warnings);
                        r.warnings.push(format!(
                            "Render checked: {:.2} frames off the timeline, sound and picture {:.2} frames apart, source unchanged.",
                            report.check.length_diff_frames, report.check.av_offset_frames
                        ));
                    }
                    Err(e) => {
                        r.status = Status::Rejected;
                        r.code = Some(e.code().into());
                        r.summary = format!("The render failed: {e}");
                    }
                }
            } else {
                r.warnings
                    .push("Not rendered: no video file, or rendering is off for this run.".into());
            }
        }
        steps.push(r);
    }
    let tl = session.project.timeline().timeline;
    let results = Results {
        session: path.to_string_lossy().into_owned(),
        time_policy: incubrix_core::resolve::TIME_POLICY.into(),
        parser: session.parser_name(),
        steps,
        final_timeline_hash: session.project.hash(),
        final_duration_s: to_secs_ms(tl.duration),
        source_sha256,
    };
    if let Some(out) = &opts.out {
        std::fs::create_dir_all(out).map_err(err)?;
        let write = |name: &str, v: String| std::fs::write(out.join(name), v + "\n").map_err(err);
        write(
            "results.json",
            serde_json::to_string_pretty(&results).map_err(err)?,
        )?;
        write(
            "timeline.json",
            serde_json::to_string_pretty(&tl).map_err(err)?,
        )?;
        write(
            "history.json",
            serde_json::to_string_pretty(&session.project).map_err(err)?,
        )?;
        let name = path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        write(
            "timeline.otio",
            serde_json::to_string_pretty(&incubrix_core::otio::to_otio(&session.project, &name))
                .map_err(err)?,
        )?;
    }
    Ok((results, session))
}

/// Compares a run against the `expect:` blocks of its session file.
/// Returns one line per failed expectation.
pub fn check(file: &SessionFile, results: &Results, session: &Session) -> Vec<String> {
    let mut failures = Vec::new();
    let tl = session.project.timeline().timeline;
    for (i, step) in file.steps.iter().enumerate() {
        let Some(e) = &step.expect else { continue };
        let r = &results.steps[i];
        let n = i + 1;
        let mut fail = |what: String| failures.push(format!("step {n} ({}): {what}", step.say));
        let status = serde_json::to_value(r.status)
            .ok()
            .and_then(|v| v.as_str().map(str::to_owned))
            .unwrap_or_default();
        if let Some(want) = &e.status {
            if &status != want {
                fail(format!(
                    "status {status}, expected {want}; summary: {}",
                    r.summary
                ));
            }
        }
        if let Some(asked) = e.asked {
            if asked != r.question.is_some() {
                fail(format!(
                    "asked = {}, expected {asked}",
                    r.question.is_some()
                ));
            }
        }
        if let Some(d) = e.duration_s {
            if (r.duration_s - d).abs() > 0.0015 {
                fail(format!("duration {} s, expected {d} s", r.duration_s));
            }
        }
        if let Some(k) = e.options {
            if r.options.len() != k {
                fail(format!(
                    "{} options, expected {k}: {:?}",
                    r.options.len(),
                    r.options
                ));
            }
        }
        if let Some(c) = &e.code {
            if r.code.as_deref() != Some(c.as_str()) {
                fail(format!("code {:?}, expected {c}", r.code));
            }
        }
        if let Some(s) = &e.summary_contains {
            if !r.summary.contains(s.as_str()) {
                fail(format!("summary lacks '{s}': {}", r.summary));
            }
        }
        if let Some(q) = &e.question_contains {
            if !r.question.as_deref().unwrap_or("").contains(q.as_str()) {
                fail(format!("question lacks '{q}': {:?}", r.question));
            }
        }
        if let Some(w) = &e.warning_contains {
            if !r.warnings.iter().any(|x| x.contains(w.as_str())) {
                fail(format!("no warning with '{w}': {:?}", r.warnings));
            }
        }
        if let Some(rec) = e.recorded {
            if r.tx.is_some() != rec {
                fail(format!("recorded = {}, expected {rec}", r.tx.is_some()));
            }
        }
        if let Some(k) = e.same_timeline_as_step {
            if results
                .steps
                .get(k.saturating_sub(1))
                .map(|s| &s.timeline_hash)
                != Some(&r.timeline_hash)
            {
                fail(format!("timeline differs from step {k}'s"));
            }
        }
        // Caption counts are about the end of the session only when given on
        // the last step; elsewhere they need the state then, which the
        // results do not keep - so they are checked on the last step only.
        if n == file.steps.len() {
            if let Some(c) = e.captions {
                if tl.captions.len() != c {
                    fail(format!("{} captions, expected {c}", tl.captions.len()));
                }
            }
            if let Some(c) = e.captions_shown {
                let shown = tl
                    .captions
                    .iter()
                    .filter(|x| !x.playback.is_empty())
                    .count();
                if shown != c {
                    fail(format!("{shown} captions on screen, expected {c}"));
                }
            }
        }
    }
    failures
}
