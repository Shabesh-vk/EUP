//! Speaker diarization with sherpa-onnx (Apache-2.0), in-process (feature
//! `sherpa`): pyannote segmentation, a speaker-embedding model, and fast
//! clustering. The models are files the caller points at.

use std::path::{Path, PathBuf};

use incubrix_core::SourceInfo;
use sherpa_onnx::{
    FastClusteringConfig, OfflineSpeakerDiarization, OfflineSpeakerDiarizationConfig,
    OfflineSpeakerSegmentationModelConfig, OfflineSpeakerSegmentationPyannoteModelConfig,
    SpeakerEmbeddingExtractorConfig,
};

use crate::audio::{decode_mono_16k, SAMPLE_RATE};
use crate::diarize::{Diarizer, SpeakerTurn};
use crate::MediaError;

/// sherpa-onnx offline diarization.
#[derive(Clone, Debug)]
pub struct SherpaOnnx {
    segmentation: PathBuf,
    embedding: PathBuf,
    /// Known number of speakers, or `None` to let clustering decide.
    speakers: Option<u32>,
}

impl SherpaOnnx {
    /// A diarizer from a pyannote segmentation model and an embedding model.
    pub fn new(
        segmentation: impl Into<PathBuf>,
        embedding: impl Into<PathBuf>,
        speakers: Option<u32>,
    ) -> Self {
        Self {
            segmentation: segmentation.into(),
            embedding: embedding.into(),
            speakers,
        }
    }
}

impl Diarizer for SherpaOnnx {
    fn id(&self) -> String {
        let stem = |p: &Path| {
            p.file_stem()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_default()
        };
        format!(
            "sherpa-{}-{}",
            stem(&self.segmentation),
            stem(&self.embedding)
        )
    }

    fn diarize(&self, media: &Path, _source: &SourceInfo) -> Result<Vec<SpeakerTurn>, MediaError> {
        let config = OfflineSpeakerDiarizationConfig {
            segmentation: OfflineSpeakerSegmentationModelConfig {
                pyannote: OfflineSpeakerSegmentationPyannoteModelConfig {
                    model: Some(self.segmentation.to_string_lossy().into_owned()),
                    ..Default::default()
                },
                ..Default::default()
            },
            embedding: SpeakerEmbeddingExtractorConfig {
                model: Some(self.embedding.to_string_lossy().into_owned()),
                ..Default::default()
            },
            clustering: FastClusteringConfig {
                num_clusters: self.speakers.map(|n| n as i32).unwrap_or(-1),
                ..Default::default()
            },
            ..Default::default()
        };
        let sd = OfflineSpeakerDiarization::create(&config).ok_or_else(|| {
            MediaError::Tool("sherpa-onnx: cannot load the diarization models".into())
        })?;
        if sd.sample_rate() != SAMPLE_RATE as i32 {
            return Err(MediaError::Tool(format!(
                "sherpa-onnx wants {} Hz audio",
                sd.sample_rate()
            )));
        }
        let audio = decode_mono_16k(media)?;
        let result = sd
            .process(&audio)
            .ok_or_else(|| MediaError::Tool("sherpa-onnx: diarization failed".into()))?;
        Ok(result
            .sort_by_start_time()
            .into_iter()
            .map(|s| SpeakerTurn {
                // Seconds as f32 from the C API, rounded to whole milliseconds.
                start: (s.start as f64 * 1000.0).round() as i64 * 1000,
                end: (s.end as f64 * 1000.0).round() as i64 * 1000,
                speaker: format!("spk{}", s.speaker),
            })
            .collect())
    }
}
