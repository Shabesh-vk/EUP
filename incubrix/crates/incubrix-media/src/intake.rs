//! A video file in, a ready-to-edit project out.

use std::path::Path;

use incubrix_core::{Project, SourceInfo, Transcript};

use crate::cache::{CachedTranscript, TranscriptCache};
use crate::diarize::{assign_speakers, Diarizer};
use crate::probe::probe;
use crate::transcribe::{clean_words, Transcriber};
use crate::MediaError;

/// The result of intake.
#[derive(Clone, PartialEq, Debug)]
pub struct Intake {
    /// The original's facts, hash included.
    pub source: SourceInfo,
    /// Every word with timing, speaker and confidence.
    pub transcript: Transcript,
    /// Everything the user should know about the file and the transcript.
    pub warnings: Vec<String>,
    /// Whether the transcript came from the cache.
    pub cached: bool,
}

impl Intake {
    /// A project with no edits on this source.
    pub fn into_project(self) -> Project {
        Project::new(self.source, self.transcript)
    }
}

/// Probes and hashes `path`, then transcribes and diarizes it (or reads
/// both from `cache`). Without a diarizer every word is speaker `S1`.
pub fn intake(
    path: &Path,
    transcriber: &dyn Transcriber,
    diarizer: Option<&dyn Diarizer>,
    cache: Option<&TranscriptCache>,
) -> Result<Intake, MediaError> {
    let probed = probe(path)?;
    let source = probed.source;
    let mut warnings = probed.warnings;
    if !source.has_audio {
        return Ok(Intake {
            source,
            transcript: Transcript::default(),
            warnings,
            cached: false,
        });
    }

    let key = match diarizer {
        Some(d) => format!("{}+{}", transcriber.id(), d.id()),
        None => transcriber.id(),
    };
    if let Some(hit) = cache.and_then(|c| c.get(&source.sha256, &key)) {
        warnings.extend(hit.warnings);
        return Ok(Intake {
            source,
            transcript: hit.transcript,
            warnings,
            cached: true,
        });
    }

    let (transcript, found) = transcribe_and_label(path, &source, transcriber, diarizer)?;
    if let Some(c) = cache {
        c.put(
            &source.sha256,
            &key,
            &CachedTranscript {
                transcript: transcript.clone(),
                warnings: found.clone(),
            },
        )?;
    }
    warnings.extend(found);
    Ok(Intake {
        source,
        transcript,
        warnings,
        cached: false,
    })
}

/// Transcription, cleanup and speaker labels, without probing: the part
/// the fixture tests check byte for byte.
pub fn transcribe_and_label(
    path: &Path,
    source: &SourceInfo,
    transcriber: &dyn Transcriber,
    diarizer: Option<&dyn Diarizer>,
) -> Result<(Transcript, Vec<String>), MediaError> {
    let raw = transcriber.transcribe(path, source)?;
    let (mut transcript, mut warnings) = clean_words(raw, source.duration);
    if transcript.words.is_empty() {
        warnings.push("No speech was recognised: word-based edits are unavailable.".into());
    }
    match diarizer {
        Some(d) => {
            let turns = d.diarize(path, source)?;
            warnings.extend(assign_speakers(&mut transcript, &turns));
        }
        None => {
            for w in &mut transcript.words {
                w.speaker = "S1".into();
            }
        }
    }
    Ok((transcript, warnings))
}
