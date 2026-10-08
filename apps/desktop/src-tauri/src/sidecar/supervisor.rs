//! One supervised child: spawn, watch, stop, reap — without a runtime and without a leak.
//!
//! RES-376 gives each desktop session exactly one `dbench api serve` child. This module owns
//! that child's whole life on a dedicated OS thread:
//!
//! * **Spawn** with all three stdio channels piped, the credential and origins passed only
//!   through the child's environment, and `CREATE_NO_WINDOW` on Windows so a GUI session
//!   never flashes a console. Nothing about the command comes from the WebView; the
//!   [`LaunchSpec`] is resolved before this module is reached.
//! * **Startup** until the first stdout line parses as the exact readiness record, bounded by
//!   [`SupervisorConfig::startup_timeout`]. A child that never speaks, speaks wrongly, or
//!   exits is classified with a bounded [`FailureCode`] and reaped before anyone is told.
//! * **Serving** with the protocol channel still watched. A second stdout line is a protocol
//!   violation; an unsolicited exit is `unexpected_exit` with `restart_required = true`.
//!   There is no automatic restart, and no path that spawns a second child.
//! * **Shutdown** through the child's stdin: the exact record, flushed, then stdin closed so
//!   the child's own EOF path is a second chance. A bounded deadline follows; exit code 0 is
//!   the only graceful success. A deadline that expires is containment: force-terminate,
//!   reap, and record `shutdown_timeout` — never called graceful.
//!
//! The thread model is deliberately plain (`std::thread` + `mpsc`). A supervisor that needs
//! an async runtime to wait on one child's pipes would be a much larger surface than the
//! problem, and the entire external interface here is synchronous: [`Supervisor::start`]
//! blocks until the session is ready or failed, and [`Supervisor::request_shutdown`] blocks
//! until the child is gone or contained.

use std::io::{self, BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender, TryRecvError};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use crate::sidecar::credential::SessionCredential;
use crate::sidecar::launch::LaunchSpec;
use crate::sidecar::protocol::{parse_readiness, shutdown_line};
use crate::sidecar::state::StartRefused;
use crate::sidecar::state::{
    FailureCode, SessionBootstrap, SessionSnapshot, SessionState, SessionStatus,
};

/// The environment variable carrying the session credential to the child.
///
/// The only channel the credential travels on. Never an argument, never a file, never a log.
pub const SESSION_TOKEN_VARIABLE: &str = "DYNAMISBENCH_SESSION_TOKEN";

/// The environment variable carrying the exact origin allow-list to the child.
pub const ALLOWED_ORIGINS_VARIABLE: &str = "DYNAMISBENCH_ALLOWED_ORIGINS";

/// The longest stdout line the protocol channel will hold in memory.
///
/// The readiness record is a small fraction of this; the cap exists so a child that writes
/// an unbounded line is a classified protocol failure rather than unbounded memory growth.
pub const MAX_PROTOCOL_LINE_BYTES: usize = 64 * 1024;

/// How often the monitor wakes to poll the child while waiting for an event.
const POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Extra time the caller waits beyond the monitor's own deadlines before giving up on it.
///
/// Defensive only: the monitor owns and enforces both deadlines, so a caller that hits this
/// outer bound is looking at a wedged thread, not at a slow child. The value is a grace for
/// scheduling and reaping, not a second protocol.
const OUTER_GRACE: Duration = Duration::from_secs(5);

/// The timeouts and deadlines one supervisor operates under.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SupervisorConfig {
    /// How long the child has to produce a valid readiness record.
    pub startup_timeout: Duration,
    /// How long the child has to exit after the shutdown record before containment.
    pub shutdown_timeout: Duration,
}

impl Default for SupervisorConfig {
    fn default() -> Self {
        Self {
            startup_timeout: Duration::from_secs(15),
            shutdown_timeout: Duration::from_secs(5),
        }
    }
}

/// Receives each lifecycle snapshot, in order, on the thread that produced it.
///
/// The shell supplies a closure that forwards these to the main WebView; tests supply one
/// that records them. The supervisor deliberately does not know about Tauri.
pub type StateListener = dyn Fn(&SessionSnapshot) + Send + Sync + 'static;

/// What a shutdown request actually achieved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShutdownOutcome {
    /// The child exited 0 after being asked through the control channel.
    Graceful,
    /// The child was force-terminated and reaped; `shutdown_timeout` or `unexpected_exit`
    /// is recorded in the session state.
    Forced,
    /// There was no running child to stop, or a shutdown was already in progress.
    NotRunning,
}

