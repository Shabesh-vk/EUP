// SPDX-License-Identifier: AGPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Jareer and Concat contributors

//! The AI tab: a chat with the IncuBrix editing engine, run in-process.
//!
//! The engine (`incubrix-core`, `incubrix-nlu`) owns the edit: a history of
//! transactions replayed on the untouched source file. This pane carries the
//! user's words to it and shows the conversation:
//!
//! - every request goes to [`incubrix_nlu::Session::say`] on a worker (an AI
//!   model may be reading it); the reply is shown as a chat message - done,
//!   a question with options, or why not - with what changed;
//! - after any change, the engine's timeline is laid onto the EUP
//!   timeline in one gesture (one Ctrl+Z there too) - one clip per segment
//!   (in-point, length, speed, muted where a mute or bleep lands) and one
//!   title per caption - and the playhead moves to the change, so the
//!   preview shows it;
//! - word-based edits stand on a transcript made by EUP's transcriber.

use incubrix_core::time::{clock, source_len, to_secs};
use incubrix_core::{
    secs, Anchor, CaptionStyle, Op, Outcome, Project, SourceInfo, SrcRange, Status, Timeline,
    Transcript, Us, Word,
};
use incubrix_nlu::intent::{EditRef, Intent};
use incubrix_nlu::{parser_from_env, Action, Reply, Session};
use slint::{ModelRc, SharedString, VecModel};

use eup_project::Command;
use eup_project::commands::{ClipMove, ClipPatch, TrimEdge};
use eup_project::model::{Clip, ClipKind, TextStyle};
use eup_speech::transcribe::{Segment, TranscribeRequest};

use crate::host::spawn_in_project;
use crate::panes::settings::installed;
use crate::studio::Studio;
use crate::ui::{AiEditData, AiMessageData, AiPanelData};

/// The video the engine edits: one file, all of it, where it sits on the
/// timeline.
#[derive(Clone, Debug)]
struct Base {
    media_id: String,
    path: String,
    name: String,
    track_id: String,
    /// Timeline seconds where the edit starts.
    start: f64,
    /// Seconds of file: the whole of it is the source.
    window: f64,
    fps: (u32, u32),
    has_audio: bool,
    /// How many clips of it were on the timeline when the chat began.
    pieces: usize,
}

enum Words {
    None,
    Running,
    Ready { transcript: Transcript, note: String },
    Failed(String),
}

/// One exchange of the chat.
struct Turn {
    /// What the user said; empty for a note from the editor alone.
    prompt: String,
    outcome: Outcome,
    /// Who read the words ("AI model ...", "built-in phrases", ...).
    reader: String,
    /// Where the playhead was moved to show the change.
    shown_at: Option<Us>,
    /// The request needs the words said; the editor is listening first.
    listening: bool,
}

/// The AI tab's state.
pub struct AiPane {
    session: Option<Session>,
    base: Option<Base>,
    /// Clips on the timeline the engine laid down (or started from).
    managed: Vec<String>,
    turns: Vec<Turn>,
    words: Words,
    gestures: u64,
    /// The request being read on a worker, while the session is away.
    busy: Option<String>,
    /// What the tab showed when the session left for the worker.
    frozen: Option<AiPanelData>,
    /// A request to carry out once the speech has been analysed.
    after_words: Option<String>,
    /// Captions the timeline already had when the chat began, by the
    /// engine's caption id: how each looked, so it keeps its look on the
    /// way back.
    adopted: std::collections::HashMap<String, Adopted>,
}

/// A caption that was on the timeline before the chat: its own look, and
/// that look as the engine was told it.
#[derive(Clone, Debug)]
struct Adopted {
    style: TextStyle,
    offset_y: f64,
    engine: CaptionStyle,
}

impl Default for AiPane {
    fn default() -> Self {
        Self {
            session: None,
            base: None,
            managed: Vec::new(),
            turns: Vec::new(),
            words: Words::None,
            gestures: 0,
            busy: None,
            frozen: None,
            after_words: None,
            adopted: std::collections::HashMap::new(),
        }
    }
}

