//! Canned intents for tests: the resolver can be tested on exact intents
//! without depending on how any parser reads the words.

use std::collections::BTreeMap;

use crate::intent::Intent;
use crate::{Context, Parser};

/// Returns the intent registered for each exact message, else `Unknown`.
#[derive(Clone, Debug, Default)]
pub struct MockParser {
    canned: BTreeMap<String, Intent>,
}

impl MockParser {
    /// Registers the intent for a message.
    pub fn with(mut self, text: &str, intent: Intent) -> Self {
        self.canned.insert(text.to_owned(), intent);
        self
    }
}

impl Parser for MockParser {
    fn name(&self) -> String {
        "mock".into()
    }

    fn parse(&self, text: &str, _ctx: &Context) -> Intent {
        self.canned.get(text).cloned().unwrap_or(Intent::Unknown {
            reason: format!("mock parser has no intent for \"{text}\""),
        })
    }
}
