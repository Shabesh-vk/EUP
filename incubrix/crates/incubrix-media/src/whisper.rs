//! Speech recognition with whisper.cpp, in-process (feature `whisper`).
//!
//! One word per segment (`max_len 1`, split on word), token timestamps on,
//! greedy decoding at temperature 0 so a rerun gives the same words. A
//! word's confidence is the mean probability of its text tokens.

use std::path::{Path, PathBuf};

use incubrix_core::SourceInfo;
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

use crate::audio::decode_mono_16k;
use crate::transcribe::{RawWord, Transcriber};
use crate::MediaError;

/// whisper.cpp with a ggml model file.
#[derive(Clone, Debug)]
pub struct WhisperRs {
    model: PathBuf,
    language: Option<String>,
}

impl WhisperRs {
    /// A recogniser using the ggml model at `model`; `language` like `"en"`,
    /// or `None` to detect it.
    pub fn new(model: impl Into<PathBuf>, language: Option<String>) -> Self {
        Self {
            model: model.into(),
            language,
        }
    }
}

impl Transcriber for WhisperRs {
    fn id(&self) -> String {
        let name = self
            .model
            .file_stem()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        format!("whisper-{name}")
    }

    fn transcribe(&self, media: &Path, _source: &SourceInfo) -> Result<Vec<RawWord>, MediaError> {
        let audio = decode_mono_16k(media)?;
        let fail = |e: whisper_rs::WhisperError| MediaError::Tool(format!("whisper: {e}"));
        let ctx = WhisperContext::new_with_params(&self.model, WhisperContextParameters::default())
            .map_err(fail)?;
        let mut state = ctx.create_state().map_err(fail)?;
        let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
        params.set_language(self.language.as_deref());
        params.set_token_timestamps(true);
        params.set_max_len(1);
        params.set_split_on_word(true);
        params.set_temperature(0.0);
        params.set_temperature_inc(0.0);
        params.set_print_progress(false);
        params.set_print_realtime(false);
        params.set_print_special(false);
        params.set_print_timestamps(false);
        state.full(params, &audio).map_err(fail)?;

        let mut words = Vec::new();
        for i in 0..state.full_n_segments() {
            let Some(seg) = state.get_segment(i) else {
                continue;
            };
            let text = seg.to_str_lossy().map_err(fail)?.into_owned();
            let mut probs = Vec::new();
            for k in 0..seg.n_tokens() {
                if let Some(tok) = seg.get_token(k) {
                    let s = tok
                        .to_str_lossy()
                        .map(|s| s.into_owned())
                        .unwrap_or_default();
                    if !s.starts_with("[_") && !s.starts_with("<|") {
                        probs.push(tok.token_probability());
                    }
                }
            }
            let confidence = if probs.is_empty() {
                0.0
            } else {
                probs.iter().sum::<f32>() / probs.len() as f32
            };
            // Segment times are centiseconds.
            words.push(RawWord {
                text,
                start: seg.start_timestamp() * 10_000,
                end: seg.end_timestamp() * 10_000,
                confidence,
            });
        }
        Ok(words)
    }
}
