//! What an instruction means, as data. This is the only thing a parser -
//! rule-based or an LLM - may produce. Turning it into timeline operations
//! is the resolver's job, in plain code.
//!
//! Times are milliseconds of **current playback** (the time policy), as typed.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// One instruction's meaning.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "intent", rename_all = "snake_case")]
pub enum Intent {
    /// Remove something.
    Cut {
        /// What.
        target: Target,
    },
    /// Remove everything except something.
    KeepOnly {
        /// What stays.
        target: Target,
    },
    /// Move a section.
    Move {
        /// What moves.
        target: Target,
        /// Where to.
        to: Place,
    },
    /// Play something faster or slower.
    Speed {
        /// What (everything when not said).
        target: Target,
        /// Thousandths: 2000 = 2x, 500 = half speed.
        speed: u32,
    },
    /// Silence words.
    Mute {
        /// What.
        target: Target,
    },
    /// Bleep words.
    Bleep {
        /// What.
        target: Target,
    },
    /// Add a caption on content.
    AddCaption {
        /// The text shown.
        text: String,
        /// Where: words said, or a time.
        target: Target,
    },
    /// Change how a caption looks.
    StyleCaption {
        /// Which caption.
        caption: CaptionRef,
        /// What changes.
        change: StyleChange,
    },
    /// Change a caption's words.
    RetextCaption {
        /// Which caption.
        caption: CaptionRef,
        /// New text.
        text: String,
    },
    /// Take a caption away.
    RemoveCaption {
        /// Which caption.
        caption: CaptionRef,
    },
    /// Caption the whole video from the transcript.
    AutoCaption,
    /// Remove um, uh and filler "like".
    RemoveFillers,
    /// Remove silences longer than a threshold.
    RemoveSilences {
        /// Threshold, milliseconds.
        min_ms: u32,
    },
    /// Keep a pause through later silence removal.
    KeepPause {
        /// The pause (after a phrase, or a time span).
        target: Target,
    },
    /// Add background music that ducks under speech.
    AddMusic {
        /// File path or URL.
        path: String,
    },
    /// Take the music away.
    RemoveMusic,
    /// Step back.
    Undo {
        /// How many instructions.
        steps: u32,
    },
    /// Step forward.
    Redo {
        /// How many instructions.
        steps: u32,
    },
    /// Switch one earlier edit off, keeping everything after it.
    Restore {
        /// Which edit.
        edit: EditRef,
        /// Anything the user asked to keep while restoring ("but keep the music").
        #[serde(default, skip_serializing_if = "Option::is_none")]
        keep: Option<String>,
    },
    /// Produce the video (a separate step).
    Render,
    /// A goal too vague to act on without asking.
    Vague {
        /// What kind.
        goal: VagueGoal,
    },
    /// Several instructions in one message, applied together or not at all.
    Multi {
        /// The parts, in order.
        parts: Vec<Part>,
    },
    /// Conversation, not an edit: "hi", "thanks", "what can you do?",
    /// "how long is my video?". The engine answers from its own state; only
    /// small talk carries words written by a model.
    Talk {
        /// What kind of talk.
        topic: TalkTopic,
        /// For small talk only: a short, friendly reply.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        reply: Option<String>,
    },
    /// Not understood.
    Unknown {
        /// Why, for the user.
        reason: String,
    },
}

/// One part of a multi-part instruction.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Part {
    /// The words of this part.
    pub text: String,
    /// What they mean.
    pub intent: Intent,
}