/// Why a start attempt did not produce a ready session.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StartError {
    /// A session is already starting or ready; one session owns one child.
    Refused(StartRefused),
    /// The child was spawned but the session failed before readiness.
    Failed(FailureCode),
    /// The session was stopped (the desktop is exiting) before it became ready.
    Stopped,
}

/// The process owner for one desktop session's API sidecar.
pub struct Supervisor {
    config: SupervisorConfig,
    state: Arc<Mutex<SessionState>>,
    listener: Arc<StateListener>,
    commands: Mutex<Option<Sender<SupervisorCommand>>>,
    shutdown_begun: AtomicBool,
    exit_begun: AtomicBool,
}

enum SupervisorCommand {
    Shutdown { reply: Sender<ShutdownOutcome> },
}

enum StartupResolution {
    Ready,
    Failed(FailureCode),
    Stopped,
}

enum ProtocolEvent {
    Line(String),
    Eof,
    Malformed,
}

impl Supervisor {
    /// A supervisor that owns no process yet.
    pub fn new(config: SupervisorConfig, listener: Arc<StateListener>) -> Self {
        Self {
            config,
            state: Arc::new(Mutex::new(SessionState::stopped())),
            listener,
            commands: Mutex::new(None),
            shutdown_begun: AtomicBool::new(false),
            exit_begun: AtomicBool::new(false),
        }
    }

    /// The current lifecycle snapshot: non-secret, and always one state version.
    pub fn snapshot(&self) -> SessionSnapshot {
        lock(&self.state).snapshot().clone()
    }

    /// The whole WebView bootstrap — snapshot and credential — from one critical section.
    ///
    /// The single replacement for reading the snapshot and a credential separately. There is
    /// deliberately no credential accessor beside it: a response that paired one state
    /// version's address with another state version's credential is exactly what two
    /// independent reads can produce, so the supervisor does not offer that shape to anyone.
    pub fn session_bootstrap(&self) -> SessionBootstrap {
        lock(&self.state).bootstrap()
    }

    /// Spawn and supervise the one child, blocking until readiness resolves.
    ///
    /// The credential is generated here, before the spawn, because the child's environment is
    /// the first and only thing that needs it; an entropy failure is a bounded
    /// `credential_unavailable` session failure rather than an error the caller must handle.
    ///
    /// `Ok` means the session is ready and the credential is held; `Err` means the session
    /// is failed or was refused, with the reason already published to the listener.
    pub fn start(&self, spec: LaunchSpec) -> Result<(), StartError> {
        {
            let mut state = lock(&self.state);
            state.begin().map_err(StartError::Refused)?;
        }

        let credential = match SessionCredential::generate() {
            Ok(credential) => credential,
            Err(_) => {
                fail(
                    &self.state,
                    &self.listener,
                    FailureCode::CredentialUnavailable,
                    false,
                );
                return Err(StartError::Failed(FailureCode::CredentialUnavailable));
            }
        };
        publish(&self.state, &self.listener);

        let (command_tx, command_rx) = mpsc::channel();
        *lock(&self.commands) = Some(command_tx);

        let (startup_tx, startup_rx) = mpsc::channel();
        let state = Arc::clone(&self.state);
        let listener = Arc::clone(&self.listener);
        let config = self.config;
        let builder = thread::Builder::new().name("dynamisbench-sidecar-monitor".to_string());
        if builder
            .spawn(move || {
                monitor(
                    spec, credential, config, state, listener, command_rx, startup_tx,
                )
            })
            .is_err()
        {
            lock(&self.state).mark_failed(FailureCode::SpawnFailed, false);
            publish(&self.state, &self.listener);
            return Err(StartError::Failed(FailureCode::SpawnFailed));
        }

        match startup_rx.recv_timeout(config.startup_timeout + OUTER_GRACE) {
            Ok(StartupResolution::Ready) => Ok(()),
            Ok(StartupResolution::Failed(code)) => Err(StartError::Failed(code)),
            Ok(StartupResolution::Stopped) => Err(StartError::Stopped),
            // The monitor owns both deadlines; reaching this bound means it is gone or stuck.
            Err(_) => Err(StartError::Failed(FailureCode::StartupTimeout)),
        }
    }

