//! The default parser: a deterministic grammar of patterns. No network, no
//! model, same intent for the same words every time.
//!
//! Quoted text ('Welcome!', "thanks") is lifted out first so captions keep
//! their exact words and casing and no pattern ever matches inside them.

use std::sync::OnceLock;

use regex::{Captures, Regex};

use crate::intent::{
    CaptionRef, EditKind, EditRef, Intent, Occurrence, Part, Place, SizeChange, StyleChange,
    TalkTopic, Target, VagueGoal, Who,
};
use crate::times::{parse_speed, parse_time};
use crate::{Context, Parser};

/// The rule-based parser.
#[derive(Clone, Copy, Debug, Default)]
pub struct RulesParser;

impl Parser for RulesParser {
    fn name(&self) -> String {
        "rules".into()
    }

    fn parse(&self, text: &str, _ctx: &Context) -> Intent {
        parse(text)
    }
}

/// Parses one message (which may hold several instructions).
pub fn parse(text: &str) -> Intent {
    if let Some(topic) = talk(text) {
        return Intent::Talk { topic, reply: None };
    }
    let (s, quotes) = lift_quotes(text);
    let s = tidy(&s);
    let pieces = split_parts(&s);
    if pieces.len() > 1 {
        return Intent::Multi {
            parts: pieces
                .into_iter()
                .map(|p| Part {
                    text: restore(&p, &quotes),
                    intent: parse_one(&tidy(&p), &quotes),
                })
                .collect(),
        };
    }
    parse_one(&s, &quotes)
}

// ---- text preparation ------------------------------------------------------

const MARK: char = '\u{1}';

/// Replaces quoted spans with `\u{1}N\u{1}` and lower-cases the rest.
fn lift_quotes(text: &str) -> (String, Vec<String>) {
    let mut out = String::new();
    let mut quotes = Vec::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        let close = match c {
            '"' => Some('"'),
            '\u{201c}' => Some('\u{201d}'),
            '\u{2018}' => Some('\u{2019}'),
            // An apostrophe opens a quote only at a word start.
            '\'' if i == 0 || !chars[i - 1].is_alphanumeric() => Some('\''),
            _ => None,
        };
        if let Some(close) = close {
            // The closing mark must end a word ("don't" is not a quote).
            let end = (i + 1..chars.len()).find(|&j| {
                chars[j] == close && (j + 1 == chars.len() || !chars[j + 1].is_alphanumeric())
            });
            if let Some(end) = end {
                quotes.push(chars[i + 1..end].iter().collect());
                out.push(MARK);
                out.push_str(&(quotes.len() - 1).to_string());
                out.push(MARK);
                i = end + 1;
                continue;
            }
        }
        out.extend(c.to_lowercase());
        i += 1;
    }
    (out, quotes)
}

/// Puts quoted text back (without the quote marks).
fn restore(s: &str, quotes: &[String]) -> String {
    let mut out = String::new();
    let mut parts = s.split(MARK);
    if let Some(first) = parts.next() {
        out.push_str(first);
    }
    let mut inside = true;
    for p in parts {
        if inside {
            match p.parse::<usize>().ok().and_then(|n| quotes.get(n)) {
                Some(q) => out.push_str(q),
                None => out.push_str(p),
            }
        } else {
            out.push_str(p);
        }
        inside = !inside;
    }
    out
}

fn re(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).expect("valid pattern"))
}

macro_rules! rx {
    ($pattern:expr) => {{
        static CELL: OnceLock<Regex> = OnceLock::new();
        re(&CELL, $pattern)
    }};
}

/// A message that is conversation only, not an edit.
fn talk(text: &str) -> Option<TalkTopic> {
    let s = text.trim().to_lowercase();
    let s = s.trim_end_matches(['.', '!', '?', ' ']).trim();
    let s = rx!(r"\s+").replace_all(s, " ").to_string();
    if rx!(r"^(?:hi|hello|hey|hiya|howdy|yo|hi there|hello there|hey there|good (?:morning|afternoon|evening))(?:[ ,!]+(?:there|team|buddy|friend|editor|ai))?$").is_match(&s) {
        return Some(TalkTopic::Greeting);
    }
    if rx!(r"^(?:(?:ok(?:ay)?|great|cool|nice|perfect|awesome|good)[ ,!]*)?(?:thanks|thank you|thx|ty|cheers)(?: so much| a lot| very much)?(?:[ ,!]+.*)?$").is_match(&s)
        && !rx!(r"\b(?:cut|remove|delete|trim|speed|slow|mute|bleep|add|caption|move|keep|undo|redo|make)\b").is_match(&s)
    {
        return Some(TalkTopic::Thanks);
    }
    if rx!(r"^(?:help|what can you do|what do you do|how does this work|how do i use (?:this|you)|what can i (?:ask|say)|what are you able to do|what can you help (?:me )?with)$").is_match(&s) {
        return Some(TalkTopic::Help);
    }
    if rx!(r"^(?:how long is (?:the|my|this) video(?: now)?|what(?:'s| is) the (?:length|duration)(?: of (?:the|my) video)?(?: now)?|how long is it(?: now)?|which video are you editing|what are you editing|what video is this)$").is_match(&s) {
        return Some(TalkTopic::Status);
    }
    if rx!(r"^(?:what (?:did you|have you|have we) (?:change|changed|do|done)(?: so far)?|what changes (?:have you made|did you make)|(?:show|list|tell) me (?:the |my |all )?(?:changes|edits)|what(?:'s| has) changed)$").is_match(&s) {
        return Some(TalkTopic::History);
    }
    if rx!(r"^(?:how are you(?: doing)?|how's it going|who are you|what are you|are you there|nice to meet you|good job|well done)$").is_match(&s) {
        return Some(TalkTopic::Smalltalk);
    }
    None
}

