//! Reads instructions with whatever parser the environment sets up and
//! prints the intents: `cargo run -p incubrix-nlu --example ask -- "trim the
//! first half minute" "make the caption red"`. With no arguments, a few
//! plain-English samples. Answers are cached under `NLU_CACHE_DIR`.

use incubrix_nlu::{parser_from_env, Context};

fn main() {
    let mut lines: Vec<String> = std::env::args().skip(1).collect();
    if lines.is_empty() {
        lines = [
            "could you trim off the opening half minute? it drags",
            "lose everything after I say thanks for watching",
            "play the bit from one minute to a minute thirty at double speed",
            "put 'Welcome!' on screen when I say welcome to the channel",
            "make that caption a bit bigger and blue",
            "take out the ums and the long pauses",
            "bring the intro back",
            "what's the weather like?",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect();
    }
    let parser = parser_from_env();
    println!("parser: {}\n", parser.name());
    let ctx = Context {
        duration_s: 240.0,
        captions: vec![("cap_1".into(), "Welcome!".into())],
        speakers: vec!["S1".into()],
        pending_question: None,
    };
    for line in &lines {
        let started = std::time::Instant::now();
        let intent = parser.parse(line, &ctx);
        println!(
            "{line}\n  read by {} in {:.1}s\n  {}\n",
            parser.last_reader(),
            started.elapsed().as_secs_f64(),
            serde_json::to_string(&intent).unwrap()
        );
    }
}
