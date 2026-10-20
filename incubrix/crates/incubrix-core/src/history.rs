//! The edit history and the replay that turns it into a timeline.
//!
//! A [`Project`] holds the untouched source, its transcript and an ordered
//! list of transactions. One user instruction is one transaction, so one
//! undo. The timeline is never stored: [`Project::timeline`] replays the
//! active transactions every time, which is why undo, redo and selective
//! restore can never leave anything half-applied.

use std::collections::BTreeSet;

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::hash::timeline_hash;
use crate::model::{Anchor, SourceInfo, Transcript};
use crate::ops::{Op, MAX_SPEED, MIN_SPEED};
use crate::time::{clock, SrcRange, Us};
use crate::timeline::{AudioMark, Caption, Cuts, MarkKind, Music, Timeline, MIN_CAPTION_US};
use crate::EditError;

/// One user instruction's worth of operations.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Tx {
    /// Sequential id, never reused.
    pub id: u32,
    /// The instruction as typed.
    pub instruction: String,
    /// What it did, in source coordinates.
    pub ops: Vec<Op>,
}

/// A timeline plus what the replay wants the user told.
#[derive(Clone, Debug)]
pub struct Replay {
    /// The edited video.
    pub timeline: Timeline,
    /// Things that happened as a consequence (caption hidden, and so on).
    pub warnings: Vec<String>,
}

/// What one successful edit did.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct ApplyReport {
    /// The transaction recorded; `None` when nothing changed (so nothing to undo).
    pub tx: Option<u32>,
    /// Edited length before, microseconds.
    pub before_duration: Us,
    /// Edited length after, microseconds.
    pub after_duration: Us,
    /// One line per operation.
    pub operations: Vec<String>,
    /// Consequences worth telling the user.
    pub warnings: Vec<String>,
    /// Hash of the new timeline.
    pub timeline_hash: String,
}

/// An editing project: the original, its words, and the history on top.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Project {
    /// The original file. Never modified.
    pub source: SourceInfo,
    /// Its words.
    pub transcript: Transcript,
    /// Every transaction, active ones first: `txs[..cursor]` are applied,
    /// the rest can be redone.
    txs: Vec<Tx>,
    cursor: usize,
    next_tx: u32,
    /// How many of the first transactions are the starting point (see
    /// [`Project::start_with`]): replayed like any edit, never undone.
    #[serde(default)]
    start: usize,
}

impl Project {
    /// A project with no edits.
    pub fn new(source: SourceInfo, transcript: Transcript) -> Self {
        Self {
            source,
            transcript,
            txs: Vec::new(),
            cursor: 0,
            next_tx: 1,
            start: 0,
        }
    }

    /// Makes `ops` the project's starting point: what the timeline already
    /// had before anyone asked for anything (captions an editor laid down
    /// by hand, say). Replayed like any edit, so cuts and speed changes
    /// carry it along, but undo stops at it and [`Project::edits`] leaves it
    /// out. Only on a project with no history yet.
    pub fn start_with(&mut self, instruction: &str, ops: Vec<Op>) -> Result<ApplyReport, EditError> {
        if !self.txs.is_empty() {
            return Err(EditError::Invalid("the starting point comes before any edit".into()));
        }
        let report = self.apply(instruction, ops)?;
        self.start = self.cursor;
        Ok(report)
    }

    /// The starting point's transactions (see [`Project::start_with`]).
    pub fn starting(&self) -> &[Tx] {
        &self.txs[..self.start.min(self.cursor)]
    }

    /// The edits made on top of the starting point, oldest first: what undo
    /// can take back and what a list of changes shows.
    pub fn edits(&self) -> &[Tx] {
        &self.txs[self.start.min(self.cursor)..self.cursor]
    }

    /// The transactions currently applied, oldest first.
    pub fn active(&self) -> &[Tx] {
        &self.txs[..self.cursor]
    }

    /// The transactions that redo would bring back, next first.
    pub fn redoable(&self) -> &[Tx] {
        &self.txs[self.cursor..]
    }

    /// Ids of active transactions some active Restore has switched off.
    pub fn restored(&self) -> BTreeSet<u32> {
        restored_ids(self.active())
    }

    /// The edited timeline now.
    pub fn timeline(&self) -> Replay {
        replay(&self.source, &self.transcript, self.active())
            .expect("the active history always replays")
    }

    /// Hash of the edited timeline now.
    pub fn hash(&self) -> String {
        timeline_hash(&self.timeline().timeline)
    }

