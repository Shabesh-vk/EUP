//! IncuBrix intake: everything between a video file and a [`Project`].
//!
//! - [`probe`]: duration, exact frame rate, variable frame rate, audio (ffprobe).
//! - [`hash`]: the source SHA-256, taken at intake and checked after renders.
//! - [`transcribe`]: the [`Transcriber`] trait, recogniser output cleanup,
//!   and the fixture adapter (whisper.cpp behind the `whisper` feature).
//! - [`diarize`]: the [`Diarizer`] trait, speaker assignment and its
//!   warnings (sherpa-onnx behind the `sherpa` feature).
//! - [`cache`]: transcripts cached by source hash.
//! - [`intake()`]: all of the above in one call.
//!
//! Nothing here edits; the result is handed to `incubrix-core` untouched.
//! Licence: MIT OR Apache-2.0. Never depends on Concat's `concat-*` crates.
//!
//! [`Project`]: incubrix_core::Project

pub mod audio;
pub mod cache;
pub mod diarize;
pub mod hash;
pub mod intake;
pub mod probe;
pub mod transcribe;

#[cfg(feature = "sherpa")]
pub mod sherpa;
#[cfg(feature = "whisper")]
pub mod whisper;

pub use cache::TranscriptCache;
pub use diarize::{assign_speakers, Diarizer, FixtureDiarizer, SpeakerTurn};
pub use intake::{intake, Intake};
pub use probe::probe;
pub use transcribe::{FixtureTranscriber, RawWord, Transcriber};

/// Why intake failed. The text is written for the user.
#[derive(Debug, thiserror::Error)]
pub enum MediaError {
    /// Not an MP4 or MOV.
    #[error("{0}")]
    Unsupported(String),
    /// The file has no picture.
    #[error("the file has no video stream")]
    NoVideo,
    /// ffprobe or ffmpeg failed or is missing.
    #[error("{0}")]
    Tool(String),
    /// Reading or writing a file failed.
    #[error("{0}")]
    Io(String),
    /// A recogniser, diarizer or fixture produced something unusable.
    #[error("{0}")]
    BadData(String),
    /// The original changed since intake.
    #[error("the source file changed: expected {expected}, found {found}")]
    SourceChanged {
        /// Hash recorded at intake.
        expected: String,
        /// Hash now.
        found: String,
    },
}

impl MediaError {
    /// The UPPER_SNAKE_CASE code the API returns.
    pub fn code(&self) -> &'static str {
        match self {
            MediaError::Unsupported(_) => "UNSUPPORTED_FORMAT",
            MediaError::NoVideo => "NO_VIDEO_STREAM",
            MediaError::Tool(_) => "MEDIA_TOOL_FAILED",
            MediaError::Io(_) => "IO_ERROR",
            MediaError::BadData(_) => "BAD_MEDIA_DATA",
            MediaError::SourceChanged { .. } => "SOURCE_CHANGED",
        }
    }
}

impl From<std::io::Error> for MediaError {
    fn from(e: std::io::Error) -> Self {
        MediaError::Io(e.to_string())
    }
}