/// Drops courtesy words and end punctuation.
fn tidy(s: &str) -> String {
    let mut s = s.trim().trim_end_matches(['.', '!', '?']).trim().to_owned();
    let lead = rx!(
        r"^(?:ok(?:ay)?|actually|now|also|and|then|please|pls|plz|so|hi|hello|hey|hiya|great|thanks|wait|hmm|oh|right|alright|can you|could you|would you|will you|can u|could u|would u|i want to|i'd like to|i would like to|i want you to|let's|lets|go ahead and|just)\b[,!]?\s*"
    );
    loop {
        let t = lead.replace(&s, "").to_string();
        if t == s {
            break;
        }
        s = t;
    }
    let s = rx!(r",?\s*please$").replace(&s, "").to_string();
    rx!(r"\s+").replace_all(s.trim(), " ").to_string()
}

const VERBS: &str = r"^(?:cut|remove|delete|trim|drop|get rid of|take out|keep|move|put|bring|speed|slow|play|mute|silence|bleep|censor|add|insert|caption|make|change|turn|set|colou?r|undo|redo|restore|render|export|auto|subtitle|shorten|tighten|protect)\b";

/// Splits "cut X, then speed up Y and add Z" into parts; a piece that does
/// not start with a verb stays with the one before ("cut 1:00 to 1:30 and
/// the outro" is one part... the outro is not a verb).
fn split_parts(s: &str) -> Vec<String> {
    let sep =
        rx!(r"\s*(?:;|,\s*and then\s|\band then\s|,\s*then\s|\bthen\s|,\s*and\s|\band\s|,\s)\s*");
    let verb = rx!(VERBS);
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0;
    for m in sep.find_iter(s) {
        let next = &s[m.end()..];
        if verb.is_match(next) && m.start() > last {
            pieces.push(s[last..m.start()].to_owned());
            last = m.end();
        }
    }
    pieces.push(s[last..].to_owned());
    pieces
        .into_iter()
        .map(|p| p.trim().to_owned())
        .filter(|p| !p.is_empty())
        .collect()
}

// ---- single instructions -----------------------------------------------------

fn ordinal(w: &str) -> Option<u32> {
    Some(match w {
        "first" | "1st" | "one" => 1,
        "second" | "2nd" | "two" => 2,
        "third" | "3rd" | "three" => 3,
        "fourth" | "4th" | "four" => 4,
        "fifth" | "5th" | "five" => 5,
        _ => w.parse().ok()?,
    })
}

fn back_from(w: &str) -> Option<u32> {
    let w = w.replace(['-', ' '], "");
    Some(match w.as_str() {
        "last" | "latest" | "previous" | "mostrecent" | "" => 0,
        "secondtolast" | "secondlast" | "penultimate" => 1,
        "thirdtolast" | "thirdlast" => 2,
        _ => return None,
    })
}

fn edit_kind(w: &str) -> EditKind {
    match w {
        "cut" | "cuts" | "removal" | "deletion" | "trim" => EditKind::Cut,
        "speed change" | "speed-up" | "speed up" | "speedup" | "speed" => EditKind::Speed,
        "caption" | "captions" => EditKind::Caption,
        "mute" | "bleep" => EditKind::Audio,
        "music" => EditKind::Music,
        "move" | "reorder" => EditKind::Move,
        _ => EditKind::Any,
    }
}

fn steps(w: &str) -> u32 {
    ordinal(w).unwrap_or(1)
}

fn g<'a>(c: &'a Captures, i: usize) -> &'a str {
    c.get(i).map(|m| m.as_str()).unwrap_or("")
}

