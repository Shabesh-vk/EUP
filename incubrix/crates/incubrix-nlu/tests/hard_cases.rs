//! Phase 5 "done when": every row of the brief's hard-cases list, typed as
//! words, with the rules parser and fixture transcripts.

mod common;

use std::path::Path;

use common::{caption_at, duration, session, worked};
use incubrix_core::{secs, Project, SourceInfo, Status, Transcript};
use incubrix_nlu::llm::{LlmConfig, LlmParser, Provider};
use incubrix_nlu::mock::MockParser;
use incubrix_nlu::{Context, Intent, Parser, RulesParser, Session};

// Row 1: a caption, then the sentence under it cut, then that cut restored.
#[test]
fn caption_comes_back_when_its_cut_is_restored() {
    let mut s = session(
        60.0,
        &[
            (10.0, "Hello there."),
            (20.0, "This is the key sentence."),
            (40.0, "Bye now."),
        ],
    );
    assert_eq!(
        s.say("Add a caption 'Key' when I say this is the key sentence")
            .outcome
            .status,
        Status::Applied
    );
    let r = s.say("Remove the part about the key sentence").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(caption_at(&s, 0), None, "hidden");
    assert!(
        r.warnings.iter().any(|w| w.contains("hidden")),
        "the user is told: {:?}",
        r.warnings
    );

    let r = s.say("put back what I removed").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert!(
        r.warnings.iter().any(|w| w.contains("Assumed")),
        "states its assumption: {:?}",
        r.warnings
    );
    assert_eq!(caption_at(&s, 0), Some((20.0, 22.0)), "back on its words");
}

// Row 2a: a section reordered, then a word inside it muted.
#[test]
fn mute_inside_a_moved_section_follows_the_word() {
    let mut s = session(
        120.0,
        &[
            (10.0, "Intro words here."),
            (60.0, "The secret word is banana."),
        ],
    );
    let r = s.say("Move 0:50 to 1:10 to the start").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    let r = s.say("mute the word banana").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    let tl = s.project.timeline().timeline;
    let m = &tl.marks[0];
    // banana is the 5th word: source 61.6-62.0, which now plays at 11.6-12.0.
    assert_eq!(
        (m.playback[0].start, m.playback[0].end),
        (secs(11.6), secs(12.0))
    );
}

// Row 2b: filler removal never cuts into a bleeped word.
#[test]
fn filler_removal_leaves_a_bleeped_filler_alone() {
    let mut s = session(
        60.0,
        &[(5.0, "So um this is fine."), (20.0, "Oh um damn it.")],
    );
    let r = s.say("bleep um damn").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    let r = s.say("remove the ums").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert!(r.summary.contains("Removed 1 filler"), "{}", r.summary);
    assert!(
        r.warnings.iter().any(|w| w.contains("inside a bleep")),
        "{:?}",
        r.warnings
    );
}

// Row 3a: "Remove 0:30-0:40" sent twice.
#[test]
fn the_same_typed_cut_twice_asks_instead_of_cutting_again() {
    let mut s = worked();
    assert_eq!(s.say("Remove 0:30-0:40").outcome.status, Status::Applied);
    assert_eq!(duration(&s), 230.0);
    let r = s.say("Remove 0:30-0:40").outcome;
    assert_eq!(r.status, Status::NeedsClarification, "{r:?}");
    assert!(r.question.unwrap().contains("different content"));
    let r = s.answer("no").outcome;
    assert_eq!(r.status, Status::Applied);
    assert_eq!(r.tx, None, "nothing recorded");
    assert_eq!(duration(&s), 230.0, "repeat is safe");
}

// Row 3b: a caption at 5:00 on a shorter video.
#[test]
fn caption_past_the_end_is_rejected() {
    let mut s = worked();
    let r = s.say("add a caption 'Hi' at 5:00").outcome;
    assert_eq!(r.status, Status::Rejected);
    assert_eq!(r.code.as_deref(), Some("OUT_OF_RANGE"));
    assert!(
        r.summary.contains("5:00 is past the end") && r.summary.contains("4:00"),
        "{}",
        r.summary
    );
}

