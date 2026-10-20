//! A conversation of edits: instruction in, one of applied /
//! needs_clarification / rejected out.
//!
//! The [`Session`] owns the [`Project`], a parser, the question waiting for
//! an answer, and what "that caption" / "that" refer to. Every intent is
//! resolved here, in plain code, against the timeline as it is now:
//!
//! - typed times are current playback time, projected to source at once;
//! - several matches for anything destructive -> a question with options;
//! - a meaning-based match ("cost" for "pricing") is always shown first;
//! - a multi-part instruction applies completely or not at all, and a
//!   rejection names the part that failed;
//! - one instruction (with its answer) is one transaction, one undo.

use incubrix_core::detect::{caption_chunks, fillers, silences, LOW_CONFIDENCE};
use incubrix_core::resolve::{playback_span, snap_to_silence, TIME_POLICY_NOTE};
use incubrix_core::search::{find_phrase, Hit};
use incubrix_core::time::{clock, to_secs_ms, PbRange};
use incubrix_core::{
    Anchor, ApplyReport, CaptionStyle, CutReason, EditError, Op, Outcome, Project, SrcRange,
    StylePatch, Timeline, Us,
};

use crate::answer::{pick, Pick};
use crate::intent::{
    CaptionRef, EditKind, EditRef, Intent, Occurrence, Part, Place, SizeChange, StyleChange,
    TalkTopic, Target, VagueGoal, Who,
};
use crate::semantic::{find_topic, label_islands, sentence, PROFANITY};
use crate::{Context, Parser};

/// Something the caller must do besides showing the outcome.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Action {
    /// Render the current timeline (a separate step).
    Render,
}

/// The answer to one message.
#[derive(Clone, PartialEq, Debug)]
pub struct Reply {
    /// applied / needs_clarification / rejected, in the brief's format.
    pub outcome: Outcome,
    /// What the caller should do next, if anything.
    pub action: Option<Action>,
    /// Who read the words: "AI model ...", "built-in phrases", or "your answer".
    pub reader: String,
}

/// Default music level and ducking.
pub const MUSIC_VOLUME_DB: i32 = -18;
/// How far music drops under speech.
pub const MUSIC_DUCK_DB: i32 = 12;
/// Speech kept either side of a removed silence.
pub const SILENCE_PAD_US: Us = 150_000;
/// A gap shorter than this is not a pause worth keeping.
pub const MIN_PAUSE_US: Us = 200_000;

/// What a part resolved to.
#[derive(Clone, Debug)]
enum Resolved {
    Ops(Done),
    Ask {
        question: String,
        choices: Vec<Choice>,
    },
    Reject {
        code: String,
        reason: String,
    },
}

/// A resolved part: its operations and how to describe them.
#[derive(Clone, Debug, Default)]
struct Done {
    ops: Vec<Op>,
    said: String,
    notes: Vec<String>,
    typed: bool,
}

#[derive(Clone, Debug)]
struct Choice {
    label: String,
    then: Then,
}

#[derive(Clone, Debug)]
enum Then {
    Ops(Done),
    Intent(Intent),
    Nothing(String),
}

#[derive(Clone, Debug)]
struct Pending {
    instruction: String,
    done: Vec<Done>,
    question: String,
    choices: Vec<Choice>,
    rest: Vec<Part>,
    render: bool,
}

/// One place a target points at.
#[derive(Clone, Debug)]
struct Cand {
    label: String,
    spans: Vec<SrcRange>,
    words: Option<(usize, usize)>,
}

enum Found {
    Picked(Vec<Cand>, Vec<String>),
    Ask {
        question: String,
        options: Vec<(String, Vec<Cand>)>,
        notes: Vec<String>,
    },
    Reject(String, String),
}

fn reject(code: &str, reason: impl Into<String>) -> Resolved {
    Resolved::Reject {
        code: code.into(),
        reason: reason.into(),
    }
}

fn from_err(e: EditError) -> Resolved {
    reject(e.code(), capitalise(&e.to_string()))
}

fn capitalise(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
        None => String::new(),
    }
}

fn short(text: &str) -> String {
    let t: String = text.chars().take(48).collect();
    if t.len() < text.len() {
        format!("{t}...")
    } else {
        t
    }
}

fn is_typed(t: &Target) -> bool {
    matches!(
        t,
        Target::Range { .. }
            | Target::First { .. }
            | Target::Last { .. }
            | Target::From { .. }
            | Target::Until { .. }
            | Target::At { .. }
    )
}

fn us(ms: i64) -> Us {
    ms * 1000
}

/// An editing conversation on one project.
pub struct Session {
    /// The project: untouched source, transcript, history.
    pub project: Project,
    parser: Box<dyn Parser>,
    pending: Option<Pending>,
    focus_caption: Option<String>,
    last_spans: Vec<SrcRange>,
    last_typed_cut: Option<(String, u32)>,
    reader: String,
}

impl Session {
    /// A session on `project`, reading instructions with `parser`.
    pub fn new(project: Project, parser: Box<dyn Parser>) -> Self {
        Self {
            project,
            parser,
            pending: None,
            focus_caption: None,
            last_spans: Vec::new(),
            last_typed_cut: None,
            reader: String::new(),
        }
    }

    /// The parser's name, for the manifest.
    pub fn parser_name(&self) -> String {
        self.parser.name()
    }

    /// The question waiting for an answer and its options, if any.
    pub fn pending(&self) -> Option<(&str, Vec<String>)> {
        self.pending.as_ref().map(|p| {
            (
                p.question.as_str(),
                p.choices.iter().map(|c| c.label.clone()).collect(),
            )
        })
    }

    /// The caption "that caption" means now.
    pub fn focus_caption(&self) -> Option<&str> {
        self.focus_caption.as_deref()
    }

    /// What a parser may know.
    pub fn context(&self) -> Context {
        let tl = self.project.timeline().timeline;
        let mut speakers: Vec<String> = Vec::new();
        for w in &self.project.transcript.words {
            if !speakers.contains(&w.speaker) {
                speakers.push(w.speaker.clone());
            }
        }
        Context {
            duration_s: to_secs_ms(tl.duration),
            captions: tl
                .captions
                .iter()
                .map(|c| (c.id.clone(), c.text.clone()))
                .collect(),
            speakers,
            pending_question: self.pending.as_ref().map(|p| p.question.clone()),
        }
    }

    /// One message from the user. While a question is waiting, a message
    /// that reads as an answer answers it; anything else drops the question.
    pub fn say(&mut self, text: &str) -> Reply {
        if let Some(p) = &self.pending {
            let labels: Vec<String> = p.choices.iter().map(|c| c.label.clone()).collect();
            if pick(text, &labels) != Pick::Unclear {
                return self.answer(text);
            }
            // In the user's own words? The model may tell an answer from a
            // new instruction.
            match self.ask_model(text) {
                Some(Some(i)) => return self.answer(&labels[i]),
                Some(None) => return self.answer("cancel"),
                None => self.pending = None,
            }
        }
        let intent = self.parser.parse(text, &self.context());
        self.reader = self.parser.last_reader();
        self.run(text, intent)
    }

    /// Applies an intent already known - a button, not words: no parser,
    /// no model. Undo, redo and "restore edit #3" take this path.
    pub fn run(&mut self, text: &str, intent: Intent) -> Reply {
        match intent {
            Intent::Undo { steps } => self.undo(steps),
            Intent::Redo { steps } => self.redo(steps),
            Intent::Render => self.reply(self.render_outcome(), Some(Action::Render)),
            Intent::Talk { topic, reply } => self.reply(self.talk(topic, reply.as_deref()), None),
            Intent::Unknown { reason } => self.reply(
                Outcome::rejected_with(
                    &self.project,
                    "UNKNOWN_INSTRUCTION",
                    format!("{reason} Try e.g. \"cut 0:30 to 0:40\", \"add a caption 'Hi' when I say hello\", \"undo\"."),
                ),
                None,
            ),
            Intent::Multi { parts } => self.drive(text.to_owned(), Vec::new(), parts, false),
            other => self.drive(
                text.to_owned(),
                Vec::new(),
                vec![Part {
                    text: text.to_owned(),
                    intent: other,
                }],
                false,
            ),
        }
    }

    /// The reply to the waiting question.
    pub fn answer(&mut self, text: &str) -> Reply {
        self.reader = "your answer".into();
        let mut text = text.to_owned();
        if let Some(p) = &self.pending {
            let labels: Vec<String> = p.choices.iter().map(|c| c.label.clone()).collect();
            if pick(&text, &labels) == Pick::Unclear {
                match self.ask_model(&text) {
                    Some(Some(i)) => text = labels[i].clone(),
                    Some(None) => text = "cancel".into(),
                    None => {}
                }
            }
        }
        let text = text.as_str();
        let Some(p) = self.pending.take() else {
            return self.reply(
                Outcome::rejected_with(
                    &self.project,
                    "NOTHING_TO_ANSWER",
                    "There is no question waiting for an answer.".into(),
                ),
                None,
            );
        };
        let labels: Vec<String> = p.choices.iter().map(|c| c.label.clone()).collect();
        match pick(text, &labels) {
            Pick::Unclear => {
                let mut o = Outcome::clarify(&self.project, p.question.clone(), labels);
                o.summary = format!("I didn't catch \"{text}\": pick one of the options.");
                self.pending = Some(p);
                self.reply(o, None)
            }
            Pick::Cancel => self.reply(
                Outcome::rejected_with(
                    &self.project,
                    "CANCELLED",
                    "Cancelled; nothing changed.".into(),
                ),
                None,
            ),
            Pick::Option(i) => {
                let choice = p.choices[i].clone();
                let instruction = format!("{} -> {}", p.instruction, choice.label);
                let mut done = p.done;
                let mut rest = p.rest;
                match choice.then {
                    Then::Ops(d) => done.push(d),
                    Then::Intent(intent) => rest.insert(
                        0,
                        Part {
                            text: choice.label.clone(),
                            intent,
                        },
                    ),
                    Then::Nothing(msg) => {
                        if done.is_empty() && rest.is_empty() {
                            return self.reply(self.noop(vec![], msg, vec![]), None);
                        }
                    }
                }
                self.drive(instruction, done, rest, p.render)
            }
        }
    }

