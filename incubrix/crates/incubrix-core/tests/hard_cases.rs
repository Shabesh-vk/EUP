//! The brief's hard cases and the Advanced-level conflict rules, at the core level.

mod common;

use incubrix_core::detect::{fillers, silences};
use incubrix_core::resolve::{cut_playback, playback_span, speed_playback, words_anchor};
use incubrix_core::search::find_phrase;
use incubrix_core::{
    secs, Anchor, CaptionStyle, CutReason, EditError, Op, Project, SourceInfo, SrcRange,
};

fn project(phrases: &[(f64, &str)]) -> Project {
    Project::new(
        SourceInfo::with_duration(secs(120.0)),
        common::transcript(120.0, phrases),
    )
}

fn caption(p: &mut Project, phrase: &str, text: &str) -> String {
    let tl = p.timeline().timeline;
    let h = &find_phrase(&p.transcript, &tl, phrase)[0];
    let anchor = words_anchor(&p.transcript, h.first, h.last);
    let id = p.next_id("cap");
    p.apply(
        "caption",
        vec![Op::AddCaption {
            id: id.clone(),
            anchor,
            text: text.into(),
            style: CaptionStyle::default(),
        }],
    )
    .unwrap();
    id
}

fn cut_src(a: f64, b: f64) -> Op {
    Op::Cut {
        ranges: vec![SrcRange::new(secs(a), secs(b)).unwrap()],
        reason: CutReason::User,
    }
}

#[test]
fn caption_hidden_when_its_sentence_is_cut_and_back_when_restored() {
    let mut p = project(&[(20.0, "this is the key sentence")]);
    caption(&mut p, "this is the key sentence", "Key");
    let r = p
        .apply("cut the sentence", vec![cut_src(20.0, 22.5)])
        .unwrap();
    assert!(p.timeline().timeline.captions[0].playback.is_empty());
    assert!(
        r.warnings.iter().any(|w| w.contains("hidden")),
        "the user is told: {:?}",
        r.warnings
    );
    p.apply("put it back", vec![Op::Restore { tx: r.tx.unwrap() }])
        .unwrap();
    let c = &p.timeline().timeline.captions[0];
    assert_eq!(
        (c.playback[0].start, c.playback[0].end),
        (secs(20.0), secs(22.5))
    );
}

#[test]
fn partial_cut_keeps_the_caption_on_the_remaining_words() {
    let mut p = project(&[(20.0, "this is the key sentence")]);
    caption(&mut p, "this is the key sentence", "Key");
    let r = p.apply("cut half", vec![cut_src(21.0, 22.5)]).unwrap();
    assert!(r.warnings.iter().any(|w| w.contains("partly")));
    let c = &p.timeline().timeline.captions[0];
    assert_eq!(
        (c.playback[0].start, c.playback[0].end),
        (secs(20.0), secs(21.0))
    );
}

#[test]
fn sped_up_caption_keeps_a_readable_minimum() {
    let mut p = project(&[(30.0, "hi")]);
    caption(&mut p, "hi", "Hi");
    p.apply(
        "4x",
        vec![Op::Speed {
            range: SrcRange::new(secs(25.0), secs(40.0)).unwrap(),
            speed: 4000,
        }],
    )
    .unwrap();
    let c = &p.timeline().timeline.captions[0];
    assert!(
        c.playback[0].len() >= 700_000,
        "0.5 s word at 4x would be 0.125 s"
    );
}

#[test]
fn reorder_then_mute_inside_it_follows_the_words() {
    let mut p = project(&[(60.0, "secret word here")]);
    // Move 0:50-1:10 to the start.
    p.apply(
        "move",
        vec![Op::Reorder {
            range: SrcRange::new(secs(50.0), secs(70.0)).unwrap(),
            before: Some(0),
        }],
    )
    .unwrap();
    let tl = p.timeline().timeline;
    let h = &find_phrase(&p.transcript, &tl, "secret")[0];
    assert_eq!(h.playback_start, Some(secs(10.0)));
    let anchor = words_anchor(&p.transcript, h.first, h.first);
    p.apply(
        "mute",
        vec![Op::Mute {
            id: "mute_1".into(),
            anchor,
        }],
    )
    .unwrap();
    let m = &p.timeline().timeline.marks[0];
    assert_eq!(m.playback[0].start, secs(10.0));
}

#[test]
fn same_cut_twice_is_safe() {
    let mut p = project(&[]);
    let first = p
        .apply("Remove 0:30-0:40", vec![cut_src(30.0, 40.0)])
        .unwrap();
    assert!(first.tx.is_some());
    let again = p
        .apply("Remove 0:30-0:40", vec![cut_src(30.0, 40.0)])
        .unwrap();
    assert_eq!(again.tx, None, "nothing changed, nothing to undo");
    assert_eq!(p.active().len(), 1);
}