// Row 3c: times as "80 seconds", "a minute twenty", "the last 10 seconds".
#[test]
fn spoken_time_forms() {
    let mut s = worked();
    s.say("cut from 80 seconds to a minute twenty five");
    assert_eq!(duration(&s), 235.0);
    s.say("cut the last 10 seconds");
    assert_eq!(duration(&s), 225.0);
    let r = s.say("add a caption 'Here' at a minute twenty").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
}

// Row 4a: undo the second-to-last cut but keep the music.
#[test]
fn undo_second_to_last_cut_keeps_the_music() {
    let mut s = worked();
    assert_eq!(
        s.say("add background music 'bed.mp3'").outcome.status,
        Status::Applied
    );
    s.say("cut 0:10 to 0:20");
    s.say("cut 0:30 to 0:40");
    assert_eq!(duration(&s), 220.0);
    let r = s
        .say("Undo the second-to-last cut but keep the music")
        .outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert!(r.summary.contains("edit #2"), "{}", r.summary);
    assert_eq!(duration(&s), 230.0);
    assert_eq!(s.project.timeline().timeline.music.len(), 1, "music kept");
    assert!(
        r.warnings.iter().any(|w| w.contains("music")),
        "{:?}",
        r.warnings
    );
}

// Row 4b: "make it bigger" with no caption.
#[test]
fn make_it_bigger_without_a_caption() {
    let mut s = worked();
    let r = s.say("make it bigger").outcome;
    assert_eq!(r.status, Status::Rejected);
    assert_eq!(r.code.as_deref(), Some("NO_CAPTION"));
}

// Row 5: "Remove everything after I say thanks", thanks said four times.
#[test]
fn everything_after_thanks_asks_which_of_four() {
    let mut s = session(
        100.0,
        &[
            (10.0, "Thanks for coming."),
            (30.0, "Thanks Sam."),
            (50.0, "And thanks again."),
            (80.0, "Thanks everyone."),
        ],
    );
    let r = s.say("Remove everything after I say thanks").outcome;
    assert_eq!(r.status, Status::NeedsClarification);
    assert_eq!(
        r.options.len(),
        4,
        "no 'all' for after-a-word: {:?}",
        r.options
    );
    assert!(r.question.unwrap().contains("4 times"));
    let r = s.answer("the third one").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    // The third "thanks" is word 2 of the sentence at 0:50: ends at 50.8.
    assert_eq!(duration(&s), 50.8);
}

// Row 6: speed up 10x, cut everything, three parts with one impossible.
#[test]
fn impossible_requests_are_rejected_and_change_nothing() {
    let mut s = worked();
    let before = s.project.hash();
    let r = s.say("Speed up 10x").outcome;
    assert_eq!(
        (r.status, r.code.as_deref()),
        (Status::Rejected, Some("SPEED_OUT_OF_RANGE"))
    );
    let r = s.say("cut everything").outcome;
    assert_eq!(
        (r.status, r.code.as_deref()),
        (Status::Rejected, Some("WOULD_REMOVE_EVERYTHING"))
    );

    let r = s
        .say("Cut the first 10 seconds, speed up 10x and add a caption 'Bye' at 0:05")
        .outcome;
    assert_eq!(r.status, Status::Rejected);
    assert!(
        r.summary.contains("part 2") && r.summary.contains("Nothing was applied"),
        "{}",
        r.summary
    );
    assert_eq!(s.project.hash(), before, "all or nothing");
    assert!(s.project.active().is_empty());
}

#[test]
fn three_possible_parts_are_one_undo_step() {
    let mut s = worked();
    let r = s.say("Cut the first 10 seconds, speed up 0:20 to 0:30 by 2x and add a caption 'Hello' at 0:32").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(r.operations.len(), 3, "{:?}", r.operations);
    assert_eq!(s.project.active().len(), 1, "one transaction");
    // The caption went on the words playing at 0:32 after the first two parts.
    assert_eq!(s.project.timeline().timeline.captions[0].text, "Hello");
    s.say("undo");
    assert!(s.project.active().is_empty());
}