fn parse_one(s: &str, q: &[String]) -> Intent {
    let unknown = || Intent::Unknown {
        reason: format!("I could not understand \"{}\".", restore(s, q)),
    };
    if s.is_empty() {
        return Intent::Unknown {
            reason: "The instruction is empty.".into(),
        };
    }

    // Undo / redo / restore.
    if rx!(r"^undo(?: that| it| the last (?:edit|change|step|one))?$").is_match(s) {
        return Intent::Undo { steps: 1 };
    }
    if let Some(c) = rx!(r"^undo (?:the last )?(\w+) (?:times|steps|edits|changes)$").captures(s) {
        return Intent::Undo {
            steps: steps(g(&c, 1)),
        };
    }
    if rx!(r"^redo(?: that| it)?$").is_match(s) {
        return Intent::Redo { steps: 1 };
    }
    if let Some(c) = rx!(r"^redo (\w+) (?:times|steps)$").captures(s) {
        return Intent::Redo {
            steps: steps(g(&c, 1)),
        };
    }
    if let Some(c) = rx!(r"^(?:undo|restore|revert|reverse) (?:the )?(last|latest|previous|most recent|second[- ]to[- ]last|second last|penultimate|third[- ]to[- ]last)? ?(cut|removal|trim|speed change|speed-up|speed up|speedup|caption|mute|bleep|move|reorder|music|edit|change|step)(?:,? but keep (?:the )?(.+))?$").captures(s) {
        return Intent::Restore {
            edit: EditRef::Recent {
                edit: edit_kind(g(&c, 2)),
                back: back_from(g(&c, 1)).unwrap_or(0),
            },
            keep: c.get(3).map(|m| m.as_str().to_owned()),
        };
    }
    if let Some(c) =
        rx!(r"^(?:undo|restore|revert|reverse) (?:edit|step|change)? ?#?(\d+)$").captures(s)
    {
        return Intent::Restore {
            edit: EditRef::Id {
                id: g(&c, 1).parse().unwrap_or(0),
            },
            keep: None,
        };
    }
    if rx!(r"^(?:put|bring|add) (?:the )?(?:intro|introduction|beginning|start|opening)(?: part| bit| section)? back(?: in)?$|^restore the (?:intro|introduction|beginning|start|opening)$").is_match(s) {
        return Intent::Restore { edit: EditRef::Intro, keep: None };
    }
    if rx!(r"^(?:put|bring) back (?:what|everything) (?:i|we|you) (?:removed|cut|deleted)$|^(?:restore|undo) what (?:i|we|you) (?:removed|cut|deleted)$|^put (?:it|that|them) back$").is_match(s) {
        return Intent::Restore { edit: EditRef::Removed, keep: None };
    }
    if let Some(c) = rx!(r"^(?:put|bring) (?:the )?(?:part|bit|section|stuff) (?:about |on )?(.+?) back(?: in)?$|^(?:put|bring) (?:the )?(.+?) (?:part |bit |section )?back(?: in)?$").captures(s) {
        let t = c.get(1).or(c.get(2)).map(|m| m.as_str()).unwrap_or("");
        return Intent::Restore {
            edit: EditRef::Topic { text: restore(t, q) },
            keep: None,
        };
    }
    if rx!(r"^(?:render|export|finish|produce)(?: it| the video| the edit| the final video| now| the result)?$").is_match(s) {
        return Intent::Render;
    }

    // Whole-video helpers.
    if rx!(r"^(?:auto[- ]?caption|auto[- ]?subtitle)|^(?:add|generate|create) (?:auto[- ]?)?(?:captions|subtitles)(?: to| for| on)?(?: (?:the|this) (?:whole |entire )?(?:video|thing)| everything| it all| it)?$|^caption (?:the|this) (?:whole |entire )?video$|^caption everything$").is_match(s) {
        return Intent::AutoCaption;
    }
    let removal =
        r"^(?:cut|remove|delete|trim|drop|get rid of|take out|cut out|clean up|strip)(?: out)?";
    if rx!(&format!(r"{removal} (?:all )?(?:of )?(?:the )?(?:filler(?: words)?|fillers|ums?(?:,? (?:and )?uhs?)?(?:,? (?:and )?likes?)?|uhs?(?:,? (?:and )?ums?)?)\b")).is_match(s) {
        return Intent::RemoveFillers;
    }
    if let Some(c) = rx!(&format!(r"{removal} (?:all )?(?:the )?(?:long |awkward )?(?:silences?|silent (?:parts|bits)|pauses|dead air|gaps)(?: (?:that are |which are )?(?:longer than|over|above|of more than|more than|>)\s*(.+))?$")).captures(s) {
        let min = c.get(1).and_then(|m| parse_time(m.as_str())).unwrap_or(1000);
        return Intent::RemoveSilences { min_ms: min.clamp(0, u32::MAX as i64) as u32 };
    }
    if let Some(c) = rx!(r"^(?:keep|protect|don't cut|do not cut|preserve|leave) (?:the |that )?(?:pause|silence|gap|beat) (after|before|at) (.+)$").captures(s) {
        let rest = g(&c, 2);
        let target = match g(&c, 1) {
            "at" => match parse_time(rest) {
                Some(ms) => Target::At { ms },
                None => return unknown(),
            },
            "before" => Target::BeforePhrase { text: phrase_text(rest, q), occurrence: None },
            _ => Target::Phrase { text: phrase_text(rest, q), occurrence: None },
        };
        return Intent::KeepPause { target };
    }

    // Music.
    if let Some(c) = rx!(r"^add (?:some )?(?:background |bg )?(?:music|track|song)(?: (?:from|using|with|called|named))?(?: (.+))?$").captures(s) {
        return Intent::AddMusic { path: restore(g(&c, 1), q).trim().to_owned() };
    }
    if rx!(r"^(?:remove|delete|drop|take out|turn off|stop|kill|mute) (?:the )?(?:background |bg )?music$").is_match(s) {
        return Intent::RemoveMusic;
    }

    // Vague goals: ask, never guess.
    if s.contains("boring") || s.contains("dull") {
        return Intent::Vague {
            goal: VagueGoal::Boring,
        };
    }
    if rx!(r"^(?:make (?:it|the video|this) (?:shorter|tighter|snappier|quicker|more concise)|shorten(?: it| the video| this)?|tighten(?: it)?(?: up)?|cut it down|trim it down|make it less long)$").is_match(s) {
        return Intent::Vague { goal: VagueGoal::Shorter };
    }

    // Captions.
    let cap_noun = r"(?:caption|text|title|subtitle|label|overlay|text overlay|lower third)";
    if let Some(c) = rx!(&format!(r"^(?:(?:add|put|insert|show|place|display|create)(?: a| the| an)? )?{cap_noun}(?: saying| that says| reading| of| with)? \x01(\d+)\x01(?: (.+))?$")).captures(s) {
        let text = q.get(g(&c, 1).parse::<usize>().unwrap_or(0)).cloned().unwrap_or_default();
        let target = caption_place(g(&c, 2), q);
        return Intent::AddCaption { text, target };
    }
    if let Some(c) =
        rx!(r"^(?:add|put|show|place) \x01(\d+)\x01(?: as a caption| on screen)?(?: (.+))?$")
            .captures(s)
    {
        let text = q
            .get(g(&c, 1).parse::<usize>().unwrap_or(0))
            .cloned()
            .unwrap_or_default();
        return Intent::AddCaption {
            text,
            target: caption_place(g(&c, 2), q),
        };
    }
    if let Some(c) = rx!(&format!(
        r"^(?:remove|delete|drop|take away|hide|get rid of) (.*?){cap_noun}s?(?: (.+))?$"
    ))
    .captures(s)
    {
        let subject = format!("{} {}", g(&c, 1), g(&c, 2));
        return Intent::RemoveCaption {
            caption: caption_ref(&subject, q),
        };
    }
    if let Some(c) = rx!(r"^(?:change|set|rename|edit|update|make) (.*?)(?:caption|text|title|it|that)(?:'s)?(?: text| words)? (?:to|say|read|into) \x01(\d+)\x01$").captures(s) {
        let text = q.get(g(&c, 2).parse::<usize>().unwrap_or(0)).cloned().unwrap_or_default();
        return Intent::RetextCaption { caption: caption_ref(g(&c, 1), q), text };
    }

    // Speed: before styles, so "make 1:00-1:30 faster" is a speed change.
    let speed_words = rx!(r"\b(?:speed(?: it)? up|speed|slow(?: it)? down|faster|slower|play)\b");
    if speed_words.is_match(s) && rx!(r"^(?:speed|slow|play|make)").is_match(s) {
        return parse_speed_intent(s, q);
    }

    // Caption styles.
    if let Some(i) = parse_style(s, q) {
        return i;
    }

    // Audio marks.
    if let Some(c) = rx!(r"^(mute|silence|bleep|censor)(?: out)? (.+)$").captures(s) {
        let rest = g(&c, 2);
        let target = if rx!(r"^(?:all )?(?:the )?(?:swear(?:ing| words)?|profanity|curse words|cursing|bad words|expletives|f-words?)$").is_match(rest) {
            Target::Profanity
        } else {
            match parse_target(rest, q) {
                Some(Target::Topic { text, occurrence }) => Target::Phrase { text, occurrence },
                Some(t) => t,
                None => return unknown(),
            }
        };
        return if matches!(g(&c, 1), "mute" | "silence") {
            Intent::Mute { target }
        } else {
            Intent::Bleep { target }
        };
    }

    // Moves.
    if let Some(c) = rx!(r"^(?:move|put|place|shift) (.+?) (?:to|at) the (start|beginning|front|top|end|back|bottom)$").captures(s) {
        let Some(target) = parse_target(g(&c, 1), q) else { return unknown() };
        let to = if matches!(g(&c, 2), "start" | "beginning" | "front" | "top") { Place::Start } else { Place::End };
        return Intent::Move { target, to };
    }
    if let Some(c) =
        rx!(r"^(?:move|put|place|shift) (.+?) (?:before|ahead of|in front of) (.+)$").captures(s)
    {
        let Some(target) = parse_target(g(&c, 1), q) else {
            return unknown();
        };
        let to = match parse_time(g(&c, 2)) {
            Some(ms) => Place::At { ms },
            None => Place::BeforePhrase {
                text: phrase_text(g(&c, 2), q),
            },
        };
        return Intent::Move { target, to };
    }

    // Keep only.
    if let Some(c) = rx!(r"^(?:keep (?:only|just)|only keep|just keep|trim (?:it |the video )?(?:down )?to|cut (?:it |the video )?down to) (.+)$").captures(s) {
        return match parse_target(g(&c, 1), q) {
            Some(target) => Intent::KeepOnly { target },
            None => unknown(),
        };
    }

    // Cuts.
    if let Some(c) = rx!(r"^(?:cut|remove|delete|trim|drop|get rid of|take out|cut out|lose|skip|chop|erase)(?: out| off| away)? (.+)$").captures(s) {
        return match parse_target(g(&c, 1), q) {
            Some(target) => Intent::Cut { target },
            None => unknown(),
        };
    }
    unknown()
}

