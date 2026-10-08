//! The minimal Tauri surface: one command and one event, carrying session plumbing only.
//!
//! Architecture §13 and RES-376 bound what the WebView may learn from the desktop shell: the
//! current API session's status, where the API is when it is ready, under which versions,
//! and — only while ready — the credential it must present. RES-378 builds the typed client
//! on this; nothing scientific, no process identifier, no stderr, no path, and no way to
//! influence a launch crosses this boundary.
//!
//! The command is [`get_api_session`]. The event is [`API_STATUS_EVENT`], emitted to the
//! main WebView on every lifecycle change with the non-secret [`SessionSnapshot`] payload, so
//! the frontend can react without polling. The event payload type has no credential field at
//! all, which is what makes "no credential through events" structural rather than a rule.
//!
//! The response type is also the one place a credential is intentionally exposed — to the
//! WebView that must use it — so its `Debug` is a redaction and its credential is populated
//! from the session state only for a ready session. A `starting` or `failed` response has no
//! credential and no origin, in the type's own construction rather than by convention.

use std::fmt;
use std::sync::Arc;

use serde::Serialize;
use tauri::State;

use crate::sidecar::{SessionCredential, SessionSnapshot, SessionStatus, Supervisor};

/// The one WebView this shell's targeted events are addressed to.
pub const MAIN_WINDOW: &str = "main";

/// The one lifecycle event name.
pub const API_STATUS_EVENT: &str = "dynamisbench-api-status";

/// The `get_api_session` response: the current session, as the WebView needs to see it.
#[derive(Serialize)]
pub struct ApiSessionResponse {
    pub status: SessionStatus,
    pub origin: Option<String>,
    pub api_version: Option<String>,
    pub protocol_version: Option<u32>,
    pub credential: Option<String>,
    pub restart_required: bool,
    pub failure: Option<crate::sidecar::FailureCode>,
}

impl ApiSessionResponse {
    /// The response for one supervisor, from its current state.
    pub fn for_supervisor(supervisor: &Supervisor) -> Self {
        Self::from_parts(&supervisor.snapshot(), supervisor.credential().as_ref())
    }

    fn from_parts(snapshot: &SessionSnapshot, credential: Option<&SessionCredential>) -> Self {
        let ready = snapshot.status == SessionStatus::Ready;
        Self {
            status: snapshot.status,
            origin: snapshot.origin.clone(),
            api_version: snapshot.api_version.clone(),
            protocol_version: snapshot.protocol_version,
            // The one place the credential is rendered as text for the WebView, and only for
            // the state that has an API to call. A stale credential beside a non-ready
            // snapshot is dropped rather than reported.
            credential: if ready {
                credential.map(|credential| credential.expose().to_string())
            } else {
                None
            },
            restart_required: snapshot.restart_required,
            failure: snapshot.failure,
        }
    }
}

impl fmt::Debug for ApiSessionResponse {
    /// A redaction for the one structure that carries the credential as a string.
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ApiSessionResponse")
            .field("status", &self.status)
            .field("origin", &self.origin)
            .field("api_version", &self.api_version)
            .field("protocol_version", &self.protocol_version)
            .field(
                "credential",
                &self.credential.as_ref().map(|_| "[redacted]"),
            )
            .field("restart_required", &self.restart_required)
            .field("failure", &self.failure)
            .finish()
    }
}

/// The one session command: what RES-378's client calls to bootstrap.
#[tauri::command]
pub fn get_api_session(supervisor: State<'_, Arc<Supervisor>>) -> ApiSessionResponse {
    ApiSessionResponse::for_supervisor(supervisor.inner())
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{ApiSessionResponse, API_STATUS_EVENT, MAIN_WINDOW};
    use crate::sidecar::{FailureCode, SessionCredential, SessionSnapshot, SessionStatus};

    fn credential() -> SessionCredential {
        SessionCredential::generate().expect("the operating system random source must exist")
    }

    fn ready_snapshot() -> SessionSnapshot {
        SessionSnapshot::ready("http://127.0.0.1:49152".to_string(), "v1".to_string(), 1)
    }

    #[test]
    fn the_surface_is_one_event_on_the_main_webview() {
        assert_eq!(MAIN_WINDOW, "main");
        assert_eq!(API_STATUS_EVENT, "dynamisbench-api-status");
    }

    #[test]
    fn a_ready_response_carries_the_credential_and_the_real_origin() {
        let credential = credential();
        let response = ApiSessionResponse::from_parts(&ready_snapshot(), Some(&credential));

        assert_eq!(response.status, SessionStatus::Ready);
        assert_eq!(response.origin.as_deref(), Some("http://127.0.0.1:49152"));
        assert_eq!(response.api_version.as_deref(), Some("v1"));
        assert_eq!(response.protocol_version, Some(1));
        assert_eq!(response.credential.as_deref(), Some(credential.expose()));
        assert!(!response.restart_required);
        assert_eq!(response.failure, None);
    }

    #[test]
    fn a_failed_response_carries_no_credential_and_no_fake_origin() {
        for status in [
            SessionStatus::Starting,
            SessionStatus::Failed,
            SessionStatus::Stopped,
        ] {
            let snapshot = match status {
                SessionStatus::Starting => SessionSnapshot::starting(),
                SessionStatus::Failed => SessionSnapshot::failed(FailureCode::UnexpectedExit, true),
                _ => SessionSnapshot::stopped(),
            };

            let response = ApiSessionResponse::from_parts(&snapshot, Some(&credential()));

            assert_eq!(response.status, status);
            assert_eq!(
                response.credential, None,
                "{status:?} must not carry a credential"
            );
            assert_eq!(response.origin, None, "{status:?} must not carry an origin");
            assert_eq!(response.api_version, None);
            assert_eq!(response.protocol_version, None);
        }
    }

    #[test]
    fn the_response_serializes_with_exactly_the_published_fields() {
        let credential = credential();

        let value = serde_json::to_value(ApiSessionResponse::from_parts(
            &ready_snapshot(),
            Some(&credential),
        ))
        .unwrap();

        assert_eq!(
            value,
            json!({
                "status": "ready",
                "origin": "http://127.0.0.1:49152",
                "api_version": "v1",
                "protocol_version": 1,
                "credential": credential.expose(),
                "restart_required": false,
                "failure": null,
            })
        );
        assert_eq!(value.as_object().unwrap().len(), 7);
    }

    #[test]
    fn the_response_debug_never_contains_the_credential() {
        let credential = credential();
        let response = ApiSessionResponse::from_parts(&ready_snapshot(), Some(&credential));

        let debug = format!("{response:?}");

        assert!(!debug.contains(credential.expose()));
        assert!(debug.contains("[redacted]"));
    }

    #[test]
    fn the_lifecycle_event_payload_has_no_credential_field_and_never_names_one() {
        let credential = credential();

        let value = serde_json::to_value(ready_snapshot()).unwrap();

        assert!(value.get("credential").is_none());
        assert!(value.get("token").is_none());
        assert_eq!(value.as_object().unwrap().len(), 6);
        assert!(!value.to_string().contains(credential.expose()));
    }
}