fn two_speakers() -> Session {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../fixtures/media/two_speakers.transcript.json");
    let v: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let t: Transcript = serde_json::from_value(v["transcript"].clone()).unwrap();
    let mut src = SourceInfo::with_duration(secs(12.0));
    src.variable_frame_rate = true;
    Session::new(Project::new(src, t), Box::new(RulesParser))
}

// Row 7 (and Advanced "two speakers"): the guest's old job, the host's lead-in.
#[test]
fn guest_lines_about_old_job_and_the_hosts_question() {
    let mut s = two_speakers();
    let r = s
        .say("Remove everything the guest says about their old job")
        .outcome;
    assert_eq!(r.status, Status::NeedsClarification, "{r:?}");
    let q = r.question.unwrap();
    assert!(q.contains("question"), "{q}");
    assert_eq!(r.options.len(), 2);
    assert!(
        r.options[1].contains("what did you do before"),
        "{:?}",
        r.options
    );

    let r = s.answer("only the guest's lines").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    let tl = s.project.timeline().timeline;
    let plays = |text: &str| {
        let w = s
            .project
            .transcript
            .words
            .iter()
            .find(|w| w.text.starts_with(text))
            .unwrap();
        tl.covered(&w.range()) > 0
    };
    assert!(!plays("bank"), "'I worked at a bank' is about the job");
    assert!(!plays("boring"), "'My old job was really boring'");
    assert!(plays("before"), "the host's question stays");
    assert!(plays("Interesting"), "the host's reply stays");
}

#[test]
fn two_speaker_phone_video_with_music() {
    let mut s = two_speakers();
    assert!(s.project.source.variable_frame_rate);
    assert_eq!(s.say("add music 'bed.mp3'").outcome.status, Status::Applied);
    let r = s.say("Remove everything the host says").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert!(
        r.warnings
            .iter()
            .any(|w| w.contains("swapped") && w.contains("hours")),
        "the label swap is reported: {:?}",
        r.warnings
    );
    assert_eq!(s.project.timeline().timeline.music.len(), 1);
}

// Outstanding "ambiguity and references".
#[test]
fn meaning_based_match_is_shown_before_cutting() {
    let mut s = session(
        60.0,
        &[(10.0, "The cost went up."), (30.0, "Anyway, moving on.")],
    );
    let r = s.say("Remove the part about pricing").outcome;
    assert_eq!(r.status, Status::NeedsClarification, "{r:?}");
    let q = r.question.unwrap();
    assert!(q.contains("by meaning (cost)"), "shows the match: {q}");
    assert!(r.options.iter().any(|o| o.starts_with("None")));
    assert_eq!(duration(&s), 60.0);
    let r = s.answer("1").outcome;
    assert_eq!(r.status, Status::Applied);
    assert_eq!(duration(&s), 58.4);
}

#[test]
fn vague_requests_ask_with_options() {
    let mut s = session(60.0, &[(5.0, "So um this is it."), (40.0, "Done.")]);
    for text in ["remove the boring bit", "make it shorter"] {
        let r = s.say(text).outcome;
        assert_eq!(r.status, Status::NeedsClarification, "{text}");
        assert!(
            r.options.iter().any(|o| o.contains("silences")),
            "{:?}",
            r.options
        );
        assert!(
            r.options.iter().any(|o| o.contains("filler")),
            "{:?}",
            r.options
        );
    }
    let r = s.answer("remove 1 filler words").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert!(r.summary.contains("filler"));
}

#[test]
fn put_back_what_i_removed_with_two_removals_asks() {
    let mut s = worked();
    s.say("cut 0:10 to 0:20");
    s.say("cut 1:00 to 1:10");
    let r = s.say("put back what I removed").outcome;
    assert_eq!(r.status, Status::NeedsClarification);
    assert_eq!(r.options.len(), 3, "{:?}", r.options);
    let r = s.answer("all").outcome;
    assert_eq!(r.status, Status::Applied);
    assert_eq!(duration(&s), 240.0);
}

