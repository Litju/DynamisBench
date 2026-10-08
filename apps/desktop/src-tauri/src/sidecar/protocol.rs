//! The machine-readable contract on the child's streams, in both directions.
//!
//! RES-375 defined one direction of this protocol: the sidecar writes exactly one readiness
//! record to stdout, and RES-376 must parse it strictly. RES-376 adds the other direction:
//! the supervisor writes exactly one shutdown record to the child's stdin. Both records are
//! modeled here, next to each other, so the two halves of the contract cannot drift.
//!
//! Strictness on the readiness side is the point of the module. A supervisor that accepts a
//! superset of the protocol can be handed a record that means something else and act on it,
//! so the model rejects extra fields outright, requires the four literal facts worth
//! requiring — kind, protocol version, loopback host, non-zero port — and refuses every type
//! coercion serde would otherwise perform. What remains, `api_version`, is required to be
//! present and non-empty; the supervisor stores it and reports it, and deliberately does not
//! interpret it.
//!
//! The shutdown record has no fields a caller can vary: one kind and one version, both
//! constants. It carries no credential (Architecture §13), so the control channel cannot
//! become a second place a secret travels.

use serde::{Deserialize, Serialize};

/// The one record kind that means the sidecar is listening.
pub const READY_KIND: &str = "dynamisbench.api.ready";

/// The supervisor/sidecar protocol version this shell speaks.
pub const PROTOCOL_VERSION: u32 = 1;

/// The one address a readiness record may announce.
pub const LOOPBACK_HOST: &str = "127.0.0.1";

/// The one record kind the supervisor may send to ask for shutdown.
pub const SHUTDOWN_KIND: &str = "dynamisbench.api.shutdown";

/// The readiness record, as a closed shape.
///
/// `deny_unknown_fields` is the whole first line of defense against a sidecar that grew a
/// field this supervisor does not understand: rather than silently ignoring it, the record
/// is refused and the session fails as a protocol error. Every field is required and every
/// type is exact, so a missing field, a coerced port, or a numeric protocol version sent as
/// a string all fail at the same boundary.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Readiness {
    pub kind: String,
    pub protocol_version: u32,
    pub api_version: String,
    pub host: String,
    pub port: u16,
}

impl Readiness {
    /// The HTTP origin the WebView will call, derived from the announced address.
    pub fn origin(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }
}

/// A readiness line that is not the protocol, with a bounded reason for diagnosis.
///
/// The reason is a static category, never the line's content: a supervisor's diagnostic must
/// not repeat whatever a misbehaving child wrote, for the same reason it must not repeat a
/// credential — the content is not trusted, and there is nothing a caller could do with it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvalidReadiness(pub &'static str);

/// Parse one stdout line as the exact readiness record of protocol v1.
pub fn parse_readiness(line: &str) -> Result<Readiness, InvalidReadiness> {
    let readiness: Readiness = serde_json::from_str(line).map_err(|_| {
        InvalidReadiness("a line that is not a readiness record of the expected shape")
    })?;

    if readiness.kind != READY_KIND {
        return Err(InvalidReadiness("a readiness record with a different kind"));
    }
    if readiness.protocol_version != PROTOCOL_VERSION {
        return Err(InvalidReadiness(
            "a readiness record with a different protocol version",
        ));
    }
    if readiness.host != LOOPBACK_HOST {
        return Err(InvalidReadiness(
            "a readiness record that did not bind loopback",
        ));
    }
    if readiness.port == 0 {
        return Err(InvalidReadiness("a readiness record with no selected port"));
    }
    if readiness.api_version.is_empty() {
        return Err(InvalidReadiness("a readiness record with no API version"));
    }

    Ok(readiness)
}

/// The shutdown record, serialized in one place so the child and the supervisor agree.
#[derive(Debug, Serialize)]
struct ShutdownRecord {
    kind: &'static str,
    protocol_version: u32,
}

/// The exact bytes of the shutdown request, including the terminating newline.
///
/// Produced by the same serializer that produces the child's records, so the JSON is valid by
/// construction rather than by string formatting. The bytes are pinned by a test against the
/// literal RES-376 states, because this is a cross-process contract and a canonical spelling
/// is cheaper to verify than any parser is to trust.
pub fn shutdown_line() -> String {
    let record = ShutdownRecord {
        kind: SHUTDOWN_KIND,
        protocol_version: PROTOCOL_VERSION,
    };
    let mut line = serde_json::to_string(&record)
        .expect("a two-field record of strings and integers cannot fail to serialize");
    line.push('\n');
    line
}

#[cfg(test)]
mod tests {
    use super::{
        parse_readiness, shutdown_line, InvalidReadiness, LOOPBACK_HOST, PROTOCOL_VERSION,
        READY_KIND, SHUTDOWN_KIND,
    };

    fn record(port: u16) -> String {
        format!(
            r#"{{"kind":"{READY_KIND}","protocol_version":{PROTOCOL_VERSION},"api_version":"v1","host":"{LOOPBACK_HOST}","port":{port}}}"#
        )
    }

    #[test]
    fn a_valid_readiness_record_parses_and_derives_its_origin() {
        let readiness = parse_readiness(&record(49152)).expect("the exact record must parse");

        assert_eq!(readiness.kind, READY_KIND);
        assert_eq!(readiness.protocol_version, PROTOCOL_VERSION);
        assert_eq!(readiness.api_version, "v1");
        assert_eq!(readiness.host, LOOPBACK_HOST);
        assert_eq!(readiness.port, 49152);
        assert_eq!(readiness.origin(), "http://127.0.0.1:49152");
    }

