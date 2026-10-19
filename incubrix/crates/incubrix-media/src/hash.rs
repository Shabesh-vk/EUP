//! The source fingerprint. Taken at intake, checked again after every
//! render: the original must come out byte-for-byte as it went in.

use std::fs::File;
use std::io::Read;
use std::path::Path;

use sha2::{Digest, Sha256};

use crate::MediaError;

/// SHA-256 of a file, lower-case hex.
pub fn sha256_file(path: &Path) -> Result<String, MediaError> {
    let mut f = File::open(path)
        .map_err(|e| MediaError::Io(format!("cannot open {}: {e}", path.display())))?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 16];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(hex(&h.finalize()))
}

/// SHA-256 of bytes, lower-case hex.
pub fn sha256_bytes(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Fails with [`MediaError::SourceChanged`] when the file no longer has the
/// hash recorded at intake.
pub fn verify_unchanged(path: &Path, expected: &str) -> Result<(), MediaError> {
    let found = sha256_file(path)?;
    if found != expected {
        return Err(MediaError::SourceChanged {
            expected: expected.to_owned(),
            found,
        });
    }
    Ok(())
}
