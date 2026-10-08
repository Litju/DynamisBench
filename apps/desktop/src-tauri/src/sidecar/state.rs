//! The bounded lifecycle vocabulary: what the shell may be in, and what it may say failed.
//!
//! RES-376 requires one explicit lifecycle model — `starting`, `ready`, `failed`, `stopped` —
//! with a failure vocabulary that is closed. This module is that vocabulary, and the reason
//! it exists separately from the supervisor is the WebView boundary: a snapshot is the only
//! thing that travels out of the process owner, and every field of it is chosen here rather
//! than being derived from whatever the child happened to say.
//!
//! Three rules are structural rather than conventional:
//!
//! * **A snapshot cannot carry a credential.** [`SessionSnapshot`] has no such field and is
//!   the only serializable type here; [`SessionState`] holds the credential beside the
//!   snapshot rather than inside it, so the event payload's type makes the leak impossible
//!   instead of screening it.
//! * **A failure has no free-form text.** [`FailureCode`] is an enum, and the frontend sees
//!   one of its names or nothing — never a stderr line, a path, an exit code or a reason
//!   string the child chose.
//! * **A snapshot and its credential are only ever read together.** What the WebView needs
//!   to bootstrap is not one value but a *pair*, and the pair is captured as one value —
//!   [`SessionBootstrap`] — under a single critical section. Reading the two separately
//!   looks harmless and is not: the monitor moves `ready → failed/stopped` on its own
//!   thread, so two reads can straddle that transition and report `status = ready` with no
//!   credential, which asks the frontend to call an address it cannot authenticate against.
//!   [`SessionBootstrap`] exists so that response cannot be assembled from two instants.

use serde::Serialize;

use crate::sidecar::credential::SessionCredential;

/// The four states a desktop session's sidecar lifecycle can be in.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionStatus {
    /// A child has been requested or spawned; readiness has not been resolved.
    Starting,
    /// A valid readiness record was received; the child is listening.
    Ready,
    /// The session is over with a bounded failure code.
    Failed,
    /// The session ended without a failure: a requested shutdown completed, or no child ran.
    Stopped,
}

/// The closed set of ways a session can fail.
///
/// Bounded on purpose: the frontend branches on these, so adding one is a frontend-visible
/// contract change rather than an implementation detail. None of them is a message — the
/// variant *is* the diagnosis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FailureCode {
    /// The child process could not be created at all.
    SpawnFailed,
    /// The operating system random source could not produce a session credential.
    CredentialUnavailable,
    /// No valid readiness record arrived before the startup deadline.
    StartupTimeout,
    /// The first stdout line was not the exact protocol v1 readiness record.
    ReadinessProtocolError,
    /// The child exited before readiness, whether or not it said anything.
    SidecarStartupExit,
    /// The child wrote to the protocol channel after readiness.
    ProtocolViolation,
    /// The child died after readiness without having been asked to stop.
    UnexpectedExit,
    /// The child did not exit within the graceful-shutdown deadline and was force-terminated.
    ShutdownTimeout,
}

/// Everything the WebView may learn about the session, and nothing more.
///
/// `origin`, `api_version` and `protocol_version` are present exactly when the session is
/// ready; a failed snapshot carries no half-remembered address. `restart_required` is true
/// only for the failures that ended an established session, because that is the condition a
/// user-facing affordance would act on.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SessionSnapshot {
    pub status: SessionStatus,
    pub origin: Option<String>,
    pub api_version: Option<String>,
    pub protocol_version: Option<u32>,
    pub restart_required: bool,
    pub failure: Option<FailureCode>,
}

impl SessionSnapshot {
    /// No child has run, and none failed.
    pub fn stopped() -> Self {
        Self {
            status: SessionStatus::Stopped,
            origin: None,
            api_version: None,
            protocol_version: None,
            restart_required: false,
            failure: None,
        }
    }

    /// A child has been requested; its readiness is not yet known.
    pub fn starting() -> Self {
        Self {
            status: SessionStatus::Starting,
            ..Self::stopped()
        }
    }

    /// A ready session, with only the three facts a client needs to connect.
    pub fn ready(origin: String, api_version: String, protocol_version: u32) -> Self {
        Self {
            status: SessionStatus::Ready,
            origin: Some(origin),
            api_version: Some(api_version),
            protocol_version: Some(protocol_version),
            restart_required: false,
            failure: None,
        }
    }

