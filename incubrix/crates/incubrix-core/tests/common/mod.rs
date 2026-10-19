//! A synthetic talking-head transcript: one word every half second, with
//! known phrases at known source times.

#![allow(dead_code)]

use incubrix_core::{secs, Project, SourceInfo, Transcript, Word};

/// Words every 0.5 s for `duration` seconds; `phrases` are (start second, text)
/// laid in at those times, one word per half second.
pub fn transcript(duration: f64, phrases: &[(f64, &str)]) -> Transcript {
    let n = (duration / 0.5) as usize;
    let mut texts: Vec<String> = (0..n).map(|_| "blah".to_owned()).collect();
    let mut speakers: Vec<String> = (0..n).map(|_| "S1".to_owned()).collect();
    for (at, phrase) in phrases {
        let (speaker, phrase) = match phrase.split_once(": ") {
            Some((s, p)) => (s.to_owned(), p),
            None => ("S1".to_owned(), *phrase),
        };
        for (k, w) in phrase.split_whitespace().enumerate() {
            let i = (at / 0.5) as usize + k;
            texts[i] = w.to_owned();
            speakers[i] = speaker.clone();
        }
    }
    Transcript {
        words: texts
            .into_iter()
            .zip(speakers)
            .enumerate()
            .map(|(i, (text, speaker))| Word {
                id: format!("w{i:05}"),
                text,
                start: secs(i as f64 * 0.5),
                end: secs(i as f64 * 0.5 + 0.5),
                speaker,
                confidence: 0.95,
            })
            .collect(),
    }
}

/// The worked example's video: 240 s, "welcome to the channel" at 0:42,
/// "pricing" at 1:05, 2:15 and 3:15.
pub fn worked_example() -> Project {
    let t = transcript(
        240.0,
        &[
            (42.0, "welcome to the channel"),
            (65.0, "our pricing is simple"),
            (135.0, "the pricing changed"),
            (195.0, "pricing for teams"),
        ],
    );
    Project::new(SourceInfo::with_duration(secs(240.0)), t)
}