    fn reply(&self, outcome: Outcome, action: Option<Action>) -> Reply {
        Reply {
            outcome,
            action,
            reader: self.reader.clone(),
        }
    }

    /// Swaps the parser, keeping the edit and the conversation - for a
    /// model that became available after the session began.
    pub fn set_parser(&mut self, parser: Box<dyn Parser>) {
        self.parser = parser;
    }

    /// The AI model reading instructions, if one is set up, for people.
    pub fn model_label(&self) -> Option<String> {
        self.parser.model_label()
    }

    /// A reply the plain matcher could not read, put to the model.
    fn ask_model(&self, text: &str) -> Option<Option<usize>> {
        let p = self.pending.as_ref()?;
        let labels: Vec<String> = p.choices.iter().map(|c| c.label.clone()).collect();
        self.parser.choose(text, &p.question, &labels)
    }

    /// An applied outcome that changed nothing (no undo step).
    fn noop(&self, operations: Vec<String>, summary: String, warnings: Vec<String>) -> Outcome {
        let tl = self.project.timeline().timeline;
        Outcome::applied(
            ApplyReport {
                tx: None,
                before_duration: tl.duration,
                after_duration: tl.duration,
                operations,
                warnings,
                timeline_hash: incubrix_core::timeline_hash(&tl),
            },
            summary,
        )
    }

    /// The video's file name, for talking about it.
    fn file_name(&self) -> String {
        std::path::Path::new(&self.project.source.path)
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .filter(|n| !n.is_empty())
            .unwrap_or_else(|| "your video".into())
    }

    /// A conversational answer, built from the engine's own state: lengths,
    /// changes and captions are facts, never a model's guess. Nothing changes.
    fn talk(&self, topic: TalkTopic, reply: Option<&str>) -> Outcome {
        let tl = self.project.timeline().timeline;
        let now = clock(tl.duration);
        let was = clock(self.project.source.duration);
        let file = self.file_name();
        let active = self.project.active();
        let length = if tl.duration == self.project.source.duration {
            format!("{now} long")
        } else {
            format!("{now} long now (it was {was})")
        };
        let text = match topic {
            TalkTopic::Greeting => format!(
                "Hi there! I'm working on {file}, which is {length}. Tell me what you'd like to change - cut a part, speed something up, add a caption, tidy up pauses - and I'll do it and show you."
            ),
            TalkTopic::Thanks => "You're welcome! Happy to help. Anything else you'd like to change?".to_owned(),
            TalkTopic::Help => "Here's what I can do: cut parts (\"cut the first 30 seconds\", \"remove 1:10 to 1:25\"), keep only a part, move a section, speed up or slow down a stretch, add and style captions, mute or bleep words, remove filler words and long pauses, add background music, and undo or bring back any earlier change. Once the speech is analysed I can also work from what's said, like \"remove the part about pricing\". Just tell me in your own words.".to_owned(),
            TalkTopic::Status => {
                let changes = match active.len() {
                    0 => "no changes yet".to_owned(),
                    1 => "1 change so far".to_owned(),
                    n => format!("{n} changes so far"),
                };
                let captions = match tl.captions.len() {
                    0 => String::new(),
                    1 => ", and 1 caption".to_owned(),
                    n => format!(", and {n} captions"),
                };
                format!("I'm editing {file}. It's {length}, with {changes}{captions}.")
            }
            TalkTopic::History => {
                if active.is_empty() {
                    "Nothing yet - your video is just as it came in. Tell me the first change you'd like.".to_owned()
                } else {
                    let off = self.project.restored();
                    let lines: Vec<String> = active
                        .iter()
                        .map(|t| {
                            let state = if off.contains(&t.id) { " (switched off)" } else { "" };
                            format!("#{}: \"{}\"{state}", t.id, t.instruction)
                        })
                        .collect();
                    format!(
                        "So far: {}. The video is {length}. You can undo the last one, or ask me to undo any single change.",
                        lines.join("; ")
                    )
                }
            }
            TalkTopic::Smalltalk => {
                let said = reply
                    .map(|r| r.trim().chars().take(280).collect::<String>())
                    .filter(|r| !r.is_empty())
                    .unwrap_or_else(|| "I'm doing great, thanks for asking!".to_owned());
                format!("{said} Whenever you're ready, just tell me what to change in {file}.")
            }
        };
        let mut o = self.noop(vec![], text, vec![]);
        o.code = Some("TALK".into());
        o
    }

    fn render_outcome(&self) -> Outcome {
        let tl = self.project.timeline().timeline;
        self.noop(
            vec!["render requested".into()],
            format!(
                "Render requested for the current timeline ({} long). Rendering is a separate step and never changes the source.",
                clock(tl.duration)
            ),
            vec![],
        )
    }

    fn undo(&mut self, steps: u32) -> Reply {
        self.pending = None;
        let before = self.project.timeline().timeline.duration;
        let mut lines = Vec::new();
        for _ in 0..steps.max(1) {
            match self.project.undo() {
                Some(tx) => lines.push(format!("undid edit #{} '{}'", tx.id, tx.instruction)),
                None => break,
            }
        }
        if lines.is_empty() {
            return self.reply(
                Outcome::rejected_with(
                    &self.project,
                    "NOTHING_TO_UNDO",
                    "There is nothing to undo.".into(),
                ),
                None,
            );
        }
        self.after_history_move();
        let after = self.project.timeline().timeline.duration;
        let summary = format!(
            "{}. Video {} -> {}.",
            capitalise(&lines.join("; ")),
            clock(before),
            clock(after)
        );
        self.reply(self.noop(lines, summary, vec![]), None)
    }

    fn redo(&mut self, steps: u32) -> Reply {
        self.pending = None;
        let before = self.project.timeline().timeline.duration;
        let mut lines = Vec::new();
        for _ in 0..steps.max(1) {
            match self.project.redo() {
                Some(tx) => lines.push(format!("redid edit #{} '{}'", tx.id, tx.instruction)),
                None => break,
            }
        }
        if lines.is_empty() {
            return self.reply(
                Outcome::rejected_with(
                    &self.project,
                    "NOTHING_TO_REDO",
                    "There is nothing to redo.".into(),
                ),
                None,
            );
        }
        self.after_history_move();
        let after = self.project.timeline().timeline.duration;
        let summary = format!(
            "{}. Video {} -> {}.",
            capitalise(&lines.join("; ")),
            clock(before),
            clock(after)
        );
        self.reply(self.noop(lines, summary, vec![]), None)
    }

    fn after_history_move(&mut self) {
        let tl = self.project.timeline().timeline;
        if let Some(f) = &self.focus_caption {
            if tl.caption(f).is_none() {
                self.focus_caption = tl.captions.last().map(|c| c.id.clone());
            }
        }
        self.last_typed_cut = None;
    }

    /// Resolves parts in order on a staged copy, so each part sees the
    /// timeline the parts before it left; then commits them as one transaction.
    fn drive(
        &mut self,
        instruction: String,
        done: Vec<Done>,
        parts: Vec<Part>,
        mut render: bool,
    ) -> Reply {
        let multi = parts.len() + done.len() > 1;
        let mut staged = self.project.clone();
        for d in &done {
            if !d.ops.is_empty() {
                if let Err(e) = staged.apply("staged", d.ops.clone()) {
                    return self.reply(Outcome::from_error(&self.project, &e), None);
                }
            }
        }
        let mut done = done;
        let total = parts.len();
        let mut parts = parts.into_iter().enumerate();
        while let Some((k, part)) = parts.next() {
            let which = |reason: &str| {
                if multi {
                    format!(
                        "Nothing was applied: part {} (\"{}\") {reason}",
                        k + 1,
                        part.text
                    )
                } else {
                    reason.to_owned()
                }
            };
            let resolved = match &part.intent {
                Intent::Undo { .. } | Intent::Redo { .. } if total > 1 => reject(
                    "CANNOT_COMBINE",
                    which("is an undo/redo, which must be sent on its own."),
                ),
                Intent::Render => {
                    render = true;
                    continue;
                }
                // "hi, and cut the first 30 seconds": the greeting is courtesy.
                Intent::Talk { .. } => continue,
                Intent::Unknown { reason } => reject(
                    "UNKNOWN_INSTRUCTION",
                    which(&format!("was not understood: {reason}")),
                ),
                intent => self.resolve(&staged, intent, &part.text),
            };
            match resolved {
                Resolved::Ops(d) => {
                    if !d.ops.is_empty() {
                        if let Err(e) = staged.apply(&part.text, d.ops.clone()) {
                            let reason =
                                which(&format!("was rejected: {}", capitalise(&e.to_string())));
                            return self.reply(
                                Outcome::rejected_with(&self.project, e.code(), reason),
                                None,
                            );
                        }
                    }
                    done.push(d);
                }
                Resolved::Ask { question, choices } => {
                    let question = if multi {
                        format!("Part {}: {question}", k + 1)
                    } else {
                        question
                    };
                    let labels = choices.iter().map(|c| c.label.clone()).collect();
                    let outcome = Outcome::clarify(&self.project, question.clone(), labels);
                    self.pending = Some(Pending {
                        instruction,
                        done,
                        question,
                        choices,
                        rest: parts.map(|(_, p)| p).collect(),
                        render,
                    });
                    return self.reply(outcome, None);
                }
                Resolved::Reject { code, reason } => {
                    let reason = if multi && !reason.starts_with("Nothing was applied") {
                        which(&format!("was rejected: {reason}"))
                    } else {
                        reason
                    };
                    return self.reply(Outcome::rejected_with(&self.project, &code, reason), None);
                }
            }
        }
        let outcome = self.commit(&instruction, done);
        let action =
            (render && outcome.status != incubrix_core::Status::Rejected).then_some(Action::Render);
        self.reply(outcome, action)
    }