#[test]
fn that_caption_with_several_captions_asks() {
    let mut s = worked();
    s.say("Add a caption 'One' when I say welcome to the channel");
    s.say("Add a caption 'Two' when I say thanks for watching");
    // "that caption" is the last one talked about.
    let r = s.say("make that caption blue").outcome;
    assert!(r.summary.contains("'Two'"), "{}", r.summary);
    let r = s.say("make the captions bigger").outcome;
    assert_eq!(r.status, Status::Applied);
    let tl = s.project.timeline().timeline;
    assert!(tl.captions.iter().all(|c| c.style.size == 60));
}

// Outstanding "imperfect data": low-confidence words are flagged, not bleeped blindly.
#[test]
fn low_confidence_words_are_not_bleeped_blindly() {
    let mut s = session(
        30.0,
        &[(5.0, "Well damn~0.3 that hurt."), (15.0, "Oh crap.")],
    );
    let r = s.say("bleep the swearing").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    assert_eq!(
        s.project.timeline().timeline.marks.len(),
        1,
        "only the confident one"
    );
    assert!(r.warnings.iter().any(|w| w.contains("low confidence")));

    let r = s.say("bleep the word damn").outcome;
    assert_eq!(r.status, Status::NeedsClarification, "asks first: {r:?}");
}

#[test]
fn deliberate_pause_survives_silence_removal() {
    let mut s = session(
        40.0,
        &[(2.0, "Wait for it."), (8.0, "Now."), (20.0, "Done.")],
    );
    assert_eq!(
        s.say("keep the pause after wait for it").outcome.status,
        Status::Applied
    );
    let r = s.say("remove silences longer than 1 second").outcome;
    assert_eq!(r.status, Status::Applied, "{r:?}");
    let tl = s.project.timeline().timeline;
    let pause = incubrix_core::SrcRange::new(secs(3.2), secs(8.0)).unwrap();
    assert_eq!(
        tl.covered(&pause),
        pause.len(),
        "the protected pause plays in full"
    );
}

#[test]
fn every_answer_has_one_of_three_statuses_and_the_policy() {
    let mut s = worked();
    for text in ["banana split", "", "redo", "undo", "answer me", "cut 1:20"] {
        let r = s.say(text).outcome;
        assert_eq!(r.time_policy, "current");
        assert_eq!(r.status, Status::Rejected, "{text}: {r:?}");
        assert!(!r.summary.is_empty());
    }
}

// The adapters: mock gives exact intents; the LLM adapter answers from its cache.
#[test]
fn mock_parser_drives_the_resolver() {
    let p = MockParser::default().with(
        "chop",
        Intent::Cut {
            target: incubrix_nlu::intent::Target::First { ms: 5000 },
        },
    );
    let mut s = Session::new(worked().project, Box::new(p));
    assert_eq!(s.say("chop").outcome.status, Status::Applied);
    assert_eq!(duration(&s), 235.0);
}

#[test]
fn llm_answers_are_cached_so_reruns_need_no_network() {
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join("nlu-cache");
    let _ = std::fs::remove_dir_all(&dir);
    let p = LlmParser::new(LlmConfig {
        provider: Provider::Anthropic,
        model: "test-model".into(),
        api_key: None,
        base_url: "http://127.0.0.1:9".into(),
        cache_dir: dir.clone(),
    });
    let ctx = Context::default();
    // No key, no cache: unavailable, never a guess.
    assert!(matches!(
        p.parse("trim the intro", &ctx),
        Intent::Unknown { .. }
    ));
    // A cached answer is used as is.
    let key = p.cache_key("trim the intro", &ctx);
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(
        dir.join(format!("{key}.json")),
        r#"{"intent":"cut","target":{"kind":"first","ms":5000}}"#,
    )
    .unwrap();
    assert_eq!(
        p.parse("trim the intro", &ctx),
        Intent::Cut {
            target: incubrix_nlu::intent::Target::First { ms: 5000 }
        }
    );
}