/// The video to edit and the clips of it on the timeline. The file is the
/// selected clip's, else the one with the most time on the timeline; every
/// clip of that file on that lane is part of the edit, so a timeline already
/// cut into pieces is edited as the one video it is.
fn find_base(studio: &Studio) -> Result<(Base, Vec<String>), String> {
    let tl = studio.timeline();
    let videos: Vec<_> = tl
        .clips
        .iter()
        .filter(|c| c.kind == ClipKind::Video)
        .collect();
    let chosen = studio
        .sole_selection()
        .and_then(|id| videos.iter().find(|c| c.id == id).cloned())
        .or_else(|| {
            videos
                .iter()
                .max_by(|a, b| {
                    (a.duration * a.speed)
                        .partial_cmp(&(b.duration * b.speed))
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .cloned()
        })
        .ok_or_else(|| "Add a video to the timeline, then tell me what to change.".to_owned())?;
    let media = studio
        .project()
        .media_by_id(&chosen.media_id)
        .ok_or_else(|| "The clip's file is missing from the bin.".to_owned())?;
    let pieces: Vec<_> = videos
        .iter()
        .filter(|c| c.media_id == chosen.media_id && c.track_id == chosen.track_id)
        .collect();
    let covered = pieces
        .iter()
        .map(|c| c.source_start + c.duration * c.speed)
        .fold(0.0, f64::max);
    let window = media.duration.filter(|d| *d > 0.0).unwrap_or(covered);
    let start = pieces.iter().map(|c| c.start).fold(f64::MAX, f64::min);
    let fps = media
        .frame_rate_fraction
        .as_deref()
        .and_then(|f| {
            let (n, d) = f.split_once('/')?;
            Some((n.trim().parse().ok()?, d.trim().parse().ok()?))
        })
        .or_else(|| media.frame_rate.map(|r| ((r * 1000.0).round() as u32, 1000)))
        .unwrap_or((30, 1));
    Ok((
        Base {
            media_id: chosen.media_id.clone(),
            path: media.path.clone(),
            name: media.name.clone(),
            track_id: chosen.track_id.clone(),
            start: if start.is_finite() { start } else { 0.0 },
            window,
            fps,
            has_audio: media.has_audio,
            pieces: pieces.len(),
        },
        pieces.iter().map(|c| c.id.clone()).collect(),
    ))
}

fn source_info(b: &Base) -> SourceInfo {
    SourceInfo {
        path: b.path.clone(),
        sha256: String::new(),
        duration: secs(b.window),
        fps_num: b.fps.0,
        fps_den: b.fps.1,
        has_audio: b.has_audio,
        variable_frame_rate: false,
    }
}

impl AiPane {
    fn transcript(&self) -> Transcript {
        match &self.words {
            Words::Ready { transcript, .. } => transcript.clone(),
            _ => Transcript::default(),
        }
    }

    fn note(&mut self, project: &Project, text: String) {
        self.turns.push(Turn {
            prompt: String::new(),
            reader: String::new(),
            shown_at: None,
            listening: false,
            outcome: Outcome::rejected_with(project, "NOTE", text),
        });
    }

    /// The session, started on the timeline as it is when there is none,
    /// or when the clips it laid down were changed by hand.
    fn ensure(&mut self, studio: &Studio) -> Result<(), String> {
        let intact = !self.managed.is_empty() && self.managed.iter().all(|id| studio.clip(id).is_some());
        if self.session.is_some() && intact {
            return Ok(());
        }
        let (base, managed) = find_base(studio)?;
        if let Some(old) = self.session.take() {
            self.note(
                &old.project,
                "The clips I made were changed by hand, so I'm starting fresh from the timeline as it is now. (Use Undo here for my changes.)".into(),
            );
        }
        if self.base.as_ref().is_some_and(|b| b.media_id != base.media_id) {
            self.words = Words::None;
        }
        let mut project = Project::new(source_info(&base), self.transcript());
        // The captions already over the video become the engine's starting
        // point, so a cut or a speed change carries them with their picture
        // and "make the captions red" reaches them too.
        let pieces: Vec<Clip> = managed.iter().filter_map(|id| studio.clip(id).cloned()).collect();
        let found = existing_captions(studio, &pieces, base.window);
        let mut managed = managed;
        self.adopted.clear();
        if !found.is_empty() {
            let mut ops = Vec::new();
            for (n, (clip_id, range, adopted)) in found.into_iter().enumerate() {
                let id = format!("cap_{}", n + 1);
                ops.push(Op::AddCaption {
                    id: id.clone(),
                    anchor: Anchor::Source { range },
                    text: adopted.style.content.clone(),
                    style: adopted.engine.clone(),
                });
                self.adopted.insert(id, adopted);
                managed.push(clip_id);
            }
            if project.start_with("captions already on the timeline", ops).is_err() {
                // Not ours to carry, then: leave them where they are.
                self.adopted.clear();
                managed.truncate(pieces.len());
            }
        }
        self.session = Some(Session::new(project, parser_from_env()));
        self.managed = managed;
        self.base = Some(base);
        Ok(())
    }
}

/// Runs `body` on the pane with the studio free to borrow.
fn with_pane(studio: &mut Studio, body: impl FnOnce(&mut AiPane, &mut Studio)) {
    let mut pane = std::mem::take(&mut studio.ai);
    body(&mut pane, studio);
    studio.ai = pane;
}

/// A request typed or clicked. Read on a worker thread: with an AI model
/// that is a network call, and the window must not wait on it.
pub fn say(studio: &mut Studio, text: &str) {
    let text = text.trim().to_owned();
    if text.is_empty() || studio.ai.busy.is_some() {
        return;
    }
    with_pane(studio, |pane, studio| {
        if let Err(why) = pane.ensure(studio) {
            studio.notify(&why, true);
            return;
        }
        pane.frozen = Some(pane.data(studio));
        let mut session = pane.session.take().expect("ensured");
        if session.model_label().is_none() && incubrix_nlu::llm::LlmConfig::detected().is_some() {
            session.set_parser(parser_from_env());
        }
        pane.busy = Some(text.clone());
        spawn_in_project(
            move || {
                let before = session.project.hash();
                let reply = session.say(&text);
                (session, reply, before, text)
            },
            |studio, _, _, (session, reply, before, text)| {
                with_pane(studio, |pane, studio| {
                    pane.session = Some(session);
                    pane.busy = None;
                    pane.frozen = None;
                    finish(pane, studio, text, reply, before);
                });
            },
        );
    });
}

/// An intent from a button: applied at once, no reading needed.
fn run(studio: &mut Studio, label: &str, intent: Intent) {
    if studio.ai.busy.is_some() {
        return;
    }
    with_pane(studio, |pane, studio| {
        if let Err(why) = pane.ensure(studio) {
            studio.notify(&why, true);
            return;
        }
        let session = pane.session.as_mut().expect("ensured");
        let before = session.project.hash();
        let mut reply = session.run(label, intent);
        reply.reader = "button".into();
        finish(pane, studio, label.to_owned(), reply, before);
    });
}

/// An option of the waiting question, by row.
pub fn answer(studio: &mut Studio, row: i32) {
    if studio.ai.busy.is_some() {
        return;
    }
    with_pane(studio, |pane, studio| {
        let Some(session) = pane.session.as_mut() else { return };
        let Some(label) = session
            .pending()
            .and_then(|(_, options)| options.get(row.max(0) as usize).cloned())
        else {
            return;
        };
        let before = session.project.hash();
        let reply = session.answer(&label);
        finish(pane, studio, label, reply, before);
    });
}

/// The engine's undo or redo: one request back or forward.
pub fn step(studio: &mut Studio, redo: bool) {
    if redo {
        run(studio, "Redo", Intent::Redo { steps: 1 });
    } else {
        run(studio, "Undo", Intent::Undo { steps: 1 });
    }
}

/// Switches one earlier change off, keeping the ones after it.
pub fn restore(studio: &mut Studio, edit: i32) {
    run(
        studio,
        &format!("Undo just change #{edit}"),
        Intent::Restore { edit: EditRef::Id { id: edit.max(0) as u32 }, keep: None },
    );
}

/// A new chat; the timeline stays as it is.
pub fn reset(studio: &mut Studio) {
    if studio.ai.busy.is_some() {
        return;
    }
    with_pane(studio, |pane, _| {
        pane.session = None;
        pane.turns.clear();
        pane.managed.clear();
    });
}

fn finish(pane: &mut AiPane, studio: &mut Studio, prompt: String, reply: Reply, before: String) {
    let Reply { outcome, action, reader } = reply;
    let session = pane.session.as_ref().expect("a session answered");
    let mut shown_at = None;
    if session.project.hash() != before {
        let tl = session.project.timeline().timeline;
        lay(pane, studio, &tl);
        // Show the change: the playhead goes where it happened.
        let session = pane.session.as_ref().expect("still here");
        if outcome.tx.is_some() {
            shown_at = session
                .project
                .active()
                .last()
                .and_then(|tx| where_shown(session, &tl, &tx.ops));
        }
        let at = shown_at.unwrap_or(0);
        if let Some(base) = &pane.base {
            studio.seek((base.start + to_secs(at)) as f32);
        }
    }
    if action == Some(Action::Render) {
        studio.notify("The timeline shows the edit: use Export to save the video.", false);
    }
    // Captions on words, fillers, topics: they need to know what is said.
    // With no transcript yet, listen first and then carry on by itself.
    let needs_words = outcome.status == Status::Rejected
        && matches!(outcome.code.as_deref(), Some("NO_TRANSCRIPT" | "NOT_FOUND"))
        && pane.transcript().words.is_empty()
        && pane.base.as_ref().is_some_and(|b| b.has_audio)
        && !matches!(pane.words, Words::Ready { .. });
    if needs_words {
        pane.after_words = Some(prompt.clone());
        if !matches!(pane.words, Words::Running) {
            start_transcribe(pane, studio);
        }
    }
    let listening = needs_words && matches!(pane.words, Words::Running);
    pane.turns.push(Turn { prompt, outcome, reader, shown_at, listening });
}

/// A note from the editor in the conversation.
fn note(pane: &mut AiPane, text: String) {
    if let Some(s) = &pane.session {
        let outcome = Outcome::rejected_with(&s.project, "NOTE", text);
        pane.turns.push(Turn {
            prompt: String::new(),
            outcome,
            reader: String::new(),
            shown_at: None,
            listening: false,
        });
    }
}

/// Where in the edited video a change can be seen.
fn where_shown(session: &Session, tl: &Timeline, ops: &[Op]) -> Option<Us> {
    let play = |t: Us| -> Us {
        tl.source_point(t).unwrap_or_else(|| {
            // Removed content: the moment the video jumps over it.
            tl.segments
                .iter()
                .find(|s| s.source.start >= t)
                .map(|s| s.playback_start)
                .unwrap_or(tl.duration)
        })
    };
    let op = ops.first()?;
    match op {
        Op::Cut { ranges, .. } => ranges.first().map(|r| play(r.end)),
        Op::KeepOnly { .. } => Some(0),
        Op::Speed { range, .. } | Op::Reorder { range, .. } | Op::ProtectPause { range } => {
            Some(play(range.start))
        }
        Op::AddCaption { id, .. } | Op::StyleCaption { id, .. } | Op::RetextCaption { id, .. } => {
            tl.caption(id).and_then(|c| c.playback.first()).map(|p| p.start)
        }
        Op::Mute { id, .. } | Op::Bleep { id, .. } => tl
            .marks
            .iter()
            .find(|m| &m.id == id)
            .and_then(|m| m.playback.first())
            .map(|p| p.start),
        Op::Restore { tx } => session
            .project
            .active()
            .iter()
            .find(|t| t.id == *tx)
            .and_then(|t| t.ops.first())
            .and_then(|o| match o {
                Op::Cut { ranges, .. } => ranges.first().map(|r| play(r.start)),
                Op::Speed { range, .. } | Op::KeepOnly { range } | Op::Reorder { range, .. } => {
                    Some(play(range.start))
                }
                _ => None,
            }),
        _ => None,
    }
}

/// One clip's worth of the engine's timeline.
struct Piece {
    playback: f64,
    source: f64,
    length: f64,
    speed: f64,
    muted: bool,
}

fn pieces(tl: &Timeline) -> Vec<Piece> {
    let mut out = Vec::new();
    for s in &tl.segments {
        // Cut each segment where a mute or bleep starts or ends, so the
        // silenced words are a clip of their own.
        let mut cuts = vec![s.playback_start, s.playback_end()];
        for m in &tl.marks {
            for p in &m.playback {
                for t in [p.start, p.end] {
                    if t > s.playback_start && t < s.playback_end() {
                        cuts.push(t);
                    }
                }
            }
        }
        cuts.sort_unstable();
        cuts.dedup();
        for w in cuts.windows(2) {
            let (a, b) = (w[0], w[1]);
            let muted = tl
                .marks
                .iter()
                .any(|m| m.playback.iter().any(|p| p.start <= a && p.end >= b));
            out.push(Piece {
                playback: to_secs(a),
                source: to_secs(s.source.start + source_len(a - s.playback_start, s.speed)),
                length: to_secs(source_len(b - a, s.speed)),
                speed: s.speed as f64 / 1000.0,
                muted,
            });
        }
    }
    out
}

/// Replaces the managed clips with the engine's timeline, as one gesture.
fn lay(pane: &mut AiPane, studio: &mut Studio, tl: &Timeline) {
    let Some(base) = pane.base.clone() else { return };
    pane.gestures += 1;
    let g = format!("incubrix-{}", pane.gestures);
    studio.flush_commit();
    studio.apply_within(
        &g,
        Command::RemoveClips {
            clip_ids: std::mem::take(&mut pane.managed),
            ripple: false,
        },
    );
    let far = studio
        .timeline()
        .clips
        .iter()
        .map(|c| c.start + c.duration)
        .fold(0.0, f64::max)
        + 60.0;
    let mut made = Vec::new();
    for p in pieces(tl) {
        let Some(id) = studio.apply_within(
            &g,
            Command::AddClip {
                media_id: base.media_id.clone(),
                track_id: base.track_id.clone(),
                start: far,
                ripple: false,
            },
        ) else {
            continue;
        };
        if p.source > 0.0 {
            studio.apply_within(&g, Command::TrimClip { clip_id: id.clone(), edge: TrimEdge::Start, delta: p.source, ripple: false });
        }
        let length = studio.clip(&id).map(|c| c.duration).unwrap_or(p.length);
        if length > p.length {
            studio.apply_within(&g, Command::TrimClip { clip_id: id.clone(), edge: TrimEdge::End, delta: p.length - length, ripple: false });
        }
        if (p.speed - 1.0).abs() > 1e-6 {
            studio.apply_within(&g, Command::SetClipSpeed { clip_id: id.clone(), speed: p.speed });
        }
        if p.muted {
            studio.apply_within(&g, Command::UpdateClip { clip_id: id.clone(), patch: ClipPatch { muted: Some(true), ..Default::default() } });
        }
        studio.apply_within(
            &g,
            Command::MoveClips {
                moves: vec![ClipMove { clip_id: id.clone(), start: base.start + p.playback, track_id: base.track_id.clone() }],
            },
        );
        made.push(id);
    }
    for c in &tl.captions {
        for p in &c.playback {
            let (style, offset) = caption_look(c, pane.adopted.get(&c.id));
            if let Some(id) = studio.apply_within(
                &g,
                Command::AddTextClip {
                    track_id: None,
                    above: true,
                    start: base.start + to_secs(p.start),
                    style: Some(style),
                    duration: Some(to_secs(p.len())),
                    offset_y: Some(offset),
                },
            ) {
                made.push(id);
            }
        }
    }
    pane.managed = made;
}

/// Where a position name puts a caption, as a share of the frame from its
/// middle.
fn position_offset(position: &str) -> f64 {
    match position {
        "top" => -0.35,
        "center" => 0.0,
        _ => 0.35,
    }
}

/// How a caption of the engine's timeline is drawn: an adopted one in its
/// own look, with only what the engine changed changed; one the engine made
/// in the engine's look.
fn caption_look(c: &incubrix_core::timeline::Caption, adopted: Option<&Adopted>) -> (TextStyle, f64) {
    let weight = |bold: bool| if bold { 800.0 } else { 600.0 };
    let Some(a) = adopted else {
        let style = TextStyle {
            content: c.text.clone(),
            font_family: "Hanken Grotesk".to_owned(),
            font_size: c.style.size as f64 / 1080.0,
            font_weight: weight(c.style.bold),
            color: c.style.color.clone(),
            ..TextStyle::default()
        };
        return (style, position_offset(&c.style.position));
    };
    let mut style = a.style.clone();
    style.content = c.text.clone();
    if c.style.color != a.engine.color {
        style.color = c.style.color.clone();
    }
    if c.style.size != a.engine.size {
        style.font_size = c.style.size as f64 / 1080.0;
    }
    if c.style.bold != a.engine.bold {
        style.font_weight = weight(c.style.bold);
    }
    let offset = if c.style.position != a.engine.position {
        position_offset(&c.style.position)
    } else {
        a.offset_y
    };
    (style, offset)
}

/// Timeline seconds to file seconds through the video's clips: inside a
/// clip by its in-point and speed, outside every clip clamped to the
/// nearest one's edge, and never past the file.
fn to_source(pieces: &[Clip], window: f64, t: f64) -> f64 {
    let edge = |c: &Clip| (c.start - t).abs().min((c.start + c.duration - t).abs());
    let piece = pieces
        .iter()
        .find(|c| t >= c.start && t < c.start + c.duration)
        .or_else(|| {
            pieces
                .iter()
                .min_by(|a, b| edge(a).partial_cmp(&edge(b)).unwrap_or(std::cmp::Ordering::Equal))
        });
    let at = match piece {
        Some(c) => c.source_start + (t.clamp(c.start, c.start + c.duration) - c.start) * c.speed,
        None => t,
    };
    at.clamp(0.0, window)
}

/// The text clips over the video being edited, oldest first on the
/// timeline, each with the span of the file under it and its look. The
/// span is read through the video's clips, so a caption sits on the
/// picture it was shown over even when the video was trimmed or sped up
/// by hand.
fn existing_captions(studio: &Studio, pieces: &[Clip], window: f64) -> Vec<(String, SrcRange, Adopted)> {
    let Some(first) = pieces.iter().map(|c| c.start).reduce(f64::min) else {
        return Vec::new();
    };
    let last = pieces.iter().map(|c| c.start + c.duration).fold(first, f64::max);
    let mut found: Vec<(f64, String, SrcRange, Adopted)> = studio
        .timeline()
        .clips
        .iter()
        .filter(|c| c.kind == ClipKind::Text && c.start < last && c.start + c.duration > first)
        .filter_map(|c| {
            let style = c.text.clone().filter(|s| !s.content.trim().is_empty())?;
            let range = SrcRange::new(
                secs(to_source(pieces, window, c.start)),
                secs(to_source(pieces, window, c.start + c.duration)),
            )?;
            Some((c.start, c.id.clone(), range, adopt(style, c.offset_y)))
        })
        .collect();
    found.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    found.into_iter().map(|(_, id, range, a)| (id, range, a)).collect()
}

/// A text clip's look, and the same look in the engine's terms.
fn adopt(style: TextStyle, offset_y: f64) -> Adopted {
    let position = if offset_y < -0.15 {
        "top"
    } else if offset_y > 0.15 {
        "bottom"
    } else {
        "center"
    };
    let engine = CaptionStyle {
        color: style.color.clone(),
        size: (style.font_size * 1080.0).round().max(1.0) as u32,
        position: position.to_owned(),
        bold: style.font_weight >= 700.0,
    };
    Adopted { style, offset_y, engine }
}

/// Transcribes the video with EUP's transcriber, for word-based edits.
pub fn transcribe(studio: &mut Studio) {
    with_pane(studio, start_transcribe);
}

fn start_transcribe(pane: &mut AiPane, studio: &mut Studio) {
    let base = match pane.base.clone() {
        Some(b) => b,
        None => match find_base(studio) {
            Ok((b, _)) => b,
            Err(why) => {
                studio.notify(&why, true);
                return;
            }
        },
    };
    let Some(model) = installed(&studio.settings.transcribers).first().map(|m| m.id.clone()) else {
        let why = "To listen to the video I need a speech model: download one in Settings > Transcriber, then ask me again.".to_owned();
        pane.words = Words::Failed(why.clone());
        if pane.after_words.take().is_some() {
            note(pane, why);
        }
        return;
    };
    let request = TranscribeRequest {
        path: base.path.clone(),
        audio_stream: None,
        source_start: 0.0,
        window: base.window,
        model_id: model.clone(),
    };
    pane.words = Words::Running;
    let dirs = studio.host.dirs.clone();
    let transcriber = std::sync::Arc::clone(&studio.host.transcriber);
    spawn_in_project(
        move || transcriber.transcribe(&dirs, &request, |_| {}),
        move |studio, _, _, result: Result<Vec<Segment>, String>| {
            let mut retry = None;
            with_pane(studio, |pane, _| {
                match result {
                    Err(e) => {
                        pane.words = Words::Failed(format!("Couldn't analyse the speech: {e}"));
                        if pane.after_words.take().is_some() {
                            note(pane, format!("Sorry, I couldn't listen to the video: {e}"));
                        }
                    }
                    Ok(segments) => {
                        let transcript = words_from_segments(&segments);
                        let n = transcript.words.len();
                        pane.words = Words::Ready {
                            transcript,
                            note: format!("{n} words from the {model} transcriber. It times phrases, not words, so word times are spread evenly inside each phrase and word edits can be a few tenths of a second off."),
                        };
                        adopt_transcript(pane);
                        if let Some(text) = pane.after_words.take() {
                            if n > 0 {
                                note(pane, format!("I've listened to the video ({n} words). Now carrying on with \"{text}\"."));
                                retry = Some(text);
                            } else {
                                note(pane, "I listened to the whole video but couldn't make out any speech, so I can't do that by what's said. Captions at a time still work - for example \"add a caption 'Hello' at 0:05\".".into());
                            }
                        }
                    }
                }
            });
            if let Some(text) = retry {
                say(studio, &text);
            }
        },
    );
}

/// Phrase timings to word timings: each phrase's time shared out by length.
fn words_from_segments(segments: &[Segment]) -> Transcript {
    let mut words = Vec::new();
    for s in segments {
        let parts: Vec<&str> = s.text.split_whitespace().collect();
        let total: usize = parts.iter().map(|w| w.chars().count().max(1)).sum();
        if total == 0 || s.end <= s.start {
            continue;
        }
        let mut at = s.start;
        for w in parts {
            let len = (s.end - s.start) * w.chars().count().max(1) as f64 / total as f64;
            words.push(Word {
                id: format!("w{:05}", words.len()),
                text: w.to_owned(),
                start: secs(at),
                end: secs(at + len),
                speaker: "S1".into(),
                confidence: 0.8,
            });
            at += len;
        }
    }
    Transcript { words }
}

/// Puts a fresh transcript under the session, replaying its edits on it.
fn adopt_transcript(pane: &mut AiPane) {
    let Some(base) = pane.base.clone() else { return };
    let transcript = pane.transcript();
    let Some(old) = pane.session.take() else { return };
    let mut project = Project::new(source_info(&base), transcript);
    for tx in old.project.starting() {
        let _ = project.start_with(&tx.instruction, tx.ops.clone());
    }
    for tx in old.project.edits() {
        // Edits so far were made without words, so they replay unchanged.
        let _ = project.apply(&tx.instruction, tx.ops.clone());
    }
    pane.session = Some(Session::new(project, parser_from_env()));
}

/// Starts an installed Ollama in the background, once, when no AI model is
/// set up: then requests in plain English work without a key or a manual
/// step. It is found again within seconds by `LlmConfig::detected`.
fn wake_local_model() {
    use std::sync::atomic::{AtomicBool, Ordering};
    static TRIED: AtomicBool = AtomicBool::new(false);
    if TRIED.swap(true, Ordering::Relaxed) {
        return;
    }
    let wanted = std::env::var("NLU_PROVIDER").map(|v| v.to_lowercase()).unwrap_or_default();
    if matches!(wanted.as_str(), "rules" | "mock" | "anthropic" | "claude" | "openai")
        || std::env::var_os("ANTHROPIC_API_KEY").is_some()
        || std::env::var_os("OPENAI_API_KEY").is_some()
    {
        return;
    }
    std::thread::spawn(|| {
        if incubrix_nlu::llm::LlmConfig::detect().is_some() {
            return;
        }
        let mut cmd = std::process::Command::new("ollama");
        cmd.arg("serve")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // No console window.
            cmd.creation_flags(0x0800_0000);
        }
        match cmd.spawn() {
            Ok(_) => log::info!("ai: started a local Ollama server"),
            Err(e) => log::info!("ai: no local model to start ({e})"),
        }
    });
}

fn short_hash(h: &str) -> String {
    h.chars().take(12).collect()
}

fn model<T: Clone + 'static>(v: Vec<T>) -> ModelRc<T> {
    ModelRc::new(VecModel::from(v))
}

