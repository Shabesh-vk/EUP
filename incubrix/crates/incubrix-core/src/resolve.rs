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

/// How far a typed cut point may move to reach a pause between words.
pub const SNAP_US: Us = 150_000;

/// Moves the ends of a typed span out of the middle of a word, to the
/// nearer edge of that word, when that edge is within [`SNAP_US`] - so a
/// cut never clips a word. Returns the span and, for each end that landed
/// in a word, a sentence saying what happened.
pub fn snap_to_silence(t: &Transcript, r: SrcRange) -> (SrcRange, Vec<String>) {
    let mut notes = Vec::new();
    let mut snap = |at: Us| -> Us {
        let Some(w) = t.words.iter().find(|w| w.start < at && at < w.end) else {
            return at;
        };
        let to = if at - w.start <= w.end - at {
            w.start
        } else {
            w.end
        };
        if (to - at).abs() <= SNAP_US {
            notes.push(format!(
                "Moved the cut point from {} to {} so '{}' is not clipped.",
                clock(at),
                clock(to),
                w.text
            ));
            to
        } else {
            notes.push(format!(
                "The cut at {} falls inside '{}' with no pause nearby; it may clip that word.",
                clock(at),
                w.text
            ));
            at
        }
    };
    let (a, b) = (snap(r.start), snap(r.end));
    match SrcRange::new(a, b) {
        Some(snapped) => (snapped, notes),
        None => (r, vec![]),
    }
}

/// An anchor on words `first..=last` (indices into the transcript).
pub fn words_anchor(t: &Transcript, first: usize, last: usize) -> Anchor {
    Anchor::Words {
        first: t.words[first].id.clone(),
        last: t.words[last].id.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Word;

    fn word(id: &str, text: &str, start: Us, end: Us) -> Word {
        Word {
            id: id.into(),
            text: text.into(),
            start,
            end,
            speaker: String::new(),
            confidence: 1.0,
        }
    }

    #[test]
    fn typed_cuts_move_out_of_words() {
        let t = Transcript {
            words: vec![
                word("w0", "hello", 1_000_000, 1_500_000),
                word("w1", "world", 3_000_000, 4_000_000),
            ],
        };
        // 1.45 s is 50 ms before the end of "hello": the cut starts after it.
        let (r, notes) = snap_to_silence(&t, SrcRange::new(1_450_000, 2_000_000).unwrap());
        assert_eq!(r.start, 1_500_000);
        assert_eq!(notes.len(), 1);
        // 3.5 s is mid-word, 0.5 s from either edge: left, with a warning.
        let (r, notes) = snap_to_silence(&t, SrcRange::new(2_000_000, 3_500_000).unwrap());
        assert_eq!(r.end, 3_500_000);
        assert!(notes[0].contains("may clip"));
        // In silence: untouched, nothing said.
        let (r, notes) = snap_to_silence(&t, SrcRange::new(2_000_000, 2_500_000).unwrap());
        assert_eq!((r.start, notes.len()), (2_000_000, 0));
    }
}