#[test]
fn caption_past_the_end_is_rejected() {
    let p = project(&[]);
    let tl = p.timeline().timeline;
    assert!(matches!(
        playback_span(&tl, secs(300.0), secs(302.0)),
        Err(EditError::OutOfRange(_))
    ));
}

#[test]
fn cutting_everything_is_rejected_and_changes_nothing() {
    let mut p = project(&[]);
    let before = p.hash();
    let tl = p.timeline().timeline;
    let err = p
        .apply(
            "cut everything",
            vec![cut_playback(&tl, 0, tl.duration).unwrap()],
        )
        .unwrap_err();
    assert_eq!(err, EditError::EmptyTimeline);
    assert_eq!(p.hash(), before);
}

#[test]
fn speed_10x_is_rejected() {
    let mut p = project(&[]);
    let tl = p.timeline().timeline;
    let ops = speed_playback(&tl, 0, secs(10.0), 10_000).unwrap();
    assert_eq!(
        p.apply("Speed up 10x", ops).unwrap_err(),
        EditError::BadSpeed(10_000)
    );
}

#[test]
fn multi_part_instruction_is_all_or_nothing() {
    let mut p = project(&[]);
    let before = p.hash();
    let ops = vec![
        cut_src(10.0, 20.0),
        Op::Speed {
            range: SrcRange::new(secs(30.0), secs(40.0)).unwrap(),
            speed: 10_000,
        },
    ];
    assert!(p.apply("cut 10-20 and speed 30-40 by 10x", ops).is_err());
    assert_eq!(p.hash(), before, "no part applied");
}

#[test]
fn overlapping_speed_changes_latest_wins() {
    let mut p = project(&[]);
    p.apply(
        "2x",
        vec![Op::Speed {
            range: SrcRange::new(secs(0.0), secs(20.0)).unwrap(),
            speed: 2000,
        }],
    )
    .unwrap();
    p.apply(
        "1.5x",
        vec![Op::Speed {
            range: SrcRange::new(secs(10.0), secs(30.0)).unwrap(),
            speed: 1500,
        }],
    )
    .unwrap();
    let tl = p.timeline().timeline;
    // 0-10 at 2x = 5 s, 10-30 at 1.5x = 13.333 s, 30-120 = 90 s.
    assert_eq!(tl.duration, secs(5.0) + 13_333_333 + secs(90.0));
}

#[test]
fn undo_redo_and_new_edit_clears_redo() {
    let mut p = project(&[]);
    p.apply("a", vec![cut_src(0.0, 10.0)]).unwrap();
    p.apply("b", vec![cut_src(20.0, 30.0)]).unwrap();
    p.undo();
    assert_eq!(p.redoable().len(), 1);
    p.redo();
    assert_eq!(p.timeline().timeline.duration, secs(100.0));
    p.undo();
    p.apply("c", vec![cut_src(50.0, 55.0)]).unwrap();
    assert!(p.redoable().is_empty());
}

#[test]
fn restore_second_to_last_cut_keeps_music() {
    let mut p = project(&[]);
    p.apply("cut a", vec![cut_src(10.0, 20.0)]).unwrap();
    p.apply(
        "music",
        vec![Op::AddMusic {
            id: "music_1".into(),
            path: "bed.mp3".into(),
            volume_db: -18,
            duck_db: 12,
        }],
    )
    .unwrap();
    p.apply("cut b", vec![cut_src(40.0, 50.0)]).unwrap();
    p.apply(
        "Undo the second-to-last cut but keep the music",
        vec![Op::Restore { tx: 1 }],
    )
    .unwrap();
    let tl = p.timeline().timeline;
    assert_eq!(tl.duration, secs(110.0));
    assert_eq!(tl.music.len(), 1);
}

#[test]
fn restore_rules() {
    let mut p = project(&[]);
    let r = p.apply("a", vec![cut_src(0.0, 10.0)]).unwrap();
    assert_eq!(
        p.apply("x", vec![Op::Restore { tx: 99 }]).unwrap_err(),
        EditError::UnknownTx(99)
    );
    let rr = p
        .apply("restore", vec![Op::Restore { tx: r.tx.unwrap() }])
        .unwrap();
    assert!(p
        .apply("again", vec![Op::Restore { tx: r.tx.unwrap() }])
        .is_err());
    assert!(p
        .apply(
            "restore the restore",
            vec![Op::Restore { tx: rr.tx.unwrap() }]
        )
        .is_err());
}

#[test]
fn caption_on_cut_words_is_rejected_naming_the_edit() {
    let mut p = project(&[(20.0, "gone words")]);
    p.apply("cut", vec![cut_src(19.0, 22.0)]).unwrap();
    let anchor = Anchor::Words {
        first: "w00040".into(),
        last: "w00041".into(),
    };
    let err = p
        .apply(
            "caption",
            vec![Op::AddCaption {
                id: "cap_1".into(),
                anchor,
                text: "x".into(),
                style: CaptionStyle::default(),
            }],
        )
        .unwrap_err();
    assert!(err.to_string().contains("edit #1"), "{err}");
}