fn strings(v: &[String]) -> ModelRc<SharedString> {
    model(v.iter().map(|s| SharedString::from(s.as_str())).collect())
}

/// Lines shown at once in a reply; the rest wait behind "Show more".
const SHOWN_CHANGES: usize = 3;
const SHOWN_NOTES: usize = 2;
/// A reply's text past this is cut at a sentence.
const TEXT_CHARS: usize = 320;

/// Repeated lines once, with a count: 73 x "Changed how the caption looks".
fn fold(lines: Vec<String>) -> Vec<String> {
    let mut out: Vec<(String, usize)> = Vec::new();
    for l in lines {
        match out.iter_mut().find(|(x, _)| *x == l) {
            Some(e) => e.1 += 1,
            None => out.push((l, 1)),
        }
    }
    out.into_iter()
        .map(|(l, n)| if n > 1 { format!("{l} (x{n})") } else { l })
        .collect()
}

/// The text, at most [`TEXT_CHARS`], ending at a sentence; the rest is
/// returned for "Show more".
fn shorten(text: String) -> (String, Option<String>) {
    if text.chars().count() <= TEXT_CHARS {
        return (text, None);
    }
    let cut: String = text.chars().take(TEXT_CHARS).collect();
    let end = cut.rfind(". ").map(|i| i + 1).unwrap_or(cut.len());
    let (head, tail) = text.split_at(end);
    (format!("{}...", head.trim_end()), Some(tail.trim().to_owned()))
}