    fn commit(&mut self, instruction: &str, done: Vec<Done>) -> Outcome {
        let ops: Vec<Op> = done.iter().flat_map(|d| d.ops.clone()).collect();
        let said: Vec<String> = done
            .iter()
            .map(|d| d.said.clone())
            .filter(|s| !s.is_empty())
            .collect();
        let notes: Vec<String> = done.iter().flat_map(|d| d.notes.clone()).collect();
        let typed = done.iter().any(|d| d.typed);
        if ops.is_empty() {
            let summary = if said.is_empty() {
                "Nothing to change.".to_owned()
            } else {
                said.join("; ") + "."
            };
            return self.noop(vec![], summary, notes);
        }
        match self.project.apply(instruction, ops.clone()) {
            Err(e) => Outcome::from_error(&self.project, &e),
            Ok(report) => {
                let tl = self.project.timeline().timeline;
                let mut summary = said.join("; ");
                // Where every caption this edit touched now plays.
                for op in &ops {
                    if let Op::AddCaption { id, .. }
                    | Op::StyleCaption { id, .. }
                    | Op::RetextCaption { id, .. } = op
                    {
                        self.focus_caption = Some(id.clone());
                    }
                    if let Op::AddCaption { id, text, .. } = op {
                        if let Some(c) = tl.caption(id) {
                            match c.playback.first() {
                                Some(p) => summary.push_str(&format!(
                                    "; '{text}' ({id}) plays {}-{}",
                                    clock(p.start),
                                    clock(p.end)
                                )),
                                None => summary.push_str(&format!("; '{text}' ({id}) is hidden")),
                            }
                        }
                    }
                }
                if let Some(f) = &self.focus_caption {
                    if tl.caption(f).is_none() {
                        self.focus_caption = None;
                    }
                }
                let spans: Vec<SrcRange> = ops
                    .iter()
                    .flat_map(|op| match op {
                        Op::Cut { ranges, .. } => ranges.clone(),
                        Op::Speed { range, .. }
                        | Op::KeepOnly { range }
                        | Op::Reorder { range, .. } => vec![*range],
                        _ => vec![],
                    })
                    .collect();
                if !spans.is_empty() {
                    self.last_spans = spans;
                }
                let typed_cut = typed
                    && ops.iter().all(|o| {
                        matches!(
                            o,
                            Op::Cut {
                                reason: CutReason::User,
                                ..
                            }
                        )
                    });
                self.last_typed_cut = match (typed_cut, report.tx) {
                    (true, Some(tx)) => Some((norm(instruction), tx)),
                    _ => None,
                };
                let delta = report.after_duration - report.before_duration;
                summary.push_str(&format!(
                    ". Video {} -> {}",
                    clock(report.before_duration),
                    clock(report.after_duration)
                ));
                if delta != 0 {
                    summary.push_str(&format!(
                        " ({}{:.1} s)",
                        if delta > 0 { "+" } else { "" },
                        to_secs_ms(delta)
                    ));
                }
                summary.push('.');
                if typed {
                    summary.push(' ');
                    summary.push_str(TIME_POLICY_NOTE);
                }
                let mut o = Outcome::applied(report, capitalise(&summary));
                o.warnings.extend(notes);
                o
            }
        }
    }

    // ---- resolution ------------------------------------------------------

