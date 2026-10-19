//! Conversation: greetings, thanks, help and questions get friendly answers
//! built from the engine's own state, and change nothing.

mod common;

use common::worked;
use incubrix_core::Status;
use incubrix_nlu::intent::{Intent, TalkTopic};
use incubrix_nlu::mock::MockParser;
use incubrix_nlu::Session;

#[test]
fn hello_thanks_and_help_change_nothing() {
    let mut s = worked();
    let before = s.project.hash();
    for text in ["hi", "thanks!", "what can you do?"] {
        let r = s.say(text).outcome;
        assert_eq!(r.status, Status::Applied, "{text}");
        assert_eq!(r.code.as_deref(), Some("TALK"));
        assert_eq!(r.tx, None, "nothing recorded");
        assert!(!r.summary.is_empty());
    }
    assert_eq!(s.project.hash(), before);
    assert!(s.project.active().is_empty(), "no undo steps from talk");
}

#[test]
fn status_and_history_answer_with_real_facts() {
    let mut s = worked();
    let r = s.say("how long is my video now?").outcome;
    assert!(
        r.summary.contains("4:00 long") && r.summary.contains("no changes"),
        "{}",
        r.summary
    );
    s.say("Cut the first 30 seconds");
    let r = s.say("how long is my video now?").outcome;
    assert!(
        r.summary.contains("3:30 long now (it was 4:00)"),
        "{}",
        r.summary
    );
    let r = s.say("what have you changed so far?").outcome;
    assert!(
        r.summary.contains("#1: \"Cut the first 30 seconds\""),
        "{}",
        r.summary
    );
}

#[test]
fn small_talk_uses_the_models_words_but_adds_no_facts() {
    let p = MockParser::default().with(
        "how are you?",
        Intent::Talk {
            topic: TalkTopic::Smalltalk,
            reply: Some("Doing great, thanks!".into()),
        },
    );
    let mut s = Session::new(worked().project, Box::new(p));
    let r = s.say("how are you?").outcome;
    assert!(
        r.summary.starts_with("Doing great, thanks!"),
        "{}",
        r.summary
    );
    assert_eq!(r.tx, None);
}

#[test]
fn a_greeting_before_a_request_is_just_courtesy() {
    let mut s = worked();
    let r = s.say("hi, can u cut the first 30 seconds please").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(s.project.timeline().timeline.duration, 210_000_000);
}