    /// A failed session, with a bounded reason and no address.
    pub fn failed(failure: FailureCode, restart_required: bool) -> Self {
        Self {
            status: SessionStatus::Failed,
            origin: None,
            api_version: None,
            protocol_version: None,
            restart_required,
            failure: Some(failure),
        }
    }
}

/// A start attempt was refused because a session is already starting or ready.
///
/// The one-process-per-session invariant, stated as an error rather than as a check a caller
/// is trusted to perform.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StartRefused;

/// One atomic capture of everything a bootstrap reader may publish.
///
/// The snapshot and the credential are captured together, so they always describe the same
/// state version. The invariant is enforced on capture rather than trusted to the caller's
/// use of two fields: a `ready` capture carries a credential and an origin, and any other
/// capture carries neither — the credential is dropped unless the captured snapshot is
/// `ready`, so a transition that raced this capture cannot leave a credential beside a
/// non-ready status.
///
/// Its fields are private and there is no constructor that takes a snapshot and a credential
/// separately, which is what makes the torn response unrepresentable rather than merely
/// discouraged.
#[derive(Debug)]
pub struct SessionBootstrap {
    snapshot: SessionSnapshot,
    credential: Option<SessionCredential>,
}

impl SessionBootstrap {
    /// The non-secret snapshot, captured with the credential beside it.
    pub fn snapshot(&self) -> &SessionSnapshot {
        &self.snapshot
    }

    /// The credential belonging to the captured state, if it was `ready`.
    pub fn credential(&self) -> Option<&SessionCredential> {
        self.credential.as_ref()
    }
}

/// The current snapshot plus the credential that belongs to a ready session.
///
/// The credential is deliberately not part of [`SessionSnapshot`]. It is set by the ready
/// transition, dropped by every later one, and read only through [`SessionState::bootstrap`]
/// — the single capture that hands a ready session to the WebView, which is the only place
/// the architecture allows it to go.
#[derive(Debug)]
pub struct SessionState {
    snapshot: SessionSnapshot,
    credential: Option<SessionCredential>,
}

impl Default for SessionState {
    fn default() -> Self {
        Self::stopped()
    }
}

impl SessionState {
    /// The state before any child has run.
    pub fn stopped() -> Self {
        Self {
            snapshot: SessionSnapshot::stopped(),
            credential: None,
        }
    }

    /// The current non-secret snapshot.
    pub fn snapshot(&self) -> &SessionSnapshot {
        &self.snapshot
    }

    /// Capture the snapshot and its credential together, under the caller's one lock.
    ///
    /// The whole reason this exists. Every transition runs under the same lock as this read,
    /// so a capture describes exactly one state version, and the credential is reported only
    /// for a captured `ready` state: a capture either has a status with an address and a
    /// credential to use against it, or has neither.
    pub fn bootstrap(&self) -> SessionBootstrap {
        let credential = if self.snapshot.status == SessionStatus::Ready {
            self.credential.clone()
        } else {
            None
        };
        SessionBootstrap {
            snapshot: self.snapshot.clone(),
            credential,
        }
    }

    /// Enter `starting`, refusing a second concurrent session.
    pub fn begin(&mut self) -> Result<(), StartRefused> {
        if matches!(
            self.snapshot.status,
            SessionStatus::Starting | SessionStatus::Ready
        ) {
            return Err(StartRefused);
        }
        self.snapshot = SessionSnapshot::starting();
        self.credential = None;
        Ok(())
    }

    /// Enter `ready` and take custody of the credential.
    pub fn mark_ready(
        &mut self,
        origin: String,
        api_version: String,
        protocol_version: u32,
        credential: SessionCredential,
    ) {
        self.snapshot = SessionSnapshot::ready(origin, api_version, protocol_version);
        self.credential = Some(credential);
    }

    /// Enter `failed`; the credential is dropped with the session.
    pub fn mark_failed(&mut self, failure: FailureCode, restart_required: bool) {
        self.snapshot = SessionSnapshot::failed(failure, restart_required);
        self.credential = None;
    }

