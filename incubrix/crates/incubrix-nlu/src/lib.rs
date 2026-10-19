//! IncuBrix instruction understanding.
//!
//! Two halves, kept apart on purpose:
//!
//! 1. A [`Parser`] turns words into an [`Intent`] - data only. Three
//!    adapters, picked by `NLU_PROVIDER`: [`rules`] (default, deterministic),
//!    [`llm`] (Claude / OpenAI / Ollama, temperature 0, cached), [`mock`].
//! 2. The [`Session`] resolves intents against the current timeline in plain
//!    code: it finds the words, asks when there is more than one candidate,
//!    refuses what is impossible, and applies one transaction per instruction.
//!
//! An AI model never touches the timeline: the worst a bad parse can do is
//! produce the wrong intent, which the resolver still validates.
//!
//! Licence: MIT OR Apache-2.0. Never depends on Concat's `concat-*` crates.

pub mod answer;
pub mod auto;
pub mod intent;
pub mod llm;
pub mod mock;
pub mod rules;
pub mod semantic;
pub mod session;
pub mod times;

pub use intent::Intent;
pub use rules::RulesParser;
pub use session::{Action, Reply, Session};

use serde::Serialize;

/// What a parser may know about the project: enough to read references,
/// never enough to edit.
#[derive(Clone, PartialEq, Debug, Default, Serialize)]
pub struct Context {
    /// Edited length, seconds (rounded to ms).
    pub duration_s: f64,
    /// Captions now: (id, text).
    pub captions: Vec<(String, String)>,
    /// Speaker labels in the transcript.
    pub speakers: Vec<String>,
    /// The question waiting for an answer, if any.
    pub pending_question: Option<String>,
}

/// Words to an [`Intent`].
pub trait Parser: Send {
    /// The adapter's name and model, for the manifest.
    fn name(&self) -> String;
    /// The meaning of one message.
    fn parse(&self, text: &str, ctx: &Context) -> Intent;
    /// Which option of a waiting question a free-form reply picks, for
    /// replies the plain matcher could not read: `Some(Some(i))` option `i`,
    /// `Some(None)` a cancel, `None` not an answer. Only models implement it.
    fn choose(&self, _reply: &str, _question: &str, _options: &[String]) -> Option<Option<usize>> {
        None
    }
    /// Who read the last message, for people: "AI model ..." or "built-in rules".
    fn last_reader(&self) -> String {
        self.name()
    }
    /// The AI model behind this parser, for people; `None` for rules alone.
    fn model_label(&self) -> Option<String> {
        None
    }
}

pub use auto::AutoParser;

/// The parser the environment sets up. `NLU_PROVIDER=rules` or `mock` pick
/// those alone; otherwise an AI model reads the words when one is configured
/// (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or a local Ollama), with the
/// built-in rules as the backup; with no model, the rules alone.
pub fn parser_from_env() -> Box<dyn Parser> {
    match std::env::var("NLU_PROVIDER")
        .unwrap_or_default()
        .to_lowercase()
        .as_str()
    {
        "rules" => Box::new(RulesParser),
        "mock" => Box::new(mock::MockParser::default()),
        _ => Box::new(AutoParser::new(
            llm::LlmConfig::detected().map(llm::LlmParser::new),
        )),
    }
}