    /// Ask the child to stop, wait for it, and contain it if it will not go.
    ///
    /// Idempotent: the first caller performs the shutdown, and every later caller is told
    /// there is no running session. There is no second record and no second child.
    pub fn request_shutdown(&self) -> ShutdownOutcome {
        if matches!(
            self.snapshot().status,
            SessionStatus::Stopped | SessionStatus::Failed
        ) {
            return ShutdownOutcome::NotRunning;
        }
        if self.shutdown_begun.swap(true, Ordering::SeqCst) {
            return ShutdownOutcome::NotRunning;
        }

        let sender = lock(&self.commands).clone();
        let Some(sender) = sender else {
            return ShutdownOutcome::NotRunning;
        };
        let (reply_tx, reply_rx) = mpsc::channel();
        if sender
            .send(SupervisorCommand::Shutdown { reply: reply_tx })
            .is_err()
        {
            return ShutdownOutcome::NotRunning;
        }
        match reply_rx.recv_timeout(self.config.shutdown_timeout + OUTER_GRACE) {
            Ok(outcome) => outcome,
            Err(_) => ShutdownOutcome::Forced,
        }
    }

    /// Claim the one desktop-exit cleanup, returning false for every later claimant.
    ///
    /// The fence for repeated exit events: whoever swaps this first performs the graceful
    /// shutdown and the final exit; everyone else does nothing.
    pub fn begin_exit(&self) -> bool {
        !self.exit_begun.swap(true, Ordering::SeqCst)
    }
}

