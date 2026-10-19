//! The brief's 8-step worked example, typed as words (rules parser).

mod common;

use common::{caption_at, duration, worked};
use incubrix_core::Status;
use incubrix_nlu::Action;

fn run() -> Vec<String> {
    let mut s = worked();
    let mut hashes = Vec::new();

    let r = s
        .say("Add a caption 'Welcome!' when I say welcome to the channel")
        .outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(
        caption_at(&s, 0),
        Some((42.0, 43.6)),
        "on the 4 words at 0:42"
    );
    assert!(r.summary.contains("w00002-w00005"), "{}", r.summary);
    hashes.push(r.timeline_hash);

    let r = s.say("Cut the first 30 seconds").outcome;
    assert_eq!(r.status, Status::Applied);
    assert_eq!(duration(&s), 210.0);
    assert_eq!(
        caption_at(&s, 0),
        Some((12.0, 13.6)),
        "still on the same words"
    );
    assert!(
        r.summary.contains("current edited playback time"),
        "{}",
        r.summary
    );
    assert_eq!(r.time_policy, "current");
    hashes.push(r.timeline_hash);

    let r = s.say("Remove the part about pricing").outcome;
    assert_eq!(r.status, Status::NeedsClarification);
    let q = r.question.clone().unwrap();
    assert!(
        q.contains("mentioned 3 times")
            && q.contains("0:35")
            && q.contains("1:45")
            && q.contains("2:45"),
        "{q}"
    );
    assert_eq!(
        r.options.len(),
        4,
        "three mentions and 'all': {:?}",
        r.options
    );
    assert_eq!(duration(&s), 210.0, "nothing cut while asking");

    let r = s.answer("the second one").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(
        duration(&s),
        208.0,
        "'The pricing changed last year.' (5 words) removed"
    );
    hashes.push(r.timeline_hash);

    let r = s.say("Speed up from 1:00 to 1:30 by 2x").outcome;
    assert_eq!(r.status, Status::Applied);
    assert_eq!(duration(&s), 193.0);
    assert!(r.summary.contains("current edited playback time"));
    hashes.push(r.timeline_hash);

    let r = s.say("Actually, put the intro back").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(
        duration(&s),
        223.0,
        "intro back; pricing cut and speed change stay"
    );
    assert_eq!(caption_at(&s, 0), Some((42.0, 43.6)));
    hashes.push(r.timeline_hash);

    let r = s.say("Undo").outcome;
    assert_eq!(r.status, Status::Applied);
    assert!(r.operations[0].contains("edit #5"), "{:?}", r.operations);
    assert_eq!(duration(&s), 193.0, "intro cut again");
    assert_eq!(caption_at(&s, 0), Some((12.0, 13.6)));
    hashes.push(r.timeline_hash);

    let r = s.say("Make that caption red").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(
        s.project.timeline().timeline.captions[0].style.color,
        "#FF0000"
    );
    assert!(s.project.redoable().is_empty(), "a new edit clears redo");
    hashes.push(r.timeline_hash);

    let r = s.say("render");
    assert_eq!(r.outcome.status, Status::Applied);
    assert_eq!(r.action, Some(Action::Render));
    hashes.push(r.outcome.timeline_hash);
    hashes
}

#[test]
fn worked_example_from_typed_words() {
    run();
}

#[test]
fn same_session_same_hashes_three_times() {
    let a = run();
    assert_eq!(a, run());
    assert_eq!(a, run());
}
