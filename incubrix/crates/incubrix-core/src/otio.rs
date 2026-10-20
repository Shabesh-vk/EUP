//! OpenTimelineIO export: the edited timeline as an `.otio` file other
//! editors (DaVinci Resolve, Premiere via plugins, OTIO tools) can open.
//!
//! One video and one audio track, a clip per segment pointing at the
//! untouched source, a `LinearTimeWarp` effect where the speed is not 1x,
//! and markers for captions, mutes and bleeps at their playback times.
//! Times are frames at the source's rate. Written directly as JSON: the
//! schema is small and stable (`Timeline.1`, `Stack.1`, `Track.1`,
//! `Clip.2`, `ExternalReference.1`, `Marker.2`).

use serde_json::{json, Value};

use crate::history::Project;
use crate::time::Us;
use crate::timeline::{MarkKind, Timeline};

fn rate(p: &Project) -> f64 {
    p.source.fps_num.max(1) as f64 / p.source.fps_den.max(1) as f64
}

fn rt(us: Us, rate: f64) -> Value {
    json!({"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": us as f64 * rate / 1_000_000.0})
}

fn range(start: Us, len: Us, rate: f64) -> Value {
    json!({"OTIO_SCHEMA": "TimeRange.1", "start_time": rt(start, rate), "duration": rt(len, rate)})
}

/// `N:\clips\a b.mp4` -> `file:///N:/clips/a%20b.mp4`.
fn file_url(path: &str) -> String {
    let p = path.replace('\\', "/").replace(' ', "%20");
    if p.starts_with('/') {
        format!("file://{p}")
    } else {
        format!("file:///{p}")
    }
}

fn track(name: &str, kind: &str, p: &Project, tl: &Timeline, markers: Vec<Value>) -> Value {
    let r = rate(p);
    let media = json!({
        "OTIO_SCHEMA": "ExternalReference.1",
        "name": name,
        "target_url": file_url(&p.source.path),
        "available_range": range(0, p.source.duration, r),
        "metadata": {},
    });
    let clips: Vec<Value> = tl
        .segments
        .iter()
        .enumerate()
        .map(|(i, s)| {
            let effects = if s.speed == 1000 {
                vec![]
            } else {
                vec![json!({
                    "OTIO_SCHEMA": "LinearTimeWarp.1",
                    "name": "speed",
                    "effect_name": "LinearTimeWarp",
                    "time_scalar": s.speed as f64 / 1000.0,
                    "metadata": {},
                })]
            };
            json!({
                "OTIO_SCHEMA": "Clip.2",
                "name": format!("segment {}", i + 1),
                // The source span; with a time warp it plays shorter or longer.
                "source_range": range(s.source.start, s.playback_len(), r),
                "media_references": {"DEFAULT_MEDIA": media},
                "active_media_reference_key": "DEFAULT_MEDIA",
                "effects": effects,
                "markers": [],
                "enabled": true,
                "metadata": {"incubrix": {"source_end_us": s.source.end, "speed_milli": s.speed}},
            })
        })
        .collect();
    json!({
        "OTIO_SCHEMA": "Track.1",
        "name": name,
        "kind": kind,
        "children": clips,
        "source_range": null,
        "effects": [],
        "markers": markers,
        "enabled": true,
        "metadata": {},
    })
}

/// The project's current timeline as an OTIO document.
pub fn to_otio(p: &Project, name: &str) -> Value {
    let tl = p.timeline().timeline;
    let r = rate(p);
    let mut markers = Vec::new();
    for c in &tl.captions {
        for pb in &c.playback {
            markers.push(json!({
                "OTIO_SCHEMA": "Marker.2",
                "name": c.text,
                "marked_range": range(pb.start, pb.len(), r),
                "color": "YELLOW",
                "comment": format!("caption {}", c.id),
                "metadata": {"incubrix": {"caption": c.id, "style": c.style}},
            }));
        }
    }
    for m in &tl.marks {
        for pb in &m.playback {
            let (what, colour) = match m.kind {
                MarkKind::Mute => ("mute", "BLUE"),
                MarkKind::Bleep => ("bleep", "RED"),
            };
            markers.push(json!({
                "OTIO_SCHEMA": "Marker.2",
                "name": what,
                "marked_range": range(pb.start, pb.len(), r),
                "color": colour,
                "comment": m.id,
                "metadata": {},
            }));
        }
    }
    json!({
        "OTIO_SCHEMA": "Timeline.1",
        "name": name,
        "global_start_time": null,
        "metadata": {"incubrix": {"timeline_hash": crate::hash::timeline_hash(&tl), "time_policy": crate::resolve::TIME_POLICY}},
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [
                track("Video", "Video", p, &tl, markers),
                track("Audio", "Audio", p, &tl, vec![]),
            ],
            "source_range": null,
            "effects": [],
            "markers": [],
            "enabled": true,
            "metadata": {},
        },
    })
}
