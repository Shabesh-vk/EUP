//! The default parser: an AI model reads plain English when one is set up,
//! and the built-in rules are the backup.
//!
//! - With a model: the model reads first. If it cannot (no network, no key,
//!   a refusal, or it does not understand), the rules try; if they read the
//!   words, their intent is used and the reply says so.
//! - Without a model: the rules alone, exactly as before.
//!
//! Either way the result is only an intent; the session resolves it.

use std::sync::Mutex;

use crate::intent::Intent;
use crate::llm::LlmParser;
use crate::rules::RulesParser;
use crate::{Context, Parser};

/// AI model first, rules as the backup.
pub struct AutoParser {
    model: Option<LlmParser>,
    last: Mutex<String>,
}

/// What the reader line says when the rules read the words.
pub const RULES: &str = "built-in phrases";

impl AutoParser {
    /// A parser using `model` when there is one.
    pub fn new(model: Option<LlmParser>) -> Self {
        Self {
            model,
            last: Mutex::new(String::new()),
        }
    }

    /// The model, if one is set up.
    pub fn model(&self) -> Option<&LlmParser> {
        self.model.as_ref()
    }

    fn said(&self, who: String) {
        if let Ok(mut l) = self.last.lock() {
            *l = who;
        }
    }
}

impl Parser for AutoParser {
    fn name(&self) -> String {
        match &self.model {
            Some(m) => format!("{} + rules", m.name()),
            None => "rules".into(),
        }
    }

    fn parse(&self, text: &str, ctx: &Context) -> Intent {
        let Some(model) = &self.model else {
            self.said(RULES.into());
            return RulesParser.parse(text, ctx);
        };
        match model.parse(text, ctx) {
            Intent::Unknown { reason } => {
                let backup = RulesParser.parse(text, ctx);
                if matches!(backup, Intent::Unknown { .. }) {
                    self.said(format!("AI model {}", model.label()));
                    Intent::Unknown { reason }
                } else {
                    self.said(format!("{RULES} (the AI model could not: {reason})"));
                    backup
                }
            }
            intent => {
                self.said(format!("AI model {}", model.label()));
                intent
            }
        }
    }

    fn choose(&self, reply: &str, question: &str, options: &[String]) -> Option<Option<usize>> {
        self.model.as_ref()?.choose_option(reply, question, options)
    }

    fn last_reader(&self) -> String {
        self.last.lock().map(|l| l.clone()).unwrap_or_default()
    }

    fn model_label(&self) -> Option<String> {
        self.model.as_ref().map(LlmParser::label)
    }
}
