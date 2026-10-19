//! Spoken-video fixtures: sentences at known times, 0.4 s per word, with
//! silence between sentences. `"S2: text"` sets the speaker; `word~0.3`
//! sets a word's recognition confidence.

#![allow(dead_code)]

use incubrix_core::{secs, Project, SourceInfo, Transcript, Word};
use incubrix_nlu::{RulesParser, Session};

pub const WORD: f64 = 0.4;

pub fn transcript(lines: &[(f64, &str)]) -> Transcript {
    let mut words = Vec::new();
    for (at, line) in lines {
        let (speaker, text) = match line.split_once(": ") {
            Some((s, t)) if s.starts_with('S') && s.len() <= 3 => (s.to_owned(), t),
            _ => ("S1".to_owned(), *line),
        };
        for (k, w) in text.split_whitespace().enumerate() {
            let (w, conf) = match w.split_once('~') {
                Some((w, c)) => (w, c.parse().unwrap()),
                None => (w, 0.95),
            };
            let start = at + k as f64 * WORD;
            words.push(Word {
                id: String::new(),
                text: w.to_owned(),
                start: secs(start),
                end: secs(start + WORD),
                speaker: speaker.clone(),
                confidence: conf,
            });
        }
    }
    words.sort_by_key(|w| w.start);
    for (i, w) in words.iter_mut().enumerate() {
        w.id = format!("w{i:05}");
    }
    Transcript { words }
}

pub fn session(duration: f64, lines: &[(f64, &str)]) -> Session {
    Session::new(
        Project::new(SourceInfo::with_duration(secs(duration)), transcript(lines)),
        Box::new(RulesParser),
    )
}

/// The worked example's talk: 4 minutes, pricing three times.
pub fn worked() -> Session {
    session(
        240.0,
        &[
            (5.0, "Hi everyone."),
            (42.0, "Welcome to the channel."),
            (65.0, "Our pricing is simple."),
            (100.0, "Let me show you the dashboard."),
            (135.0, "The pricing changed last year."),
            (195.0, "Pricing for teams is different."),
            (230.0, "Thanks for watching."),
        ],
    )
}

pub fn duration(s: &Session) -> f64 {
    s.project.timeline().timeline.duration as f64 / 1e6
}

pub fn caption_at(s: &Session, i: usize) -> Option<(f64, f64)> {
    let tl = s.project.timeline().timeline;
    tl.captions[i]
        .playback
        .first()
        .map(|p| (p.start as f64 / 1e6, p.end as f64 / 1e6))
}
