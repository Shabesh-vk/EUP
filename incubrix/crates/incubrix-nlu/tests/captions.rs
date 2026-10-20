//! Captioning end to end at the engine level: on words, at a time, auto
//! captions for the whole video, styling, and captions following their
//! content through cuts and speed changes.

mod common;

use common::{caption_at, session, worked};
use incubrix_core::Status;

#[test]
fn caption_on_words_follows_them_through_a_cut() {
    let mut s = worked();
    assert_eq!(
        s.say("Add a caption 'Welcome!' when I say welcome to the channel")
            .outcome
            .status,
        Status::Applied
    );
    assert_eq!(caption_at(&s, 0), Some((42.0, 43.6)));
    s.say("cut 0:10 to 0:20");
    assert_eq!(
        caption_at(&s, 0),
        Some((32.0, 33.6)),
        "moved with its words"
    );
}

#[test]
fn caption_at_a_time_works_without_speech_there() {
    // Silence at 0:05: the caption is pinned to that stretch of the source.
    let mut s = session(60.0, &[(30.0, "Hello there.")]);
    let r = s.say("add a caption 'Intro' at 0:05").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(caption_at(&s, 0), Some((5.0, 7.0)));
    s.say("cut the first 2 seconds");
    assert_eq!(
        caption_at(&s, 0),
        Some((3.0, 5.0)),
        "follows its content, not the clock"
    );
}

#[test]
fn auto_caption_covers_the_speech_in_readable_lines() {
    let mut s = session(
        60.0,
        &[
            (2.0, "Hi everyone, welcome back to the show."),
            (20.0, "Today we look at pricing."),
            (40.0, "Thanks for watching."),
        ],
    );
    let r = s.say("auto-caption the whole video").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    let tl = s.project.timeline().timeline;
    assert!(tl.captions.len() >= 3, "{} captions", tl.captions.len());
    assert!(tl.captions.iter().all(|c| !c.playback.is_empty()));
    assert!(
        tl.captions
            .iter()
            .all(|c| c.text.split_whitespace().count() <= 7),
        "short lines"
    );
    assert_eq!(s.project.active().len(), 1, "one undo step for all of them");
}

#[test]
fn caption_style_size_and_position() {
    let mut s = worked();
    s.say("Add a caption 'Welcome!' when I say welcome to the channel");
    s.say("make it bigger, yellow and at the top");
    let c = &s.project.timeline().timeline.captions[0];
    assert_eq!(
        (
            c.style.size,
            c.style.color.as_str(),
            c.style.position.as_str()
        ),
        (60, "#FFFF00", "top")
    );
}

#[test]
fn auto_caption_without_speech_says_why() {
    let mut s = session(30.0, &[]);
    let r = s.say("auto-caption the whole video").outcome;
    assert_eq!(r.status, Status::Rejected);
    assert_eq!(r.code.as_deref(), Some("NO_TRANSCRIPT"));
}
