//! Runs the brief's worked example on a synthetic 4-minute transcript and
//! prints `results.json` in the session runner's shape:
//! `cargo run -p incubrix-core --example worked_example`.
//!
//! Instructions are resolved by hand here (the language layer is Phase 5);
//! every timeline decision is the engine's.

use incubrix_core::resolve::{cut_playback, speed_playback, words_anchor, TIME_POLICY_NOTE};
use incubrix_core::search::{find_phrase, playing};
use incubrix_core::time::clock;
use incubrix_core::{
    secs, CaptionStyle, CutReason, Op, Outcome, Project, SourceInfo, SrcRange, StylePatch,
    Transcript, Word,
};
use serde_json::json;

fn transcript() -> Transcript {
    let phrases: [(f64, &str); 4] = [
        (42.0, "welcome to the channel"),
        (65.0, "our pricing is simple"),
        (135.0, "the pricing changed"),
        (195.0, "pricing for teams"),
    ];
    let mut texts = vec!["blah".to_owned(); 480];
    for (at, p) in phrases {
        for (k, w) in p.split_whitespace().enumerate() {
            texts[(at / 0.5) as usize + k] = w.to_owned();
        }
    }
    Transcript {
        words: texts
            .into_iter()
            .enumerate()
            .map(|(i, text)| Word {
                id: format!("w{i:05}"),
                text,
                start: secs(i as f64 * 0.5),
                end: secs(i as f64 * 0.5 + 0.5),
                speaker: "S1".into(),
                confidence: 0.95,
            })
            .collect(),
    }
}

fn caption_span(p: &Project) -> String {
    let tl = p.timeline().timeline;
    match tl.captions.first().and_then(|c| c.playback.first()) {
        Some(r) => format!("{}-{}", clock(r.start), clock(r.end)),
        None => "hidden".into(),
    }
}

fn main() {
    let mut p = Project::new(SourceInfo::with_duration(secs(240.0)), transcript());
    let mut steps = Vec::new();
    let mut push = |say: &str, o: Outcome| {
        steps.push(json!({ "say": say, "result": o }));
    };

    // 1
    let say = "Add a caption 'Welcome!' when I say welcome to the channel";
    let tl = p.timeline().timeline;
    let h = &find_phrase(&p.transcript, &tl, "welcome to the channel")[0];
    let anchor = words_anchor(&p.transcript, h.first, h.last);
    let id = p.next_id("cap");
    let r = p
        .apply(
            say,
            vec![Op::AddCaption {
                id,
                anchor,
                text: "Welcome!".into(),
                style: CaptionStyle::default(),
            }],
        )
        .unwrap();
    let s = format!(
        "Caption attached to 'welcome to the channel' (now {}).",
        caption_span(&p)
    );
    push(say, Outcome::applied(r, s));

    // 2
    let say = "Cut the first 30 seconds";
    let tl = p.timeline().timeline;
    let r = p
        .apply(say, vec![cut_playback(&tl, 0, secs(30.0)).unwrap()])
        .unwrap();
    let s = format!("Video is 30 s shorter. Caption now plays at {}, still on the same words. {TIME_POLICY_NOTE}", caption_span(&p));
    push(say, Outcome::applied(r, s));

    // 3: ask, then apply the answer
    let say = "Remove the part about pricing";
    let tl = p.timeline().timeline;
    let hits = playing(find_phrase(&p.transcript, &tl, "pricing"));
    let options: Vec<String> = hits
        .iter()
        .enumerate()
        .map(|(i, h)| format!("#{} at {}", i + 1, clock(h.playback_start.unwrap())))
        .chain(["all".to_owned()])
        .collect();
    let q = format!(
        "Pricing is mentioned {} times - which one, or all?",
        hits.len()
    );
    push(say, Outcome::clarify(&p, q, options));
    let say = "the second one";
    let h = &hits[1];
    let range = SrcRange::new(
        p.transcript.words[h.first - 1].start,
        p.transcript.words[h.last + 1].end,
    )
    .unwrap();
    let r = p
        .apply(
            "Remove the part about pricing (the second one)",
            vec![Op::Cut {
                ranges: vec![range],
                reason: CutReason::User,
            }],
        )
        .unwrap();
    push(
        say,
        Outcome::applied(r, "Removed 'the pricing changed'.".into()),
    );

    // 4
    let say = "Speed up from 1:00 to 1:30 by 2x";
    let tl = p.timeline().timeline;
    let r = p
        .apply(
            say,
            speed_playback(&tl, secs(60.0), secs(90.0), 2000).unwrap(),
        )
        .unwrap();
    push(
        say,
        Outcome::applied(r, format!("1:00-1:30 now plays at 2x. {TIME_POLICY_NOTE}")),
    );

    // 5
    let say = "Actually, put the intro back";
    let r = p.apply(say, vec![Op::Restore { tx: 2 }]).unwrap();
    let s = format!(
        "The first 30 s are back; caption at {}; the pricing cut and speed change stay.",
        caption_span(&p)
    );
    push(say, Outcome::applied(r, s));

    // 6
    let say = "Undo";
    let undone = p.undo().map(|t| t.instruction.clone()).unwrap();
    let mut o = Outcome::rejected(&p, String::new());
    o.status = incubrix_core::Status::Applied;
    o.summary = format!(
        "Undid: '{undone}'. The intro is cut again; caption at {}.",
        caption_span(&p)
    );
    push(say, o);

    // 7
    let say = "Make that caption red";
    let tl = p.timeline().timeline;
    let id = tl.captions[0].id.clone();
    let r = p
        .apply(
            say,
            vec![Op::StyleCaption {
                id,
                patch: StylePatch {
                    color: Some("#FF0000".into()),
                    ..Default::default()
                },
            }],
        )
        .unwrap();
    push(
        say,
        Outcome::applied(r, "The Welcome! caption (the only one) is now red.".into()),
    );

    let out = json!({
        "steps": steps,
        "final_timeline": p.timeline().timeline,
        "final_timeline_hash": p.hash(),
    });
    println!("{}", serde_json::to_string_pretty(&out).unwrap());
}