/// What an edit applies to.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Target {
    /// A typed span of current playback time.
    Range {
        /// Start, ms.
        start_ms: i64,
        /// End, ms.
        end_ms: i64,
    },
    /// The first N ms.
    First {
        /// Length, ms.
        ms: i64,
    },
    /// The last N ms.
    Last {
        /// Length, ms.
        ms: i64,
    },
    /// From a time to the end.
    From {
        /// Start, ms.
        start_ms: i64,
    },
    /// From the start to a time.
    Until {
        /// End, ms.
        end_ms: i64,
    },
    /// One moment (for a caption: the words said then).
    At {
        /// The time, ms.
        ms: i64,
    },
    /// Exact words said.
    Phrase {
        /// The words.
        text: String,
        /// Which time they are said.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        occurrence: Option<Occurrence>,
    },
    /// The sentences about a subject (meaning-based: "pricing" finds "cost").
    Topic {
        /// The subject.
        text: String,
        /// Which mention.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        occurrence: Option<Occurrence>,
    },
    /// Everything after a phrase is said.
    AfterPhrase {
        /// The words.
        text: String,
        /// Which time they are said.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        occurrence: Option<Occurrence>,
    },
    /// Everything before a phrase is said.
    BeforePhrase {
        /// The words.
        text: String,
        /// Which time they are said.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        occurrence: Option<Occurrence>,
    },
    /// What one speaker says, optionally only about a subject.
    Speaker {
        /// Who.
        who: Who,
        /// About what.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        topic: Option<String>,
    },
    /// Swear words.
    Profanity,
    /// The whole video.
    Everything,
    /// Whatever the last instruction pointed at.
    That,
}

/// Which mention.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", content = "n", rename_all = "snake_case")]
pub enum Occurrence {
    /// 1-based.
    Nth(u32),
    /// The last one.
    Last,
    /// Every one.
    All,
}

/// A speaker.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", content = "label", rename_all = "snake_case")]
pub enum Who {
    /// Whoever speaks first.
    Host,
    /// The other speaker.
    Guest,
    /// A diarization label, `S1`, `S2`, ...
    Label(String),
}

/// Where a moved section goes.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Place {
    /// The very beginning.
    Start,
    /// The very end.
    End,
    /// Just before a phrase is said.
    BeforePhrase {
        /// The words.
        text: String,
    },
    /// Just before a playback time.
    At {
        /// The time, ms.
        ms: i64,
    },
}

/// Which caption.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum CaptionRef {
    /// "that caption", "it": the one last talked about.
    That,
    /// By id, `cap_2`.
    Id(String),
    /// The caption whose text contains this.
    Text(String),
    /// The nth caption, 1-based, in the order added.
    Nth(u32),
    /// Every caption.
    All,
}

/// A style change.
#[derive(Clone, PartialEq, Eq, Debug, Default, Serialize, Deserialize, JsonSchema)]
pub struct StyleChange {
    /// `#RRGGBB`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub color: Option<String>,
    /// Bigger, smaller or a size.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size: Option<SizeChange>,
    /// `top`, `center`, `bottom`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub position: Option<String>,
    /// Bold or not.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bold: Option<bool>,
}

impl StyleChange {
    /// Whether nothing would change.
    pub fn is_empty(&self) -> bool {
        self == &StyleChange::default()
    }
}

/// A size change.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", content = "px", rename_all = "snake_case")]
pub enum SizeChange {
    /// A quarter bigger.
    Bigger,
    /// A fifth smaller.
    Smaller,
    /// An exact size.
    Px(u32),
}

/// Which earlier edit.
#[derive(Clone, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EditRef {
    /// By number, `#3`.
    Id {
        /// The edit number.
        id: u32,
    },
    /// The latest of a kind; `back` 0 is the last, 1 the second-to-last.
    Recent {
        /// What kind.
        edit: EditKind,
        /// How far back.
        back: u32,
    },
    /// The edit that removed the opening.
    Intro,
    /// The edit that removed this subject.
    Topic {
        /// The subject.
        text: String,
    },
    /// "what I removed": ask which.
    Removed,
}

/// Kinds of edits, for "the last cut", "the speed change".
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum EditKind {
    /// Anything that removed content.
    Cut,
    /// Speed changes.
    Speed,
    /// Captions.
    Caption,
    /// Mutes and bleeps.
    Audio,
    /// Music.
    Music,
    /// Moves.
    Move,
    /// Any edit.
    Any,
}

/// What a conversational message is about.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum TalkTopic {
    /// "hi", "hello", "good morning".
    Greeting,
    /// "thanks", "great, thank you".
    Thanks,
    /// "what can you do?", "help".
    Help,
    /// "how long is my video?", "what are you editing?".
    Status,
    /// "what have you changed?", "show me the changes".
    History,
    /// Anything else friendly that is not about the video.
    Smalltalk,
}

/// Goals that need a question, never a guess.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum VagueGoal {
    /// "remove the boring bit".
    Boring,
    /// "make it shorter".
    Shorter,
}
