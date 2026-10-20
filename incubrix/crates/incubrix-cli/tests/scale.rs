//! Outstanding level: scale and imperfect data, as `incubrix metrics`
//! measures them.

use incubrix_cli::metrics::{latency, word_clipping};

/// On a 60-minute video every instruction answers in under 3 seconds
/// (transcription and rendering excluded). Timed in release builds only:
/// a debug build is several times slower and says nothing about the product.
#[test]
fn sixty_minutes_every_instruction_under_3_s() {
    let l = latency(60);
    assert!(l.words > 6000, "{} words", l.words);
    if cfg!(debug_assertions) {
        eprintln!(
            "debug build: timings not checked ({} ms slowest)",
            l.slowest_ms
        );
        return;
    }
    assert!(
        l.slowest_ms < 3000.0,
        "slowest {} ms: {}",
        l.slowest_ms,
        l.slowest
    );
}

/// 20 cuts typed at times inside words: no edge is left inside a word.
#[test]
fn twenty_cuts_clip_no_word() {
    let (cuts, clipped) = word_clipping();
    assert_eq!(cuts, 20);
    assert_eq!(clipped, 0);
}
