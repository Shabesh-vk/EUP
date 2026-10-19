//! The brief's 8-step worked example, at the core level (instructions are
//! given as resolved operations; the language layer comes later).

mod common;

use incubrix_core::resolve::{cut_playback, speed_playback, words_anchor};
use incubrix_core::search::{find_phrase, playing};
use incubrix_core::{secs, CaptionStyle, CutReason, Op, Project, SrcRange, StylePatch};

fn caption_at(p: &Project) -> (f64, f64) {
    let tl = p.timeline().timeline;
    let c = &tl.captions[0];
    assert_eq!(c.playback.len(), 1, "caption should be on one span");
    (
        c.playback[0].start as f64 / 1e6,
        c.playback[0].end as f64 / 1e6,
    )
}

fn duration(p: &Project) -> f64 {
    p.timeline().timeline.duration as f64 / 1e6
}

/// Runs the example and returns the hash after every step.
fn run() -> Vec<String> {
    let mut p = common::worked_example();
    let mut hashes = vec![];

    // 1. Add a caption 'Welcome!' when I say welcome to the channel
    let tl = p.timeline().timeline;
    let hits = find_phrase(&p.transcript, &tl, "welcome to the channel");
    assert_eq!(hits.len(), 1);
    let anchor = words_anchor(&p.transcript, hits[0].first, hits[0].last);
    let id = p.next_id("cap");
    let r = p
        .apply(
            "Add a caption 'Welcome!' when I say welcome to the channel",
            vec![Op::AddCaption {
                id,
                anchor,
                text: "Welcome!".into(),
                style: CaptionStyle::default(),
            }],
        )
        .unwrap();
    assert_eq!(r.tx, Some(1));
    assert_eq!(caption_at(&p), (42.0, 44.0));
    hashes.push(r.timeline_hash);

    // 2. Cut the first 30 seconds
    let tl = p.timeline().timeline;
    let r = p
        .apply(
            "Cut the first 30 seconds",
            vec![cut_playback(&tl, 0, secs(30.0)).unwrap()],
        )
        .unwrap();
    assert_eq!(duration(&p), 210.0);
    assert_eq!(caption_at(&p), (12.0, 14.0), "caption stays on its words");
    hashes.push(r.timeline_hash);

    // 3. Remove the part about pricing -> three matches, the user picks the second.
    let tl = p.timeline().timeline;
    let hits = playing(find_phrase(&p.transcript, &tl, "pricing"));
    assert_eq!(hits.len(), 3, "pricing is mentioned three times: ask");
    let second = &hits[1];
    // "the part about" = the sentence around it; here the phrase's words.
    let first_w = &p.transcript.words[second.first - 1];
    let range = SrcRange::new(first_w.start, p.transcript.words[second.last + 1].end).unwrap();
    let r = p
        .apply(
            "Remove the part about pricing (the second one)",
            vec![Op::Cut {
                ranges: vec![range],
                reason: CutReason::User,
            }],
        )
        .unwrap();
    assert_eq!(duration(&p), 208.5);
    hashes.push(r.timeline_hash);

    // 4. Speed up from 1:00 to 1:30 by 2x (current time)
    let tl = p.timeline().timeline;
    let ops = speed_playback(&tl, secs(60.0), secs(90.0), 2000).unwrap();
    let r = p.apply("Speed up from 1:00 to 1:30 by 2x", ops).unwrap();
    assert_eq!(duration(&p), 193.5);
    hashes.push(r.timeline_hash);

    // 5. Actually, put the intro back -> restore edit #2 only.
    let r = p
        .apply("Actually, put the intro back", vec![Op::Restore { tx: 2 }])
        .unwrap();
    assert_eq!(
        duration(&p),
        223.5,
        "intro returns; pricing cut and speed change stay"
    );
    assert_eq!(caption_at(&p), (42.0, 44.0));
    hashes.push(r.timeline_hash);

    // 6. Undo -> reverses step 5 only.
    let undone = p.undo().unwrap().id;
    assert_eq!(undone, 5);
    assert_eq!(duration(&p), 193.5);
    assert_eq!(caption_at(&p), (12.0, 14.0));
    hashes.push(p.hash());

    // 7. Make that caption red -> the only caption.
    let tl = p.timeline().timeline;
    assert_eq!(tl.captions.len(), 1);
    let cid = tl.captions[0].id.clone();
    let r = p
        .apply(
            "Make that caption red",
            vec![Op::StyleCaption {
                id: cid,
                patch: StylePatch {
                    color: Some("#FF0000".into()),
                    ..Default::default()
                },
            }],
        )
        .unwrap();
    assert_eq!(p.timeline().timeline.captions[0].style.color, "#FF0000");
    assert!(p.redoable().is_empty(), "a new edit clears redo");
    hashes.push(r.timeline_hash);

    hashes
}

#[test]
fn worked_example_runs_as_the_brief_describes() {
    run();
}

#[test]
fn worked_example_is_deterministic_over_three_runs() {
    let a = run();
    assert_eq!(a, run());
    assert_eq!(a, run());
}