    fn resolve(&self, p: &Project, intent: &Intent, text: &str) -> Resolved {
        let tl = p.timeline().timeline;
        match intent {
            Intent::Cut { target } => {
                if is_typed(target) {
                    if let Some((prev, tx)) = &self.last_typed_cut {
                        let still_last = p.active().last().map(|t| t.id) == Some(*tx);
                        if still_last && *prev == norm(text) {
                            return self.repeat_question(p, &tl, target, text, *tx);
                        }
                    }
                }
                self.with_targets(p, &tl, target, Purpose::Cut, |cands| {
                    let mut notes = Vec::new();
                    let ranges: Vec<SrcRange> = cands
                        .iter()
                        .flat_map(|c| c.spans.clone())
                        .map(|r| {
                            // Typed times may land mid-word; words found by
                            // search are already whole.
                            if !is_typed(target) {
                                return r;
                            }
                            let (r, n) = snap_to_silence(&p.transcript, r);
                            notes.extend(n);
                            r
                        })
                        .collect();
                    Ok(Done {
                        ops: vec![Op::Cut {
                            ranges,
                            reason: CutReason::User,
                        }],
                        said: format!("Cut {}", labels(cands)),
                        notes,
                        typed: is_typed(target),
                    })
                })
            }
            Intent::KeepOnly { target } => {
                self.with_targets(p, &tl, target, Purpose::Cut, |cands| {
                    let spans: Vec<SrcRange> = cands.iter().flat_map(|c| c.spans.clone()).collect();
                    let range = SrcRange {
                        start: spans.iter().map(|s| s.start).min().unwrap_or(0),
                        end: spans.iter().map(|s| s.end).max().unwrap_or(0),
                    };
                    Ok(Done {
                        ops: vec![Op::KeepOnly { range }],
                        said: format!("Kept only {}", labels(cands)),
                        notes: vec![],
                        typed: is_typed(target),
                    })
                })
            }
            Intent::Speed { target, speed } => {
                if !(incubrix_core::ops::MIN_SPEED..=incubrix_core::ops::MAX_SPEED).contains(speed)
                {
                    return from_err(EditError::BadSpeed(*speed));
                }
                let x = *speed as f64 / 1000.0;
                self.with_targets(p, &tl, target, Purpose::Cut, |cands| {
                    let ops = cands
                        .iter()
                        .flat_map(|c| c.spans.clone())
                        .map(|range| Op::Speed {
                            range,
                            speed: *speed,
                        })
                        .collect();
                    Ok(Done {
                        ops,
                        said: format!("Played {} at {x}x", labels(cands)),
                        notes: vec!["Where speed changes overlap, the later one wins.".into()],
                        typed: is_typed(target),
                    })
                })
            }
            Intent::Move { target, to } => self.resolve_move(p, &tl, target, to),
            Intent::Mute { target } | Intent::Bleep { target } => {
                let bleep = matches!(intent, Intent::Bleep { .. });
                let purpose = if bleep { Purpose::Bleep } else { Purpose::Mute };
                self.with_targets(p, &tl, target, purpose, |cands| {
                    let prefix = if bleep { "bleep" } else { "mute" };
                    let mut ids = ids(p, prefix, cands.len());
                    let mut ops = Vec::new();
                    for c in cands {
                        for anchor in anchors(p, c) {
                            let id = ids.next().unwrap_or_default();
                            ops.push(if bleep {
                                Op::Bleep { id, anchor }
                            } else {
                                Op::Mute { id, anchor }
                            });
                        }
                    }
                    Ok(Done {
                        ops,
                        said: format!(
                            "{} {}",
                            if bleep { "Bleeped" } else { "Muted" },
                            labels(cands)
                        ),
                        notes: vec![],
                        typed: is_typed(target),
                    })
                })
            }
            Intent::AddCaption {
                text: caption,
                target,
            } => self.resolve_add_caption(p, &tl, caption, target),
            Intent::StyleCaption { caption, change } => {
                if change.is_empty() {
                    return reject(
                        "NOTHING_TO_CHANGE",
                        "Say how the caption should change (colour, size, position or bold).",
                    );
                }
                self.with_captions(
                    &tl,
                    caption,
                    "change",
                    |id, cur| {
                        let mut patch = StylePatch {
                            color: change.color.clone(),
                            position: change.position.clone(),
                            bold: change.bold,
                            size: None,
                        };
                        patch.size = change.size.map(|s| match s {
                            SizeChange::Bigger => (cur.size * 5).div_ceil(4),
                            SizeChange::Smaller => (cur.size * 4 / 5).max(8),
                            SizeChange::Px(n) => n,
                        });
                        Op::StyleCaption {
                            id: id.to_owned(),
                            patch,
                        }
                    },
                    describe_change(change),
                )
            }
            Intent::RetextCaption { caption, text: new } => self.with_captions(
                &tl,
                caption,
                "change",
                |id, _| Op::RetextCaption {
                    id: id.to_owned(),
                    text: new.clone(),
                },
                format!("now reads '{new}'"),
            ),
            Intent::RemoveCaption { caption } => self.with_captions(
                &tl,
                caption,
                "remove",
                |id, _| Op::RemoveCaption { id: id.to_owned() },
                "removed".into(),
            ),
            Intent::AutoCaption => {
                let t = &p.transcript;
                let chunks: Vec<(usize, usize)> = caption_chunks(t, 7, 600_000)
                    .into_iter()
                    .filter(|(a, b)| {
                        p.transcript
                            .span(&t.words[*a].id, &t.words[*b].id)
                            .is_some_and(|r| tl.covered(&r) > 0)
                    })
                    .collect();
                if chunks.is_empty() {
                    return reject(
                        "NO_TRANSCRIPT",
                        "There are no spoken words left to caption.",
                    );
                }
                let mut ids = ids(p, "cap", chunks.len());
                let ops = chunks
                    .iter()
                    .map(|(a, b)| Op::AddCaption {
                        id: ids.next().unwrap_or_default(),
                        anchor: incubrix_core::resolve::words_anchor(t, *a, *b),
                        text: t.text_between(&t.words[*a].id, &t.words[*b].id),
                        style: CaptionStyle::default(),
                    })
                    .collect();
                Resolved::Ops(Done {
                    ops,
                    said: format!(
                        "Auto-captioned the video: {} caption lines on the spoken words",
                        chunks.len()
                    ),
                    notes: vec![],
                    typed: false,
                })
            }
            Intent::RemoveFillers => {
                let f = fillers(&p.transcript, &tl);
                if f.ranges.is_empty() {
                    let mut notes = f.warnings;
                    notes.push("No filler words found.".into());
                    return Resolved::Ops(Done {
                        said: "No filler words to remove".into(),
                        notes,
                        ..Default::default()
                    });
                }
                let mut counts: Vec<(String, usize)> = Vec::new();
                for w in &f.words {
                    let k = incubrix_core::model::normalize(w);
                    match counts.iter_mut().find(|(x, _)| *x == k) {
                        Some(c) => c.1 += 1,
                        None => counts.push((k, 1)),
                    }
                }
                let list: Vec<String> = counts.iter().map(|(w, n)| format!("'{w}' x{n}")).collect();
                Resolved::Ops(Done {
                    ops: vec![Op::Cut {
                        ranges: f.ranges.clone(),
                        reason: CutReason::Filler,
                    }],
                    said: format!(
                        "Removed {} filler words ({})",
                        f.ranges.len(),
                        list.join(", ")
                    ),
                    notes: f.warnings,
                    typed: false,
                })
            }
            Intent::RemoveSilences { min_ms } => {
                let gaps = silences(
                    &p.transcript,
                    &tl,
                    p.source.duration,
                    us(*min_ms as i64),
                    SILENCE_PAD_US,
                );
                let mut notes = Vec::new();
                if !tl.protected_pauses.is_empty() {
                    notes.push(format!(
                        "Kept {} protected pause(s).",
                        tl.protected_pauses.len()
                    ));
                }
                if gaps.is_empty() {
                    notes.push(format!(
                        "No silences longer than {:.1} s found.",
                        *min_ms as f64 / 1000.0
                    ));
                    return Resolved::Ops(Done {
                        said: "No silences to remove".into(),
                        notes,
                        ..Default::default()
                    });
                }
                let saved: Us = gaps.iter().map(|g| tl.covered(g)).sum();
                Resolved::Ops(Done {
                    ops: vec![Op::Cut { ranges: gaps.clone(), reason: CutReason::Silence }],
                    said: format!(
                        "Removed {} silences longer than {:.1} s (about {:.1} s), keeping {:.2} s of air around speech",
                        gaps.len(),
                        *min_ms as f64 / 1000.0,
                        to_secs_ms(saved),
                        to_secs_ms(SILENCE_PAD_US)
                    ),
                    notes,
                    typed: false,
                })
            }
            Intent::KeepPause { target } => self.resolve_keep_pause(p, &tl, target),
            Intent::AddMusic { path } => {
                if path.trim().is_empty() {
                    return reject(
                        "MUSIC_PATH_MISSING",
                        "Say which music file, e.g. add music 'track.mp3'.",
                    );
                }
                Resolved::Ops(Done {
                    ops: vec![Op::AddMusic {
                        id: p.next_id("music"),
                        path: path.clone(),
                        volume_db: MUSIC_VOLUME_DB,
                        duck_db: MUSIC_DUCK_DB,
                    }],
                    said: format!("Added music '{path}' at {MUSIC_VOLUME_DB} dB, ducking {MUSIC_DUCK_DB} dB under speech"),
                    notes: vec![],
                    typed: false,
                })
            }
            Intent::RemoveMusic => {
                if tl.music.is_empty() {
                    return reject("NO_MUSIC", "There is no music to remove.");
                }
                Resolved::Ops(Done {
                    ops: tl
                        .music
                        .iter()
                        .map(|m| Op::RemoveMusic { id: m.id.clone() })
                        .collect(),
                    said: format!(
                        "Removed the music ({})",
                        tl.music
                            .iter()
                            .map(|m| m.path.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    ),
                    notes: vec![],
                    typed: false,
                })
            }
            Intent::Restore { edit, keep } => self.resolve_restore(p, edit, keep.as_deref()),
            Intent::Vague { goal } => self.vague(p, &tl, *goal),
            Intent::Undo { .. }
            | Intent::Redo { .. }
            | Intent::Render
            | Intent::Talk { .. }
            | Intent::Multi { .. }
            | Intent::Unknown { .. } => reject(
                "CANNOT_COMBINE",
                "That instruction must be sent on its own.",
            ),
        }
    }

    fn repeat_question(
        &self,
        p: &Project,
        tl: &Timeline,
        target: &Target,
        text: &str,
        tx: u32,
    ) -> Resolved {
        let again = match self.find(p, tl, target, Purpose::Cut) {
            Found::Picked(c, _) => c,
            Found::Reject(code, reason) => return reject(&code, reason),
            Found::Ask { .. } => return reject("INVALID_EDIT", "That span is ambiguous."),
        };
        let ranges: Vec<SrcRange> = again.iter().flat_map(|c| c.spans.clone()).collect();
        Resolved::Ask {
            question: format!(
                "You just did this (edit #{tx}). Under the current-time policy, \"{text}\" now points at different content ({}). Remove that too, or was it a repeat?",
                labels(&again)
            ),
            choices: vec![
                Choice {
                    label: "No, it was a repeat - change nothing".into(),
                    then: Then::Nothing(format!("Nothing changed: edit #{tx} already did that.")),
                },
                Choice {
                    label: format!("Yes, also cut what now plays at {}", labels(&again)),
                    then: Then::Ops(Done {
                        ops: vec![Op::Cut { ranges, reason: CutReason::User }],
                        said: format!("Cut {}", labels(&again)),
                        notes: vec![],
                        typed: true,
                    }),
                },
            ],
        }
    }

    /// Finds the target, asks when there is a choice, then builds ops.
    fn with_targets(
        &self,
        p: &Project,
        tl: &Timeline,
        target: &Target,
        purpose: Purpose,
        make: impl Fn(&[Cand]) -> Result<Done, Resolved>,
    ) -> Resolved {
        match self.find(p, tl, target, purpose) {
            Found::Reject(code, reason) => reject(&code, reason),
            Found::Picked(cands, notes) => match make(&cands) {
                Ok(mut d) => {
                    d.notes.extend(notes);
                    Resolved::Ops(d)
                }
                Err(r) => r,
            },
            Found::Ask {
                question,
                options,
                notes,
            } => {
                let mut choices = Vec::new();
                for (label, cands) in options {
                    let then = if cands.is_empty() {
                        Then::Nothing("Nothing changed.".into())
                    } else {
                        match make(&cands) {
                            Ok(mut d) => {
                                d.notes.extend(notes.clone());
                                Then::Ops(d)
                            }
                            Err(r) => return r,
                        }
                    };
                    choices.push(Choice { label, then });
                }
                Resolved::Ask { question, choices }
            }
        }
    }

    /// Where a target points in the current edit.
    fn find(&self, p: &Project, tl: &Timeline, target: &Target, purpose: Purpose) -> Found {
        let t = &p.transcript;
        let dur = tl.duration;
        let span = |a: Us, b: Us| -> Found {
            match playback_span(tl, a, b) {
                Ok(spans) => Found::Picked(
                    vec![Cand {
                        label: format!("{}-{}", clock(a), clock(b.min(dur))),
                        spans,
                        words: None,
                    }],
                    vec![],
                ),
                Err(e) => Found::Reject(e.code().into(), capitalise(&e.to_string())),
            }
        };
        match target {
            Target::Range { start_ms, end_ms } => span(us(*start_ms), us(*end_ms)),
            Target::First { ms } => span(0, us(*ms)),
            Target::Last { ms } => {
                if us(*ms) > dur {
                    return Found::Reject(
                        "OUT_OF_RANGE".into(),
                        format!("The edited video is only {} long.", clock(dur)),
                    );
                }
                span(dur - us(*ms), dur)
            }
            Target::From { start_ms } => span(us(*start_ms), dur),
            Target::Until { end_ms } => span(0, us(*end_ms)),
            Target::Everything => span(0, dur),
            Target::At { ms } => Found::Reject(
                "NEEDS_A_SPAN".into(),
                format!(
                    "{} is a moment; say a span, e.g. \"{} to {}\".",
                    clock(us(*ms)),
                    clock(us(*ms)),
                    clock(us(*ms) + 5_000_000)
                ),
            ),
            Target::That => {
                let spans: Vec<SrcRange> = self
                    .last_spans
                    .iter()
                    .copied()
                    .filter(|s| tl.covered(s) > 0)
                    .collect();
                if spans.is_empty() {
                    return Found::Reject(
                        "NOTHING_REFERRED_TO".into(),
                        "I don't know what \"that\" refers to here; say which part.".into(),
                    );
                }
                Found::Picked(
                    vec![Cand {
                        label: "the same part as before".into(),
                        spans,
                        words: None,
                    }],
                    vec![],
                )
            }
            Target::Phrase { text, occurrence } => {
                let hits = find_phrase(t, tl, text);
                let playing: Vec<Hit> = hits
                    .iter()
                    .filter(|h| h.playback_start.is_some())
                    .cloned()
                    .collect();
                if playing.is_empty() {
                    return not_found(p, text, &hits);
                }
                let cands: Vec<Cand> = playing
                    .iter()
                    .map(|h| word_cand(p, tl, h.first, h.last))
                    .collect();
                let mut found = choose(cands, *occurrence, &format!("'{text}'"), true);
                if purpose != Purpose::Cut {
                    found = confidence_check(p, found, purpose);
                }
                found
            }
            Target::Topic { text, occurrence } => {
                let hits = find_topic(t, tl, text);
                if hits.is_empty() {
                    let all = find_phrase(t, tl, text);
                    return not_found(p, text, &all);
                }
                let mut cands: Vec<Cand> = Vec::new();
                let mut by_meaning = Vec::new();
                let mut notes = Vec::new();
                let mut seen: Vec<(usize, usize)> = Vec::new();
                for h in &hits {
                    let (a, b) = match sentence(t, h.word) {
                        Some(s) => s,
                        None => {
                            notes.push(format!(
                                "No sentence boundary near '{}' at {}; only that word is used.",
                                t.words[h.word].text,
                                clock(t.words[h.word].start)
                            ));
                            (h.word, h.word)
                        }
                    };
                    if seen.contains(&(a, b)) {
                        continue;
                    }
                    seen.push((a, b));
                    if !h.literal {
                        by_meaning.push(t.words[h.word].text.clone());
                    }
                    cands.push(word_cand(p, tl, a, b));
                }
                if !by_meaning.is_empty() {
                    // Meaning-based matches are always shown before cutting.
                    let mut options: Vec<(String, Vec<Cand>)> = cands
                        .iter()
                        .map(|c| (c.label.clone(), vec![c.clone()]))
                        .collect();
                    if cands.len() > 1 {
                        options.push((format!("All {}", cands.len()), cands.clone()));
                    }
                    options.push(("None of these".into(), vec![]));
                    return Found::Ask {
                        question: format!(
                            "'{text}' matched by meaning ({}): {}. Which should go?",
                            by_meaning.join(", "),
                            cands
                                .iter()
                                .map(|c| c.label.clone())
                                .collect::<Vec<_>>()
                                .join("; ")
                        ),
                        options,
                        notes,
                    };
                }
                match choose(cands, *occurrence, &format!("'{text}'"), true) {
                    Found::Picked(c, mut n) => {
                        n.extend(notes);
                        Found::Picked(c, n)
                    }
                    other => other,
                }
            }
            Target::AfterPhrase { text, occurrence }
            | Target::BeforePhrase { text, occurrence } => {
                let after = matches!(target, Target::AfterPhrase { .. });
                let hits = find_phrase(t, tl, text);
                let playing: Vec<Hit> = hits
                    .iter()
                    .filter(|h| h.playback_start.is_some())
                    .cloned()
                    .collect();
                if playing.is_empty() {
                    return not_found(p, text, &hits);
                }
                let mut cands = Vec::new();
                for h in &playing {
                    let pb = tl.source_to_playback(&h.range);
                    let (a, b) = if after {
                        (pb.last().map(|r| r.end).unwrap_or(0), dur)
                    } else {
                        (0, pb.first().map(|r| r.start).unwrap_or(0))
                    };
                    let Ok(spans) = playback_span(tl, a, b) else {
                        continue;
                    };
                    let ctx = context_words(p, h.first, h.last);
                    cands.push(Cand {
                        label: format!(
                            "{} '{}' (removes {}-{})",
                            clock(h.playback_start.unwrap_or(0)),
                            ctx,
                            clock(a),
                            clock(b)
                        ),
                        spans,
                        words: None,
                    });
                }
                if cands.is_empty() {
                    return Found::Reject(
                        "NOTHING_THERE".into(),
                        format!(
                            "Nothing plays {} '{text}'.",
                            if after { "after" } else { "before" }
                        ),
                    );
                }
                // "All" makes no sense here: after the first mention already covers the rest.
                choose(cands, *occurrence, &format!("'{text}'"), false)
            }
            Target::Speaker { who, topic } => self.find_speaker(p, tl, who, topic.as_deref()),
            Target::Profanity => {
                let mut cands = Vec::new();
                let mut notes = Vec::new();
                for (i, w) in t.words.iter().enumerate() {
                    if !PROFANITY.contains(&w.norm().as_str()) || tl.covered(&w.range()) == 0 {
                        continue;
                    }
                    if w.confidence < LOW_CONFIDENCE {
                        notes.push(format!("Not bleeped: '{}' at {} was recognised with low confidence ({:.2}); check it by ear.", w.text, clock(w.start), w.confidence));
                        continue;
                    }
                    cands.push(word_cand(p, tl, i, i));
                }
                if cands.is_empty() {
                    if notes.is_empty() {
                        return Found::Reject(
                            "NOT_FOUND".into(),
                            "No swear words were found in what still plays.".into(),
                        );
                    }
                    return Found::Reject("LOW_CONFIDENCE_ONLY".into(), notes.join(" "));
                }
                Found::Picked(cands, notes)
            }
        }
    }

    fn find_speaker(&self, p: &Project, tl: &Timeline, who: &Who, topic: Option<&str>) -> Found {
        let t = &p.transcript;
        let mut order: Vec<String> = Vec::new();
        for w in &t.words {
            if !order.contains(&w.speaker) {
                order.push(w.speaker.clone());
            }
        }
        let label = match who {
            Who::Host => order.first().cloned(),
            Who::Guest => order.get(1).cloned(),
            Who::Label(l) => order.iter().find(|s| s.eq_ignore_ascii_case(l)).cloned(),
        };
        let name = match who {
            Who::Host => "the host".to_owned(),
            Who::Guest => "the guest".to_owned(),
            Who::Label(l) => l.clone(),
        };
        let Some(label) = label else {
            return Found::Reject(
                "NO_SUCH_SPEAKER".into(),
                format!(
                    "There is no {name}: the transcript has {} speaker(s) ({}).",
                    order.len(),
                    order.join(", ")
                ),
            );
        };
        let topic_words: Vec<usize> = match topic {
            Some(tp) => find_topic(t, tl, tp).into_iter().map(|h| h.word).collect(),
            None => vec![],
        };
        let mut sentences: Vec<(usize, usize)> = Vec::new();
        let mut i = 0;
        while i < t.words.len() {
            let w = &t.words[i];
            if w.speaker != label || tl.covered(&w.range()) == 0 {
                i += 1;
                continue;
            }
            let (a, b) = sentence(t, i).unwrap_or((i, i));
            if topic.is_none() || topic_words.iter().any(|k| (a..=b).contains(k)) {
                sentences.push((a, b));
            }
            i = b + 1;
        }
        if sentences.is_empty() {
            return Found::Reject(
                "NOT_FOUND".into(),
                match topic {
                    Some(tp) => format!(
                        "{} never talks about '{tp}' in what still plays.",
                        capitalise(&name)
                    ),
                    None => format!("{} says nothing in what still plays.", capitalise(&name)),
                },
            );
        }
        let cands: Vec<Cand> = sentences
            .iter()
            .map(|(a, b)| word_cand(p, tl, *a, *b))
            .collect();
        let mut notes = Vec::new();
        for (a, b) in label_islands(t) {
            let near = sentences.iter().any(|(s, e)| a + 1 >= *s && b <= e + 1);
            if near {
                notes.push(format!(
                    "Speaker labels may be swapped at {} ('{}'): check that part before relying on it.",
                    clock(t.words[a].start),
                    t.text_between(&t.words[a].id, &t.words[b].id)
                ));
            }
        }
        for (a, b) in &sentences {
            let r = SrcRange {
                start: t.words[*a].start,
                end: t.words[*b].end,
            };
            if t.words
                .iter()
                .any(|w| w.speaker != label && w.range().intersect(&r).is_some())
            {
                notes.push(format!(
                    "Overlapping speech at {}-{}: the other speaker's words there go too.",
                    clock(r.start),
                    clock(r.end)
                ));
            }
        }
        // The host's lead-in question before the first selected line.
        let (first, _) = sentences[0];
        if first > 0 && t.words[first - 1].speaker != label {
            if let Some((qa, qb)) = sentence(t, first - 1) {
                if t.words[qb].text.trim_end().ends_with('?')
                    && tl.covered(&t.words[qb].range()) > 0
                {
                    let q = word_cand(p, tl, qa, qb);
                    let mut with_q = vec![q.clone()];
                    with_q.extend(cands.iter().cloned());
                    return Found::Ask {
                        question: format!(
                            "{} says this in {} line(s): {}. The other speaker leads in with a question at {}. Remove that question too?",
                            capitalise(&name),
                            cands.len(),
                            cands.iter().map(|c| c.label.clone()).collect::<Vec<_>>().join("; "),
                            q.label
                        ),
                        options: vec![
                            (format!("Only {name}'s lines"), cands),
                            (format!("Also the lead-in question {}", q.label), with_q),
                        ],
                        notes,
                    };
                }
            }
        }
        Found::Picked(cands, notes)
    }

    fn resolve_move(&self, p: &Project, tl: &Timeline, target: &Target, to: &Place) -> Resolved {
        let before: Option<Us> = match to {
            Place::Start => tl.segments.first().map(|s| s.source.start),
            Place::End => None,
            Place::At { ms } => match tl.playback_point(us(*ms)) {
                Some(t) => Some(t),
                None => {
                    return reject(
                        "OUT_OF_RANGE",
                        format!(
                            "{} is past the end ({} long).",
                            clock(us(*ms)),
                            clock(tl.duration)
                        ),
                    )
                }
            },
            Place::BeforePhrase { text } => {
                let hits = find_phrase(&p.transcript, tl, text);
                match hits.iter().find(|h| h.playback_start.is_some()) {
                    Some(h) => Some(h.range.start),
                    None => {
                        return reject("NOT_FOUND", format!("'{text}' is not in what still plays."))
                    }
                }
            }
        };
        let to_label = match to {
            Place::Start => "the start".to_owned(),
            Place::End => "the end".to_owned(),
            Place::At { ms } => clock(us(*ms)),
            Place::BeforePhrase { text } => format!("just before '{text}'"),
        };
        self.with_targets(p, tl, target, Purpose::Cut, |cands| {
            let mut spans: Vec<SrcRange> = cands.iter().flat_map(|c| c.spans.clone()).collect();
            spans.sort();
            let joined = spans.windows(2).all(|w| w[1].start - w[0].end <= 1_000);
            if !joined {
                return Err(reject(
                    "SPANS_A_CUT",
                    "That section crosses an earlier edit; move a section that plays in one piece.",
                ));
            }
            let range = SrcRange {
                start: spans[0].start,
                end: spans[spans.len() - 1].end,
            };
            if before == Some(range.start) {
                return Err(reject("ALREADY_THERE", "That section is already there."));
            }
            Ok(Done {
                ops: vec![Op::Reorder { range, before }],
                said: format!("Moved {} to {to_label}", labels(cands)),
                notes: vec![],
                typed: is_typed(target),
            })
        })
    }

    fn resolve_add_caption(
        &self,
        p: &Project,
        tl: &Timeline,
        text: &str,
        target: &Target,
    ) -> Resolved {
        if text.trim().is_empty() {
            return reject(
                "EMPTY_CAPTION",
                "The caption has no text; put it in quotes, e.g. add a caption 'Welcome!'.",
            );
        }
        let t = &p.transcript;
        let cands = match target {
            Target::That => {
                return reject(
                    "CAPTION_PLACE_MISSING",
                    "Say where the caption goes: \"when I say ...\" or \"at 1:20\".",
                );
            }
            Target::Everything => {
                return reject(
                    "CAPTION_PLACE_MISSING",
                    "A caption goes on some words or at a time, not the whole video.",
                )
            }
            Target::At { ms } => {
                let at = us(*ms);
                if at >= tl.duration {
                    return reject(
                        "OUT_OF_RANGE",
                        format!(
                            "{} is past the end: the edited video is {} long.",
                            clock(at),
                            clock(tl.duration)
                        ),
                    );
                }
                let src = tl.playback_point(at).unwrap_or(0);
                // The words said from that moment, up to the end of the sentence.
                let start = t
                    .words
                    .iter()
                    .position(|w| w.end > src && tl.covered(&w.range()) > 0);
                match start {
                    Some(i) if t.words[i].start - src < 1_000_000 => {
                        let mut j = i;
                        while j + 1 < t.words.len()
                            && j - i < 7
                            && !t.words[j].text.ends_with(['.', '?', '!'])
                            && t.words[j + 1].start - t.words[j].end < 400_000
                        {
                            j += 1;
                        }
                        vec![word_cand(p, tl, i, j)]
                    }
                    _ => {
                        // No speech there: anchor to that stretch of the source.
                        let spans = tl.playback_to_source(&PbRange {
                            start: at,
                            end: (at + 2_000_000).min(tl.duration),
                        });
                        vec![Cand {
                            label: clock(at),
                            spans: spans.into_iter().take(1).collect(),
                            words: None,
                        }]
                    }
                }
            }
            other => match self.find(p, tl, other, Purpose::Caption) {
                Found::Picked(c, _) => c,
                Found::Reject(code, reason) => return reject(&code, reason),
                Found::Ask {
                    question, options, ..
                } => {
                    let mut choices = Vec::new();
                    for (label, cands) in options {
                        let then = if cands.is_empty() {
                            Then::Nothing("Nothing changed.".into())
                        } else {
                            Then::Ops(caption_ops(p, &cands, text))
                        };
                        choices.push(Choice { label, then });
                    }
                    return Resolved::Ask {
                        question: question
                            .replace("Which should go?", "Which one gets the caption?")
                            .replace(", or all?", ", or all of them?"),
                        choices,
                    };
                }
            },
        };
        let mut d = caption_ops(p, &cands, text);
        d.typed = is_typed(target);
        Resolved::Ops(d)
    }

    fn with_captions(
        &self,
        tl: &Timeline,
        caption: &CaptionRef,
        verb: &str,
        make: impl Fn(&str, &CaptionStyle) -> Op,
        what: String,
    ) -> Resolved {
        let caps = &tl.captions;
        if caps.is_empty() {
            return reject(
                "NO_CAPTION",
                format!("There is no caption to {verb} yet. Add one first, e.g. \"add a caption 'Hi' when I say hello\"."),
            );
        }
        let label = |id: &str| -> String {
            let c = tl.caption(id).expect("caption exists");
            match c.playback.first() {
                Some(pb) => format!("'{}' at {}", short(&c.text), clock(pb.start)),
                None => format!("'{}' (hidden)", short(&c.text)),
            }
        };
        let build = |ids: &[String], note: Option<String>| -> Done {
            Done {
                ops: ids
                    .iter()
                    .map(|id| make(id, &tl.caption(id).expect("caption exists").style))
                    .collect(),
                // A few captions are named; many are counted.
                said: match ids.len() {
                    1 => format!("Caption {} {what}", label(&ids[0])),
                    2 | 3 => format!(
                        "Captions {} {what}",
                        ids.iter().map(|i| label(i)).collect::<Vec<_>>().join(", ")
                    ),
                    n if n == caps.len() => format!("All {n} captions {what}"),
                    n => format!("{n} captions {what}"),
                },
                notes: note.into_iter().collect(),
                typed: false,
            }
        };
        let ids: Vec<String> = match caption {
            CaptionRef::Id(id) => {
                if tl.caption(id).is_none() {
                    return reject("UNKNOWN_CAPTION", format!("There is no caption {id}."));
                }
                vec![id.clone()]
            }
            CaptionRef::All => caps.iter().map(|c| c.id.clone()).collect(),
            CaptionRef::Nth(n) => match caps.get((*n as usize).saturating_sub(1)) {
                Some(c) => vec![c.id.clone()],
                None => {
                    return reject(
                        "UNKNOWN_CAPTION",
                        format!("There are only {} caption(s).", caps.len()),
                    )
                }
            },
            CaptionRef::Text(t) => {
                let m: Vec<String> = caps
                    .iter()
                    .filter(|c| c.text.to_lowercase().contains(&t.to_lowercase()))
                    .map(|c| c.id.clone())
                    .collect();
                if m.is_empty() {
                    return reject("UNKNOWN_CAPTION", format!("No caption says '{t}'."));
                }
                m
            }
            CaptionRef::That => {
                if let Some(f) = self
                    .focus_caption
                    .as_ref()
                    .filter(|f| tl.caption(f).is_some())
                {
                    vec![f.clone()]
                } else if caps.len() == 1 {
                    let id = caps[0].id.clone();
                    let note = format!(
                        "Assumed \"that caption\" means {}, the only caption.",
                        label(&id)
                    );
                    return Resolved::Ops(build(&[id], Some(note)));
                } else {
                    vec![]
                }
            }
        };
        if ids.len() == 1 || matches!(caption, CaptionRef::All) {
            return Resolved::Ops(build(&ids, None));
        }
        // Several candidates: ask.
        let pool: Vec<String> = if ids.is_empty() {
            caps.iter().map(|c| c.id.clone()).collect()
        } else {
            ids
        };
        let mut choices: Vec<Choice> = pool
            .iter()
            .map(|id| Choice {
                label: label(id),
                then: Then::Ops(build(std::slice::from_ref(id), None)),
            })
            .collect();
        choices.push(Choice {
            label: format!("All {} captions", pool.len()),
            then: Then::Ops(build(&pool, None)),
        });
        Resolved::Ask {
            question: format!("Which caption should I {verb}? There are {}.", pool.len()),
            choices,
        }
    }

    fn resolve_keep_pause(&self, p: &Project, tl: &Timeline, target: &Target) -> Resolved {
        let t = &p.transcript;
        let gap_after = |i: usize| -> Option<SrcRange> {
            let next = t
                .words
                .get(i + 1)
                .map(|w| w.start)
                .unwrap_or(p.source.duration);
            SrcRange::new(t.words[i].end, next).filter(|r| r.len() >= MIN_PAUSE_US)
        };
        let gap_before = |i: usize| -> Option<SrcRange> {
            let prev = if i == 0 { 0 } else { t.words[i - 1].end };
            SrcRange::new(prev, t.words[i].start).filter(|r| r.len() >= MIN_PAUSE_US)
        };
        let (range, label) = match target {
            Target::Phrase { text, .. } | Target::BeforePhrase { text, .. } => {
                let after = matches!(target, Target::Phrase { .. });
                let hits = find_phrase(t, tl, text);
                let Some(h) = hits.iter().find(|h| h.playback_start.is_some()) else {
                    return not_found_resolved(p, text, &hits);
                };
                let g = if after {
                    gap_after(h.last)
                } else {
                    gap_before(h.first)
                };
                match g {
                    Some(r) => (
                        r,
                        format!(
                            "the pause {} '{text}'",
                            if after { "after" } else { "before" }
                        ),
                    ),
                    None => {
                        return reject(
                            "NO_PAUSE",
                            format!(
                                "There is no pause {} '{text}' to keep.",
                                if after { "after" } else { "before" }
                            ),
                        )
                    }
                }
            }
            Target::At { ms } => {
                let Some(src) = tl.playback_point(us(*ms)) else {
                    return reject(
                        "OUT_OF_RANGE",
                        format!("{} is past the end.", clock(us(*ms))),
                    );
                };
                let i = t.words.iter().position(|w| w.start > src);
                let r = match i {
                    Some(0) => SrcRange::new(0, t.words[0].start),
                    Some(i) => SrcRange::new(t.words[i - 1].end, t.words[i].start),
                    None => SrcRange::new(
                        t.words.last().map(|w| w.end).unwrap_or(0),
                        p.source.duration,
                    ),
                };
                match r.filter(|r| r.contains(src) && r.len() >= MIN_PAUSE_US) {
                    Some(r) => (r, format!("the pause at {}", clock(us(*ms)))),
                    None => {
                        return reject(
                            "NO_PAUSE",
                            format!(
                                "There is no pause at {}: someone is speaking.",
                                clock(us(*ms))
                            ),
                        )
                    }
                }
            }
            _ => {
                return reject(
                    "NO_PAUSE",
                    "Say which pause: \"keep the pause after 'thank you'\".",
                )
            }
        };
        Resolved::Ops(Done {
            ops: vec![Op::ProtectPause { range }],
            said: format!(
                "Protected {label} ({:.1} s); silence removal will keep it",
                to_secs_ms(range.len())
            ),
            notes: vec![],
            typed: is_typed(target),
        })
    }

    fn resolve_restore(&self, p: &Project, edit: &EditRef, keep: Option<&str>) -> Resolved {
        let off = p.restored();
        let pool: Vec<&incubrix_core::Tx> = p
            .active()
            .iter()
            .filter(|tx| {
                !off.contains(&tx.id) && !tx.ops.iter().any(|o| matches!(o, Op::Restore { .. }))
            })
            .collect();
        let removes = |tx: &incubrix_core::Tx| {
            tx.ops
                .iter()
                .any(|o| matches!(o, Op::Cut { .. } | Op::KeepOnly { .. }))
        };
        let kind_of = |tx: &incubrix_core::Tx, k: EditKind| -> bool {
            tx.ops.iter().any(|o| match k {
                EditKind::Cut => matches!(o, Op::Cut { .. } | Op::KeepOnly { .. }),
                EditKind::Speed => matches!(o, Op::Speed { .. }),
                EditKind::Caption => matches!(
                    o,
                    Op::AddCaption { .. }
                        | Op::StyleCaption { .. }
                        | Op::RetextCaption { .. }
                        | Op::RemoveCaption { .. }
                ),
                EditKind::Audio => matches!(o, Op::Mute { .. } | Op::Bleep { .. }),
                EditKind::Music => matches!(o, Op::AddMusic { .. } | Op::RemoveMusic { .. }),
                EditKind::Move => matches!(o, Op::Reorder { .. }),
                EditKind::Any => true,
            })
        };
        let restore = |tx: &incubrix_core::Tx, note: Option<String>| -> Done {
            let mut ops = vec![Op::Restore { tx: tx.id }];
            let mut notes: Vec<String> = note.into_iter().collect();
            if let Some(k) = keep {
                if k.contains("music") {
                    let music: Vec<Op> = tx
                        .ops
                        .iter()
                        .filter(|o| matches!(o, Op::AddMusic { .. }))
                        .cloned()
                        .collect();
                    if music.is_empty() {
                        notes.push(
                            "The music is not part of that edit, so it stays as it is.".into(),
                        );
                    } else {
                        notes.push("That edit also added the music; the music is kept.".into());
                        ops.extend(music);
                    }
                }
            }
            Done {
                ops,
                said: format!(
                    "Restored edit #{} ('{}'); every later edit is kept",
                    tx.id, tx.instruction
                ),
                notes,
                typed: false,
            }
        };
        let tx: &incubrix_core::Tx = match edit {
            EditRef::Id { id } => match pool.iter().find(|t| t.id == *id) {
                Some(t) => t,
                None => return from_err(EditError::UnknownTx(*id)),
            },
            EditRef::Recent { edit: k, back } => {
                let of_kind: Vec<&&incubrix_core::Tx> =
                    pool.iter().rev().filter(|t| kind_of(t, *k)).collect();
                match of_kind.get(*back as usize) {
                    Some(t) => t,
                    None => {
                        let what = match k {
                            EditKind::Cut => "cut",
                            EditKind::Speed => "speed change",
                            EditKind::Caption => "caption edit",
                            EditKind::Audio => "mute or bleep",
                            EditKind::Music => "music edit",
                            EditKind::Move => "move",
                            EditKind::Any => "edit",
                        };
                        return reject(
                            "NOTHING_TO_RESTORE",
                            format!(
                                "There are only {} active {what}(s), so there is no {} to undo.",
                                of_kind.len(),
                                match back {
                                    0 => "last one".to_owned(),
                                    1 => "second-to-last one".to_owned(),
                                    n => format!("{}th-to-last one", n + 1),
                                }
                            ),
                        );
                    }
                }
            }
            EditRef::Intro => {
                let hit = pool.iter().rev().find(|t| {
                    t.ops.iter().any(|o| match o {
                        Op::Cut { ranges, .. } => ranges.iter().any(|r| r.start == 0),
                        Op::KeepOnly { range } => range.start > 0,
                        _ => false,
                    })
                });
                match hit {
                    Some(t) => t,
                    None => {
                        return reject(
                            "NOTHING_TO_RESTORE",
                            "No active edit removed the opening of the video.",
                        )
                    }
                }
            }
            EditRef::Topic { text } => {
                let t = &p.transcript;
                let terms = crate::semantic::topic_terms(text);
                let hits: Vec<&&incubrix_core::Tx> = pool
                    .iter()
                    .filter(|tx| removes(tx))
                    .filter(|tx| {
                        tx.ops.iter().any(|o| match o {
                            Op::Cut { ranges, .. } => ranges.iter().any(|r| {
                                t.words_in(r)
                                    .any(|w| terms.contains(&crate::semantic::stem(&w.text)))
                            }),
                            _ => false,
                        })
                    })
                    .collect();
                match hits.len() {
                    0 => {
                        return reject(
                            "NOTHING_TO_RESTORE",
                            format!("No active edit removed anything about '{text}'."),
                        )
                    }
                    1 => hits[0],
                    _ => {
                        let choices = hits
                            .iter()
                            .map(|tx| Choice {
                                label: format!("#{} '{}'", tx.id, tx.instruction),
                                then: Then::Ops(restore(tx, None)),
                            })
                            .collect();
                        return Resolved::Ask { question: format!("Several edits removed something about '{text}'. Which one should come back?"), choices };
                    }
                }
            }
            EditRef::Removed => {
                let cuts: Vec<&&incubrix_core::Tx> = pool.iter().filter(|t| removes(t)).collect();
                match cuts.len() {
                    0 => return reject("NOTHING_TO_RESTORE", "Nothing has been removed."),
                    1 => {
                        let note = format!(
                            "Assumed you mean edit #{} ('{}'), the only removal.",
                            cuts[0].id, cuts[0].instruction
                        );
                        return Resolved::Ops(restore(cuts[0], Some(note)));
                    }
                    _ => {
                        let mut choices: Vec<Choice> = cuts
                            .iter()
                            .rev()
                            .map(|tx| Choice {
                                label: format!("#{} '{}'", tx.id, tx.instruction),
                                then: Then::Ops(restore(tx, None)),
                            })
                            .collect();
                        choices.push(Choice {
                            label: format!("All {} removals", cuts.len()),
                            then: Then::Ops(Done {
                                ops: cuts.iter().map(|t| Op::Restore { tx: t.id }).collect(),
                                said: format!(
                                    "Restored edits {}; every later edit is kept",
                                    cuts.iter()
                                        .map(|t| format!("#{}", t.id))
                                        .collect::<Vec<_>>()
                                        .join(", ")
                                ),
                                notes: vec![],
                                typed: false,
                            }),
                        });
                        return Resolved::Ask {
                            question: format!(
                                "{} edits removed content. Which should come back?",
                                cuts.len()
                            ),
                            choices,
                        };
                    }
                }
            }
        };
        Resolved::Ops(restore(tx, None))
    }

    fn vague(&self, p: &Project, tl: &Timeline, goal: VagueGoal) -> Resolved {
        let mut choices = Vec::new();
        let gaps = silences(
            &p.transcript,
            tl,
            p.source.duration,
            1_000_000,
            SILENCE_PAD_US,
        );
        if !gaps.is_empty() {
            let saved: Us = gaps.iter().map(|g| tl.covered(g)).sum();
            choices.push(Choice {
                label: format!(
                    "Remove {} silences longer than 1 s (saves about {:.1} s)",
                    gaps.len(),
                    to_secs_ms(saved)
                ),
                then: Then::Intent(Intent::RemoveSilences { min_ms: 1000 }),
            });
        }
        let f = fillers(&p.transcript, tl);
        if !f.ranges.is_empty() {
            choices.push(Choice {
                label: format!("Remove {} filler words", f.ranges.len()),
                then: Then::Intent(Intent::RemoveFillers),
            });
        }
        if goal == VagueGoal::Shorter {
            let saved = tl.duration - incubrix_core::time::playback_len(tl.duration, 1250);
            choices.push(Choice {
                label: format!(
                    "Play everything at 1.25x (saves about {:.1} s)",
                    to_secs_ms(saved)
                ),
                then: Then::Intent(Intent::Speed {
                    target: Target::Everything,
                    speed: 1250,
                }),
            });
        }
        choices.push(Choice {
            label: "None - I'll name a time range".into(),
            then: Then::Nothing(
                "Nothing changed. Say which part, e.g. \"cut 1:00 to 1:30\".".into(),
            ),
        });
        let question = match goal {
            VagueGoal::Boring => "Which part is boring? I won't guess on a cut. I can:".to_owned(),
            VagueGoal::Shorter => format!(
                "How should I make it shorter? It is {} now. I can:",
                clock(tl.duration)
            ),
        };
        Resolved::Ask { question, choices }
    }
}

/// What the target is for: decides the low-confidence checks.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Purpose {
    Cut,
    Mute,
    Bleep,
    Caption,
}