fn reply(kind: i32, title: &str, text: String, changes: Vec<String>, notes: Vec<String>, options: Vec<String>) -> AiMessageData {
    // Every reply is a summary: a short text, the first few changes and
    // notes; everything else is one click away.
    let (text, rest) = shorten(text);
    let mut changes = fold(changes);
    let mut notes = fold(notes);
    let mut more: Vec<String> = Vec::new();
    if let Some(rest) = rest {
        more.push(rest);
    }
    if changes.len() > SHOWN_CHANGES {
        more.extend(changes.split_off(SHOWN_CHANGES).into_iter().map(|c| format!("- {c}")));
    }
    if notes.len() > SHOWN_NOTES {
        more.extend(notes.split_off(SHOWN_NOTES).into_iter().map(|n| format!("Note: {n}")));
    }
    AiMessageData {
        mine: false,
        kind,
        title: title.into(),
        text: text.into(),
        changes: strings(&changes),
        notes: strings(&notes),
        options: strings(&options),
        more: strings(&more),
    }
}

fn mine(text: &str) -> AiMessageData {
    AiMessageData {
        mine: true,
        text: text.into(),
        ..Default::default()
    }
}

impl AiPane {
    /// The conversation, oldest first, as chat messages.
    fn messages(&self, base: Option<&Base>, model_label: &str) -> Vec<AiMessageData> {
        let mut out = Vec::new();
        // The editor says hello and what it can do.
        let hello = match base {
            Some(b) => {
                let mut t = format!(
                    "Hi! I'm your editing helper, and I've got {} ({}) open. Just tell me what you'd like, in your own words - like \"cut the first 30 seconds\", \"speed up 1:00 to 1:30\" or \"add a caption 'Welcome!' at 0:05\". I'll make the change, show it to you in the preview, and tell you what I did. You can also just ask me things, like \"what can you do?\"",
                    b.name,
                    clock(secs(b.window))
                );
                if b.pieces > 1 {
                    t.push_str(&format!(
                        " The timeline has {} pieces of this video; my first change replaces them with one clean edit of the whole file (Ctrl+Z brings them back).",
                        b.pieces
                    ));
                }
                t
            }
            None => "Hi! Add a video to the timeline and tell me what to change.".to_owned(),
        };
        let mut hello_notes = Vec::new();
        if model_label.is_empty() {
            hello_notes.push("I understand common phrases only right now. To type requests freely, set up an AI model (ANTHROPIC_API_KEY, OPENAI_API_KEY, or a running Ollama) and restart EUP.".to_owned());
        }
        out.push(reply(5, "AI editor", hello, vec![], hello_notes, vec![]));

        let pending = self
            .session
            .as_ref()
            .and_then(|s| s.pending().map(|(_, o)| o));
        let last = self.turns.len().saturating_sub(1);
        for (i, t) in self.turns.iter().enumerate() {
            if !t.prompt.is_empty() {
                out.push(mine(&t.prompt));
            }
            let options = if i == last { pending.clone().unwrap_or_default() } else { vec![] };
            out.push(turn_message(t, options, i));
        }
        if let Some(text) = &self.busy {
            out.push(mine(text));
            let who = if model_label.is_empty() { String::new() } else { format!(" with {model_label}") };
            out.push(reply(4, "Working", format!("On it - reading your request{who}..."), vec![], vec![], vec![]));
        }
        out
    }