#[test]
fn filler_removal_skips_bleeped_and_handles_like() {
    let mut t = common::transcript(
        20.0,
        &[(2.0, "um so"), (5.0, "uh damn it"), (10.0, "I like pizza")],
    );
    // A standalone "like" with pauses round it: shift neighbours away.
    t.words.push(incubrix_core::Word {
        id: "w99999".into(),
        text: "like".into(),
        start: secs(19.6),
        end: secs(19.8),
        speaker: "S1".into(),
        confidence: 0.9,
    });
    t.words
        .retain(|w| !(w.start >= secs(19.0) && w.id != "w99999"));
    let mut p = Project::new(SourceInfo::with_duration(secs(20.0)), t);
    // Bleep "uh damn" (the filler sits inside the bleep).
    p.apply(
        "bleep",
        vec![Op::Bleep {
            id: "bleep_1".into(),
            anchor: Anchor::Words {
                first: "w00010".into(),
                last: "w00011".into(),
            },
        }],
    )
    .unwrap();
    let f = fillers(&p.transcript, &p.timeline().timeline);
    assert_eq!(
        f.words,
        vec!["um", "like"],
        "'I like pizza' keeps its like; the bleeped uh is kept"
    );
    assert!(f.warnings.iter().any(|w| w.contains("bleep")));
}

#[test]
fn silence_removal_keeps_protected_pauses() {
    let mut t = common::transcript(30.0, &[]);
    t.words.retain(|w| {
        !(w.start >= secs(10.0) && w.start < secs(13.0))
            && !(w.start >= secs(20.0) && w.start < secs(24.0))
    });
    let mut p = Project::new(SourceInfo::with_duration(secs(30.0)), t);
    p.apply(
        "keep this pause",
        vec![Op::ProtectPause {
            range: SrcRange::new(secs(20.0), secs(24.0)).unwrap(),
        }],
    )
    .unwrap();
    let tl = p.timeline().timeline;
    let gaps = silences(&p.transcript, &tl, secs(30.0), secs(2.0), 100_000);
    assert_eq!(gaps, vec![SrcRange::new(secs(10.1), secs(12.9)).unwrap()]);
}

fn source_caption(id: &str, a: f64, b: f64, text: &str) -> Op {
    Op::AddCaption {
        id: id.into(),
        anchor: Anchor::Source { range: SrcRange::new(secs(a), secs(b)).unwrap() },
        text: text.into(),
        style: CaptionStyle::default(),
    }
}

/// Captions the timeline already had are the starting point: a cut takes
/// the ones in it away and moves the rest with their picture, a speed-up
/// shortens them with it, and undo never takes them away.
#[test]
fn starting_captions_follow_cuts_and_speed_and_survive_undo() {
    let mut p = project(&[]);
    p.start_with(
        "captions on the timeline",
        vec![
            source_caption("cap_1", 10.0, 12.0, "early"),
            source_caption("cap_2", 40.0, 42.0, "later"),
            source_caption("cap_3", 60.0, 64.0, "fast"),
        ],
    )
    .unwrap();
    assert!(p.edits().is_empty(), "the starting point is not an edit");
    assert_eq!(p.starting().len(), 1);
    assert!(p.undo().is_none(), "nothing to undo yet");
    assert_eq!(p.timeline().timeline.captions.len(), 3);

    p.apply("cut the first 30 seconds", vec![cut_src(0.0, 30.0)]).unwrap();
    let tl = p.timeline().timeline;
    let by = |id: &str| tl.captions.iter().find(|c| c.id == id).unwrap().playback.clone();
    assert!(by("cap_1").is_empty(), "its picture was cut");
    assert_eq!(by("cap_2")[0].start, secs(10.0), "moved 30 s earlier with its picture");

    p.apply(
        "speed up 1:00 to 1:04",
        vec![Op::Speed { range: SrcRange::new(secs(60.0), secs(64.0)).unwrap(), speed: 2000 }],
    )
    .unwrap();
    let tl = p.timeline().timeline;
    let fast = &tl.captions.iter().find(|c| c.id == "cap_3").unwrap().playback[0];
    assert_eq!((fast.start, fast.end), (secs(30.0), secs(32.0)), "twice as fast, half as long");

    assert!(p.undo().is_some());
    assert!(p.undo().is_some());
    assert!(p.undo().is_none(), "undo stops at the starting point");
    assert_eq!(p.timeline().timeline.captions.len(), 3);
    assert!(p.start_with("again", vec![source_caption("cap_9", 1.0, 2.0, "x")]).is_err());
}