/// Where a caption goes: "when I say X", "on X", "at 1:20", "from A to B".
fn caption_place(rest: &str, q: &[String]) -> Target {
    let rest = rest.trim();
    if rest.is_empty() {
        return Target::That;
    }
    if let Some(c) = rx!(r"^(?:when|where|as|while|whenever) (?:i|we|he|she|they|you|the (?:host|guest|speaker)|someone|speaker \w+) (?:say|says|said|mention|mentions|mentioned)(?: the words?)? (.+)$").captures(rest) {
        return phrase_target(g(&c, 1), q);
    }
    if let Some(c) =
        rx!(r"^(?:on|over|for|during|across|above|under) (?:the )?(?:words?|phrase|line) (.+)$")
            .captures(rest)
    {
        return phrase_target(g(&c, 1), q);
    }
    if let Some(c) = rx!(r"^(?:at|around) (.+)$").captures(rest) {
        if let Some(ms) = parse_time(g(&c, 1)) {
            return Target::At { ms };
        }
    }
    if let Some(t) = parse_target(
        rest.trim_start_matches("on ").trim_start_matches("over "),
        q,
    ) {
        return t;
    }
    Target::That
}

fn parse_speed_intent(s: &str, q: &[String]) -> Intent {
    let expr = rx!(
        r"(?:by |to |at )?(\d+(?:\.\d+)?\s?x|\d+(?:\.\d+)?\s?times(?: faster| as fast)?|twice(?: as fast)?|double speed|half speed|\d+(?:\.\d+)?\s?%)"
    );
    let slow = s.contains("slow");
    let Some(m) = expr.captures(s) else {
        return Intent::Unknown {
            reason: "Say how fast, e.g. \"speed up 1:00 to 1:30 by 2x\".".into(),
        };
    };
    let Some(mut speed) = parse_speed(g(&m, 1).trim()) else {
        return Intent::Unknown {
            reason: "I could not read the speed.".into(),
        };
    };
    if slow && speed > 1000 {
        // "slow down by 2x" means half speed.
        speed = 1_000_000 / speed;
    }
    let rest = expr.replace(s, " ");
    let rest =
        rx!(r"^(?:speed(?: it)? up|speed|slow(?: it)? down|play|make)\s*").replace(rest.trim(), "");
    let rest = rx!(r"\s*(?:faster|slower|speed)$").replace(rest.trim(), "");
    let rest = rest.trim().trim_start_matches("the speed of ").trim();
    let target = if rest.is_empty()
        || rx!(r"^(?:it|everything|the (?:whole |entire )?video|all|the whole thing)$")
            .is_match(rest)
    {
        Target::Everything
    } else {
        match parse_target(rest, q) {
            Some(t) => t,
            None => {
                return Intent::Unknown {
                    reason: format!(
                        "I could not tell which part to speed up: \"{}\".",
                        restore(rest, q)
                    ),
                }
            }
        }
    };
    Intent::Speed { target, speed }
}