    #[test]
    fn the_ephemeral_range_is_accepted_at_its_edges() {
        assert_eq!(parse_readiness(&record(1)).unwrap().port, 1);
        assert_eq!(parse_readiness(&record(65_535)).unwrap().port, 65_535);
    }

    #[test]
    fn a_record_that_is_not_json_is_refused() {
        for line in ["", " ", "not json", "{", "[]", "null", "{}"] {
            assert!(parse_readiness(line).is_err(), "{line:?} must be refused");
        }
    }

    #[test]
    fn every_required_field_is_required() {
        let fields = [
            "\"kind\":\"dynamisbench.api.ready\"",
            "\"protocol_version\":1",
            "\"api_version\":\"v1\"",
            "\"host\":\"127.0.0.1\"",
            "\"port\":49152",
        ];

        for missing in fields {
            let line = format!(
                "{{{}}}",
                fields
                    .iter()
                    .filter(|field| **field != missing)
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(",")
            );
            assert!(
                parse_readiness(&line).is_err(),
                "a record missing {missing} must be refused: {line}"
            );
        }
    }

    #[test]
    fn an_extra_field_is_refused_rather_than_ignored() {
        let line = record(49152).replace(
            "\"port\":49152",
            "\"port\":49152,\"token\":\"not-a-credential\"",
        );

        assert_eq!(
            parse_readiness(&line).unwrap_err(),
            InvalidReadiness("a line that is not a readiness record of the expected shape")
        );
    }

    #[test]
    fn a_different_kind_is_refused() {
        let line = record(49152).replace(READY_KIND, "dynamisbench.api.ready.v2");

        assert_eq!(
            parse_readiness(&line).unwrap_err(),
            InvalidReadiness("a readiness record with a different kind")
        );
    }

    #[test]
    fn a_different_protocol_version_is_refused() {
        for version in [0, 2, 3] {
            let line = record(49152).replace(
                "\"protocol_version\":1",
                &format!("\"protocol_version\":{version}"),
            );
            assert_eq!(
                parse_readiness(&line).unwrap_err(),
                InvalidReadiness("a readiness record with a different protocol version")
            );
        }
    }

    #[test]
    fn a_host_that_is_not_loopback_is_refused() {
        for host in ["0.0.0.0", "localhost", "::1", "192.168.1.10", "127.0.0.2"] {
            let line =
                record(49152).replace("\"host\":\"127.0.0.1\"", &format!("\"host\":\"{host}\""));
            assert_eq!(
                parse_readiness(&line).unwrap_err(),
                InvalidReadiness("a readiness record that did not bind loopback"),
                "{host} must be refused"
            );
        }
    }

    #[test]
    fn a_port_outside_the_tcp_range_is_refused() {
        for port in [0, 65_536, 70_000] {
            let line = record(49152).replace("\"port\":49152", &format!("\"port\":{port}"));
            assert!(
                parse_readiness(&line).is_err(),
                "port {port} must be refused"
            );
        }
    }

    #[test]
    fn a_coerced_field_is_refused() {
        for line in [
            record(49152).replace("\"port\":49152", "\"port\":\"49152\""),
            record(49152).replace("\"port\":49152", "\"port\":49152.0"),
            record(49152).replace("\"protocol_version\":1", "\"protocol_version\":\"1\""),
            record(49152).replace("\"api_version\":\"v1\"", "\"api_version\":1"),
            record(49152).replace("\"port\":49152", "\"port\":true"),
        ] {
            assert!(parse_readiness(&line).is_err(), "{line} must be refused");
        }
    }

    #[test]
    fn an_empty_api_version_is_refused() {
        let line = record(49152).replace("\"api_version\":\"v1\"", "\"api_version\":\"\"");

        assert_eq!(
            parse_readiness(&line).unwrap_err(),
            InvalidReadiness("a readiness record with no API version")
        );
    }

    #[test]
    fn trailing_content_after_the_record_is_refused() {
        let line = format!("{} extra", record(49152));

        assert!(parse_readiness(&line).is_err());
    }

    #[test]
    fn the_shutdown_line_is_exactly_the_published_bytes() {
        assert_eq!(
            shutdown_line(),
            "{\"kind\":\"dynamisbench.api.shutdown\",\"protocol_version\":1}\n"
        );
        assert_eq!(SHUTDOWN_KIND, "dynamisbench.api.shutdown");
    }

    #[test]
    fn the_shutdown_line_carries_no_credential_and_no_free_form_value() {
        let line = shutdown_line();
        let parsed: serde_json::Value = serde_json::from_str(line.trim()).unwrap();

        assert_eq!(
            parsed,
            serde_json::json!({"kind": "dynamisbench.api.shutdown", "protocol_version": 1})
        );
        assert_eq!(parsed.as_object().unwrap().len(), 2);
    }

    #[test]
    fn the_readiness_model_has_exactly_the_five_published_fields() {
        let parsed: serde_json::Value =
            serde_json::from_str(&record(49152)).expect("the fixture itself must be valid JSON");

        assert_eq!(parsed.as_object().unwrap().len(), 5);
        assert!(parsed.get("token").is_none());
        assert!(parsed.get("pid").is_none());
        assert!(parsed.get("path").is_none());
    }
}