    /// The tab as Slint shows it.
    pub fn data(&self, studio: &Studio) -> AiPanelData {
        wake_local_model();
        if let Some(frozen) = &self.frozen {
            let mut d = frozen.clone();
            d.busy = true;
            d.asking = false;
            let model_label = d.model.to_string();
            d.messages = model(self.messages(self.base.as_ref(), &model_label));
            return d;
        }
        let found = find_base(studio);
        let base = self.base.clone().or_else(|| found.as_ref().ok().map(|(b, _)| b.clone()));
        let (transcript, detail, state) = match &self.words {
            Words::None => (
                "Edits by time work now. Analyse the speech to also edit by what is said (captions on words, filler words, topics).".to_owned(),
                String::new(),
                0,
            ),
            Words::Running => ("Analysing the speech...".to_owned(), String::new(), 1),
            Words::Ready { transcript, note } => {
                let n = transcript.words.len();
                let line = match n {
                    0 => "No speech was found in this video. Edits by time still work.".to_owned(),
                    1..=9 => format!("Only {n} spoken word(s) found, so edits by what is said are limited."),
                    _ => format!("Speech analysed: {n} words. You can edit by what is said."),
                };
                (line, note.clone(), 2)
            }
            Words::Failed(e) => (e.clone(), String::new(), 3),
        };
        let model_label = match &self.session {
            Some(s) => s.model_label().unwrap_or_default(),
            None => incubrix_nlu::llm::LlmConfig::detected()
                .map(|c| incubrix_nlu::llm::LlmParser::new(c).label())
                .unwrap_or_default(),
        };
        let length = base.as_ref().map(|b| clock(secs(b.window))).unwrap_or_default();
        let mut data = AiPanelData {
            ready: base.is_some(),
            not_ready: found.err().unwrap_or_default().into(),
            file: base.as_ref().map(|b| b.name.clone()).unwrap_or_default().into(),
            duration: length.clone().into(),
            original: length.into(),
            model: model_label.clone().into(),
            transcript: transcript.into(),
            transcript_detail: detail.into(),
            transcript_state: state,
            can_transcribe: base.as_ref().is_some_and(|b| b.has_audio),
            hash: "-".into(),
            policy: "Times mean the video as it plays now".into(),
            parser: "rules".into(),
            messages: model(self.messages(base.as_ref(), &model_label)),
            ..Default::default()
        };
        let Some(s) = &self.session else { return data };
        let tl = s.project.timeline().timeline;
        data.hash = short_hash(&s.project.hash()).into();
        data.duration = clock(tl.duration).into();
        data.original = clock(s.project.source.duration).into();
        data.parser = s.parser_name().into();
        data.edits = s.project.edits().len() as i32;
        data.can_undo = !s.project.edits().is_empty();
        data.can_redo = !s.project.redoable().is_empty();
        data.asking = s.pending().is_some();
        let off = s.project.restored();
        let mut ledger: Vec<AiEditData> = s
            .project
            .edits()
            .iter()
            .rev()
            .map(|tx| {
                let restored = off.contains(&tx.id);
                let is_restore = tx.ops.iter().any(|o| matches!(o, Op::Restore { .. }));
                AiEditData {
                    id: tx.id as i32,
                    instruction: tx.instruction.clone().into(),
                    operations: tx.ops.iter().map(|o| o.describe()).collect::<Vec<_>>().join("; ").into(),
                    state: if restored { 1 } else { 0 },
                    state_label: if restored { "Switched off" } else { "In effect" }.into(),
                    can_restore: !restored && !is_restore,
                }
            })
            .collect();
        ledger.extend(s.project.redoable().iter().map(|tx| AiEditData {
            id: tx.id as i32,
            instruction: tx.instruction.clone().into(),
            operations: tx.ops.iter().map(|o| o.describe()).collect::<Vec<_>>().join("; ").into(),
            state: 2,
            state_label: "Undone".into(),
            can_restore: false,
        }));
        data.ledger = model(ledger);
        let captions: Vec<String> = tl
            .captions
            .iter()
            .map(|c| match c.playback.first() {
                Some(p) => format!("'{}' shows at {}-{}", c.text, clock(p.start), clock(p.end)),
                None => format!("'{}' is hidden because its words were cut", c.text),
            })
            .collect();
        data.captions = strings(&captions);
        data
    }
}

