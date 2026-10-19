//! Transcripts cached by source hash. Transcription is the slowest step and
//! its output is fixed for a given file and recogniser, so it runs once.

use std::path::{Path, PathBuf};

use incubrix_core::Transcript;
use serde::{Deserialize, Serialize};

use crate::MediaError;

/// What is stored per source.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize)]
pub struct CachedTranscript {
    /// The cleaned, speaker-labelled transcript.
    pub transcript: Transcript,
    /// The warnings produced with it.
    pub warnings: Vec<String>,
}

/// A directory of `<sha256>-<recogniser>.json` files.
#[derive(Clone, Debug)]
pub struct TranscriptCache {
    dir: PathBuf,
}

impl TranscriptCache {
    /// A cache in `dir` (created on first write).
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        Self { dir: dir.into() }
    }

    /// Where the entry for this source and recogniser lives.
    pub fn path(&self, sha256: &str, key: &str) -> PathBuf {
        let key: String = key
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '-' {
                    c
                } else {
                    '_'
                }
            })
            .collect();
        self.dir.join(format!("{sha256}-{key}.json"))
    }

    /// The cached transcript, if there is one.
    pub fn get(&self, sha256: &str, key: &str) -> Option<CachedTranscript> {
        let text = std::fs::read_to_string(self.path(sha256, key)).ok()?;
        serde_json::from_str(&text).ok()
    }

    /// Stores a transcript.
    pub fn put(&self, sha256: &str, key: &str, entry: &CachedTranscript) -> Result<(), MediaError> {
        std::fs::create_dir_all(&self.dir)?;
        let json =
            serde_json::to_string_pretty(entry).map_err(|e| MediaError::BadData(e.to_string()))?;
        write_atomic(&self.path(sha256, key), json.as_bytes())
    }
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), MediaError> {
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(&tmp, path)?;
    Ok(())
}
