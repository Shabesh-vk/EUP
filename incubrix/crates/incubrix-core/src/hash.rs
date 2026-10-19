//! `timeline_hash`: SHA-256 of the timeline's canonical JSON.
//!
//! The timeline holds only integers, strings and ordered lists, and serde
//! writes struct fields in declaration order, so the JSON is byte-identical
//! for identical timelines. Nothing session-specific (ids of HTTP requests,
//! wall-clock times, presigned URLs) is part of a `Timeline`, so it cannot
//! leak into the hash.

use sha2::{Digest, Sha256};

use crate::timeline::Timeline;

/// Lower-case hex SHA-256 of the canonical timeline JSON.
pub fn timeline_hash(t: &Timeline) -> String {
    let bytes = serde_json::to_vec(t).expect("a timeline always serialises");
    let digest = Sha256::digest(&bytes);
    digest.iter().map(|b| format!("{b:02x}")).collect()
}
