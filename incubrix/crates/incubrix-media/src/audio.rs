//! Decoding the sound track for the recognisers: 16 kHz mono 32-bit float,
//! piped out of ffmpeg. Only the `whisper` and `sherpa` adapters use it.

use std::path::Path;
use std::process::Command;

use crate::probe::ffmpeg_bin;
use crate::MediaError;

/// Sample rate the recognisers expect.
pub const SAMPLE_RATE: u32 = 16_000;

/// The file's sound as 16 kHz mono samples.
pub fn decode_mono_16k(path: &Path) -> Result<Vec<f32>, MediaError> {
    let out = Command::new(ffmpeg_bin())
        .args(["-v", "error", "-nostdin", "-i"])
        .arg(path)
        .args(["-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"])
        .output()
        .map_err(|e| {
            MediaError::Tool(format!("cannot run ffmpeg ({e}); install it or set FFMPEG"))
        })?;
    if !out.status.success() {
        return Err(MediaError::Tool(format!(
            "ffmpeg could not decode the sound: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        )));
    }
    Ok(out
        .stdout
        .as_chunks::<4>()
        .0
        .iter()
        .map(|b| f32::from_le_bytes(*b))
        .collect())
}