const COLORS: &[(&str, &str)] = &[
    ("red", "#FF0000"),
    ("blue", "#0000FF"),
    ("green", "#00FF00"),
    ("yellow", "#FFFF00"),
    ("white", "#FFFFFF"),
    ("black", "#000000"),
    ("orange", "#FFA500"),
    ("purple", "#800080"),
    ("pink", "#FFC0CB"),
    ("gray", "#808080"),
    ("grey", "#808080"),
    ("cyan", "#00FFFF"),
];

fn parse_style(s: &str, q: &[String]) -> Option<Intent> {
    if !rx!(r"^(?:make|turn|set|change|colou?r|move|put|increase|decrease|bump|enlarge|shrink|bold|unbold)\b").is_match(s) {
        return None;
    }
    let mut change = StyleChange::default();
    for (name, hex) in COLORS {
        if rx!(r"[a-z]+").find_iter(s).any(|m| m.as_str() == *name) {
            change.color = Some((*hex).into());
        }
    }
    if let Some(c) = rx!(r"#([0-9a-f]{6})\b").captures(s) {
        change.color = Some(format!("#{}", g(&c, 1).to_uppercase()));
    }
    if let Some(c) =
        rx!(r"(?:size |to )?(\d{1,3}) ?(?:px|pt|pixels|points)\b|\bsize (\d{1,3})\b").captures(s)
    {
        let n = c.get(1).or(c.get(2)).and_then(|m| m.as_str().parse().ok());
        change.size = n.map(SizeChange::Px);
    } else if rx!(r"\b(?:bigger|larger|enlarge|increase|huge|bigger font|large)\b").is_match(s) {
        change.size = Some(SizeChange::Bigger);
    } else if rx!(r"\b(?:smaller|shrink|decrease|tiny|small)\b").is_match(s) {
        change.size = Some(SizeChange::Smaller);
    }
    if let Some(c) = rx!(r"\b(top|bottom|center|centre|middle)\b").captures(s) {
        change.position = Some(match g(&c, 1) {
            "centre" | "middle" => "center".into(),
            p => p.into(),
        });
    }
    if rx!(r"\b(?:not bold|unbold|regular weight|normal weight)\b").is_match(s) {
        change.bold = Some(false);
    } else if rx!(r"\bbold\b").is_match(s) {
        change.bold = Some(true);
    }
    if change.is_empty() {
        return None;
    }
    // The subject: between the verb and the style words.
    let subject = rx!(r"^(?:make|turn|set|change|colou?r|move|put|increase|decrease|bump|enlarge|shrink|bold|unbold)\s*(?:the (?:colou?r|size|font|position) of\s*)?")
        .replace(s, "")
        .to_string();
    let caption_like = rx!(
        r"\b(?:caption|captions|text|title|subtitle|label|overlay|it|that|this|them|those)\b|\x01"
    )
    .is_match(&subject)
        || subject.trim().is_empty();
    if !caption_like {
        return None;
    }
    Some(Intent::StyleCaption {
        caption: caption_ref(&subject, q),
        change,
    })
}

