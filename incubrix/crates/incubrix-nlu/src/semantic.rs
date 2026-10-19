//! Finding content by meaning, with no model: sentence boundaries, a small
//! stemmer, and a synonym table, so "the part about pricing" also finds
//! "cost". Matches by synonym are always shown to the user before anything
//! is cut.

use incubrix_core::model::normalize;
use incubrix_core::{Timeline, Transcript, Us};

/// Words that carry no subject.
const STOP: &[&str] = &[
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "at", "for", "about", "with", "my",
    "our", "their", "his", "her", "its", "your", "this", "that", "these", "those", "is", "are",
    "was", "were", "be", "it", "i", "we", "they", "he", "she", "you", "me", "us", "them", "part",
    "bit", "stuff", "thing", "things", "old", "new", "previous", "former", "first", "last", "some",
    "any", "all",
];

/// Words that mean the same subject. Matching any word of a group by
/// meaning is reported as a meaning-based match.
const GROUPS: &[&[&str]] = &[
    &[
        "price",
        "prices",
        "pricing",
        "priced",
        "cost",
        "costs",
        "costly",
        "expensive",
        "cheap",
        "affordable",
        "fee",
        "fees",
        "pay",
        "paying",
        "paid",
        "plan",
        "plans",
        "subscription",
        "subscriptions",
        "dollars",
        "money",
        "budget",
    ],
    &[
        "job",
        "jobs",
        "work",
        "worked",
        "working",
        "career",
        "employer",
        "company",
        "office",
        "boss",
        "position",
        "role",
        "occupation",
    ],
    &["intro", "introduction", "welcome", "hello", "hi"],
    &["outro", "bye", "goodbye", "thanks", "thank"],
    &[
        "sponsor",
        "sponsored",
        "sponsors",
        "ad",
        "ads",
        "advert",
        "advertisement",
    ],
];

/// Swear words for "bleep the swearing".
pub const PROFANITY: &[&str] = &[
    "damn", "dammit", "shit", "fuck", "fucking", "fucked", "crap", "bitch", "bastard", "asshole",
    "hell", "piss",
];

/// A crude stem: enough to make "prices"/"price" and "worked"/"work" meet.
pub fn stem(w: &str) -> String {
    let w = normalize(w);
    let w = w.trim_end_matches("'s").to_owned();
    let n = w.len();
    if n > 4 && w.ends_with("ies") {
        return format!("{}y", &w[..n - 3]);
    }
    if n > 5 && w.ends_with("ing") {
        return w[..n - 3].to_owned();
    }
    if n > 4 && w.ends_with("ed") {
        return w[..n - 2].to_owned();
    }
    if n > 3 && w.ends_with('s') && !w.ends_with("ss") {
        return w[..n - 1].to_owned();
    }
    w
}

/// The subject words of a topic, stemmed.
pub fn topic_terms(topic: &str) -> Vec<String> {
    let words: Vec<String> = topic
        .split_whitespace()
        .map(normalize)
        .filter(|w| !w.is_empty())
        .collect();
    let content: Vec<String> = words
        .iter()
        .filter(|w| !STOP.contains(&w.as_str()))
        .map(|w| stem(w))
        .collect();
    if content.is_empty() {
        words.iter().map(|w| stem(w)).collect()
    } else {
        content
    }
}

fn related(term: &str) -> Vec<String> {
    GROUPS
        .iter()
        .filter(|g| g.iter().any(|w| stem(w) == term))
        .flat_map(|g| g.iter().map(|w| stem(w)))
        .collect()
}

/// One word that matches a topic.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct TopicHit {
    /// Index into the transcript.
    pub word: usize,
    /// True when the word is the topic's own word; false when it matched by meaning.
    pub literal: bool,
}

/// Words that still play and match the topic, literally or by meaning.
pub fn find_topic(t: &Transcript, tl: &Timeline, topic: &str) -> Vec<TopicHit> {
    let terms = topic_terms(topic);
    let near: Vec<String> = terms.iter().flat_map(|t| related(t)).collect();
    t.words
        .iter()
        .enumerate()
        .filter(|(_, w)| tl.covered(&w.range()) > 0)
        .filter_map(|(i, w)| {
            let s = stem(&w.text);
            if terms.contains(&s) {
                Some(TopicHit {
                    word: i,
                    literal: true,
                })
            } else if near.contains(&s) {
                Some(TopicHit {
                    word: i,
                    literal: false,
                })
            } else {
                None
            }
        })
        .collect()
}

/// A pause this long ends a sentence even without punctuation.
pub const SENTENCE_GAP_US: Us = 700_000;

/// The longest a sentence may run either side of a word before the search
/// gives up and keeps just the matched words.
pub const MAX_SIDE_WORDS: usize = 30;

fn ends_sentence(text: &str) -> bool {
    text.trim_end_matches(['"', '\'', ')'])
        .ends_with(['.', '?', '!'])
}

/// The sentence around word `i`: bounded by . ? !, a long pause, or a
/// change of speaker. Returns `None` when no boundary is found nearby.
pub fn sentence(t: &Transcript, i: usize) -> Option<(usize, usize)> {
    let w = &t.words;
    let mut a = i;
    let mut steps = 0;
    while a > 0 {
        let prev = &w[a - 1];
        if ends_sentence(&prev.text)
            || w[a].start - prev.end > SENTENCE_GAP_US
            || prev.speaker != w[a].speaker
        {
            break;
        }
        a -= 1;
        steps += 1;
        if steps > MAX_SIDE_WORDS {
            return None;
        }
    }
    let mut b = i;
    steps = 0;
    while b + 1 < w.len() && !ends_sentence(&w[b].text) {
        let next = &w[b + 1];
        if next.start - w[b].end > SENTENCE_GAP_US || next.speaker != w[b].speaker {
            break;
        }
        b += 1;
        steps += 1;
        if steps > MAX_SIDE_WORDS {
            return None;
        }
    }
    Some((a, b))
}

/// Runs of one or two words labelled with another speaker inside someone's
/// flowing sentence: likely diarization swaps.
pub fn label_islands(t: &Transcript) -> Vec<(usize, usize)> {
    let w = &t.words;
    let mut out = Vec::new();
    let mut i = 0;
    while i < w.len() {
        let mut j = i;
        while j + 1 < w.len() && w[j + 1].speaker == w[i].speaker {
            j += 1;
        }
        if i > 0 && j + 1 < w.len() && j - i < 2 {
            let flows = w[i].start - w[i - 1].end < 250_000 && w[j + 1].start - w[j].end < 250_000;
            if w[i - 1].speaker == w[j + 1].speaker && w[i - 1].speaker != w[i].speaker && flows {
                out.push((i, j));
            }
        }
        i = j + 1;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stems_meet() {
        assert_eq!(stem("prices"), stem("price"));
        assert_eq!(stem("worked"), stem("work"));
        assert_eq!(topic_terms("their old job"), vec!["job"]);
        assert!(related(&stem("pricing")).contains(&stem("cost")));
    }
}