/// Ways to hand the conversation back, picked by turn so replies vary.
const NEXT: &[&str] = &["Anything else?", "What's next?", "Want me to change anything else?"];

/// The editor's reply to one request, as a chat message.
fn turn_message(t: &Turn, options: Vec<String>, index: usize) -> AiMessageData {
    let o = &t.outcome;
    if t.listening {
        return reply(
            4,
            "Listening",
            "To do that I need to know what's said in the video, so I'm listening to it now - for a long video this takes a minute or two. I'll carry on with your request by myself as soon as I'm done.".into(),
            vec![],
            vec![],
            vec![],
        );
    }
    match o.code.as_deref() {
        Some("NOTE") => return reply(3, "", o.summary.clone(), vec![], vec![], vec![]),
        // Conversation: the words are the reply, no badge needed.
        Some("TALK") => return reply(5, "", o.summary.clone(), vec![], vec![], vec![]),
        _ => {}
    }
    let history = o.tx.is_none()
        && o.status == Status::Applied
        && o.operations.first().is_some_and(|op| op.starts_with("undid") || op.starts_with("redid"));
    let mut notes: Vec<String> = o.warnings.iter().map(|w| friendly(w)).collect();
    if t.reader.starts_with("built-in phrases (") {
        notes.push("I couldn't reach the AI model just now, so I went by the built-in phrases.".into());
    }
    let next = NEXT[index % NEXT.len()];
    match o.status {
        _ if history => {
            let undo = o.operations.first().is_some_and(|op| op.starts_with("undid"));
            reply(
                3,
                if undo { "Undone" } else { "Redone" },
                format!("{} {next}", friendly(&o.summary)),
                o.operations.iter().map(|op| plain_op(op)).collect(),
                notes,
                vec![],
            )
        }
        Status::Applied if o.tx.is_none() => reply(
            3,
            "Nothing to change",
            format!("{} {next}", friendly(&o.summary)),
            vec![],
            notes,
            vec![],
        ),
        Status::Applied => {
            let mut text = format!("Done! {}", friendly(&o.summary));
            if let Some(at) = t.shown_at {
                text.push_str(&format!(" I've moved the preview to {} so you can see it.", clock(at)));
            }
            text.push(' ');
            text.push_str(next);
            reply(0, "Done", text, o.operations.iter().map(|op| plain_op(op)).collect(), notes, vec![])
        }
        Status::NeedsClarification => reply(
            1,
            "Quick question",
            format!("Happy to! Just one thing first: {}", friendly(&o.question.clone().unwrap_or_default())),
            vec![],
            notes,
            options,
        ),
        Status::Rejected => reply(
            2,
            "Couldn't do that",
            format!("Sorry, I couldn't do that. {}", friendly(&o.summary)),
            vec![],
            notes,
            vec![],
        ),
    }
}

