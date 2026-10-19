//! What the file is: length, exact frame rate, variable frame rate, sound.
//!
//! Read with `ffprobe -show_streams -show_format -of json`. Times come back
//! as decimal strings and are parsed straight to integer microseconds, so no
//! floating point enters the model. Only MP4 and MOV are accepted.

use std::path::Path;
use std::process::Command;

use incubrix_core::{SourceInfo, Us};
use serde::Deserialize;

use crate::hash::sha256_file;
use crate::MediaError;

/// File extensions intake accepts.
pub const EXTENSIONS: &[&str] = &["mp4", "mov", "m4v"];

/// The ffprobe binary: `$FFPROBE`, else `ffprobe` on the PATH.
pub fn ffprobe_bin() -> String {
    std::env::var("FFPROBE").unwrap_or_else(|_| "ffprobe".into())
}

/// The ffmpeg binary: `$FFMPEG`, else `ffmpeg` on the PATH.
pub fn ffmpeg_bin() -> String {
    std::env::var("FFMPEG").unwrap_or_else(|_| "ffmpeg".into())
}

/// What probing found, beyond [`SourceInfo`].
#[derive(Clone, PartialEq, Debug)]
pub struct Probe {
    /// The facts the engine keeps.
    pub source: SourceInfo,
    /// Picture size.
    pub width: u32,
    /// Picture size.
    pub height: u32,
    /// Things the user should know (no audio, variable frame rate).
    pub warnings: Vec<String>,
}