    /// A fresh overlay id with this prefix (`cap`, `mute`, ...), unique
    /// across the whole history including redoable steps.
    pub fn next_id(&self, prefix: &str) -> String {
        let mut max = 0u32;
        for tx in &self.txs {
            for op in &tx.ops {
                let id = match op {
                    Op::AddCaption { id, .. }
                    | Op::Mute { id, .. }
                    | Op::Bleep { id, .. }
                    | Op::AddMusic { id, .. } => id,
                    _ => continue,
                };
                if let Some(n) = id
                    .strip_prefix(prefix)
                    .and_then(|s| s.strip_prefix('_'))
                    .and_then(|s| s.parse::<u32>().ok())
                {
                    max = max.max(n);
                }
            }
        }
        format!("{prefix}_{}", max + 1)
    }

    /// Applies one instruction's operations as one transaction: all of them
    /// or none. A new edit clears redo. An edit that changes nothing is
    /// accepted but not recorded.
    pub fn apply(&mut self, instruction: &str, ops: Vec<Op>) -> Result<ApplyReport, EditError> {
        if ops.is_empty() {
            return Err(EditError::Invalid("no operations".into()));
        }
        let before = self.timeline();
        // Each op is checked against the edit as the ops before it in the
        // same transaction left it ("cut 10 s, then caption what is at 0:05").
        let mut now = before.timeline.clone();
        let mut tx = Tx {
            id: self.next_tx,
            instruction: instruction.to_owned(),
            ops: Vec::with_capacity(ops.len()),
        };
        let mut staged: Vec<Tx> = self.active().to_vec();
        let mut after = before.clone();
        // Ops not yet replayed into `now`, and whether any of them changes
        // more than overlays. An overlay (caption, mute, bleep) is checked
        // only against the cuts, which overlays never change, so a run of
        // them needs no replay in between: auto-captioning a 60-minute video
        // replays once, not once per caption.
        let (mut pending, mut pending_structural) = (0usize, false);
        let overlay = |op: &Op| {
            matches!(
                op,
                Op::AddCaption { .. } | Op::Mute { .. } | Op::Bleep { .. }
            )
        };
        for op in ops {
            if pending > 0 && (pending_structural || !overlay(&op)) {
                after = self.stage(&mut staged, &tx)?;
                now = after.timeline.clone();
                (pending, pending_structural) = (0, false);
            }
            self.validate(&op, &now)?;
            pending_structural |= !overlay(&op);
            pending += 1;
            tx.ops.push(op);
        }
        if pending > 0 {
            after = self.stage(&mut staged, &tx)?;
        }
        let before_hash = timeline_hash(&before.timeline);
        let after_hash = timeline_hash(&after.timeline);
        let operations = tx.ops.iter().map(Op::describe).collect();
        // Only warnings this edit caused, not ones already standing.
        let warnings: Vec<String> = after
            .warnings
            .iter()
            .filter(|w| !before.warnings.contains(w))
            .cloned()
            .collect();
        if before_hash == after_hash {
            return Ok(ApplyReport {
                tx: None,
                before_duration: before.timeline.duration,
                after_duration: before.timeline.duration,
                operations,
                warnings: vec!["Nothing changed: this edit is already in effect.".into()],
                timeline_hash: before_hash,
            });
        }
        self.txs.truncate(self.cursor);
        self.txs.push(tx);
        self.cursor += 1;
        self.next_tx += 1;
        Ok(ApplyReport {
            tx: Some(self.next_tx - 1),
            before_duration: before.timeline.duration,
            after_duration: after.timeline.duration,
            operations,
            warnings,
            timeline_hash: after_hash,
        })
    }

    /// Replays the active history plus `tx` as it stands.
    fn stage(&self, staged: &mut Vec<Tx>, tx: &Tx) -> Result<Replay, EditError> {
        staged.truncate(self.cursor);
        staged.push(tx.clone());
        replay(&self.source, &self.transcript, staged)
    }

    /// Steps back one instruction. Returns the transaction undone.
    pub fn undo(&mut self) -> Option<&Tx> {
        if self.cursor <= self.start {
            return None;
        }
        self.cursor -= 1;
        self.txs.get(self.cursor)
    }

    /// Steps forward one instruction. Returns the transaction redone.
    pub fn redo(&mut self) -> Option<&Tx> {
        if self.cursor >= self.txs.len() {
            return None;
        }
        self.cursor += 1;
        self.txs.get(self.cursor - 1)
    }