    /// Enter `stopped`; the credential is dropped with the session.
    pub fn mark_stopped(&mut self) {
        self.snapshot = SessionSnapshot::stopped();
        self.credential = None;
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::{FailureCode, SessionSnapshot, SessionState, SessionStatus, StartRefused};
    use crate::sidecar::credential::SessionCredential;

    fn credential() -> SessionCredential {
        SessionCredential::generate().expect("the operating system random source must exist")
    }

    fn ready_state() -> SessionState {
        let mut state = SessionState::stopped();
        state.begin().expect("the first start is allowed");
        state.mark_ready(
            "http://127.0.0.1:49152".to_string(),
            "v1".to_string(),
            1,
            credential(),
        );
        state
    }

    #[test]
    fn the_lifecycle_starts_stopped_and_transitions_in_order() {
        let mut state = SessionState::stopped();

        assert_eq!(state.snapshot().status, SessionStatus::Stopped);
        assert_eq!(state.begin(), Ok(()));
        assert_eq!(state.snapshot().status, SessionStatus::Starting);
        assert!(state.bootstrap().credential().is_none());

        state.mark_ready(
            "http://127.0.0.1:49152".to_string(),
            "v1".to_string(),
            1,
            credential(),
        );

        let ready = state.snapshot().clone();
        assert_eq!(ready.status, SessionStatus::Ready);
        assert_eq!(ready.origin.as_deref(), Some("http://127.0.0.1:49152"));
        assert_eq!(ready.api_version.as_deref(), Some("v1"));
        assert_eq!(ready.protocol_version, Some(1));
        assert!(!ready.restart_required);
        assert_eq!(ready.failure, None);
        assert!(state.bootstrap().credential().is_some());
    }

    #[test]
    fn a_second_session_is_refused_while_one_is_starting_or_ready() {
        let mut state = SessionState::stopped();

        state.begin().expect("the first start is allowed");
        assert_eq!(state.begin(), Err(StartRefused));

        state.mark_ready(
            "http://127.0.0.1:49152".to_string(),
            "v1".to_string(),
            1,
            credential(),
        );

        assert_eq!(state.begin(), Err(StartRefused));
        assert_eq!(state.snapshot().status, SessionStatus::Ready);
    }

    #[test]
    fn a_failed_session_drops_the_credential_and_keeps_the_bounded_failure() {
        let mut state = ready_state();

        state.mark_failed(FailureCode::UnexpectedExit, true);

        let failed = state.snapshot().clone();
        assert_eq!(failed.status, SessionStatus::Failed);
        assert_eq!(failed.failure, Some(FailureCode::UnexpectedExit));
        assert!(failed.restart_required);
        assert_eq!(
            failed.origin, None,
            "a failed session has no address to report"
        );
        assert!(state.bootstrap().credential().is_none());
    }

    #[test]
    fn a_stopped_session_drops_the_credential_too() {
        let mut state = ready_state();

        state.mark_stopped();

        assert_eq!(state.snapshot().status, SessionStatus::Stopped);
        assert!(state.bootstrap().credential().is_none());
        assert_eq!(state.snapshot().failure, None);
    }

    #[test]
    fn a_ready_snapshot_serializes_without_a_credential_or_a_path() {
        let snapshot =
            SessionSnapshot::ready("http://127.0.0.1:49152".to_string(), "v1".to_string(), 1);

        let value: Value = serde_json::to_value(&snapshot).unwrap();

        assert_eq!(
            value,
            json!({
                "status": "ready",
                "origin": "http://127.0.0.1:49152",
                "api_version": "v1",
                "protocol_version": 1,
                "restart_required": false,
                "failure": null,
            })
        );
        let object = value.as_object().unwrap();
        assert_eq!(object.len(), 6, "the snapshot has exactly these six fields");
        for forbidden in [
            "credential",
            "token",
            "stderr",
            "pid",
            "path",
            "environment",
        ] {
            assert!(
                !object.contains_key(forbidden),
                "{forbidden} must not be published"
            );
        }
    }

    #[test]
    fn every_status_serializes_as_its_stated_name() {
        let names = [
            (SessionStatus::Starting, "starting"),
            (SessionStatus::Ready, "ready"),
            (SessionStatus::Failed, "failed"),
            (SessionStatus::Stopped, "stopped"),
        ];

        for (status, name) in names {
            assert_eq!(serde_json::to_value(status).unwrap(), json!(name));
        }
    }

    #[test]
    fn every_failure_code_is_bounded_and_named() {
        let codes = [
            (FailureCode::SpawnFailed, "spawn_failed"),
            (FailureCode::CredentialUnavailable, "credential_unavailable"),
            (FailureCode::StartupTimeout, "startup_timeout"),
            (
                FailureCode::ReadinessProtocolError,
                "readiness_protocol_error",
            ),
            (FailureCode::SidecarStartupExit, "sidecar_startup_exit"),
            (FailureCode::ProtocolViolation, "protocol_violation"),
            (FailureCode::UnexpectedExit, "unexpected_exit"),
            (FailureCode::ShutdownTimeout, "shutdown_timeout"),
        ];

        for (code, name) in codes {
            assert_eq!(serde_json::to_value(code).unwrap(), json!(name));
        }
    }

    #[test]
    fn a_start_failure_does_not_require_a_restart() {
        let snapshot = SessionSnapshot::failed(FailureCode::StartupTimeout, false);

        assert!(!snapshot.restart_required);
        assert_eq!(snapshot.status, SessionStatus::Failed);
    }

    /// The regression this module's capture exists for: `ready` implies the address *and*
    /// the credential, and nothing else implies either. Checked over every state a session
    /// can be captured in, so it is not one path that happens to hold.
    #[test]
    fn a_capture_is_either_a_ready_session_with_a_credential_or_neither() {
        let mut states = Vec::new();

        states.push(("never started", SessionState::stopped()));

        let mut starting = SessionState::stopped();
        starting.begin().expect("the first start is allowed");
        states.push(("starting", starting));

        states.push(("ready", ready_state()));

        let mut failed = ready_state();
        failed.mark_failed(FailureCode::UnexpectedExit, true);
        states.push(("failed after readiness", failed));

        let mut stopped = ready_state();
        stopped.mark_stopped();
        states.push(("stopped after readiness", stopped));

        for (label, state) in states {
            let bootstrap = state.bootstrap();
            let snapshot = bootstrap.snapshot();
            let ready = snapshot.status == SessionStatus::Ready;

            assert_eq!(
                snapshot.origin.is_some(),
                ready,
                "{label}: an address exists only for a ready session"
            );
            assert_eq!(
                snapshot.api_version.is_some(),
                ready,
                "{label}: an API version exists only for a ready session"
            );
            assert_eq!(
                snapshot.protocol_version.is_some(),
                ready,
                "{label}: a protocol version exists only for a ready session"
            );
            assert_eq!(
                bootstrap.credential().is_some(),
                ready,
                "{label}: a credential exists exactly when the session is ready"
            );
            assert_eq!(
                snapshot.failure.is_some(),
                snapshot.status == SessionStatus::Failed,
                "{label}: only a failed session carries a failure"
            );
        }
    }

    /// The normalisation is not merely a consequence of the transitions being correct: a
    /// capture drops the credential itself, so even a state that had been left inconsistent
    /// cannot be reported as a ready session without one.
    #[test]
    fn a_capture_drops_a_credential_that_does_not_belong_to_a_ready_state() {
        let inconsistent = SessionState {
            snapshot: SessionSnapshot::stopped(),
            credential: Some(credential()),
        };

        let bootstrap = inconsistent.bootstrap();

        assert_eq!(bootstrap.snapshot().status, SessionStatus::Stopped);
        assert!(bootstrap.credential().is_none());
    }

    #[test]
    fn a_capture_is_unaffected_by_the_transitions_that_follow_it() {
        let mut state = ready_state();

        let captured_credential = state
            .bootstrap()
            .credential()
            .expect("a ready session captures its credential")
            .expose()
            .to_string();
        let captured_origin = state
            .bootstrap()
            .snapshot()
            .origin
            .clone()
            .expect("a ready capture has the address it captured");

        state.mark_failed(FailureCode::UnexpectedExit, true);

        let after = state.bootstrap();
        assert!(after.credential().is_none());
        assert!(after.snapshot().origin.is_none());
        assert_eq!(captured_origin, "http://127.0.0.1:49152");
        assert_eq!(
            captured_credential.len(),
            43,
            "the earlier capture still holds the secret it captured"
        );
    }
}
