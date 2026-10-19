//! Exact time. Every time inside the engine is an integer number of
//! microseconds (`Us`). Floating point never enters the timeline model, so a
//! session replayed on any machine produces the same numbers and the same hash.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// Microseconds.
pub type Us = i64;

/// Microseconds per second.
pub const US_PER_S: Us = 1_000_000;

/// Speed is stored in thousandths: 1000 = normal, 2000 = twice as fast.
pub type SpeedMilli = u32;

/// Normal speed.
pub const NORMAL_SPEED: SpeedMilli = 1000;

/// Seconds (as typed by a user or read from a file) to microseconds.
pub fn secs(s: f64) -> Us {
    (s * US_PER_S as f64).round() as Us
}

/// Microseconds to seconds, for display and JSON responses only.
pub fn to_secs(us: Us) -> f64 {
    us as f64 / US_PER_S as f64
}

/// Seconds rounded to milliseconds, for responses: avoids 12.000000001.
pub fn to_secs_ms(us: Us) -> f64 {
    ((us as f64) / 1000.0).round() / 1000.0
}

/// `m:ss` (or `m:ss.s` when there is a fraction), the way users read times.
pub fn clock(us: Us) -> String {
    let neg = us < 0;
    let us = us.abs();
    let tenths = (us + 50_000) / 100_000;
    let whole = tenths / 10;
    let frac = tenths % 10;
    let (m, s) = (whole / 60, whole % 60);
    let sign = if neg { "-" } else { "" };
    if frac == 0 {
        format!("{sign}{m}:{s:02}")
    } else {
        format!("{sign}{m}:{s:02}.{frac}")
    }
}

/// How long `source_len` of source plays at `speed`.
pub fn playback_len(source_len: Us, speed: SpeedMilli) -> Us {
    let n = source_len as i128 * NORMAL_SPEED as i128;
    let d = speed as i128;
    ((n + d / 2) / d) as Us
}

/// How much source `playback_len` of playback covers at `speed`.
pub fn source_len(playback_len: Us, speed: SpeedMilli) -> Us {
    let n = playback_len as i128 * speed as i128;
    let d = NORMAL_SPEED as i128;
    ((n + d / 2) / d) as Us
}

/// A half-open span `[start, end)` of the **original source** file.
#[derive(
    Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug, Serialize, Deserialize, JsonSchema,
)]
pub struct SrcRange {
    /// Start, microseconds into the source.
    pub start: Us,
    /// End (exclusive), microseconds into the source.
    pub end: Us,
}

impl SrcRange {
    /// A range; `None` when it would be empty or inverted.
    pub fn new(start: Us, end: Us) -> Option<Self> {
        (end > start).then_some(Self { start, end })
    }

    /// Length in microseconds.
    pub fn len(&self) -> Us {
        self.end - self.start
    }

    /// Never true for a range made by [`SrcRange::new`].
    pub fn is_empty(&self) -> bool {
        self.end <= self.start
    }

    /// The overlap of two ranges, if any.
    pub fn intersect(&self, other: &SrcRange) -> Option<SrcRange> {
        SrcRange::new(self.start.max(other.start), self.end.min(other.end))
    }

    /// Whether `t` lies inside the range.
    pub fn contains(&self, t: Us) -> bool {
        t >= self.start && t < self.end
    }

    /// `self` minus `other`: zero, one or two pieces, in order.
    pub fn subtract(&self, other: &SrcRange) -> Vec<SrcRange> {
        let mut out = Vec::with_capacity(2);
        if let Some(r) = SrcRange::new(self.start, self.end.min(other.start)) {
            out.push(r);
        }
        if let Some(r) = SrcRange::new(self.start.max(other.end), self.end) {
            out.push(r);
        }
        if self.intersect(other).is_none() {
            return vec![*self];
        }
        out
    }
}

/// A half-open span `[start, end)` of the **edited playback**.
#[derive(
    Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug, Serialize, Deserialize, JsonSchema,
)]
pub struct PbRange {
    /// Start, microseconds into the edited video.
    pub start: Us,
    /// End (exclusive), microseconds into the edited video.
    pub end: Us,
}

impl PbRange {
    /// A range; `None` when it would be empty or inverted.
    pub fn new(start: Us, end: Us) -> Option<Self> {
        (end > start).then_some(Self { start, end })
    }

    /// Length in microseconds.
    pub fn len(&self) -> Us {
        self.end - self.start
    }

    /// Never true for a range made by [`PbRange::new`].
    pub fn is_empty(&self) -> bool {
        self.end <= self.start
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clock_formats() {
        assert_eq!(clock(secs(42.0)), "0:42");
        assert_eq!(clock(secs(80.0)), "1:20");
        assert_eq!(clock(secs(12.25)), "0:12.3");
    }

    #[test]
    fn speed_round_trips() {
        assert_eq!(playback_len(secs(30.0), 2000), secs(15.0));
        assert_eq!(source_len(secs(15.0), 2000), secs(30.0));
    }

    #[test]
    fn subtract_pieces() {
        let a = SrcRange::new(0, 100).unwrap();
        assert_eq!(a.subtract(&SrcRange::new(20, 30).unwrap()).len(), 2);
        assert_eq!(a.subtract(&SrcRange::new(0, 100).unwrap()).len(), 0);
        assert_eq!(a.subtract(&SrcRange::new(200, 300).unwrap()), vec![a]);
        assert_eq!(
            a.subtract(&SrcRange::new(50, 300).unwrap()),
            vec![SrcRange::new(0, 50).unwrap()]
        );
    }
}