/// "that caption", "it", "the second caption", "the 'Hi' caption", "cap_2", "all captions".
fn caption_ref(subject: &str, q: &[String]) -> CaptionRef {
    let s = subject.trim();
    if let Some(c) = rx!(r"\bcap_(\d+)\b").captures(s) {
        return CaptionRef::Id(format!("cap_{}", g(&c, 1)));
    }
    if let Some(c) = rx!(r"\x01(\d+)\x01").captures(s) {
        if let Some(t) = q.get(g(&c, 1).parse::<usize>().unwrap_or(usize::MAX)) {
            return CaptionRef::Text(t.clone());
        }
    }
    if rx!(r"\b(?:all|every|each|both|them|those)\b|\bcaptions\b").is_match(s) {
        return CaptionRef::All;
    }
    if let Some(c) =
        rx!(r"\bthe (first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)) (?:caption|text|title)")
            .captures(s)
    {
        let w = g(&c, 1).trim_end_matches(|c: char| c.is_alphabetic());
        let n = ordinal(g(&c, 1)).or_else(|| w.parse().ok()).unwrap_or(1);
        return CaptionRef::Nth(n);
    }
    CaptionRef::That
}

fn phrase_text(s: &str, q: &[String]) -> String {
    let s = rx!(r"^(?:the (?:words?|phrase) |i say |we say |he says |she says |they say |saying )")
        .replace(s.trim(), "");
    restore(s.trim(), q)
}

fn phrase_target(s: &str, q: &[String]) -> Target {
    let (text, occurrence) = occurrence_of(s);
    Target::Phrase {
        text: phrase_text(&text, q),
        occurrence,
    }
}

/// Pulls "the second", "(the last one)", "every time" off a phrase.
fn occurrence_of(s: &str) -> (String, Option<Occurrence>) {
    let s = s.trim();
    if let Some(c) = rx!(r"^(?:all|every|each)(?: of)?(?: the)? (?:mentions? of |times? (?:i say )?|instances? of )?(.+)$").captures(s) {
        return (g(&c, 1).to_owned(), Some(Occurrence::All));
    }
    if let Some(c) = rx!(
        r"^(.+?),? (?:every time|each time|everywhere|all of them|all mentions|all times|wherever)$"
    )
    .captures(s)
    {
        return (g(&c, 1).to_owned(), Some(Occurrence::All));
    }
    if let Some(c) = rx!(r"^(?:the )?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th) (?:mention of |time (?:i say |i mention |we say )?|instance of |one about |part about |bit about )?(.+)$").captures(s) {
        let o = if g(&c, 1) == "last" { Occurrence::Last } else { Occurrence::Nth(ordinal(g(&c, 1)).unwrap_or(1)) };
        return (g(&c, 2).to_owned(), Some(o));
    }
    if let Some(c) = rx!(r"^(.+?),? \(?(?:the )?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)(?: one| time| mention)?\)?$").captures(s) {
        let o = if g(&c, 2) == "last" { Occurrence::Last } else { Occurrence::Nth(ordinal(g(&c, 2)).unwrap_or(1)) };
        return (g(&c, 1).to_owned(), Some(o));
    }
    (s.to_owned(), None)
}

fn who(w: &str) -> Who {
    match w {
        "host" | "interviewer" | "presenter" | "me" => Who::Host,
        "guest" | "interviewee" | "other person" => Who::Guest,
        other => {
            let n: String = other.chars().filter(|c| c.is_ascii_digit()).collect();
            Who::Label(format!("S{n}"))
        }
    }
}