    /// The latest active, not-restored transaction that removed any of `r`
    /// from the edit - the answer to "which edit cut this?".
    pub fn who_removed(&self, r: &SrcRange) -> Option<u32> {
        let off = self.restored();
        self.active()
            .iter()
            .rev()
            .filter(|tx| !off.contains(&tx.id))
            .find_map(|tx| {
                tx.ops
                    .iter()
                    .any(|op| match op {
                        Op::Cut { ranges, .. } => ranges.iter().any(|c| c.intersect(r).is_some()),
                        Op::KeepOnly { range } => SrcRange::new(r.start, r.end)
                            .map(|r| r.subtract(range).iter().any(|p| !p.is_empty()))
                            .unwrap_or(false),
                        _ => false,
                    })
                    .then_some(tx.id)
            })
    }

    fn validate(&self, op: &Op, now: &Timeline) -> Result<(), EditError> {
        let whole = self.source.range();
        let check = |r: &SrcRange| -> Result<(), EditError> {
            if r.is_empty() || r.start < whole.start || r.end > whole.end {
                return Err(EditError::OutOfRange(format!(
                    "{}-{} is outside the video (0:00-{})",
                    clock(r.start),
                    clock(r.end),
                    clock(whole.end)
                )));
            }
            Ok(())
        };
        match op {
            Op::Cut { ranges, .. } => ranges.iter().try_for_each(check)?,
            Op::KeepOnly { range } | Op::ProtectPause { range } => check(range)?,
            Op::Reorder { range, before } => {
                check(range)?;
                if let Some(b) = before {
                    if range.contains(*b) {
                        return Err(EditError::Invalid(
                            "cannot move a section in front of itself".into(),
                        ));
                    }
                }
            }
            Op::Speed { range, speed } => {
                check(range)?;
                if !(MIN_SPEED..=MAX_SPEED).contains(speed) {
                    return Err(EditError::BadSpeed(*speed));
                }
            }
            Op::AddCaption { id, anchor, .. }
            | Op::Mute { id, anchor }
            | Op::Bleep { id, anchor } => {
                if self.active().iter().flat_map(|t| &t.ops).any(|o| matches!(o, Op::AddCaption { id: x, .. } | Op::Mute { id: x, .. } | Op::Bleep { id: x, .. } if x == id)) {
                    return Err(EditError::Invalid(format!("{id} already exists")));
                }
                let r = anchor.range(&self.transcript).ok_or_else(|| match anchor {
                    Anchor::Words { first, .. } => EditError::UnknownWord(first.clone()),
                    Anchor::Source { .. } => EditError::Invalid("bad anchor".into()),
                })?;
                check(&r)?;
                if now.covered(&r) == 0 {
                    let by = self
                        .who_removed(&r)
                        .map(|t| format!(" (removed by edit #{t})"))
                        .unwrap_or_default();
                    return Err(EditError::Contradicts(format!(
                        "those words are not in the edit any more{by}"
                    )));
                }
            }
            Op::StyleCaption { id, .. }
            | Op::RetextCaption { id, .. }
            | Op::RemoveCaption { id } => {
                if now.caption(id).is_none() {
                    return Err(EditError::UnknownCaption(id.clone()));
                }
            }
            Op::AddMusic { .. } => {}
            Op::RemoveMusic { id } => {
                if !now.music.iter().any(|m| &m.id == id) {
                    return Err(EditError::Invalid(format!("no music {id}")));
                }
            }
            Op::Restore { tx } => {
                let target = self
                    .active()
                    .iter()
                    .find(|t| t.id == *tx)
                    .ok_or(EditError::UnknownTx(*tx))?;
                if target.ops.iter().any(|o| matches!(o, Op::Restore { .. })) {
                    return Err(EditError::Invalid(
                        "a restore cannot be restored; use undo".into(),
                    ));
                }
                if self.restored().contains(tx) {
                    return Err(EditError::Invalid(format!(
                        "edit #{tx} is already restored"
                    )));
                }
            }
        }
        Ok(())
    }
}

fn restored_ids(txs: &[Tx]) -> BTreeSet<u32> {
    txs.iter()
        .flat_map(|t| &t.ops)
        .filter_map(|o| match o {
            Op::Restore { tx } => Some(*tx),
            _ => None,
        })
        .collect()
}