/// The whole child's life, on one thread, from spawn to reap.
fn monitor(
    spec: LaunchSpec,
    credential: SessionCredential,
    config: SupervisorConfig,
    state: Arc<Mutex<SessionState>>,
    listener: Arc<StateListener>,
    command_rx: Receiver<SupervisorCommand>,
    startup: Sender<StartupResolution>,
) {
    let mut child = match spawn_child(&spec, &credential) {
        Ok(child) => child,
        Err(_) => {
            fail(&state, &listener, FailureCode::SpawnFailed, false);
            let _ = startup.send(StartupResolution::Failed(FailureCode::SpawnFailed));
            return;
        }
    };

    let (Some(stdout), Some(stderr), Some(stdin)) =
        (child.stdout.take(), child.stderr.take(), child.stdin.take())
    else {
        // Cannot happen with `Stdio::piped`, and if it did, nothing can be supervised.
        terminate_and_reap(&mut child);
        fail(&state, &listener, FailureCode::SpawnFailed, false);
        let _ = startup.send(StartupResolution::Failed(FailureCode::SpawnFailed));
        return;
    };

    let (lines_tx, lines_rx) = mpsc::channel();
    let _ = thread::Builder::new()
        .name("dynamisbench-sidecar-stdout".to_string())
        .spawn(move || read_protocol(stdout, lines_tx));
    let _ = thread::Builder::new()
        .name("dynamisbench-sidecar-stderr".to_string())
        .spawn(move || drain(stderr));

    let deadline = Instant::now() + config.startup_timeout;
    let stdin = Some(stdin);

    // Startup: the first stdout line is either the exact readiness record or a failure.
    loop {
        if let Some(outcome) = pending_shutdown(&command_rx) {
            terminate_and_reap(&mut child);
            lock(&state).mark_stopped();
            publish(&state, &listener);
            let _ = startup.send(StartupResolution::Stopped);
            let _ = outcome.send(ShutdownOutcome::Forced);
            return;
        }

        let remaining = deadline.saturating_duration_since(Instant::now());
        match lines_rx.recv_timeout(remaining.min(POLL_INTERVAL)) {
            Ok(ProtocolEvent::Line(line)) => match parse_readiness(&line) {
                Ok(readiness) => {
                    lock(&state).mark_ready(
                        readiness.origin(),
                        readiness.api_version.clone(),
                        readiness.protocol_version,
                        credential,
                    );
                    publish(&state, &listener);
                    let _ = startup.send(StartupResolution::Ready);
                    serve(child, stdin, command_rx, lines_rx, config, state, listener);
                    return;
                }
                Err(_) => {
                    terminate_and_reap(&mut child);
                    fail(
                        &state,
                        &listener,
                        FailureCode::ReadinessProtocolError,
                        false,
                    );
                    let _ = startup.send(StartupResolution::Failed(
                        FailureCode::ReadinessProtocolError,
                    ));
                    return;
                }
            },
            Ok(ProtocolEvent::Eof) => {
                terminate_and_reap(&mut child);
                fail(&state, &listener, FailureCode::SidecarStartupExit, false);
                let _ = startup.send(StartupResolution::Failed(FailureCode::SidecarStartupExit));
                return;
            }
            Ok(ProtocolEvent::Malformed) => {
                terminate_and_reap(&mut child);
                fail(
                    &state,
                    &listener,
                    FailureCode::ReadinessProtocolError,
                    false,
                );
                let _ = startup.send(StartupResolution::Failed(
                    FailureCode::ReadinessProtocolError,
                ));
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if Instant::now() >= deadline {
                    terminate_and_reap(&mut child);
                    fail(&state, &listener, FailureCode::StartupTimeout, false);
                    let _ = startup.send(StartupResolution::Failed(FailureCode::StartupTimeout));
                    return;
                }
                if matches!(child.try_wait(), Ok(Some(_))) {
                    terminate_and_reap(&mut child);
                    fail(&state, &listener, FailureCode::SidecarStartupExit, false);
                    let _ =
                        startup.send(StartupResolution::Failed(FailureCode::SidecarStartupExit));
                    return;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                terminate_and_reap(&mut child);
                fail(
                    &state,
                    &listener,
                    FailureCode::ReadinessProtocolError,
                    false,
                );
                let _ = startup.send(StartupResolution::Failed(
                    FailureCode::ReadinessProtocolError,
                ));
                return;
            }
        }
    }
}

/// The serving phase: the child is listening, and the protocol channel stays watched.
fn serve(
    mut child: Child,
    stdin: Option<ChildStdin>,
    command_rx: Receiver<SupervisorCommand>,
    lines_rx: Receiver<ProtocolEvent>,
    config: SupervisorConfig,
    state: Arc<Mutex<SessionState>>,
    listener: Arc<StateListener>,
) {
    let mut stdin = stdin;
    loop {
        match command_rx.try_recv() {
            Ok(SupervisorCommand::Shutdown { reply }) => {
                let (outcome, failure) =
                    graceful_shutdown(&mut child, stdin.take(), config.shutdown_timeout);
                match failure {
                    None => lock(&state).mark_stopped(),
                    Some(code) => lock(&state).mark_failed(code, false),
                }
                publish(&state, &listener);
                let _ = reply.send(outcome);
                return;
            }
            Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) => {}
        }

        match lines_rx.recv_timeout(POLL_INTERVAL) {
            Ok(ProtocolEvent::Line(_)) | Ok(ProtocolEvent::Malformed) => {
                terminate_and_reap(&mut child);
                fail(&state, &listener, FailureCode::ProtocolViolation, true);
                return;
            }
            Ok(ProtocolEvent::Eof) => {
                terminate_and_reap(&mut child);
                fail(&state, &listener, FailureCode::UnexpectedExit, true);
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    terminate_and_reap(&mut child);
                    fail(&state, &listener, FailureCode::UnexpectedExit, true);
                    return;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                terminate_and_reap(&mut child);
                fail(&state, &listener, FailureCode::ProtocolViolation, true);
                return;
            }
        }
    }
}

/// Build the child command: fixed spec, environment-only secrets, piped stdio, no console.
fn spawn_child(spec: &LaunchSpec, credential: &SessionCredential) -> io::Result<Child> {
    let origins = serde_json::to_string(&spec.origins)
        .expect("a vector of static strings cannot fail to serialize");
    let mut command = Command::new(&spec.program);
    command
        .args(&spec.args)
        .current_dir(&spec.cwd)
        .env(SESSION_TOKEN_VARIABLE, credential.expose())
        .env(ALLOWED_ORIGINS_VARIABLE, origins)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command.spawn()
}

/// Read protocol lines until EOF, handing each one to the monitor.
fn read_protocol(reader: impl Read, events: Sender<ProtocolEvent>) {
    let mut reader = BufReader::new(reader);
    loop {
        match read_protocol_line(&mut reader) {
            Ok(Some(line)) => {
                if events.send(ProtocolEvent::Line(line)).is_err() {
                    return;
                }
            }
            Ok(None) => {
                let _ = events.send(ProtocolEvent::Eof);
                return;
            }
            Err(_) => {
                let _ = events.send(ProtocolEvent::Malformed);
                return;
            }
        }
    }
}

