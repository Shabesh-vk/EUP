//! The one answer every instruction gets: applied, needs clarification, or
//! rejected - in the shape the brief's session runner expects.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::history::{ApplyReport, Project};
use crate::resolve::TIME_POLICY;
use crate::time::to_secs_ms;
use crate::EditError;

/// Which of the three answers.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    /// Done; `operations` and `summary` say what.
    Applied,
    /// Not done; `question` and `options` say what to answer.
    NeedsClarification,
    /// Not done; `summary` says why.
    Rejected,
}

/// The response to one instruction.
#[derive(Clone, PartialEq, Debug, Serialize, Deserialize, JsonSchema)]
pub struct Outcome {
    /// Which answer.
    pub status: Status,
    /// What was done, one line each.
    pub operations: Vec<String>,
    /// Before/after in a sentence, or the reason for a rejection.
    pub summary: String,
    /// The question, when one is asked.
    pub question: Option<String>,
    /// Choices for the question.
    pub options: Vec<String>,
    /// Consequences and doubts worth knowing.
    pub warnings: Vec<String>,
    /// Always "current": typed times are current playback time.
    pub time_policy: String,
    /// Hash of the timeline after this step.
    pub timeline_hash: String,
    /// Length of the edited video after this step, seconds.
    pub duration_s: f64,
    /// The transaction recorded, if any.
    pub tx: Option<u32>,
    /// For a rejection: the UPPER_SNAKE_CASE reason code.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
}

impl Outcome {
    /// An applied edit.
    pub fn applied(report: ApplyReport, summary: String) -> Self {
        Self {
            status: Status::Applied,
            operations: report.operations,
            summary,
            question: None,
            options: vec![],
            warnings: report.warnings,
            time_policy: TIME_POLICY.into(),
            timeline_hash: report.timeline_hash,
            duration_s: to_secs_ms(report.after_duration),
            tx: report.tx,
            code: None,
        }
    }

    /// A question; nothing changed.
    pub fn clarify(p: &Project, question: String, options: Vec<String>) -> Self {
        Self::unchanged(
            p,
            Status::NeedsClarification,
            String::new(),
            Some(question),
            options,
        )
    }

    /// A refusal; nothing changed.
    pub fn rejected(p: &Project, reason: String) -> Self {
        Self::unchanged(p, Status::Rejected, reason, None, vec![])
    }

    /// A refusal with its reason code; nothing changed.
    pub fn rejected_with(p: &Project, code: &str, reason: String) -> Self {
        Self {
            code: Some(code.to_owned()),
            ..Self::rejected(p, reason)
        }
    }

    /// A refusal from an [`EditError`]; nothing changed.
    pub fn from_error(p: &Project, e: &EditError) -> Self {
        Self::rejected_with(p, e.code(), e.to_string())
    }

    fn unchanged(
        p: &Project,
        status: Status,
        summary: String,
        question: Option<String>,
        options: Vec<String>,
    ) -> Self {
        let tl = p.timeline().timeline;
        Self {
            status,
            operations: vec![],
            summary,
            question,
            options,
            warnings: vec![],
            time_policy: TIME_POLICY.into(),
            timeline_hash: crate::hash::timeline_hash(&tl),
            duration_s: to_secs_ms(tl.duration),
            tx: None,
            code: None,
        }
    }
}