/// Replays transactions on the untouched source. Pure: same inputs, same
/// timeline, on any machine.
pub fn replay(
    source: &SourceInfo,
    transcript: &Transcript,
    txs: &[Tx],
) -> Result<Replay, EditError> {
    let off = restored_ids(txs);
    let mut cuts = Cuts::whole(source.range());
    let mut captions: Vec<Caption> = Vec::new();
    let mut marks: Vec<AudioMark> = Vec::new();
    let mut music: Vec<Music> = Vec::new();
    let mut pauses: Vec<SrcRange> = Vec::new();
    let mut warnings = Vec::new();

    for tx in txs.iter().filter(|t| !off.contains(&t.id)) {
        for op in &tx.ops {
            match op {
                Op::Cut { ranges, .. } => {
                    for r in ranges {
                        cuts.cut(r);
                    }
                }
                Op::KeepOnly { range } => cuts.keep_only(range),
                Op::Reorder { range, before } => {
                    if !cuts.reorder(range, *before) {
                        warnings.push(format!("Edit #{}: the place a section was moved to is gone; it now plays last.", tx.id));
                    }
                }
                Op::Speed { range, speed } => cuts.speed(range, *speed),
                Op::AddCaption {
                    id,
                    anchor,
                    text,
                    style,
                } => {
                    captions.retain(|c| &c.id != id);
                    captions.push(Caption {
                        id: id.clone(),
                        text: text.clone(),
                        anchor: anchor.clone(),
                        style: style.clone(),
                        playback: vec![],
                        tx: tx.id,
                    });
                }
                Op::StyleCaption { id, patch } => match captions.iter_mut().find(|c| &c.id == id) {
                    Some(c) => c.style.patch(patch),
                    None => warnings.push(format!(
                        "Edit #{}: caption {id} no longer exists, style change skipped.",
                        tx.id
                    )),
                },
                Op::RetextCaption { id, text } => {
                    if let Some(c) = captions.iter_mut().find(|c| &c.id == id) {
                        c.text = text.clone();
                    }
                }
                Op::RemoveCaption { id } => captions.retain(|c| &c.id != id),
                Op::Mute { id, anchor } | Op::Bleep { id, anchor } => {
                    let kind = if matches!(op, Op::Mute { .. }) {
                        MarkKind::Mute
                    } else {
                        MarkKind::Bleep
                    };
                    marks.retain(|m| &m.id != id);
                    marks.push(AudioMark {
                        id: id.clone(),
                        kind,
                        anchor: anchor.clone(),
                        playback: vec![],
                        tx: tx.id,
                    });
                }
                Op::ProtectPause { range } => pauses.push(*range),
                Op::AddMusic {
                    id,
                    path,
                    volume_db,
                    duck_db,
                } => {
                    music.retain(|m| &m.id != id);
                    music.push(Music {
                        id: id.clone(),
                        path: path.clone(),
                        volume_db: *volume_db,
                        duck_db: *duck_db,
                        tx: tx.id,
                    });
                }
                Op::RemoveMusic { id } => music.retain(|m| &m.id != id),
                Op::Restore { .. } => {}
            }
        }
    }

    let segments = cuts.into_segments();
    if segments.is_empty() {
        return Err(EditError::EmptyTimeline);
    }
    let duration = segments.last().map(|s| s.playback_end()).unwrap_or(0);
    let mut tl = Timeline {
        duration,
        segments,
        captions: vec![],
        marks: vec![],
        music,
        protected_pauses: pauses,
    };

    // Overlays: content anchors projected onto the playback axis.
    for mut c in captions {
        let Some(r) = c.anchor.range(transcript) else {
            warnings.push(format!(
                "Caption {} points at words that do not exist; hidden.",
                c.id
            ));
            tl.captions.push(c);
            continue;
        };
        let mut pb = tl.source_to_playback(&r);
        let covered = tl.covered(&r);
        if pb.is_empty() {
            warnings.push(format!("Caption '{}' ({}) is hidden: all of its words were cut. Restoring that cut brings it back.", c.text, c.id));
        } else if covered < r.len() {
            warnings.push(format!(
                "Caption '{}' ({}) was partly cut; it now shows over the words that remain.",
                c.text, c.id
            ));
        }
        if tl.sped_up(&r) {
            for p in &mut pb {
                if p.len() < MIN_CAPTION_US {
                    p.end = (p.start + MIN_CAPTION_US).min(duration);
                }
            }
        }
        c.playback = pb;
        tl.captions.push(c);
    }
    for mut m in marks {
        if let Some(r) = m.anchor.range(transcript) {
            m.playback = tl.source_to_playback(&r);
        }
        tl.marks.push(m);
    }
    Ok(Replay {
        timeline: tl,
        warnings,
    })
}
