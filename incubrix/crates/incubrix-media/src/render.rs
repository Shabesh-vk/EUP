//! Rendering: the timeline, and only the timeline, made into a video by one
//! ffmpeg run, then checked.
//!
//! - Every segment is cut from the source with `trim`/`atrim` at the same
//!   points, snapped to the source's frame grid, so picture and sound leave
//!   each cut together and cannot drift apart across many cuts.
//! - Speed: `setpts` for the picture, chained `atempo` for the sound.
//! - Mutes are `volume=0` over their playback spans; bleeps add a 1 kHz tone
//!   there. Music loops under the speech and is ducked by a sidechain
//!   compressor keyed on the speech.
//! - Captions are burned in from an ASS file at their projected times.
//! - Output is constant frame rate at the source's rate (a variable-rate
//!   source is resampled, with a warning) and is padded or trimmed to
//!   exactly the timeline's length.
//!
//! After the run, [`verify`] measures the file with ffprobe: length within
//! one frame of the timeline, audio and video starting within one frame of
//! each other, and the source's hash unchanged. A render that fails a check
//! is an error, never a quiet success.

use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

use incubrix_core::time::to_secs;
use incubrix_core::timeline::MarkKind;
use incubrix_core::{Project, SourceInfo, Timeline, Us};
use serde::Deserialize;

use crate::hash::sha256_file;
use crate::probe::{ffmpeg_bin, ffprobe_bin, parse_secs, probe};
use crate::MediaError;

/// How to encode.
#[derive(Clone, Debug)]
pub struct RenderOptions {
    /// x264 quality, lower is better.
    pub crf: u8,
    /// x264 speed preset.
    pub preset: String,
    /// Where the caption file is written; next to the output by default.
    pub work_dir: Option<PathBuf>,
}

impl Default for RenderOptions {
    fn default() -> Self {
        Self {
            crf: 20,
            preset: "veryfast".into(),
            work_dir: None,
        }
    }
}

/// What the checks measured.
#[derive(Clone, PartialEq, Debug)]
pub struct RenderCheck {
    /// The timeline's length.
    pub expected_us: Us,
    /// The rendered picture's length.
    pub video_us: Us,
    /// The rendered sound's length, if there is sound.
    pub audio_us: Option<Us>,
    /// One frame at the output rate.
    pub frame_us: Us,
    /// |picture length - timeline length|, in frames.
    pub length_diff_frames: f64,
    /// |picture start - sound start|, in frames.
    pub av_offset_frames: f64,
    /// |picture length - sound length|, in frames.
    pub av_length_diff_frames: f64,
    /// Every check passed.
    pub ok: bool,
    /// What failed, for the user.
    pub problems: Vec<String>,
}

/// What a render did.
#[derive(Clone, PartialEq, Debug)]
pub struct RenderReport {
    /// The file written.
    pub output: PathBuf,
    /// The measurements.
    pub check: RenderCheck,
    /// The source's hash, before and after.
    pub source_sha256: String,
    /// The source came out byte-for-byte as it went in.
    pub source_unchanged: bool,
    /// Captions drawn into the picture.
    pub burned_captions: usize,
    /// Things worth knowing.
    pub warnings: Vec<String>,
    /// Wall-clock seconds the render took.
    pub seconds: f64,
}

/// Seconds as ffmpeg reads them, to the microsecond.
fn s(us: Us) -> String {
    format!("{:.6}", to_secs(us))
}

/// A source time snapped to the nearest frame of the source.
fn to_frame(t: Us, fps: (u32, u32)) -> Us {
    let (num, den) = (fps.0.max(1) as i128, fps.1.max(1) as i128);
    let frames = (t as i128 * num + den * 500_000) / (den * 1_000_000);
    ((frames * den * 1_000_000 + num / 2) / num) as Us
}

/// `atempo` takes 0.5..=100 per stage: chain stages for the rest.
fn atempo(speed_milli: u32) -> String {
    let mut x = speed_milli as f64 / 1000.0;
    let mut out = Vec::new();
    while x < 0.5 {
        out.push("atempo=0.5".to_owned());
        x /= 0.5;
    }
    while x > 2.0 {
        out.push("atempo=2.0".to_owned());
        x /= 2.0;
    }
    if (x - 1.0).abs() > 1e-9 {
        out.push(format!("atempo={x:.6}"));
    }
    out.join(",")
}

/// `#RRGGBB` as ASS writes colours: `&HBBGGRR&`.
fn ass_colour(hex: &str) -> String {
    let h = hex.trim_start_matches('#');
    if h.len() != 6 {
        return "&HFFFFFF&".into();
    }
    format!("&H{}{}{}&", &h[4..6], &h[2..4], &h[0..2]).to_uppercase()
}

