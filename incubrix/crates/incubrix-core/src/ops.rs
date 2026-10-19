//! Every edit as data. Operations are always stored in **source** coordinates
//! or as **content anchors**: whatever time the user typed has already been
//! projected through the timeline by the time an `Op` exists. That is what
//! keeps edits on their content when earlier edits are undone or restored.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::model::{Anchor, CaptionStyle, StylePatch};
use crate::time::{clock, SpeedMilli, SrcRange, NORMAL_SPEED};

/// Slowest speed allowed (0.25x).
pub const MIN_SPEED: SpeedMilli = 250;
/// Fastest speed allowed (4x). "Speed up 10x" is rejected, not clamped.
pub const MAX_SPEED: SpeedMilli = 4000;

/// Why a cut was made: shown in summaries, and used by later rules
/// (silence removal never re-cuts a protected pause, and so on).
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CutReason {
    /// The user asked for this span to go.
    User,
    /// A filler word (um, uh, filler "like").
    Filler,
    /// A silence longer than the asked threshold.
    Silence,
}

/// One edit.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Op {
    /// Removes spans of the source from the edit.
    Cut {
        /// The spans, in source time.
        ranges: Vec<SrcRange>,
        /// Why.
        reason: CutReason,
    },
    /// Removes everything outside one span.
    KeepOnly {
        /// The span to keep.
        range: SrcRange,
    },
    /// Moves a span so it plays just before another point of the source.
    Reorder {
        /// The span to move.
        range: SrcRange,
        /// Source time it is placed in front of; `None` puts it last.
        before: Option<i64>,
    },
    /// Plays a span faster or slower. Where speed changes overlap, the later
    /// one wins on the overlap.
    Speed {
        /// The span, in source time.
        range: SrcRange,
        /// Thousandths: 2000 = 2x.
        speed: SpeedMilli,
    },
    /// Adds a caption attached to content.
    AddCaption {
        /// Caption id, e.g. `cap_1`.
        id: String,
        /// What it sits on.
        anchor: Anchor,
        /// The words shown.
        text: String,
        /// How it looks.
        style: CaptionStyle,
    },
    /// Changes how a caption looks.
    StyleCaption {
        /// Caption id.
        id: String,
        /// What changes.
        patch: StylePatch,
    },
    /// Changes a caption's text.
    RetextCaption {
        /// Caption id.
        id: String,
        /// New text.
        text: String,
    },
    /// Takes a caption away.
    RemoveCaption {
        /// Caption id.
        id: String,
    },
    /// Silences content.
    Mute {
        /// Mark id, e.g. `mute_1`.
        id: String,
        /// What is silenced.
        anchor: Anchor,
    },
    /// Replaces content with a tone.
    Bleep {
        /// Mark id, e.g. `bleep_1`.
        id: String,
        /// What is bleeped.
        anchor: Anchor,
    },
    /// Marks a pause the user wants kept; silence removal skips it.
    ProtectPause {
        /// The pause.
        range: SrcRange,
    },
    /// Background music that ducks under speech.
    AddMusic {
        /// Music id.
        id: String,
        /// File path or URL.
        path: String,
        /// Level when nobody speaks, dB.
        volume_db: i32,
        /// How far it drops under speech, dB (positive number).
        duck_db: i32,
    },
    /// Takes music away.
    RemoveMusic {
        /// Music id.
        id: String,
    },
    /// Switches an earlier transaction off, keeping everything after it.
    Restore {
        /// The transaction to switch off.
        tx: u32,
    },
}

impl Op {
    /// A short sentence for the response's operation list.
    pub fn describe(&self) -> String {
        match self {
            Op::Cut { ranges, reason } => {
                let what = match reason {
                    CutReason::User => "cut",
                    CutReason::Filler => "removed filler",
                    CutReason::Silence => "removed silence",
                };
                if ranges.len() == 1 {
                    let r = ranges[0];
                    format!("{what} source {}-{}", clock(r.start), clock(r.end))
                } else {
                    format!("{what}: {} spans", ranges.len())
                }
            }
            Op::KeepOnly { range } => format!(
                "kept only source {}-{}",
                clock(range.start),
                clock(range.end)
            ),
            Op::Reorder { range, before } => match before {
                Some(b) => format!(
                    "moved source {}-{} before source {}",
                    clock(range.start),
                    clock(range.end),
                    clock(*b)
                ),
                None => format!(
                    "moved source {}-{} to the end",
                    clock(range.start),
                    clock(range.end)
                ),
            },
            Op::Speed { range, speed } => format!(
                "speed {}x on source {}-{}",
                *speed as f64 / NORMAL_SPEED as f64,
                clock(range.start),
                clock(range.end)
            ),
            Op::AddCaption { id, text, .. } => format!("added caption {id} '{text}'"),
            Op::StyleCaption { id, .. } => format!("restyled caption {id}"),
            Op::RetextCaption { id, text } => format!("changed caption {id} to '{text}'"),
            Op::RemoveCaption { id } => format!("removed caption {id}"),
            Op::Mute { id, .. } => format!("muted ({id})"),
            Op::Bleep { id, .. } => format!("bleeped ({id})"),
            Op::ProtectPause { range } => format!(
                "protected pause {}-{}",
                clock(range.start),
                clock(range.end)
            ),
            Op::AddMusic { id, .. } => format!("added music {id}"),
            Op::RemoveMusic { id } => format!("removed music {id}"),
            Op::Restore { tx } => format!("restored edit #{tx}"),
        }
    }

    /// Whether the op changes which parts of the source play, or how fast.
    pub fn is_structural(&self) -> bool {
        matches!(
            self,
            Op::Cut { .. } | Op::KeepOnly { .. } | Op::Reorder { .. } | Op::Speed { .. }
        )
    }
}
