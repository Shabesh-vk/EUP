//! IncuBrix editing engine core.
//!
//! The deterministic heart of prompt-based editing: no AI, no IO, no clock.
//! An AI model may only turn words into [`ops::Op`]s; everything after that
//! is the plain code in this crate.
//!
//! - [`time`]: integer microsecond time, source and playback ranges.
//! - [`model`]: the untouched source, its transcript, content anchors.
//! - [`ops`]: every edit as data, in source coordinates.
//! - [`history`]: transactions, undo/redo, selective restore, replay.
//! - [`timeline`]: the derived edit and its projections between source and playback time.
//! - [`resolve`]: the time policy (typed times are current playback time).
//! - [`search`], [`detect`]: finding phrases, fillers, silences, caption chunks.
//! - [`outcome`]: the applied / needs_clarification / rejected answer.
//! - [`hash`]: the deterministic `timeline_hash`.
//! - [`otio`]: OpenTimelineIO export for other editors.
//!
//! Licence: MIT OR Apache-2.0. This crate must never depend on Concat's
//! AGPL `concat-*` crates.

pub mod detect;
pub mod hash;
pub mod history;
pub mod model;
pub mod ops;
pub mod otio;
pub mod outcome;
pub mod resolve;
pub mod search;
pub mod time;
pub mod timeline;

pub use hash::timeline_hash;
pub use history::{ApplyReport, Project, Replay, Tx};
pub use model::{Anchor, CaptionStyle, SourceInfo, StylePatch, Transcript, Word};
pub use ops::{CutReason, Op};
pub use outcome::{Outcome, Status};
pub use time::{secs, PbRange, SrcRange, Us};
pub use timeline::Timeline;

/// Why an edit was refused. The text is written for the user.
#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum EditError {
    /// The edit would leave nothing to play.
    #[error("that would remove the entire video")]
    EmptyTimeline,
    /// A time or span outside the video.
    #[error("{0}")]
    OutOfRange(String),
    /// Speed outside 0.25x to 4x.
    #[error("speed {}x is outside the supported 0.25x-4x", *.0 as f64 / 1000.0)]
    BadSpeed(u32),
    /// An anchor names a word the transcript does not have.
    #[error("unknown word {0}")]
    UnknownWord(String),
    /// No caption with that id is in the edit.
    #[error("there is no caption {0}")]
    UnknownCaption(String),
    /// No active transaction with that id.
    #[error("there is no edit #{0} to restore")]
    UnknownTx(u32),
    /// The edit conflicts with an earlier one.
    #[error("{0}")]
    Contradicts(String),
    /// Anything else malformed.
    #[error("{0}")]
    Invalid(String),
}

impl EditError {
    /// The UPPER_SNAKE_CASE code the API returns.
    pub fn code(&self) -> &'static str {
        match self {
            EditError::EmptyTimeline => "WOULD_REMOVE_EVERYTHING",
            EditError::OutOfRange(_) => "OUT_OF_RANGE",
            EditError::BadSpeed(_) => "SPEED_OUT_OF_RANGE",
            EditError::UnknownWord(_) => "UNKNOWN_WORD",
            EditError::UnknownCaption(_) => "UNKNOWN_CAPTION",
            EditError::UnknownTx(_) => "UNKNOWN_EDIT",
            EditError::Contradicts(_) => "CONTRADICTS_EARLIER_EDIT",
            EditError::Invalid(_) => "INVALID_EDIT",
        }
    }
}
