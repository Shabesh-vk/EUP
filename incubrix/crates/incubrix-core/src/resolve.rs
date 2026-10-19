//! The time policy, in one place.
//!
//! **Policy: current time.** When a user types "at 1:20" or "from 1:00 to
//! 1:30", they mean what they see now - the edited video's playback time.
//! The engine projects that span through the current timeline into source
//! coordinates the moment the instruction arrives, and stores only those.
//! Every response says so in its `time_policy` field.

use crate::model::{Anchor, Transcript};
use crate::ops::{CutReason, Op};
use crate::time::{clock, PbRange, SpeedMilli, SrcRange, Us};
use crate::timeline::Timeline;
use crate::EditError;

/// The name every response carries.
pub const TIME_POLICY: &str = "current";

/// The sentence summaries append when a time was typed.
pub const TIME_POLICY_NOTE: &str = "Times are read as the current edited playback time.";

/// The source spans behind a typed playback span. Rejects spans that start
/// past the end, end before they start, or reach past the end.
pub fn playback_span(tl: &Timeline, start: Us, end: Us) -> Result<Vec<SrcRange>, EditError> {
    if start < 0 || end <= start {
        return Err(EditError::Invalid(format!(
            "{}-{} is not a valid span",
            clock(start),
            clock(end)
        )));
    }
    // One millisecond of slack so "the last 10 seconds" lands exactly.
    if start >= tl.duration || end > tl.duration + 1_000 {
        return Err(EditError::OutOfRange(format!(
            "{}-{} is past the end: the edited video is {} long",
            clock(start),
            clock(end),
            clock(tl.duration)
        )));
    }
    let spans = tl.playback_to_source(&PbRange {
        start,
        end: end.min(tl.duration),
    });
    if spans.is_empty() {
        return Err(EditError::OutOfRange("nothing plays there".into()));
    }
    Ok(spans)
}

/// "Cut from A to B" in current time.
pub fn cut_playback(tl: &Timeline, start: Us, end: Us) -> Result<Op, EditError> {
    Ok(Op::Cut {
        ranges: playback_span(tl, start, end)?,
        reason: CutReason::User,
    })
}

/// "Keep only A to B" in current time. A span that crosses a reorder keeps
/// its first source piece only; the caller should ask when that happens.
pub fn keep_playback(tl: &Timeline, start: Us, end: Us) -> Result<Vec<Op>, EditError> {
    let spans = playback_span(tl, start, end)?;
    let keep = SrcRange {
        start: spans.iter().map(|s| s.start).min().unwrap(),
        end: spans.iter().map(|s| s.end).max().unwrap(),
    };
    Ok(vec![Op::KeepOnly { range: keep }])
}

/// "Speed up A to B by N" in current time: one op per source piece.
pub fn speed_playback(
    tl: &Timeline,
    start: Us,
    end: Us,
    speed: SpeedMilli,
) -> Result<Vec<Op>, EditError> {
    Ok(playback_span(tl, start, end)?
        .into_iter()
        .map(|range| Op::Speed { range, speed })
        .collect())
}

/// An anchor on words `first..=last` (indices into the transcript).
pub fn words_anchor(t: &Transcript, first: usize, last: usize) -> Anchor {
    Anchor::Words {
        first: t.words[first].id.clone(),
        last: t.words[last].id.clone(),
    }
}