/// What a cut, move or speed change applies to.
pub fn parse_target(s: &str, q: &[String]) -> Option<Target> {
    let s = s.trim().trim_end_matches(['.', ',']);
    let s = rx!(r"^(?:out |off )").replace(s, "");
    let s = s.trim();
    if s.is_empty() {
        return None;
    }
    if rx!(r"^(?:everything|all of it|the whole (?:video|thing|clip)|it all|the entire (?:video|thing|clip)|all|the video|whole video)$").is_match(s) {
        return Some(Target::Everything);
    }
    if rx!(r"^(?:that|it|this|that (?:part|bit|section)|the same (?:part|bit))$").is_match(s) {
        return Some(Target::That);
    }
    if let Some(c) = rx!(r"^(?:the )?(?:first|opening|initial|starting) (.+)$").captures(s) {
        if let Some(ms) = parse_time(g(&c, 1)) {
            return Some(Target::First { ms });
        }
    }
    if let Some(c) = rx!(r"^(?:the )?(?:last|final|closing|ending) (.+)$").captures(s) {
        if let Some(ms) = parse_time(g(&c, 1)) {
            return Some(Target::Last { ms });
        }
    }
    if let Some(c) = rx!(
        r"^(?:everything|anything|all|the rest|whatever comes) (?:after|following|from|past) (.+)$"
    )
    .captures(s)
    {
        let rest = g(&c, 1);
        if let Some(ms) = parse_time(rest) {
            return Some(Target::From { start_ms: ms });
        }
        let (text, occurrence) = occurrence_of(&strip_say(rest));
        return Some(Target::AfterPhrase {
            text: restore(&text, q),
            occurrence,
        });
    }
    if let Some(c) = rx!(
        r"^(?:everything|anything|all|whatever comes) (?:before|until|up to|till|preceding) (.+)$"
    )
    .captures(s)
    {
        let rest = g(&c, 1);
        if let Some(ms) = parse_time(rest) {
            return Some(Target::Until { end_ms: ms });
        }
        let (text, occurrence) = occurrence_of(&strip_say(rest));
        return Some(Target::BeforePhrase {
            text: restore(&text, q),
            occurrence,
        });
    }
    if let Some(c) = rx!(
        r"^(?:from |between )?(.+?)\s*(?:-|–|\bto\b|\buntil\b|\btill\b|\bthrough\b|\band\b)\s*(.+)$"
    )
    .captures(s)
    {
        let a = g(&c, 1)
            .trim_start_matches("the section ")
            .trim_start_matches("the part ");
        if let (Some(start_ms), Some(end_ms)) = (parse_time(a), parse_time(g(&c, 2))) {
            return Some(Target::Range { start_ms, end_ms });
        }
    }
    if let Some(c) = rx!(r"^(?:from) (.+)$").captures(s) {
        if let Some(ms) = parse_time(g(&c, 1)) {
            return Some(Target::From { start_ms: ms });
        }
    }
    if let Some(c) = rx!(r"^(?:at|around) (.+)$").captures(s) {
        if let Some(ms) = parse_time(g(&c, 1)) {
            return Some(Target::At { ms });
        }
    }
    if let Some(c) = rx!(r"^(?:everything|all|anything|whatever|the parts?|the bits?|the lines?|what) (?:that |where )?(?:the |my |our )?(host|guest|interviewer|interviewee|presenter|speaker \d+|s\d+) (?:says|said|talks|talked|speaks|spoke|mentions|mentioned)(?: about (.+))?$").captures(s) {
        return Some(Target::Speaker {
            who: who(g(&c, 1)),
            topic: c.get(2).map(|m| restore(m.as_str(), q)),
        });
    }
    if let Some(c) = rx!(r"^(?:the |my |our )?(host|guest|interviewer|interviewee|speaker \d+|s\d+)'s? (?:lines|parts|answers|questions|bits|words|stuff)(?: about (.+))?$").captures(s) {
        return Some(Target::Speaker {
            who: who(g(&c, 1)),
            topic: c.get(2).map(|m| restore(m.as_str(), q)),
        });
    }
    if let Some(c) = rx!(r"^(?:the |that )?(?:(first|second|third|fourth|fifth|last) )?(?:part|bit|section|segment|stuff|portion|piece|discussion|talk|sentence)s? (?:about|on|regarding|discussing|mentioning|covering|where (?:i|we|he|she|they) (?:talks?|talked|discuss(?:es|ed)?|mentions?|mentioned|says?|said) (?:about )?)(.+)$").captures(s) {
        let (text, mut occurrence) = occurrence_of(g(&c, 2));
        if let Some(o) = c.get(1) {
            occurrence = Some(if o.as_str() == "last" { Occurrence::Last } else { Occurrence::Nth(ordinal(o.as_str()).unwrap_or(1)) });
        }
        return Some(Target::Topic { text: restore(&text, q), occurrence });
    }
    if let Some(c) = rx!(r"^(?:the |every |all )?(?:words?|phrase) (.+)$|^(?:where|when) (?:i|we|he|she|they) (?:say|says|said) (.+)$").captures(s) {
        let t = c.get(1).or(c.get(2)).map(|m| m.as_str()).unwrap_or("");
        let all = s.starts_with("every ") || s.starts_with("all ");
        let (text, occurrence) = occurrence_of(t);
        return Some(Target::Phrase {
            text: restore(&text, q),
            occurrence: if all { Some(Occurrence::All) } else { occurrence },
        });
    }
    if rx!(r"^\x01\d+\x01$").is_match(s) {
        return Some(Target::Phrase {
            text: restore(s, q),
            occurrence: None,
        });
    }
    if parse_time(s).is_some() {
        // "cut 1:20" names a moment, not a span.
        return None;
    }
    let (text, occurrence) = occurrence_of(s);
    let text = rx!(r"^(?:the|a|an|our|my|this|that) ")
        .replace(&text, "")
        .to_string();
    Some(Target::Topic {
        text: restore(&text, q),
        occurrence,
    })
}