/// Probes `path` and hashes it. Rejects anything but MP4/MOV with video.
pub fn probe(path: &Path) -> Result<Probe, MediaError> {
    check_extension(path)?;
    if !path.is_file() {
        return Err(MediaError::Io(format!("{} does not exist", path.display())));
    }
    let out = Command::new(ffprobe_bin())
        .args([
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
        .map_err(|e| {
            MediaError::Tool(format!(
                "cannot run ffprobe ({e}); install ffmpeg or set FFPROBE"
            ))
        })?;
    if !out.status.success() {
        return Err(MediaError::Unsupported(format!(
            "ffprobe could not read {}: {}",
            path.display(),
            String::from_utf8_lossy(&out.stderr).trim()
        )));
    }
    let json = String::from_utf8_lossy(&out.stdout);
    let mut p = parse_probe(&json, &path.to_string_lossy())?;
    p.source.sha256 = sha256_file(path)?;
    Ok(p)
}

/// Fails unless the extension is one of [`EXTENSIONS`].
pub fn check_extension(path: &Path) -> Result<(), MediaError> {
    let ext = path
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if EXTENSIONS.contains(&ext.as_str()) {
        Ok(())
    } else {
        Err(MediaError::Unsupported(format!(
            "only MP4 and MOV are supported, not '{}'",
            if ext.is_empty() { "no extension" } else { &ext }
        )))
    }
}

#[derive(Deserialize)]
struct Json {
    #[serde(default)]
    streams: Vec<Stream>,
    format: Option<Format>,
}

#[derive(Deserialize)]
struct Stream {
    codec_type: Option<String>,
    r_frame_rate: Option<String>,
    avg_frame_rate: Option<String>,
    duration: Option<String>,
    width: Option<u32>,
    height: Option<u32>,
}

#[derive(Deserialize)]
struct Format {
    format_name: Option<String>,
    duration: Option<String>,
}

/// Turns ffprobe's JSON into a [`Probe`] (without the hash). Pure, so it is
/// tested on recorded output.
pub fn parse_probe(json: &str, path: &str) -> Result<Probe, MediaError> {
    let j: Json = serde_json::from_str(json)
        .map_err(|e| MediaError::BadData(format!("ffprobe output: {e}")))?;
    let format = j.format.as_ref();
    let name = format
        .and_then(|f| f.format_name.clone())
        .unwrap_or_default();
    if !name.split(',').any(|n| n == "mov" || n == "mp4") {
        return Err(MediaError::Unsupported(format!(
            "only MP4 and MOV are supported; this file is '{name}'"
        )));
    }
    let video = j
        .streams
        .iter()
        .find(|s| s.codec_type.as_deref() == Some("video"))
        .ok_or(MediaError::NoVideo)?;
    let has_audio = j
        .streams
        .iter()
        .any(|s| s.codec_type.as_deref() == Some("audio"));

    let duration = format
        .and_then(|f| f.duration.as_deref())
        .or(video.duration.as_deref())
        .and_then(parse_secs)
        .filter(|d| *d > 0)
        .ok_or_else(|| MediaError::BadData("the file has no duration".into()))?;

    let r = video.r_frame_rate.as_deref().and_then(parse_ratio);
    let avg = video.avg_frame_rate.as_deref().and_then(parse_ratio);
    let (fps_num, fps_den) = avg
        .or(r)
        .ok_or_else(|| MediaError::BadData("the video has no frame rate".into()))?;
    // ffprobe reports the container's base rate and the measured average;
    // when they disagree by more than 0.1 % the frames are not evenly spaced.
    let vfr = match (r, avg) {
        (Some((rn, rd)), Some((an, ad))) => {
            let a = rn as u128 * ad as u128;
            let b = an as u128 * rd as u128;
            a.abs_diff(b) * 1000 > a.max(b)
        }
        _ => false,
    };

    let mut warnings = Vec::new();
    if !has_audio {
        warnings.push(
            "The video has no sound: word-based edits (captions on words, fillers, silences) are unavailable; time-based edits still work."
                .into(),
        );
    }
    if vfr {
        warnings.push(format!(
            "Variable frame rate (phone video): edits use the average {fps_num}/{fps_den} fps and renders are made constant-rate."
        ));
    }
    Ok(Probe {
        source: SourceInfo {
            path: path.to_owned(),
            sha256: String::new(),
            duration,
            fps_num,
            fps_den,
            has_audio,
            variable_frame_rate: vfr,
        },
        width: video.width.unwrap_or(0),
        height: video.height.unwrap_or(0),
        warnings,
    })
}

/// `"30000/1001"` to a reduced fraction; `None` for `0/0` and junk.
pub fn parse_ratio(s: &str) -> Option<(u32, u32)> {
    let (n, d) = s.split_once('/').unwrap_or((s, "1"));
    let (n, d): (u64, u64) = (n.trim().parse().ok()?, d.trim().parse().ok()?);
    if n == 0 || d == 0 {
        return None;
    }
    let g = gcd(n, d);
    Some(((n / g) as u32, (d / g) as u32))
}

fn gcd(a: u64, b: u64) -> u64 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

/// A decimal seconds string (`"10.010000"`) to microseconds, exactly:
/// digits past the sixth decimal round half up.
pub fn parse_secs(s: &str) -> Option<Us> {
    let s = s.trim();
    let (int, frac) = s.split_once('.').unwrap_or((s, ""));
    if int.is_empty() && frac.is_empty() {
        return None;
    }
    if !int.chars().all(|c| c.is_ascii_digit()) || !frac.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let whole: Us = if int.is_empty() { 0 } else { int.parse().ok()? };
    let mut micros: Us = 0;
    for (i, c) in frac.chars().take(6).enumerate() {
        micros += (c as Us - '0' as Us) * 10i64.pow(5 - i as u32);
    }
    if frac.chars().nth(6).is_some_and(|c| c >= '5') {
        micros += 1;
    }
    Some(whole * 1_000_000 + micros)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decimal_seconds_are_exact() {
        assert_eq!(parse_secs("10.010000"), Some(10_010_000));
        assert_eq!(parse_secs("0.0000005"), Some(1));
        assert_eq!(parse_secs("240"), Some(240_000_000));
        assert_eq!(parse_secs("N/A"), None);
    }

    #[test]
    fn ratios_reduce() {
        assert_eq!(parse_ratio("60000/2002"), Some((30000, 1001)));
        assert_eq!(parse_ratio("25/1"), Some((25, 1)));
        assert_eq!(parse_ratio("0/0"), None);
    }
}
