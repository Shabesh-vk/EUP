//! Who speaks when.
//!
//! A [`Diarizer`] returns speaker turns; [`assign_speakers`] gives every
//! word the speaker whose turn covers most of it, names speakers `S1`, `S2`,
//! ... in order of first appearance, and warns about the two things
//! diarizers get wrong: overlapping speech, and a word or two labelled with
//! the other speaker in the middle of someone's sentence (a likely swap).
//! Labels are never silently changed; the user is told.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use incubrix_core::time::clock;
use incubrix_core::{SourceInfo, Transcript, Us};
use serde::{Deserialize, Serialize};

use crate::MediaError;

/// A stretch of one speaker talking.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize)]
pub struct SpeakerTurn {
    /// Start in the source, microseconds.
    pub start: Us,
    /// End in the source, microseconds.
    pub end: Us,
    /// The diarizer's own label (any string; renamed to `S1`, `S2`, ...).
    pub speaker: String,
}

/// A diarizer's output file: `{"turns": [...]}`.
#[derive(Clone, PartialEq, Debug, Default, Serialize, Deserialize)]
pub struct Turns {
    /// The turns, in any order; they may overlap.
    pub turns: Vec<SpeakerTurn>,
}

/// Audio to speaker turns.
pub trait Diarizer {
    /// Names the diarizer and its models, for the cache key and the manifest.
    fn id(&self) -> String;
    /// The speaker turns of `media`'s sound track.
    fn diarize(&self, media: &Path, source: &SourceInfo) -> Result<Vec<SpeakerTurn>, MediaError>;
}

/// Reads recorded turns from a JSON file, for tests and CI.
#[derive(Clone, Debug)]
pub struct FixtureDiarizer {
    path: PathBuf,
}

impl FixtureDiarizer {
    /// A diarizer that returns the turns in `path`.
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }
}

impl Diarizer for FixtureDiarizer {
    fn id(&self) -> String {
        let name = self
            .path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        format!("fixture-{name}")
    }

    fn diarize(&self, _media: &Path, _source: &SourceInfo) -> Result<Vec<SpeakerTurn>, MediaError> {
        let text = std::fs::read_to_string(&self.path)
            .map_err(|e| MediaError::Io(format!("cannot read {}: {e}", self.path.display())))?;
        let t: Turns = serde_json::from_str(&text)
            .map_err(|e| MediaError::BadData(format!("{}: {e}", self.path.display())))?;
        Ok(t.turns)
    }
}

/// A word overlapping another speaker's turn by at least this share of its
/// length counts as overlapping speech (percent).
pub const OVERLAP_SHARE: Us = 30;

/// A run of at most this many words labelled with another speaker, inside
/// one speaker's flowing sentence, is reported as a possible swap.
pub const SWAP_MAX_WORDS: usize = 2;

/// Gaps shorter than this keep a sentence flowing.
pub const FLOW_GAP_US: Us = 250_000;

/// Labels every word with a speaker and returns the warnings. With no
/// turns, everyone is `S1`.
pub fn assign_speakers(t: &mut Transcript, turns: &[SpeakerTurn]) -> Vec<String> {
    let mut turns: Vec<SpeakerTurn> = turns.iter().filter(|x| x.end > x.start).cloned().collect();
    turns.sort_by(|a, b| (a.start, a.end, &a.speaker).cmp(&(b.start, b.end, &b.speaker)));
    // Stable names by first appearance.
    let mut names: BTreeMap<String, String> = BTreeMap::new();
    for turn in &turns {
        let n = names.len() + 1;
        names
            .entry(turn.speaker.clone())
            .or_insert_with(|| format!("S{n}"));
    }

    let mut overlap_words: Vec<usize> = Vec::new();
    for (i, w) in t.words.iter_mut().enumerate() {
        let len = (w.end - w.start).max(1);
        let mut per: BTreeMap<&str, Us> = BTreeMap::new();
        for turn in &turns {
            let o = w.end.min(turn.end) - w.start.max(turn.start);
            if o > 0 {
                *per.entry(names[&turn.speaker].as_str()).or_default() += o;
            }
        }
        // Most overlap wins; ties go to the lower label, so it is deterministic.
        w.speaker = per
            .iter()
            .max_by(|a, b| a.1.cmp(b.1).then(b.0.cmp(a.0)))
            .map(|(s, _)| (*s).to_owned())
            .unwrap_or_else(|| {
                // Between turns: the nearest one.
                turns
                    .iter()
                    .min_by_key(|x| (x.start - w.end).abs().min((w.start - x.end).abs()))
                    .map(|x| names[&x.speaker].clone())
                    .unwrap_or_else(|| "S1".into())
            });
        if per
            .values()
            .filter(|o| **o * 100 >= len * OVERLAP_SHARE)
            .count()
            >= 2
        {
            overlap_words.push(i);
        }
    }

    let mut warnings = Vec::new();
    for run in runs(&overlap_words) {
        let (a, b) = (&t.words[run.0], &t.words[run.1]);
        warnings.push(format!(
            "Overlapping speech at {}-{} ('{}'): two people talk at once, so speaker labels and cuts there may be imprecise.",
            clock(a.start),
            clock(b.end),
            t.text_between(&a.id, &b.id)
        ));
    }
    warnings.extend(swap_warnings(t));
    warnings
}