fn ass_time(us: Us) -> String {
    let cs = (us.max(0) + 5_000) / 10_000;
    format!(
        "{}:{:02}:{:02}.{:02}",
        cs / 360_000,
        cs / 6000 % 60,
        cs / 100 % 60,
        cs % 100
    )
}

/// The captions as an ASS script for a `width` x `height` picture.
pub fn ass_script(tl: &Timeline, width: u32, height: u32) -> (String, usize) {
    let (w, h) = (width.max(16), height.max(16));
    let mut out = format!(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nScaledBorderAndShadow: yes\nWrapStyle: 0\n\n\
         [V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n\
         Style: Default,Arial,{},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{},1,2,{},{},{},1\n\n\
         [Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n",
        h * 48 / 1080,
        (h / 360).max(1),
        w / 20,
        w / 20,
        h / 20
    );
    let mut n = 0;
    for c in &tl.captions {
        let align = match c.style.position.as_str() {
            "top" => 8,
            "center" => 5,
            _ => 2,
        };
        let size = (c.style.size as u64 * h as u64 / 1080).max(8);
        let text: String = c
            .text
            .chars()
            .filter(|ch| *ch != '{' && *ch != '}')
            .collect::<String>()
            .replace('\n', "\\N");
        for p in &c.playback {
            let _ = writeln!(
                out,
                "Dialogue: 0,{},{},Default,,0,0,0,,{{\\an{align}\\fs{size}\\c{}\\b{}}}{text}",
                ass_time(p.start),
                ass_time(p.end),
                ass_colour(&c.style.color),
                u8::from(c.style.bold)
            );
            n += 1;
        }
    }
    (out, n)
}

/// The filtergraph for `tl` cut from a source at `fps`. Captions, if any,
/// are read from `ass_file` (a name relative to ffmpeg's working folder).
fn filtergraph(
    tl: &Timeline,
    src: &SourceInfo,
    ass_file: Option<&str>,
    music_input: Option<usize>,
) -> String {
    let fps = (src.fps_num.max(1), src.fps_den.max(1));
    let frame = src.frame();
    let total = s(tl.duration);
    let mut g = String::new();
    let n = tl.segments.len();
    for (i, seg) in tl.segments.iter().enumerate() {
        let a = to_frame(seg.source.start, fps);
        let b = to_frame(seg.source.end, fps).max(a + frame);
        // A quarter frame early, so a frame exactly on the grid is never
        // lost to rounding.
        let (va, vb) = ((a - frame / 4).max(0), b - frame / 4);
        let speed = seg.speed as f64 / 1000.0;
        let _ = write!(
            g,
            "[0:v]trim=start={}:end={},setpts=(PTS-STARTPTS)/{speed:.6}[v{i}];",
            s(va),
            s(vb)
        );
        if src.has_audio {
            let tempo = atempo(seg.speed);
            let _ = write!(
                g,
                "[0:a]atrim=start={}:end={},asetpts=PTS-STARTPTS{}{}[a{i}];",
                s(a),
                s(b),
                if tempo.is_empty() { "" } else { "," },
                tempo
            );
        }
    }
    for i in 0..n {
        let _ = write!(g, "[v{i}]");
        if src.has_audio {
            let _ = write!(g, "[a{i}]");
        }
    }
    let _ = write!(g, "concat=n={n}:v=1:a={}", u8::from(src.has_audio));
    g.push_str(if src.has_audio { "[vc][ac];" } else { "[vc];" });

    // Picture: constant rate, exactly the timeline's length, captions on top.
    let _ = write!(
        g,
        "[vc]fps={}/{},tpad=stop_mode=clone:stop_duration=1,trim=duration={total},setpts=PTS-STARTPTS",
        fps.0, fps.1
    );
    if let Some(f) = ass_file {
        let _ = write!(g, ",ass={f}");
    }
    g.push_str("[vout]");

    if !src.has_audio {
        return g;
    }
    // Sound: 48 kHz stereo, mutes and bleeps over their playback spans.
    g.push_str(";[ac]aresample=48000,aformat=channel_layouts=stereo");
    let mut tone = Vec::new();
    for m in &tl.marks {
        for p in &m.playback {
            let _ = write!(
                g,
                ",volume=enable='between(t,{},{})':volume=0",
                s(p.start),
                s(p.end)
            );
            if m.kind == MarkKind::Bleep {
                tone.push(format!("between(t,{},{})", s(p.start), s(p.end)));
            }
        }
    }
    g.push_str("[sp0]");
    let mut speech = "sp0".to_owned();
    if !tone.is_empty() {
        let _ = write!(
            g,
            ";aevalsrc=exprs='0.25*sin(2*PI*1000*t)*({})':s=48000:c=stereo:d={total}[beep];[{speech}][beep]amix=inputs=2:duration=first:normalize=0[sp1]",
            tone.join("+")
        );
        speech = "sp1".into();
    }
    if let (Some(k), Some(m)) = (music_input, tl.music.first()) {
        // Ducking: the compressor listens to the speech and pulls the
        // music down while someone talks. Ratio from the asked depth.
        let ratio = (m.duck_db as f64 / 1.5).clamp(1.0, 20.0);
        let _ = write!(
            g,
            ";[{speech}]asplit=2[talk][key];[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={}dB,atrim=duration={total}[bed];[bed][key]sidechaincompress=threshold=0.02:ratio={ratio:.2}:attack=20:release=300[ducked];[talk][ducked]amix=inputs=2:duration=first:normalize=0[mixed]",
            m.volume_db
        );
        speech = "mixed".into();
    }
    let _ = write!(
        g,
        ";[{speech}]apad,atrim=duration={total},asetpts=PTS-STARTPTS[aout]"
    );
    g
}

/// Renders the project's current timeline to `out` (MP4, H.264 + AAC) and
/// checks the result. A failed check is an error.
pub fn render(
    project: &Project,
    out: &Path,
    opts: &RenderOptions,
) -> Result<RenderReport, MediaError> {
    let started = Instant::now();
    let src = &project.source;
    let input = Path::new(&src.path);
    let before = sha256_file(input)?;
    if !src.sha256.is_empty() && src.sha256 != before {
        return Err(MediaError::SourceChanged {
            expected: src.sha256.clone(),
            found: before,
        });
    }
    let probed = probe(input)?;
    let tl = project.timeline().timeline;
    let mut warnings = Vec::new();
    if src.variable_frame_rate || probed.source.variable_frame_rate {
        warnings.push(format!(
            "The source has a variable frame rate; the render is constant {}/{} fps.",
            src.fps_num, src.fps_den
        ));
    }

    let work = opts
        .work_dir
        .clone()
        .unwrap_or_else(|| out.parent().map(Path::to_path_buf).unwrap_or_default());
    std::fs::create_dir_all(&work)?;
    let stem = out
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "render".into());
    let (ass, burned) = ass_script(&tl, probed.width, probed.height);
    let ass_name = format!("{stem}.captions.ass");
    if burned > 0 {
        std::fs::write(work.join(&ass_name), ass)?;
    }

    let mut cmd = Command::new(ffmpeg_bin());
    // The caption file is named relative to here: Windows drive colons in a
    // filter argument would need escaping.
    cmd.current_dir(&work);
    cmd.args(["-v", "error", "-nostdin", "-y", "-i"])
        .arg(absolute(input));
    let mut music_input = None;
    if let Some(m) = tl.music.first() {
        let path = Path::new(&m.path);
        if !path.is_file() {
            return Err(MediaError::Io(format!(
                "the music file {} does not exist",
                m.path
            )));
        }
        cmd.args(["-stream_loop", "-1", "-i"]).arg(absolute(path));
        music_input = Some(1);
    }
    let graph = filtergraph(
        &tl,
        src,
        (burned > 0).then_some(ass_name.as_str()),
        music_input,
    );
    cmd.arg("-filter_complex").arg(&graph);
    cmd.args(["-map", "[vout]"]);
    if src.has_audio {
        cmd.args([
            "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        ]);
    }
    cmd.args([
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        &opts.preset,
        "-crf",
        &opts.crf.to_string(),
    ]);
    cmd.args(["-movflags", "+faststart"]).arg(absolute(out));
    let run = cmd.output().map_err(|e| {
        MediaError::Tool(format!("cannot run ffmpeg ({e}); install it or set FFMPEG"))
    })?;
    if !run.status.success() {
        let err = String::from_utf8_lossy(&run.stderr);
        let tail: String = err
            .lines()
            .rev()
            .take(6)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect::<Vec<_>>()
            .join(" | ");
        return Err(MediaError::Tool(format!("ffmpeg could not render: {tail}")));
    }

    let check = verify(out, tl.duration, (src.fps_num, src.fps_den), src.has_audio)?;
    let after = sha256_file(input)?;
    if after != before {
        return Err(MediaError::SourceChanged {
            expected: before,
            found: after,
        });
    }
    if !check.ok {
        return Err(MediaError::RenderMismatch(check.problems.join(" ")));
    }
    if !tl.music.is_empty() {
        warnings.push(
            "Music ducking uses a compressor keyed on the speech; the drop is approximate.".into(),
        );
    }
    Ok(RenderReport {
        output: out.to_path_buf(),
        check,
        source_sha256: before,
        source_unchanged: true,
        burned_captions: burned,
        warnings,
        seconds: started.elapsed().as_secs_f64(),
    })
}

fn absolute(p: &Path) -> PathBuf {
    std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf())
}

#[derive(Deserialize)]
struct Probed {
    #[serde(default)]
    streams: Vec<Stream>,
}

#[derive(Deserialize)]
struct Stream {
    codec_type: Option<String>,
    start_time: Option<String>,
    duration: Option<String>,
}

fn signed_secs(s: &str) -> Option<Us> {
    match s.trim().strip_prefix('-') {
        Some(rest) => parse_secs(rest).map(|v| -v),
        None => parse_secs(s),
    }
}

/// Measures a rendered file against the timeline it came from.
pub fn verify(
    output: &Path,
    expected: Us,
    fps: (u32, u32),
    has_audio: bool,
) -> Result<RenderCheck, MediaError> {
    let run = Command::new(ffprobe_bin())
        .args([
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,start_time,duration",
            "-of",
            "json",
        ])
        .arg(output)
        .output()
        .map_err(|e| MediaError::Tool(format!("cannot run ffprobe ({e})")))?;
    if !run.status.success() {
        return Err(MediaError::Tool(format!(
            "ffprobe could not read the render: {}",
            String::from_utf8_lossy(&run.stderr).trim()
        )));
    }
    let p: Probed = serde_json::from_slice(&run.stdout)
        .map_err(|e| MediaError::BadData(format!("ffprobe output: {e}")))?;
    let stream = |kind: &str| {
        p.streams
            .iter()
            .find(|s| s.codec_type.as_deref() == Some(kind))
    };
    let v = stream("video").ok_or(MediaError::NoVideo)?;
    let read = |s: &Stream| {
        (
            s.start_time.as_deref().and_then(signed_secs).unwrap_or(0),
            s.duration.as_deref().and_then(signed_secs).unwrap_or(0),
        )
    };
    let (v_start, v_len) = read(v);
    let a = stream("audio").map(read);
    let frame = SourceInfo {
        fps_num: fps.0,
        fps_den: fps.1,
        ..SourceInfo::with_duration(1)
    }
    .frame();
    let frames = |us: Us| us.abs() as f64 / frame as f64;

    let length_diff_frames = frames(v_len - expected);
    let (av_offset_frames, av_length_diff_frames) = match a {
        Some((a_start, a_len)) => (frames(v_start - a_start), frames(v_len - a_len)),
        None => (0.0, 0.0),
    };
    let mut problems = Vec::new();
    if length_diff_frames > 1.0 {
        problems.push(format!(
            "The render's length is {length_diff_frames:.2} frames off the timeline ({} s vs {} s).",
            s(v_len),
            s(expected)
        ));
    }
    if has_audio && a.is_none() {
        problems.push("The render has no sound, but the source does.".into());
    }
    if av_offset_frames > 1.0 {
        problems.push(format!(
            "Sound and picture start {av_offset_frames:.2} frames apart."
        ));
    }
    if av_length_diff_frames > 1.0 {
        problems.push(format!(
            "Sound and picture lengths differ by {av_length_diff_frames:.2} frames."
        ));
    }
    Ok(RenderCheck {
        expected_us: expected,
        video_us: v_len,
        audio_us: a.map(|(_, l)| l),
        frame_us: frame,
        length_diff_frames,
        av_offset_frames,
        av_length_diff_frames,
        ok: problems.is_empty(),
        problems,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frames_snap_to_the_source_grid() {
        let fps = (30000, 1001);
        assert_eq!(to_frame(0, fps), 0);
        assert_eq!(to_frame(1_001_000, fps), 1_001_000, "30 frames at 29.97");
        assert_eq!(to_frame(1_010_000, fps), 1_001_000);
    }

    #[test]
    fn atempo_chains_outside_its_range() {
        assert_eq!(atempo(1000), "");
        assert_eq!(atempo(2000), "atempo=2.000000");
        assert_eq!(atempo(4000), "atempo=2.0,atempo=2.000000");
        assert_eq!(atempo(250), "atempo=0.5,atempo=0.500000");
    }

    #[test]
    fn ass_colours_and_times() {
        assert_eq!(ass_colour("#FF0000"), "&H0000FF&");
        assert_eq!(ass_time(62_345_000), "0:01:02.35");
    }
}
