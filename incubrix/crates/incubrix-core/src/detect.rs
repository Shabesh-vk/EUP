//! Deterministic detectors over the transcript: filler words, long
//! silences, and caption chunks for auto-captioning. Each returns concrete
//! source spans, so what they decided is stored in the history and replays
//! identically.

use crate::model::Transcript;
use crate::time::{SrcRange, Us};
use crate::timeline::{MarkKind, Timeline};

/// Words that are always fillers.
pub const FILLERS: &[&str] = &["um", "umm", "uh", "uhh", "uhm", "er", "erm", "hmm", "mm"];

/// A pause either side of "like" this long makes it a filler.
pub const LIKE_PAUSE_US: Us = 150_000;

/// Words below this confidence are flagged, never acted on blindly.
pub const LOW_CONFIDENCE: f32 = 0.5;

/// What filler detection found.
#[derive(Clone, Debug, Default)]
pub struct Fillers {
    /// Spans to cut.
    pub ranges: Vec<SrcRange>,
    /// The words cut, for the summary.
    pub words: Vec<String>,
    /// Things the user should know (skipped, low confidence).
    pub warnings: Vec<String>,
}

/// Filler words that still play. "like" counts only when it stands apart
/// (a pause on both sides, or doubled: "like, like"). A filler inside a
/// bleeped span is left alone; a low-confidence one is flagged and skipped.
pub fn fillers(t: &Transcript, tl: &Timeline) -> Fillers {
    let mut out = Fillers::default();
    let bleeps: Vec<SrcRange> = tl
        .marks
        .iter()
        .filter(|m| m.kind == MarkKind::Bleep)
        .filter_map(|m| m.anchor.range(t))
        .collect();
    let w = &t.words;
    for i in 0..w.len() {
        let norm = w[i].norm();
        let is_filler = if FILLERS.contains(&norm.as_str()) {
            true
        } else if norm == "like" {
            let gap_before = if i == 0 {
                Us::MAX
            } else {
                w[i].start - w[i - 1].end
            };
            let gap_after = if i + 1 == w.len() {
                Us::MAX
            } else {
                w[i + 1].start - w[i].end
            };
            let doubled = (i > 0 && w[i - 1].norm() == "like")
                || (i + 1 < w.len() && w[i + 1].norm() == "like");
            (gap_before >= LIKE_PAUSE_US && gap_after >= LIKE_PAUSE_US) || doubled
        } else {
            false
        };
        if !is_filler || tl.covered(&w[i].range()) == 0 {
            continue;
        }
        if bleeps.iter().any(|b| b.intersect(&w[i].range()).is_some()) {
            out.warnings.push(format!(
                "Kept '{}' ({}): it is inside a bleep.",
                w[i].text, w[i].id
            ));
            continue;
        }
        if w[i].confidence < LOW_CONFIDENCE {
            out.warnings.push(format!(
                "Kept '{}' ({}): low recognition confidence, check it by ear.",
                w[i].text, w[i].id
            ));
            continue;
        }
        out.ranges.push(w[i].range());
        out.words.push(w[i].text.clone());
    }
    out
}

/// Silences longer than `min` between words that still play, trimmed by
/// `pad` on each side so speech is never clipped. Protected pauses are kept.
pub fn silences(t: &Transcript, tl: &Timeline, source_end: Us, min: Us, pad: Us) -> Vec<SrcRange> {
    let mut gaps = Vec::new();
    let mut prev_end = 0;
    for w in t.words.iter().chain(std::iter::once(&crate::model::Word {
        id: String::new(),
        text: String::new(),
        start: source_end,
        end: source_end,
        speaker: String::new(),
        confidence: 1.0,
    })) {
        if w.start - prev_end > min {
            let lead = if prev_end == 0 { 0 } else { pad };
            let tail = if w.start == source_end { 0 } else { pad };
            if let Some(r) = SrcRange::new(prev_end + lead, w.start - tail) {
                gaps.push(r);
            }
        }
        prev_end = prev_end.max(w.end);
    }
    gaps.into_iter()
        .filter(|g| !tl.protected_pauses.iter().any(|p| p.intersect(g).is_some()))
        .filter(|g| tl.covered(g) > 0)
        .collect()
}

/// Groups words into caption-sized chunks: at most `max_words`, broken at
/// pauses longer than `max_gap` or a change of speaker. Returns index pairs.
pub fn caption_chunks(t: &Transcript, max_words: usize, max_gap: Us) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start = 0;
    for i in 0..t.words.len() {
        let next = t.words.get(i + 1);
        let brk = match next {
            None => true,
            Some(n) => {
                i + 1 - start >= max_words
                    || n.start - t.words[i].end > max_gap
                    || n.speaker != t.words[i].speaker
            }
        };
        if brk {
            out.push((start, i));
            start = i + 1;
        }
    }
    out
}