/// An engine operation line as a person reads it.
fn plain_op(op: &str) -> String {
    let (head, rest) = op.split_once(' ').unwrap_or((op, ""));
    let rest = rest.replace("source ", "");
    let line = match head {
        "cut" if rest.starts_with(':') => format!("Removed{rest}"),
        "cut" => format!("Removed {rest} (original time)"),
        "kept" => format!("Kept {} (original time); the rest removed", rest.trim_start_matches("only ")),
        "moved" => format!("Moved {rest} (original time)"),
        "speed" => match rest.split_once(" on ") {
            Some((x, span)) => format!("Played {span} (original time) at {x}"),
            None => op.to_owned(),
        },
        "added" if rest.starts_with("caption") => {
            format!("Added the caption {}", rest.split_once('\'').map(|(_, t)| format!("'{t}")).unwrap_or_default())
        }
        "added" if rest.starts_with("music") => "Added background music".into(),
        "restyled" => "Changed how the caption looks".into(),
        "changed" => format!("Changed the caption text to {}", rest.split_once(" to ").map(|(_, t)| t).unwrap_or("")),
        "removed" if rest.starts_with("caption") => "Removed a caption".into(),
        "removed" if rest.starts_with("music") => "Removed the music".into(),
        "removed" => format!("Removed {rest}"),
        "muted" => "Muted those words".into(),
        "bleeped" => "Bleeped those words".into(),
        "protected" => format!("Kept the pause at {}", rest.trim_start_matches("pause ")),
        "restored" => format!("Switched off change {}", rest.trim_start_matches("edit ")),
        "undid" | "redid" => {
            let what = rest.split_once('\'').map(|(_, t)| t.trim_end_matches('\'')).unwrap_or(&rest);
            format!("{} \"{what}\"", if head == "undid" { "Undid" } else { "Redid" })
        }
        _ => op.to_owned(),
    };
    line.replace(" -> ", " \u{2192} ")
}

/// The engine's text as a viewer reads it: no word ids, no caption ids, no
/// restated time policy (the tab says it once, in the details).
fn friendly(summary: &str) -> String {
    let mut s = summary.replace(&format!(" {}", incubrix_core::resolve::TIME_POLICY_NOTE), "");
    for marker in [" (w0", " (cap_"] {
        while let Some(at) = s.find(marker) {
            match s[at..].find(')') {
                Some(close) => s.replace_range(at..at + close + 1, ""),
                None => break,
            }
        }
    }
    let s = s
        .replace(" -> ", " \u{2192} ")
        .replace("current edited playback time", "the video as it plays now");
    tidy(&plain_length(&s))
}

/// "Video 4:08 -> 4:05.3 (-2.7 s)." -> "The video is now 4:05.3 (2.7 s shorter)."
fn plain_length(s: &str) -> String {
    let Some(at) = s.find("Video ") else { return s.to_owned() };
    let rest = &s[at + "Video ".len()..];
    let Some((_, after)) = rest.split_once(" \u{2192} ") else { return s.to_owned() };
    let (now, delta, tail) = match after.split_once(" (") {
        Some((now, more)) => match more.split_once(" s).") {
            Some((d, tail)) => (now, Some(d), tail),
            None => return s.to_owned(),
        },
        None => match after.find(". ") {
            Some(i) => (&after[..i], None, &after[i + 1..]),
            None => (after.trim_end_matches('.'), None, ""),
        },
    };
    let change = match delta {
        Some(d) if d.starts_with('-') => format!(" ({} s shorter)", d.trim_start_matches('-')),
        Some(d) => format!(" ({} s longer)", d.trim_start_matches('+')),
        None => String::new(),
    };
    format!("{}The video is now {now}{change}.{tail}", &s[..at])
}

/// Quoted words that end a sentence don't need a second full stop.
fn tidy(s: &str) -> String {
    let mut s = s.to_owned();
    for p in ['.', '?', '!'] {
        for q in ['\'', '"'] {
            s = s.replace(&format!("{p}{q}."), &format!("{p}{q}"));
            s = s.replace(&format!("{p}{q};"), &format!("{p}{q},"));
        }
    }
    s.replace("..", ".")
}

#[cfg(test)]
mod tests {
    use super::*;
    use slint::Model;

    /// Phase 9 "Done when": the worked example's 8 prompts, typed into the
    /// tab's session, give the session runner's timeline, and the clips laid
    /// for it cover exactly that timeline.
    #[test]
    fn worked_example_matches_the_session_runner() {
        let fixture = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../incubrix/fixtures/sessions/01_worked_example.yaml");
        let file = incubrix_cli::load(&fixture).unwrap();
        let (runner, _) = incubrix_cli::run(
            &fixture,
            Box::new(incubrix_nlu::RulesParser),
            &incubrix_cli::RunOptions::default(),
        )
        .unwrap();

        let src = file.source.clone().unwrap();
        let project = Project::new(
            SourceInfo::with_duration(secs(src.duration_s)),
            incubrix_cli::synthetic_transcript(&src.lines),
        );
        let mut session = Session::new(project, Box::new(incubrix_nlu::RulesParser));
        for (i, step) in file.steps.iter().enumerate() {
            let mut reply = session.say(&step.say);
            if let Some(a) = &step.answer {
                reply = session.answer(a);
            }
            assert_eq!(
                session.project.hash(),
                runner.steps[i].timeline_hash,
                "step {}: {} -> {:?}",
                i + 1,
                step.say,
                reply.outcome.status
            );
        }
        assert_eq!(session.project.hash(), runner.final_timeline_hash);

        // The clips: back to back from 0, ending at the timeline's length.
        let tl = session.project.timeline().timeline;
        let laid = pieces(&tl);
        let mut at = 0.0;
        for p in &laid {
            assert!((p.playback - at).abs() < 1e-6, "gap at {at}");
            at += p.length / p.speed;
        }
        assert!((at - to_secs(tl.duration)).abs() < 1e-3, "{at}");
        assert!((at - 193.0).abs() < 1e-3);
        assert!(laid.iter().any(|p| (p.speed - 2.0).abs() < 1e-9));
        assert_eq!(tl.captions.len(), 1);
        assert_eq!(tl.captions[0].style.color, "#FF0000");
    }