fn strip_say(s: &str) -> String {
    rx!(r"^(?:i|we|he|she|they|you|the (?:host|guest)) (?:say|says|said|mention|mentions|mentioned) |^(?:saying|the words?|the phrase) ")
        .replace(s.trim(), "")
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn p(s: &str) -> Intent {
        parse(s)
    }

    #[test]
    fn worked_example_sentences() {
        assert_eq!(
            p("Add a caption 'Welcome!' when I say welcome to the channel"),
            Intent::AddCaption {
                text: "Welcome!".into(),
                target: Target::Phrase {
                    text: "welcome to the channel".into(),
                    occurrence: None
                }
            }
        );
        assert_eq!(
            p("Cut the first 30 seconds"),
            Intent::Cut {
                target: Target::First { ms: 30_000 }
            }
        );
        assert_eq!(
            p("Remove the part about pricing"),
            Intent::Cut {
                target: Target::Topic {
                    text: "pricing".into(),
                    occurrence: None
                }
            }
        );
        assert_eq!(
            p("Speed up from 1:00 to 1:30 by 2x"),
            Intent::Speed {
                target: Target::Range {
                    start_ms: 60_000,
                    end_ms: 90_000
                },
                speed: 2000
            }
        );
        assert_eq!(
            p("Actually, put the intro back"),
            Intent::Restore {
                edit: EditRef::Intro,
                keep: None
            }
        );
        assert_eq!(p("Undo"), Intent::Undo { steps: 1 });
        assert_eq!(
            p("Make that caption red"),
            Intent::StyleCaption {
                caption: CaptionRef::That,
                change: StyleChange {
                    color: Some("#FF0000".into()),
                    ..Default::default()
                }
            }
        );
        assert_eq!(p("render"), Intent::Render);
    }

    #[test]
    fn hard_case_sentences() {
        assert_eq!(
            p("Remove 0:30-0:40"),
            Intent::Cut {
                target: Target::Range {
                    start_ms: 30_000,
                    end_ms: 40_000
                }
            }
        );
        assert_eq!(
            p("add a caption 'Hi' at 5:00"),
            Intent::AddCaption {
                text: "Hi".into(),
                target: Target::At { ms: 300_000 }
            }
        );
        assert_eq!(
            p("cut the last 10 seconds"),
            Intent::Cut {
                target: Target::Last { ms: 10_000 }
            }
        );
        assert_eq!(
            p("cut from 80 seconds to a minute thirty"),
            Intent::Cut {
                target: Target::Range {
                    start_ms: 80_000,
                    end_ms: 90_000
                }
            }
        );
        assert_eq!(
            p("Undo the second-to-last cut but keep the music"),
            Intent::Restore {
                edit: EditRef::Recent {
                    edit: EditKind::Cut,
                    back: 1
                },
                keep: Some("music".into())
            }
        );
        assert_eq!(
            p("make it bigger"),
            Intent::StyleCaption {
                caption: CaptionRef::That,
                change: StyleChange {
                    size: Some(SizeChange::Bigger),
                    ..Default::default()
                }
            }
        );
        assert_eq!(
            p("Remove everything after I say thanks"),
            Intent::Cut {
                target: Target::AfterPhrase {
                    text: "thanks".into(),
                    occurrence: None
                }
            }
        );
        assert_eq!(
            p("Speed up 10x"),
            Intent::Speed {
                target: Target::Everything,
                speed: 10_000
            }
        );
        assert_eq!(
            p("cut everything"),
            Intent::Cut {
                target: Target::Everything
            }
        );
        assert_eq!(
            p("Remove everything the guest says about their old job"),
            Intent::Cut {
                target: Target::Speaker {
                    who: Who::Guest,
                    topic: Some("their old job".into())
                }
            }
        );
        assert_eq!(
            p("remove the boring bit"),
            Intent::Vague {
                goal: VagueGoal::Boring
            }
        );
        assert_eq!(
            p("make it shorter"),
            Intent::Vague {
                goal: VagueGoal::Shorter
            }
        );
        assert_eq!(p("remove the ums"), Intent::RemoveFillers);
        assert_eq!(
            p("remove silences longer than 2 seconds"),
            Intent::RemoveSilences { min_ms: 2000 }
        );
        assert_eq!(
            p("slow down 0:10 to 0:20 by 2x"),
            Intent::Speed {
                target: Target::Range {
                    start_ms: 10_000,
                    end_ms: 20_000
                },
                speed: 500
            }
        );
    }

    #[test]
    fn conversation_is_not_an_edit() {
        let t = |s: &str| match p(s) {
            Intent::Talk { topic, .. } => Some(topic),
            _ => None,
        };
        assert_eq!(t("hi"), Some(TalkTopic::Greeting));
        assert_eq!(t("Hello there!"), Some(TalkTopic::Greeting));
        assert_eq!(t("thanks!"), Some(TalkTopic::Thanks));
        assert_eq!(t("great, thank you so much"), Some(TalkTopic::Thanks));
        assert_eq!(t("what can you do?"), Some(TalkTopic::Help));
        assert_eq!(t("how long is my video now?"), Some(TalkTopic::Status));
        assert_eq!(t("what have you changed so far?"), Some(TalkTopic::History));
        assert_eq!(t("how are you?"), Some(TalkTopic::Smalltalk));
        // A greeting in front of a request is courtesy: the request counts.
        assert_eq!(
            p("hi, can u cut the first 30 seconds please"),
            Intent::Cut {
                target: Target::First { ms: 30_000 }
            }
        );
    }

    #[test]
    fn three_parts_split_and_quotes_survive() {
        let Intent::Multi { parts } = p(
            "Cut the first 10 seconds, speed up 10x and add a caption 'Bye, and thanks' at 0:05",
        ) else {
            panic!("expected three parts")
        };
        assert_eq!(parts.len(), 3);
        assert_eq!(
            parts[1].intent,
            Intent::Speed {
                target: Target::Everything,
                speed: 10_000
            }
        );
        assert_eq!(
            parts[2].intent,
            Intent::AddCaption {
                text: "Bye, and thanks".into(),
                target: Target::At { ms: 5000 }
            }
        );
    }

    #[test]
    fn occurrences() {
        assert_eq!(
            p("remove the second mention of pricing"),
            Intent::Cut {
                target: Target::Topic {
                    text: "pricing".into(),
                    occurrence: Some(Occurrence::Nth(2))
                }
            }
        );
        assert_eq!(
            p("bleep the word damn every time"),
            Intent::Bleep {
                target: Target::Phrase {
                    text: "damn".into(),
                    occurrence: Some(Occurrence::All)
                }
            }
        );
    }
}
