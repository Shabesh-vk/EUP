//! The edited timeline: what plays, in what order, how fast, and where every
//! overlay lands. It is never edited directly; [`crate::history`] derives it
//! by replaying operations on top of the untouched source.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::model::{Anchor, CaptionStyle};
use crate::time::{playback_len, source_len, PbRange, SpeedMilli, SrcRange, Us, NORMAL_SPEED};

/// Shortest time a sped-up caption stays on screen (brief: about 0.7 s).
pub const MIN_CAPTION_US: Us = 700_000;

/// Gaps shorter than this between two playback pieces are treated as joined.
pub const JOIN_US: Us = 1_000;

/// A piece of the source playing at one speed.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Segment {
    /// The source span.
    pub source: SrcRange,
    /// Speed in thousandths.
    pub speed: SpeedMilli,
    /// Where it starts in the edited video.
    pub playback_start: Us,
}

impl Segment {
    /// Length in the edited video.
    pub fn playback_len(&self) -> Us {
        playback_len(self.source.len(), self.speed)
    }

    /// Where it ends in the edited video.
    pub fn playback_end(&self) -> Us {
        self.playback_start + self.playback_len()
    }
}

/// A caption, with where it lands now.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Caption {
    /// Caption id.
    pub id: String,
    /// Text shown.
    pub text: String,
    /// What it is attached to.
    pub anchor: Anchor,
    /// How it looks.
    pub style: CaptionStyle,
    /// Where it plays in the edited video; empty when its content is cut.
    pub playback: Vec<PbRange>,
    /// The transaction that added it.
    pub tx: u32,
}

/// Mute or bleep.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum MarkKind {
    /// Silence.
    Mute,
    /// A tone over the words.
    Bleep,
}

/// A mute or bleep, with where it lands now.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct AudioMark {
    /// Mark id.
    pub id: String,
    /// Mute or bleep.
    pub kind: MarkKind,
    /// What it covers.
    pub anchor: Anchor,
    /// Where it plays in the edited video.
    pub playback: Vec<PbRange>,
    /// The transaction that added it.
    pub tx: u32,
}

/// Background music.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Music {
    /// Music id.
    pub id: String,
    /// File path or URL.
    pub path: String,
    /// Level with no speech, dB.
    pub volume_db: i32,
    /// Drop under speech, dB.
    pub duck_db: i32,
    /// The transaction that added it.
    pub tx: u32,
}

/// The whole edited video, as data. This is what is hashed and rendered.
#[derive(Clone, PartialEq, Eq, Debug, Default, Serialize, Deserialize, JsonSchema)]
pub struct Timeline {
    /// Length of the edited video.
    pub duration: Us,
    /// What plays, in order.
    pub segments: Vec<Segment>,
    /// Captions, in the order they were added (hidden ones included, with no playback).
    pub captions: Vec<Caption>,
    /// Mutes and bleeps.
    pub marks: Vec<AudioMark>,
    /// Music beds.
    pub music: Vec<Music>,
    /// Pauses silence removal must keep.
    pub protected_pauses: Vec<SrcRange>,
}

impl Timeline {
    /// Where a span of the source plays now: zero or more playback pieces,
    /// sorted and with touching pieces joined.
    pub fn source_to_playback(&self, r: &SrcRange) -> Vec<PbRange> {
        let mut out = Vec::new();
        for s in &self.segments {
            if let Some(o) = s.source.intersect(r) {
                let a = s.playback_start + playback_len(o.start - s.source.start, s.speed);
                let b = s.playback_start + playback_len(o.end - s.source.start, s.speed);
                if let Some(p) = PbRange::new(a, b) {
                    out.push(p);
                }
            }
        }
        merge(out)
    }

    /// Which source spans a span of the edited video shows, in playback order.
    pub fn playback_to_source(&self, p: &PbRange) -> Vec<SrcRange> {
        let mut out = Vec::new();
        for s in &self.segments {
            let (ps, pe) = (s.playback_start, s.playback_end());
            let a = p.start.max(ps);
            let b = p.end.min(pe);
            if b <= a {
                continue;
            }
            let sa = (s.source.start + source_len(a - ps, s.speed)).min(s.source.end);
            let sb = (s.source.start + source_len(b - ps, s.speed)).min(s.source.end);
            if let Some(r) = SrcRange::new(sa, sb) {
                out.push(r);
            }
        }
        out
    }

    /// The playback time of one source instant, if it still plays.
    pub fn source_point(&self, t: Us) -> Option<Us> {
        self.segments
            .iter()
            .find(|s| s.source.contains(t))
            .map(|s| s.playback_start + playback_len(t - s.source.start, s.speed))
    }

    /// The source instant shown at one playback time.
    pub fn playback_point(&self, t: Us) -> Option<Us> {
        self.segments
            .iter()
            .find(|s| t >= s.playback_start && t < s.playback_end())
            .map(|s| s.source.start + source_len(t - s.playback_start, s.speed))
    }