    fn video(start: f64, duration: f64, source_start: f64, speed: f64) -> Clip {
        Clip {
            id: "v".into(),
            kind: ClipKind::Video,
            start,
            duration,
            source_start,
            speed,
            ..Clip::default()
        }
    }

    /// A caption over a trimmed, sped-up clip lands on the file's seconds
    /// it was shown over; outside the clip it is held to the clip's edge.
    #[test]
    fn timeline_time_reads_through_the_clip() {
        let pieces = [video(10.0, 20.0, 5.0, 2.0)];
        assert_eq!(to_source(&pieces, 100.0, 10.0), 5.0);
        assert_eq!(to_source(&pieces, 100.0, 15.0), 15.0);
        assert_eq!(to_source(&pieces, 100.0, 0.0), 5.0);
        assert_eq!(to_source(&pieces, 100.0, 40.0), 45.0);
        assert_eq!(to_source(&pieces, 30.0, 25.0), 30.0, "never past the file");
    }

    /// The user's case: the video already has captions. "Cut the first 30
    /// seconds" takes the captions in them away and moves the rest with
    /// their picture, "make the captions red" reaches every one, a
    /// speed-up shortens a caption with its picture, and each keeps its
    /// own font and place on the way back.
    #[test]
    fn existing_captions_are_cut_coloured_and_sped_with_the_video() {
        let mut project = Project::new(SourceInfo::with_duration(secs(120.0)), Transcript::default());
        let look = TextStyle {
            content: "x".into(),
            font_family: "Serif Display".into(),
            font_size: 54.0 / 1080.0,
            font_weight: 400.0,
            color: "#ffffff".into(),
            ..TextStyle::default()
        };
        let mut adopted = std::collections::HashMap::new();
        let mut ops = Vec::new();
        for (n, (a, b, text)) in [(10.0, 12.0, "early"), (40.0, 43.0, "later"), (70.0, 74.0, "fast")].into_iter().enumerate() {
            let id = format!("cap_{}", n + 1);
            let a2 = adopt(TextStyle { content: text.into(), ..look.clone() }, 0.4);
            ops.push(Op::AddCaption {
                id: id.clone(),
                anchor: Anchor::Source { range: SrcRange::new(secs(a), secs(b)).unwrap() },
                text: text.into(),
                style: a2.engine.clone(),
            });
            adopted.insert(id, a2);
        }
        project.start_with("captions already on the timeline", ops).unwrap();
        let mut session = Session::new(project, Box::new(incubrix_nlu::RulesParser));

        let cut = session.say("cut the first 30 seconds");
        assert_eq!(cut.outcome.status, Status::Applied, "{}", cut.outcome.summary);
        let red = session.say("make the captions red");
        assert_eq!(red.outcome.status, Status::Applied, "{}", red.outcome.summary);
        let fast = session.say("speed up 0:40 to 0:44 by 2x");
        assert_eq!(fast.outcome.status, Status::Applied, "{}", fast.outcome.summary);

        let tl = session.project.timeline().timeline;
        let by = |id: &str| tl.captions.iter().find(|c| c.id == id).unwrap();
        assert!(by("cap_1").playback.is_empty(), "its picture was cut");
        let later = by("cap_2").playback[0];
        assert_eq!((later.start, later.end), (secs(10.0), secs(13.0)), "30 s earlier, with its picture");
        let sped = by("cap_3").playback[0];
        assert_eq!((sped.start, sped.end), (secs(40.0), secs(42.0)), "half as long at 2x");
        for c in &tl.captions {
            assert_eq!(c.style.color, "#FF0000", "{} is red", c.id);
            let (style, offset) = caption_look(c, adopted.get(&c.id));
            assert_eq!(style.color, "#FF0000");
            assert_eq!(style.font_family, "Serif Display", "its own font");
            assert_eq!(style.font_weight, 400.0, "its own weight");
            assert_eq!(offset, 0.4, "its own place");
        }

        // Undo takes back the three requests and stops there.
        for _ in 0..3 {
            assert_eq!(session.say("undo").outcome.status, Status::Applied);
        }
        assert_eq!(session.say("undo").outcome.status, Status::Rejected);
        assert_eq!(session.project.timeline().timeline.captions.len(), 3);
        assert!(session.project.edits().is_empty());
    }

    #[test]
    fn summaries_lose_the_engine_detail() {
        assert_eq!(
            friendly("Added caption 'Hi' on 'hello there' (w00002-w00003, original 0:42). Video 1:00 -> 1:00. Times are read as the current edited playback time."),
            "Added caption 'Hi' on 'hello there'. The video is now 1:00."
        );
    }

    #[test]
    fn lengths_and_quotes_read_naturally() {
        assert_eq!(
            friendly("Cut 0:02 'Job interview.'. Video 4:08 -> 4:05.3 (-2.7 s)."),
            "Cut 0:02 'Job interview.' The video is now 4:05.3 (2.7 s shorter)."
        );
        assert_eq!(friendly("Undid edit #2. Video 3:30 -> 4:00."), "Undid edit #2. The video is now 4:00.");
    }

    #[test]
    fn replies_fold_and_cap_their_lines() {
        let changes: Vec<String> = (0..73).map(|_| "Changed how the caption looks".to_owned()).collect();
        let m = reply(0, "Done", "Done!".into(), changes, vec![], vec![]);
        assert_eq!(m.changes.row_count(), 1);
        assert_eq!(m.changes.row_data(0).unwrap().as_str(), "Changed how the caption looks (x73)");
        let many: Vec<String> = (0..10).map(|i| format!("Removed part {i}")).collect();
        let m = reply(0, "Done", "x".repeat(500), many, vec![], vec![]);
        assert_eq!(m.changes.row_count(), 3);
        assert!(m.more.row_count() >= 7);
        assert!(m.text.len() <= 330);
    }

    #[test]
    fn operations_read_as_plain_words() {
        assert_eq!(plain_op("cut source 0:00-0:30"), "Removed 0:00-0:30 (original time)");
        assert_eq!(plain_op("speed 2x on source 1:30-2:00"), "Played 1:30-2:00 (original time) at 2x");
        assert_eq!(plain_op("added caption cap_1 'Welcome!'"), "Added the caption 'Welcome!'");
        assert_eq!(plain_op("undid edit #5 'Actually, put the intro back'"), "Undid \"Actually, put the intro back\"");
    }

    #[test]
    fn phrases_become_words_in_order() {
        let t = words_from_segments(&[Segment { start: 1.0, end: 2.0, text: "hi there".into() }]);
        assert_eq!(t.words.len(), 2);
        assert_eq!(t.words[0].start, 1_000_000);
        assert_eq!(t.words[1].end, 2_000_000);
    }
}