fn norm(s: &str) -> String {
    s.to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn labels(c: &[Cand]) -> String {
    c.iter()
        .map(|c| c.label.clone())
        .collect::<Vec<_>>()
        .join(", ")
}

fn context_words(p: &Project, a: usize, b: usize) -> String {
    let t = &p.transcript;
    short(&t.text_between(&t.words[a].id, &t.words[b].id))
}

fn word_cand(p: &Project, tl: &Timeline, a: usize, b: usize) -> Cand {
    let t = &p.transcript;
    let r = SrcRange {
        start: t.words[a].start,
        end: t.words[b].end.max(t.words[a].start + 1),
    };
    let pb = tl.source_to_playback(&r);
    let at = pb.first().map(|x| x.start).unwrap_or(0);
    let spans: Vec<SrcRange> = tl
        .segments
        .iter()
        .filter_map(|s| s.source.intersect(&r))
        .collect();
    Cand {
        label: format!("{} '{}'", clock(at), context_words(p, a, b)),
        spans,
        words: Some((a, b)),
    }
}

fn choose(cands: Vec<Cand>, occurrence: Option<Occurrence>, what: &str, allow_all: bool) -> Found {
    let n = cands.len();
    match occurrence {
        Some(Occurrence::All) if allow_all => Found::Picked(cands, vec![]),
        Some(Occurrence::Nth(k)) => match cands.get(k as usize - 1) {
            Some(c) => Found::Picked(vec![c.clone()], vec![]),
            None => Found::Reject(
                "NOT_FOUND".into(),
                format!("{what} is only said {n} time(s)."),
            ),
        },
        Some(Occurrence::Last) => Found::Picked(vec![cands[n - 1].clone()], vec![]),
        _ if n == 1 => Found::Picked(cands, vec![]),
        _ => {
            let times: Vec<String> = cands
                .iter()
                .map(|c| c.label.split(' ').next().unwrap_or("").to_owned())
                .collect();
            let list = match times.len() {
                0 | 1 => times.join(""),
                k => format!("{} and {}", times[..k - 1].join(", "), times[k - 1]),
            };
            let mut options: Vec<(String, Vec<Cand>)> = cands
                .iter()
                .map(|c| (c.label.clone(), vec![c.clone()]))
                .collect();
            if allow_all {
                options.push((format!("All {n}"), cands.clone()));
            }
            Found::Ask {
                question: if allow_all {
                    format!("{what} is mentioned {n} times: at {list}. Which one, or all?")
                } else {
                    format!("{what} is said {n} times: at {list}. Which one?")
                },
                options,
                notes: vec![],
            }
        }
    }
}

/// Mutes and bleeps on words recognised with low confidence ask first.
fn confidence_check(p: &Project, found: Found, purpose: Purpose) -> Found {
    let Found::Picked(cands, notes) = found else {
        return found;
    };
    let t = &p.transcript;
    let low: Vec<String> = cands
        .iter()
        .filter_map(|c| c.words)
        .flat_map(|(a, b)| a..=b)
        .filter(|i| t.words[*i].confidence < LOW_CONFIDENCE)
        .map(|i| {
            format!(
                "'{}' at {} ({:.2})",
                t.words[i].text,
                clock(t.words[i].start),
                t.words[i].confidence
            )
        })
        .collect();
    if low.is_empty() || purpose == Purpose::Caption {
        return Found::Picked(cands, notes);
    }
    let verb = if purpose == Purpose::Bleep {
        "Bleep"
    } else {
        "Mute"
    };
    Found::Ask {
        question: format!(
            "{} was recognised with low confidence, so it may not be that word. {verb} it anyway?",
            low.join(", ")
        ),
        options: vec![
            (format!("Yes, {} it", verb.to_lowercase()), cands),
            ("No, leave it".into(), vec![]),
        ],
        notes,
    }
}

fn not_found(p: &Project, text: &str, hits: &[Hit]) -> Found {
    match hits.first() {
        Some(h) => {
            let by = p
                .who_removed(&h.range)
                .map(|t| format!(" by edit #{t}"))
                .unwrap_or_default();
            Found::Reject(
                "CONTENT_REMOVED".into(),
                format!(
                    "'{text}' was said at {} (original time) but that part was removed{by}.",
                    clock(h.range.start)
                ),
            )
        }
        None => Found::Reject(
            "NOT_FOUND".into(),
            format!("I can't find '{text}' in the transcript."),
        ),
    }
}

fn not_found_resolved(p: &Project, text: &str, hits: &[Hit]) -> Resolved {
    match not_found(p, text, hits) {
        Found::Reject(code, reason) => reject(&code, reason),
        _ => reject("NOT_FOUND", format!("I can't find '{text}'.")),
    }
}

/// `n` fresh ids with this prefix.
fn ids(p: &Project, prefix: &str, n: usize) -> impl Iterator<Item = String> {
    let first: u32 = p
        .next_id(prefix)
        .rsplit('_')
        .next()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1);
    let prefix = prefix.to_owned();
    (0..n as u32).map(move |k| format!("{prefix}_{}", first + k))
}