/// Consecutive indices grouped into (first, last) runs.
fn runs(ix: &[usize]) -> Vec<(usize, usize)> {
    let mut out: Vec<(usize, usize)> = Vec::new();
    for &i in ix {
        match out.last_mut() {
            Some(r) if r.1 + 1 == i => r.1 = i,
            _ => out.push((i, i)),
        }
    }
    out
}

fn swap_warnings(t: &Transcript) -> Vec<String> {
    let w = &t.words;
    let mut out = Vec::new();
    let mut i = 0;
    while i < w.len() {
        let mut j = i;
        while j + 1 < w.len() && w[j + 1].speaker == w[i].speaker {
            j += 1;
        }
        // Run i..=j has one speaker; is it a short island inside another's flow?
        if i > 0 && j + 1 < w.len() && j - i < SWAP_MAX_WORDS {
            let (before, after) = (&w[i - 1], &w[j + 1]);
            let flows =
                w[i].start - before.end < FLOW_GAP_US && after.start - w[j].end < FLOW_GAP_US;
            if before.speaker == after.speaker && before.speaker != w[i].speaker && flows {
                out.push(format!(
                    "Possible speaker-label swap at {}: '{}' is labelled {} in the middle of {}'s sentence. Check it before speaker-based edits.",
                    clock(w[i].start),
                    t.text_between(&w[i].id, &w[j].id),
                    w[i].speaker,
                    before.speaker
                ));
            }
        }
        i = j + 1;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use incubrix_core::Word;

    fn words(spec: &[(&str, Us, Us)]) -> Transcript {
        Transcript {
            words: spec
                .iter()
                .enumerate()
                .map(|(i, (t, a, b))| Word {
                    id: format!("w{i:05}"),
                    text: (*t).into(),
                    start: *a,
                    end: *b,
                    speaker: String::new(),
                    confidence: 1.0,
                })
                .collect(),
        }
    }

    fn turn(a: Us, b: Us, s: &str) -> SpeakerTurn {
        SpeakerTurn {
            start: a,
            end: b,
            speaker: s.into(),
        }
    }

    #[test]
    fn names_follow_first_appearance() {
        let mut t = words(&[("hi", 0, 400_000), ("hello", 1_000_000, 1_400_000)]);
        let w = assign_speakers(
            &mut t,
            &[turn(900_000, 2_000_000, "spk_0"), turn(0, 500_000, "spk_7")],
        );
        assert!(w.is_empty());
        assert_eq!(t.words[0].speaker, "S1");
        assert_eq!(t.words[1].speaker, "S2");
    }

    #[test]
    fn island_in_a_flowing_sentence_is_flagged() {
        let mut t = words(&[
            ("so", 0, 300_000),
            ("I", 300_000, 500_000),
            ("think", 500_000, 800_000),
            ("this", 800_000, 1_100_000),
        ]);
        let w = assign_speakers(
            &mut t,
            &[
                turn(0, 500_000, "a"),
                turn(500_000, 800_000, "b"),
                turn(800_000, 1_200_000, "a"),
            ],
        );
        assert_eq!(w.len(), 1, "{w:?}");
        assert!(w[0].contains("'think' is labelled S2"));
    }
}
