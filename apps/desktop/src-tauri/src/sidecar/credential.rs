//! The session credential: generated once, held in volatile memory, never printable.
//!
//! Architecture §13 gives the desktop session — not the sidecar — the job of producing the
//! session secret. This module is that generation and that custody, and it holds to the same
//! representation RES-375 validates on the Python side: **32 cryptographically random bytes,
//! unpadded URL-safe base64, exactly 43 ASCII characters**. The two halves of the contract
//! live in two repositories-of-record, so the shape is pinned by tests on both sides rather
//! than by a comment on one.
//!
//! Three properties are load-bearing:
//!
//! * **The bytes come from the operating system CSPRNG.** `getrandom` is the platform random
//!   source (``getrandom(2)``/``/dev/urandom`` semantics on Unix, ``BCryptGenRandom`` on
//!   Windows); there is no seeded generator, no fallback, and no user input anywhere in the
//!   path. A failure to obtain entropy is an error, never a weaker credential.
//! * **The secret cannot be printed by accident.** [`SessionCredential`] implements `Debug`
//!   as a redaction and implements neither `Display`, `Serialize`, nor `PartialEq`. The one
//!   way to obtain the characters is [`SessionCredential::expose`], whose name makes every
//!   call site a place a reviewer can see.
//! * **The secret is not persisted.** There is no `Serialize`, no file I/O, no environment
//!   lookup and no global; the value lives in this struct and dies when the session does.

use std::fmt;

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;

/// The entropy of the session credential: 32 cryptographically random bytes.
pub const CREDENTIAL_BYTES: usize = 32;

/// The encoded length of [`CREDENTIAL_BYTES`] as unpadded URL-safe base64.
///
/// Base64 pads to a multiple of four; 32 bytes encode to 44 characters and the trailing
/// ``=`` is dropped, so 43 is the only correct length and any other one is not this credential.
pub const CREDENTIAL_LENGTH: usize = 43;

/// The entropy source failed, so no credential was produced.
///
/// Deliberately not wrapping the platform error: the character of an OS random failure is
/// not something this process can act on, and a supervisor that saw the cause could not do
/// anything with it either.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CredentialError;

impl fmt::Display for CredentialError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("the operating system random source is unavailable")
    }
}

impl std::error::Error for CredentialError {}

/// One desktop session's credential, held as the encoded secret and nothing else.
///
/// The inner `String` is private to this module. There is no accessor other than
/// [`SessionCredential::expose`], so "the credential appears only where it is meant to" is a
/// property of the type rather than a rule callers are asked to remember.
#[derive(Clone)]
pub struct SessionCredential {
    secret: String,
}

impl SessionCredential {
    /// Generate a credential from the operating system CSPRNG.
    ///
    /// The only constructor, and the only place entropy enters the desktop shell.
    pub fn generate() -> Result<Self, CredentialError> {
        let mut bytes = [0_u8; CREDENTIAL_BYTES];
        getrandom::fill(&mut bytes).map_err(|_| CredentialError)?;
        Ok(Self {
            secret: URL_SAFE_NO_PAD.encode(bytes),
        })
    }

    /// The credential characters, for the two callers allowed to see them: the child's
    /// environment and the Tauri command that hands a ready session to the WebView.
    pub fn expose(&self) -> &str {
        &self.secret
    }
}

impl fmt::Debug for SessionCredential {
    /// A redaction, so a `{:?}` anywhere — a log line, a panic message, a future utility —
    /// cannot disclose the secret that would let a local process talk to the API.
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SessionCredential([redacted])")
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use base64::engine::general_purpose::URL_SAFE_NO_PAD;
    use base64::Engine as _;

    use super::{CredentialError, SessionCredential, CREDENTIAL_BYTES, CREDENTIAL_LENGTH};

    const URL_SAFE_ALPHABET: &str =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

    fn generated() -> SessionCredential {
        SessionCredential::generate().expect("the operating system random source must exist")
    }

    #[test]
    fn a_generated_credential_is_thirty_two_bytes_as_unpadded_url_safe_base64() {
        let credential = generated();

        assert_eq!(credential.expose().len(), CREDENTIAL_LENGTH);
        assert_eq!(CREDENTIAL_LENGTH, 43);
        assert!(credential.expose().is_ascii());
        assert!(
            !credential.expose().contains('='),
            "the credential is unpadded base64 by contract"
        );
        assert!(credential
            .expose()
            .chars()
            .all(|c| URL_SAFE_ALPHABET.contains(c)));

        let decoded = URL_SAFE_NO_PAD
            .decode(credential.expose())
            .expect("the credential must be valid unpadded URL-safe base64");
        assert_eq!(decoded.len(), CREDENTIAL_BYTES);
    }

    #[test]
    fn every_generated_credential_is_a_different_credential() {
        let credentials: HashSet<String> =
            (0..64).map(|_| generated().expose().to_string()).collect();

        assert_eq!(
            credentials.len(),
            64,
            "two sessions must not share a credential"
        );
    }

    #[test]
    fn the_debug_representation_never_contains_the_secret() {
        let credential = generated();

        let debug = format!("{credential:?}");

        assert!(!debug.contains(credential.expose()));
        assert_eq!(debug, "SessionCredential([redacted])");
    }

    #[test]
    fn a_cloned_credential_is_the_same_secret_and_still_redacted() {
        let credential = generated();
        let clone = credential.clone();

        assert_eq!(clone.expose(), credential.expose());
        assert!(!format!("{clone:?}").contains(clone.expose()));
    }

    #[test]
    fn the_entropy_failure_is_a_plain_bounded_value() {
        let error = CredentialError;

        assert!(!format!("{error}").is_empty());
        assert_eq!(format!("{error:?}"), "CredentialError");
    }
}
