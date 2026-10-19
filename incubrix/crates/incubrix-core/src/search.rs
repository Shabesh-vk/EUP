//! Finding content in the transcript: exact phrases and single terms. What
//! still plays is decided against the current timeline, so a phrase that was
//! cut is reported as such rather than silently matched.

use crate::model::{normalize, Transcript};
use crate::time::{SrcRange, Us};
use crate::timeline::Timeline;

/// One place a phrase is said.
#[derive(Clone, PartialEq, Debug)]
pub struct Hit {
    /// Index of the first word.
    pub first: usize,
    /// Index of the last word.
    pub last: usize,
    /// Its span of the source.
    pub range: SrcRange,
    /// Where it starts in the current edit, if it still plays.
    pub playback_start: Option<Us>,
}

/// Every occurrence of `phrase` (case and punctuation ignored), in source order.
pub fn find_phrase(transcript: &Transcript, timeline: &Timeline, phrase: &str) -> Vec<Hit> {
    let want: Vec<String> = phrase
        .split_whitespace()
        .map(normalize)
        .filter(|w| !w.is_empty())
        .collect();
    if want.is_empty() {
        return vec![];
    }
    let words: Vec<String> = transcript.words.iter().map(|w| w.norm()).collect();
    let mut hits = Vec::new();
    let mut i = 0;
    while i + want.len() <= words.len() {
        if words[i..i + want.len()] == want[..] {
            let first = &transcript.words[i];
            let last = &transcript.words[i + want.len() - 1];
            let range = SrcRange {
                start: first.start,
                end: last.end.max(first.start + 1),
            };
            let playback_start = timeline.source_to_playback(&range).first().map(|p| p.start);
            hits.push(Hit {
                first: i,
                last: i + want.len() - 1,
                range,
                playback_start,
            });
            i += want.len();
        } else {
            i += 1;
        }
    }
    hits
}

/// Occurrences of any of `terms` (each a single word or a phrase).
pub fn find_any(transcript: &Transcript, timeline: &Timeline, terms: &[&str]) -> Vec<Hit> {
    let mut hits: Vec<Hit> = terms
        .iter()
        .flat_map(|t| find_phrase(transcript, timeline, t))
        .collect();
    hits.sort_by_key(|h| (h.first, h.last));
    hits.dedup_by_key(|h| h.first);
    hits
}

/// Only the hits that still play in the current edit.
pub fn playing(hits: Vec<Hit>) -> Vec<Hit> {
    hits.into_iter()
        .filter(|h| h.playback_start.is_some())
        .collect()
}