/// One newline-terminated line, with the trailing newline removed and the length bounded.
fn read_protocol_line(reader: &mut impl BufRead) -> io::Result<Option<String>> {
    let mut buffer: Vec<u8> = Vec::new();
    loop {
        let mut byte = [0_u8; 1];
        if reader.read(&mut byte)? == 0 {
            if buffer.is_empty() {
                return Ok(None);
            }
            break;
        }
        if byte[0] == b'\n' {
            break;
        }
        buffer.push(byte[0]);
        if buffer.len() > MAX_PROTOCOL_LINE_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "a protocol line exceeded the supervisor's bound",
            ));
        }
    }
    if buffer.last() == Some(&b'\r') {
        buffer.pop();
    }
    Ok(Some(String::from_utf8_lossy(&buffer).into_owned()))
}

/// Read diagnostics and discard them, so the child can never block on a full stderr pipe.
///
/// stderr is never parsed and never forwarded: it exists for a human debugging the Python
/// side, and the shell's contract is a bounded failure code instead.
fn drain(reader: impl Read) {
    let mut reader = reader;
    let _ = io::copy(&mut reader, &mut io::sink());
}

/// A pending shutdown request, taken non-blockingly from the command channel.
fn pending_shutdown(command_rx: &Receiver<SupervisorCommand>) -> Option<Sender<ShutdownOutcome>> {
    match command_rx.try_recv() {
        Ok(SupervisorCommand::Shutdown { reply }) => Some(reply),
        Err(TryRecvError::Empty | TryRecvError::Disconnected) => None,
    }
}

/// Ask through stdin, then wait a bounded time for exit code 0.
///
/// Returns the outcome to report and, when the session must be recorded as failed, the
/// bounded failure code. `None` means the child exited 0 and the session may be `stopped`.
fn graceful_shutdown(
    child: &mut Child,
    stdin: Option<ChildStdin>,
    timeout: Duration,
) -> (ShutdownOutcome, Option<FailureCode>) {
    if let Some(mut stdin) = stdin {
        // A write failure is not classified here: the child may already be gone, and the
        // wait below is what actually decides. Dropping the handle closes the pipe, which
        // is also the child's own signal for supervisor loss.
        let _ = stdin.write_all(shutdown_line().as_bytes());
        let _ = stdin.flush();
    }

    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return (ShutdownOutcome::Graceful, None),
            Ok(Some(_)) => {
                return (ShutdownOutcome::Forced, Some(FailureCode::UnexpectedExit));
            }
            Ok(None) => {
                if Instant::now() >= deadline {
                    terminate_and_reap(child);
                    return (ShutdownOutcome::Forced, Some(FailureCode::ShutdownTimeout));
                }
                thread::sleep(Duration::from_millis(10));
            }
            Err(_) => {
                terminate_and_reap(child);
                return (ShutdownOutcome::Forced, Some(FailureCode::UnexpectedExit));
            }
        }
    }
}