/// Content anchors for a candidate: its words, or the words inside its
/// spans, or (no words) the spans themselves.
fn anchors(p: &Project, c: &Cand) -> Vec<Anchor> {
    let t = &p.transcript;
    if let Some((a, b)) = c.words {
        return vec![Anchor::Words {
            first: t.words[a].id.clone(),
            last: t.words[b].id.clone(),
        }];
    }
    c.spans
        .iter()
        .map(|r| {
            let inside: Vec<&incubrix_core::Word> = t
                .words
                .iter()
                .filter(|w| w.start >= r.start && w.end <= r.end)
                .collect();
            match (inside.first(), inside.last()) {
                (Some(f), Some(l)) if f.start - r.start < 300_000 && r.end - l.end < 300_000 => {
                    Anchor::Words {
                        first: f.id.clone(),
                        last: l.id.clone(),
                    }
                }
                _ => Anchor::Source { range: *r },
            }
        })
        .collect()
}

fn caption_ops(p: &Project, cands: &[Cand], text: &str) -> Done {
    let mut ids = ids(p, "cap", cands.len());
    let ops = cands
        .iter()
        .filter_map(|c| {
            let anchor = anchors(p, c).into_iter().next()?;
            Some(Op::AddCaption {
                id: ids.next().unwrap_or_default(),
                anchor,
                text: text.to_owned(),
                style: CaptionStyle::default(),
            })
        })
        .collect();
    let on: Vec<String> = cands
        .iter()
        .map(|c| match c.words {
            Some((a, b)) => format!(
                "'{}' ({}-{}, original {})",
                context_words(p, a, b),
                p.transcript.words[a].id,
                p.transcript.words[b].id,
                clock(p.transcript.words[a].start)
            ),
            None => c.label.clone(),
        })
        .collect();
    Done {
        ops,
        said: format!("Added caption '{text}' on {}", on.join(", ")),
        notes: vec![],
        typed: false,
    }
}

fn describe_change(c: &StyleChange) -> String {
    let mut parts = Vec::new();
    if let Some(col) = &c.color {
        parts.push(format!("colour {col}"));
    }
    if let Some(s) = c.size {
        parts.push(match s {
            SizeChange::Bigger => "bigger".into(),
            SizeChange::Smaller => "smaller".into(),
            SizeChange::Px(n) => format!("size {n}px"),
        });
    }
    if let Some(pos) = &c.position {
        parts.push(format!("at the {pos}"));
    }
    if let Some(b) = c.bold {
        parts.push(if b { "bold".into() } else { "not bold".into() });
    }
    format!("now {}", parts.join(", "))
}
