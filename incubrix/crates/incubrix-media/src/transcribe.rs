//! Word-level transcripts.
//!
//! A [`Transcriber`] returns raw words; [`clean_words`] turns them into the
//! engine's [`Transcript`]: sorted, inside the video, no overlapping words,
//! stable ids, punctuation kept on the word before it, and low-confidence
//! words flagged. Recognisers make mistakes; this is where they are caught.

use std::path::{Path, PathBuf};

use incubrix_core::detect::LOW_CONFIDENCE;
use incubrix_core::model::normalize;
use incubrix_core::time::clock;
use incubrix_core::{SourceInfo, Transcript, Us, Word};
use serde::{Deserialize, Serialize};

use crate::MediaError;

/// One word as a recogniser gives it.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize)]
pub struct RawWord {
    /// The text, possibly with punctuation or a leading space.
    pub text: String,
    /// Start in the source, microseconds.
    pub start: Us,
    /// End in the source, microseconds.
    pub end: Us,
    /// 0 to 1.
    #[serde(default = "one")]
    pub confidence: f32,
}

fn one() -> f32 {
    1.0
}

/// A recogniser's output file: `{"words": [...]}`.
#[derive(Clone, PartialEq, Debug, Default, Serialize, Deserialize)]
pub struct RawTranscript {
    /// The words, in any order.
    pub words: Vec<RawWord>,
}

/// Speech to words with timings and confidences.
pub trait Transcriber {
    /// Names the recogniser and its model, for the cache key and the manifest.
    fn id(&self) -> String;
    /// The words of `media`'s sound track.
    fn transcribe(&self, media: &Path, source: &SourceInfo) -> Result<Vec<RawWord>, MediaError>;
}

/// Reads recorded recogniser output from a JSON file: what the tests and CI
/// use, so they need no model and no API key.
#[derive(Clone, Debug)]
pub struct FixtureTranscriber {
    path: PathBuf,
}

impl FixtureTranscriber {
    /// A transcriber that returns the words in `path`.
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }
}

impl Transcriber for FixtureTranscriber {
    fn id(&self) -> String {
        let name = self
            .path
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        format!("fixture-{name}")
    }

    fn transcribe(&self, _media: &Path, _source: &SourceInfo) -> Result<Vec<RawWord>, MediaError> {
        let text = std::fs::read_to_string(&self.path)
            .map_err(|e| MediaError::Io(format!("cannot read {}: {e}", self.path.display())))?;
        let raw: RawTranscript = serde_json::from_str(&text)
            .map_err(|e| MediaError::BadData(format!("{}: {e}", self.path.display())))?;
        Ok(raw.words)
    }
}

/// Words glued to punctuation only (`","`, `"."`) are joined to the word
/// before; the rest are cleaned and given ids `w00000`, `w00001`, ...
/// Returns the transcript and what was fixed or flagged.
pub fn clean_words(raw: Vec<RawWord>, duration: Us) -> (Transcript, Vec<String>) {
    let mut raw = raw;
    raw.sort_by_key(|w| (w.start, w.end));
    let mut words: Vec<Word> = Vec::with_capacity(raw.len());
    let (mut clamped, mut trimmed, mut dropped) = (0, 0, 0);
    for w in raw {
        let text = w.text.trim().to_owned();
        if normalize(&text).is_empty() {
            // Punctuation belongs to the word that ended just before it, which
            // under overlapping speech is not always the last word started.
            let owner = words
                .iter_mut()
                .rev()
                .filter(|p| p.end <= w.start)
                .max_by_key(|p| p.end);
            match owner {
                Some(prev) if !text.is_empty() => prev.text.push_str(&text),
                _ => dropped += 1,
            }
            continue;
        }
        let (mut start, mut end) = (w.start, w.end);
        if start < 0 || end > duration || start >= duration {
            clamped += 1;
            start = start.clamp(0, duration.saturating_sub(1).max(0));
            end = end.clamp(start, duration);
        }
        if end < start {
            end = start;
        }
        let confidence = if w.confidence.is_nan() {
            0.0
        } else {
            w.confidence.clamp(0.0, 1.0)
        };
        words.push(Word {
            id: String::new(),
            text,
            start,
            end,
            speaker: String::new(),
            confidence,
        });
    }
    // A word may not run into the next one.
    for i in 0..words.len().saturating_sub(1) {
        let next = words[i + 1].start;
        if words[i].end > next && next > words[i].start {
            words[i].end = next;
            trimmed += 1;
        }
    }
    for (i, w) in words.iter_mut().enumerate() {
        w.id = format!("w{i:05}");
    }

    let mut warnings = Vec::new();
    if clamped + trimmed + dropped > 0 {
        warnings.push(format!(
            "Recogniser output fixed: {clamped} word time(s) outside the video clamped, {trimmed} overlapping word(s) trimmed, {dropped} empty token(s) dropped."
        ));
    }
    let t = Transcript { words };
    if let Some(w) = low_confidence_warning(&t) {
        warnings.push(w);
    }
    (t, warnings)
}

/// One warning naming the words below [`LOW_CONFIDENCE`], if any.
pub fn low_confidence_warning(t: &Transcript) -> Option<String> {
    let low: Vec<&Word> = t
        .words
        .iter()
        .filter(|w| w.confidence < LOW_CONFIDENCE)
        .collect();
    if low.is_empty() {
        return None;
    }
    let shown: Vec<String> = low
        .iter()
        .take(5)
        .map(|w| format!("'{}' at {}", w.text, clock(w.start)))
        .collect();
    let more = if low.len() > 5 {
        format!(" and {} more", low.len() - 5)
    } else {
        String::new()
    };
    Some(format!(
        "{} word(s) have low recognition confidence and are flagged, never cut or bleeped blindly: {}{more}.",
        low.len(),
        shown.join(", ")
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raw(text: &str, a: Us, b: Us, c: f32) -> RawWord {
        RawWord {
            text: text.into(),
            start: a,
            end: b,
            confidence: c,
        }
    }

    #[test]
    fn cleanup_sorts_trims_and_numbers() {
        let (t, warnings) = clean_words(
            vec![
                raw(" world", 500_000, 900_000, 0.9),
                raw(" Hello", 0, 600_000, 0.9),
                raw(".", 900_000, 900_000, 0.9),
                raw(" late", 9_000_000, 12_000_000, 0.3),
            ],
            10_000_000,
        );
        let texts: Vec<_> = t.words.iter().map(|w| w.text.as_str()).collect();
        assert_eq!(texts, ["Hello", "world.", "late"]);
        assert_eq!(t.words[0].end, 500_000, "overlap trimmed");
        assert_eq!(t.words[2].end, 10_000_000, "clamped to the video");
        assert_eq!(t.words[1].id, "w00001");
        assert_eq!(warnings.len(), 2, "{warnings:?}");
        assert!(warnings[1].contains("'late' at 0:09"));
    }
}