/// Containment: terminate, then reap, whatever state the child is in.
///
/// The `wait` is the part that matters. Windows `TerminateProcess` gives the child no chance
/// to clean up, so this is never the *normal* path — it is what guarantees no orphan when a
/// deadline expires — and reaping is what keeps the operating system from holding a zombie.
fn terminate_and_reap(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

/// Write a failed snapshot and notify, in that order.
fn fail(
    state: &Arc<Mutex<SessionState>>,
    listener: &Arc<StateListener>,
    code: FailureCode,
    restart_required: bool,
) {
    lock(state).mark_failed(code, restart_required);
    publish(state, listener);
}

/// Hand the listener the current snapshot without holding the state lock across the call.
fn publish(state: &Arc<Mutex<SessionState>>, listener: &Arc<StateListener>) {
    let snapshot = lock(state).snapshot().clone();
    listener(&snapshot);
}

/// A mutex lock, recovering from poisoning rather than cascading a panic.
///
/// Every critical section in this file is a field read or a field write that cannot panic,
/// so a poisoned lock means a listener panicked in some other thread; refusing to continue
/// would turn that into a second failure. Recovering keeps containment working.
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    use super::{
        lock, ShutdownOutcome, StartError, Supervisor, SupervisorConfig, ALLOWED_ORIGINS_VARIABLE,
        SESSION_TOKEN_VARIABLE,
    };
    use crate::sidecar::credential::SessionCredential;
    use crate::sidecar::launch::LaunchSpec;
    use crate::sidecar::state::{FailureCode, SessionState, SessionStatus};

    fn quiet_supervisor() -> Supervisor {
        Supervisor::new(
            SupervisorConfig {
                startup_timeout: Duration::from_millis(250),
                shutdown_timeout: Duration::from_millis(250),
            },
            Arc::new(|_snapshot| {}),
        )
    }

    #[test]
    fn a_supervisor_that_never_started_has_nothing_to_stop() {
        let supervisor = quiet_supervisor();

        assert_eq!(supervisor.snapshot().status, SessionStatus::Stopped);
        assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
        assert!(supervisor.snapshot().origin.is_none());
    }

    #[test]
    fn the_two_child_environment_variables_are_the_published_names() {
        assert_eq!(SESSION_TOKEN_VARIABLE, "DYNAMISBENCH_SESSION_TOKEN");
        assert_eq!(ALLOWED_ORIGINS_VARIABLE, "DYNAMISBENCH_ALLOWED_ORIGINS");
    }

    #[test]
    fn a_spawn_that_cannot_happen_is_a_bounded_failure_not_a_panic() {
        let supervisor = quiet_supervisor();
        let missing = crate::sidecar::launch::LaunchSpec {
            program: "definitely-not-a-real-executable-dynamisbench".into(),
            args: Vec::new(),
            cwd: ".".into(),
            origins: vec!["http://localhost:5173"],
        };

        let result = supervisor.start(missing);

        assert_eq!(result, Err(StartError::Failed(FailureCode::SpawnFailed)));
        let snapshot = supervisor.snapshot();
        assert_eq!(snapshot.status, SessionStatus::Failed);
        assert_eq!(snapshot.failure, Some(FailureCode::SpawnFailed));
        assert!(!snapshot.restart_required);
    }

    #[test]
    fn the_exit_fence_admits_one_claimant() {
        let supervisor = quiet_supervisor();

        assert!(supervisor.begin_exit());
        assert!(!supervisor.begin_exit());
        assert!(!supervisor.begin_exit());
    }

    /// The defect, made deterministic: the two reads this replaces are reproduced against the
    /// real state, with the monitor's transition forced into the gap between them.
    ///
    /// There is no timing here. The transition is not raced for — it is placed exactly where
    /// the second read would begin, so the torn pair is a fact about the *composition*, not a
    /// window that has to be caught.
    #[test]
    fn reading_the_snapshot_and_the_credential_separately_straddles_a_transition() {
        let state = Arc::new(Mutex::new(SessionState::stopped()));

        {
            let mut held = lock(&state);
            held.begin().expect("the first start is admitted");
            held.mark_ready(
                "http://127.0.0.1:49152".into(),
                "v1".into(),
                1,
                SessionCredential::generate().unwrap(),
            );
        }

        // Read #1, exactly as the bridge used to read it.
        let snapshot = lock(&state).snapshot().clone();

        // The monitor's own transition, forced into the gap.
        lock(&state).mark_stopped();

        // Read #2, exactly as the bridge used to read it.
        let credential = lock(&state).bootstrap().credential().cloned();

        assert_eq!(
            snapshot.status,
            SessionStatus::Ready,
            "the first read saw a ready session"
        );
        assert_eq!(
            snapshot.origin.as_deref(),
            Some("http://127.0.0.1:49152"),
            "and with an address"
        );
        assert!(
            credential.is_none(),
            "the second read saw a stopped session: paired, this is status=ready with \
             credential=null, a response the WebView cannot act on"
        );

        // The replacement, captured at the same instant, cannot straddle anything.
        let bootstrap = lock(&state).bootstrap();
        assert_eq!(bootstrap.snapshot().status, SessionStatus::Stopped);
        assert_eq!(bootstrap.snapshot().origin, None);
        assert!(bootstrap.credential().is_none());
    }

    #[test]
    fn a_capture_never_publishes_a_credential_for_a_session_that_is_not_ready() {
        let supervisor = quiet_supervisor();

        let result = supervisor.start(LaunchSpec {
            program: "definitely-not-a-real-executable-dynamisbench".into(),
            args: Vec::new(),
            cwd: ".".into(),
            origins: vec!["http://localhost:5173"],
        });
        assert_eq!(result, Err(StartError::Failed(FailureCode::SpawnFailed)));

        let bootstrap = supervisor.session_bootstrap();
        assert_eq!(bootstrap.snapshot().status, SessionStatus::Failed);
        assert_eq!(bootstrap.snapshot().origin, None);
        assert!(bootstrap.credential().is_none());
    }
}