    /// How much of `r` still plays, in source microseconds.
    pub fn covered(&self, r: &SrcRange) -> Us {
        self.segments
            .iter()
            .filter_map(|s| s.source.intersect(r))
            .map(|o| o.len())
            .sum()
    }

    /// Whether any part of `r` plays faster than normal.
    pub fn sped_up(&self, r: &SrcRange) -> bool {
        self.segments
            .iter()
            .any(|s| s.speed > NORMAL_SPEED && s.source.intersect(r).is_some())
    }

    /// A caption by id.
    pub fn caption(&self, id: &str) -> Option<&Caption> {
        self.captions.iter().find(|c| c.id == id)
    }
}

/// Sorts pieces and joins the ones that touch.
pub fn merge(mut v: Vec<PbRange>) -> Vec<PbRange> {
    v.sort();
    let mut out: Vec<PbRange> = Vec::with_capacity(v.len());
    for p in v {
        match out.last_mut() {
            Some(last) if p.start <= last.end + JOIN_US => last.end = last.end.max(p.end),
            _ => out.push(p),
        }
    }
    out
}

/// The segment list while operations are being replayed: `(source, speed)` in
/// playback order. Playback positions are only computed at the end.
#[derive(Clone, Debug, Default)]
pub(crate) struct Cuts(pub Vec<(SrcRange, SpeedMilli)>);

impl Cuts {
    pub fn whole(r: SrcRange) -> Self {
        Self(vec![(r, NORMAL_SPEED)])
    }

    pub fn cut(&mut self, r: &SrcRange) {
        self.0 = self
            .0
            .iter()
            .flat_map(|(s, sp)| s.subtract(r).into_iter().map(move |p| (p, *sp)))
            .collect();
    }

    pub fn keep_only(&mut self, r: &SrcRange) {
        self.0 = self
            .0
            .iter()
            .filter_map(|(s, sp)| s.intersect(r).map(|p| (p, *sp)))
            .collect();
    }

    pub fn speed(&mut self, r: &SrcRange, speed: SpeedMilli) {
        let mut out = Vec::with_capacity(self.0.len() + 2);
        for (s, sp) in &self.0 {
            match s.intersect(r) {
                None => out.push((*s, *sp)),
                Some(mid) => {
                    if let Some(a) = SrcRange::new(s.start, mid.start) {
                        out.push((a, *sp));
                    }
                    out.push((mid, speed));
                    if let Some(b) = SrcRange::new(mid.end, s.end) {
                        out.push((b, *sp));
                    }
                }
            }
        }
        self.0 = out;
    }

    /// Splits whatever segment contains `t` so a segment boundary falls on it.
    fn split_at(&mut self, t: Us) {
        if let Some(i) = self.0.iter().position(|(s, _)| s.start < t && t < s.end) {
            let (s, sp) = self.0[i];
            self.0[i] = (
                SrcRange {
                    start: s.start,
                    end: t,
                },
                sp,
            );
            self.0.insert(
                i + 1,
                (
                    SrcRange {
                        start: t,
                        end: s.end,
                    },
                    sp,
                ),
            );
        }
    }

    /// Moves `r` in front of source instant `before`. Returns false when
    /// `before` no longer plays (the block then goes last).
    pub fn reorder(&mut self, r: &SrcRange, before: Option<Us>) -> bool {
        self.split_at(r.start);
        self.split_at(r.end);
        let (moved, mut rest): (Vec<_>, Vec<_>) =
            self.0.iter().partition(|(s, _)| s.intersect(r).is_some());
        if moved.is_empty() {
            return true;
        }
        let mut found = true;
        let at = match before {
            None => rest.len(),
            Some(t) => {
                let mut tmp = Cuts(rest.clone());
                tmp.split_at(t);
                rest = tmp.0;
                match rest.iter().position(|(s, _)| s.start == t || s.contains(t)) {
                    Some(i) => i,
                    None => {
                        found = false;
                        rest.len()
                    }
                }
            }
        };
        let mut out = rest[..at].to_vec();
        out.extend(moved);
        out.extend_from_slice(&rest[at..]);
        self.0 = out;
        found
    }

    /// Joins neighbours that continue each other at one speed, then lays the
    /// segments out on the playback axis.
    pub fn into_segments(self) -> Vec<Segment> {
        let mut joined: Vec<(SrcRange, SpeedMilli)> = Vec::with_capacity(self.0.len());
        for (s, sp) in self.0 {
            match joined.last_mut() {
                Some((last, lsp)) if *lsp == sp && last.end == s.start => last.end = s.end,
                _ => joined.push((s, sp)),
            }
        }
        let mut at = 0;
        joined
            .into_iter()
            .map(|(source, speed)| {
                let seg = Segment {
                    source,
                    speed,
                    playback_start: at,
                };
                at = seg.playback_end();
                seg
            })
            .collect()
    }
}
