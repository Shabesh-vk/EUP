//! The inputs the engine edits: the untouched source, its transcript, and the
//! content anchors overlays attach to.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::time::{SrcRange, Us};

/// Facts about the original file. The file itself is never written to.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct SourceInfo {
    /// Where the original lives (path or URL).
    pub path: String,
    /// SHA-256 of the original, recorded at intake and checked after renders.
    pub sha256: String,
    /// Length of the original.
    pub duration: Us,
    /// Frame rate numerator (e.g. 30000 for 29.97).
    pub fps_num: u32,
    /// Frame rate denominator (e.g. 1001 for 29.97).
    pub fps_den: u32,
    /// Whether the file has a sound stream.
    pub has_audio: bool,
    /// Whether the file's frame rate varies (phone video).
    #[serde(default)]
    pub variable_frame_rate: bool,
}

impl SourceInfo {
    /// A source with only a duration, for tests and fixtures.
    pub fn with_duration(duration: Us) -> Self {
        Self {
            path: String::new(),
            sha256: String::new(),
            duration,
            fps_num: 30,
            fps_den: 1,
            has_audio: true,
            variable_frame_rate: false,
        }
    }

    /// The whole source as a range.
    pub fn range(&self) -> SrcRange {
        SrcRange {
            start: 0,
            end: self.duration,
        }
    }

    /// One frame, in microseconds (rounded).
    pub fn frame(&self) -> Us {
        let num = self.fps_num.max(1) as i64;
        let den = self.fps_den.max(1) as i64;
        (1_000_000 * den + num / 2) / num
    }
}

/// One transcribed word.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Word {
    /// Stable id, e.g. `w0042`. Anchors refer to words by this id.
    pub id: String,
    /// The word as recognised.
    pub text: String,
    /// Start in the source.
    pub start: Us,
    /// End in the source.
    pub end: Us,
    /// Speaker label from diarization, e.g. `S1`.
    #[serde(default)]
    pub speaker: String,
    /// Recogniser confidence, 0 to 1.
    #[serde(default = "one")]
    pub confidence: f32,
}

fn one() -> f32 {
    1.0
}

impl Word {
    /// The word's span of the source.
    pub fn range(&self) -> SrcRange {
        SrcRange {
            start: self.start,
            end: self.end.max(self.start + 1),
        }
    }

    /// Lower-case letters and digits only: what search compares.
    pub fn norm(&self) -> String {
        normalize(&self.text)
    }
}

/// Lower-case, keeping letters, digits and inner apostrophes.
pub fn normalize(text: &str) -> String {
    text.chars()
        .filter(|c| c.is_alphanumeric() || *c == '\'')
        .flat_map(|c| c.to_lowercase())
        .collect::<String>()
        .trim_matches('\'')
        .to_owned()
}

/// Every word of the source, in time order.
#[derive(Clone, PartialEq, Debug, Default, Serialize, Deserialize, JsonSchema)]
pub struct Transcript {
    /// The words, sorted by start.
    pub words: Vec<Word>,
}

impl Transcript {
    /// Index of the word with `id`.
    pub fn index_of(&self, id: &str) -> Option<usize> {
        self.words.iter().position(|w| w.id == id)
    }

    /// The word with `id`.
    pub fn word(&self, id: &str) -> Option<&Word> {
        self.words.iter().find(|w| w.id == id)
    }

    /// The source span from the start of `first` to the end of `last`.
    pub fn span(&self, first: &str, last: &str) -> Option<SrcRange> {
        let a = self.word(first)?;
        let b = self.word(last)?;
        SrcRange::new(a.start.min(b.start), a.end.max(b.end))
    }

    /// The words between two ids, inclusive.
    pub fn words_between(&self, first: &str, last: &str) -> &[Word] {
        match (self.index_of(first), self.index_of(last)) {
            (Some(a), Some(b)) if a <= b => &self.words[a..=b],
            _ => &[],
        }
    }

    /// Words whose span overlaps `range`.
    pub fn words_in(&self, range: &SrcRange) -> impl Iterator<Item = &Word> {
        let range = *range;
        self.words
            .iter()
            .filter(move |w| w.range().intersect(&range).is_some())
    }

    /// Text of the words between two ids.
    pub fn text_between(&self, first: &str, last: &str) -> String {
        self.words_between(first, last)
            .iter()
            .map(|w| w.text.as_str())
            .collect::<Vec<_>>()
            .join(" ")
    }
}

/// What an overlay is attached to. Content, never a clock position.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Anchor {
    /// A run of transcript words, first to last inclusive.
    Words {
        /// First word id.
        first: String,
        /// Last word id.
        last: String,
    },
    /// A span of the source with no words in it (e.g. a caption over music).
    Source {
        /// The span.
        range: SrcRange,
    },
}

impl Anchor {
    /// The source span the anchor covers, if its words exist.
    pub fn range(&self, transcript: &Transcript) -> Option<SrcRange> {
        match self {
            Anchor::Words { first, last } => transcript.span(first, last),
            Anchor::Source { range } => Some(*range),
        }
    }
}

/// How a caption looks.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct CaptionStyle {
    /// `#RRGGBB`.
    pub color: String,
    /// Font size in pixels at 1080p.
    pub size: u32,
    /// `bottom`, `top` or `center`.
    pub position: String,
    /// Bold or not.
    pub bold: bool,
}

impl Default for CaptionStyle {
    fn default() -> Self {
        Self {
            color: "#FFFFFF".into(),
            size: 48,
            position: "bottom".into(),
            bold: false,
        }
    }
}

/// A change to some of a caption's style; absent fields stay as they are.
#[derive(Clone, PartialEq, Eq, Debug, Default, Serialize, Deserialize, JsonSchema)]
pub struct StylePatch {
    /// New colour.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub color: Option<String>,
    /// New size.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size: Option<u32>,
    /// New position.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub position: Option<String>,
    /// New weight.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bold: Option<bool>,
}

impl CaptionStyle {
    /// Applies a patch.
    pub fn patch(&mut self, p: &StylePatch) {
        if let Some(c) = &p.color {
            self.color = c.clone();
        }
        if let Some(s) = p.size {
            self.size = s;
        }
        if let Some(pos) = &p.position {
            self.position = pos.clone();
        }
        if let Some(b) = p.bold {
            self.bold = b;
        }
    }
}
