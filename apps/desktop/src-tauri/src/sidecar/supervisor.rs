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
//! Two properties are structural here rather than conventional, and both are why there is
//! exactly one lock in this module:
//!
//! * **A requested shutdown does not stop watching stdout.** The protocol channel stays
//!   observed from the moment the shutdown record is written until the child is reaped, so
//!   "exactly one readiness line per session" is enforced during shutdown too. A child that
//!   writes a second line and *then* exits 0 is a protocol violation that was force-contained,
//!   not a graceful shutdown.
//! * **A start and a desktop exit cannot both be in flight.** [`Supervisor::admit_start`]
//!   refuses a start once the desktop has claimed its exit, and
//!   [`Supervisor::request_shutdown`] waits out a start that has already been admitted instead
//!   of reporting that there is nothing to stop. There is no interleaving in which
//!   `request_shutdown` answers `NotRunning` and a child is spawned afterwards.
//!
//! The thread model is deliberately plain (`std::thread` + `mpsc`). A supervisor that needs
//! an async runtime to wait on one child's pipes would be a much larger surface than the
//! problem, and the entire external interface here is synchronous: [`Supervisor::start`]
//! blocks until the session is ready or failed, and [`Supervisor::request_shutdown`] blocks
//! until the child is gone or contained.

use std::io::{self, BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender, TryRecvError};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};
use std::thread;
use std::time::{Duration, Instant};

use crate::sidecar::credential::SessionCredential;
use crate::sidecar::launch::LaunchSpec;
use crate::sidecar::protocol::{parse_readiness, shutdown_line};
use crate::sidecar::state::{
    FailureCode, SessionBootstrap, SessionSnapshot, SessionState, StartRefused,
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

/// How often a requested shutdown re-examines the process while it waits.
///
/// Tighter than [`POLL_INTERVAL`] because this is the phase that ends the desktop session:
/// the deadline it guards is a few seconds long and the exit it waits for should be noticed
/// promptly rather than up to a tenth of a second after it happened.
const SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(10);

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
    /// The child exited 0 after being asked through the control channel, having written
    /// nothing further to the protocol channel.
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

/// How the one child is created.
///
/// The product always uses [`spawn_sidecar`]. This indirection exists so qualification can
/// count spawn attempts and reach a forced interleaving without a real process — it is not a
/// configuration surface: the [`LaunchSpec`] still comes from the fixed launch resolution, no
/// WebView input reaches it, and nothing about the launch becomes caller-chosen.
pub type SpawnSidecar = dyn Fn(&LaunchSpec, &SessionCredential) -> io::Result<Child> + Send + Sync;

/// Where a session is in the supervisor's own lifecycle.
///
/// This is not the vocabulary the WebView sees — that is [`crate::sidecar::SessionStatus`] —
/// but the authority for two questions that the public state alone cannot answer: may a start
/// proceed, and is there a monitor that a shutdown can be addressed to.
///
/// [`Phase::StartReserved`] is what makes the start/exit race impossible. It is the window
/// between admitting a start and publishing the monitor's command channel, and while it is
/// held neither a second start nor an exit may conclude that nothing is running.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Phase {
    /// No start has been admitted and none is in flight.
    Idle,
    /// A start has been admitted; the child is being created and no channel exists yet.
    StartReserved,
    /// The monitor is running and its command channel is established.
    Running,
    /// A shutdown has been delivered to the monitor and is in progress.
    Exiting,
    /// The child is gone: never spawned, contained, or reaped.
    Terminated,
}

/// The session's public state beside the supervisor's own control decisions, under one lock.
///
/// [`crate::sidecar::SessionState`] is what the WebView is told; this record is what the
/// supervisor is allowed to decide. They share a mutex because the two must not be readable
/// at different instants: a WebView bootstrap capture and an "is the desktop exiting" claim
/// that disagree is the defect this module exists to prevent.
#[derive(Debug)]
struct Control {
    session: SessionState,
    phase: Phase,
    exit_claimed: bool,
    commands: Option<Sender<SupervisorCommand>>,
}

impl Control {
    fn new() -> Self {
        Self {
            session: SessionState::stopped(),
            phase: Phase::Idle,
            exit_claimed: false,
            commands: None,
        }
    }

    /// Admit a start, or refuse it.
    ///
    /// Refusal has two distinct reasons and they are kept apart because they are different
    /// facts: a session that is already starting or ready is [`StartError::Refused`], while a
    /// desktop that has claimed its exit is [`StartError::Stopped`] — the session is over and
    /// no later start may create a child.
    fn admit_start(&mut self) -> Result<(), StartError> {
        if self.exit_claimed {
            return Err(StartError::Stopped);
        }
        self.session.begin().map_err(StartError::Refused)?;
        self.phase = Phase::StartReserved;
        Ok(())
    }

    /// Claim the one desktop-exit cleanup, returning false for every later claimant.
    fn admit_exit(&mut self) -> bool {
        if self.exit_claimed {
            return false;
        }
        self.exit_claimed = true;
        true
    }

    /// Publish the monitor's command channel: the reservation is resolved and addressable.
    fn established(&mut self, commands: Sender<SupervisorCommand>) {
        self.commands = Some(commands);
        self.phase = Phase::Running;
    }

    /// The child is gone; nothing is addressable and no start may follow.
    fn terminated(&mut self) {
        self.commands = None;
        self.phase = Phase::Terminated;
    }

    fn snapshot(&self) -> SessionSnapshot {
        self.session.snapshot().clone()
    }

    fn bootstrap(&self) -> SessionBootstrap {
        self.session.bootstrap()
    }
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

/// The one lock every supervision decision goes through.
///
/// [`Control`] is the record; [`Condvar::resolved`] exists so a shutdown request that arrives
/// inside a start's reservation can wait for that reservation to resolve instead of reporting
/// that there is nothing to stop. It is the wait — not a sleep, and not a retry — that makes
/// "exit wins before spawn" and "start wins before exit" the only two possible orders.
struct Gate {
    control: Mutex<Control>,
    resolved: Condvar,
}

impl Gate {
    fn new() -> Self {
        Self {
            control: Mutex::new(Control::new()),
            resolved: Condvar::new(),
        }
    }

    /// Announce that the record changed, after the guard is released.
    ///
    /// Called outside the critical section so a waiter is not woken only to block on a lock
    /// the notifier is still holding.
    fn announce(&self) {
        self.resolved.notify_all();
    }
}

/// The child between spawn and the monitor thread that owns it.
///
/// `std::process::Child` does not stop its process when dropped, so a monitor thread that
/// cannot be created would leak the child it was created for. The slot is shared so the
/// failed spawn can still reach the process and contain it.
struct ChildSlot(Mutex<Option<Child>>);

impl ChildSlot {
    fn new(child: Child) -> Arc<Self> {
        Arc::new(Self(Mutex::new(Some(child))))
    }

    fn take(&self) -> Option<Child> {
        lock(&self.0).take()
    }
}

/// The process owner for one desktop session's API sidecar.
pub struct Supervisor {
    config: SupervisorConfig,
    gate: Arc<Gate>,
    listener: Arc<StateListener>,
    spawn_sidecar: Arc<SpawnSidecar>,
}

impl Supervisor {
    /// A supervisor that owns no process yet.
    pub fn new(config: SupervisorConfig, listener: Arc<StateListener>) -> Self {
        Self::with_spawner(
            config,
            listener,
            Arc::new(|spec, credential| spawn_sidecar(spec, credential)),
        )
    }

    /// A supervisor whose child creation is wrapped by `spawner`.
    ///
    /// A qualification seam, not a second production path: [`Supervisor::new`] is the only
    /// constructor the shell uses, and the seam can neither change the resolved command nor
    /// be reached from the WebView. It exists so "the exit won, so no child was spawned" and
    /// "the exit arrived while the spawn was still in flight" can both be forced as exact
    /// orderings rather than hunted for.
    pub fn with_spawner(
        config: SupervisorConfig,
        listener: Arc<StateListener>,
        spawner: Arc<SpawnSidecar>,
    ) -> Self {
        Self {
            config,
            gate: Arc::new(Gate::new()),
            listener,
            spawn_sidecar: spawner,
        }
    }

    /// The current lifecycle snapshot: non-secret, and always one state version.
    pub fn snapshot(&self) -> SessionSnapshot {
        lock(&self.gate.control).snapshot()
    }

    /// The whole WebView bootstrap — snapshot and credential — from one critical section.
    ///
    /// The single replacement for reading [`Supervisor::snapshot`] and a credential
    /// separately. There is deliberately no credential accessor beside it: a response that
    /// paired one state version's address with another state version's credential is exactly
    /// what the previous pair of reads could produce, so the supervisor does not offer that
    /// shape to any caller.
    pub fn session_bootstrap(&self) -> SessionBootstrap {
        lock(&self.gate.control).bootstrap()
    }

    /// Spawn and supervise the one child, blocking until readiness resolves.
    ///
    /// The credential is generated here, before the spawn, because the child's environment is
    /// the first and only thing that needs it; an entropy failure is a bounded
    /// `credential_unavailable` session failure rather than an error the caller must handle.
    ///
    /// `Ok` means the session is ready and the credential is held; `Err` means the session
    /// is failed, was refused, or the desktop claimed its exit first — in which case no child
    /// was created.
    pub fn start(&self, spec: LaunchSpec) -> Result<(), StartError> {
        {
            // Admission and reservation in one critical section: from here until the command
            // channel is published, this session is claimed, and a shutdown that arrives in
            // that window waits for it rather than concluding nothing is running.
            lock(&self.gate.control).admit_start()?;
        }
        publish(&self.gate, &self.listener);

        let credential = match SessionCredential::generate() {
            Ok(credential) => credential,
            Err(_) => {
                self.end_session(FailureCode::CredentialUnavailable, false);
                return Err(StartError::Failed(FailureCode::CredentialUnavailable));
            }
        };

        let mut child = match (self.spawn_sidecar)(&spec, &credential) {
            Ok(child) => child,
            Err(_) => {
                self.end_session(FailureCode::SpawnFailed, false);
                return Err(StartError::Failed(FailureCode::SpawnFailed));
            }
        };

        let (Some(stdout), Some(stderr), Some(stdin)) =
            (child.stdout.take(), child.stderr.take(), child.stdin.take())
        else {
            // Cannot happen with `Stdio::piped`, and if it did, nothing can be supervised.
            terminate_and_reap(&mut child);
            self.end_session(FailureCode::SpawnFailed, false);
            return Err(StartError::Failed(FailureCode::SpawnFailed));
        };

        let (command_tx, command_rx) = mpsc::channel();
        {
            let mut control = lock(&self.gate.control);
            control.established(command_tx);
        }
        self.gate.announce();

        let slot = ChildSlot::new(child);
        let handed_over = Arc::clone(&slot);
        let (startup_tx, startup_rx) = mpsc::channel();
        let gate = Arc::clone(&self.gate);
        let listener = Arc::clone(&self.listener);
        let config = self.config;
        let builder = thread::Builder::new().name("dynamisbench-sidecar-monitor".to_string());
        if builder
            .spawn(move || {
                let child = handed_over
                    .take()
                    .expect("the monitor thread is the only holder of the child slot");
                monitor(
                    child,
                    stdout,
                    stderr,
                    Some(stdin),
                    credential,
                    config,
                    gate,
                    listener,
                    command_rx,
                    startup_tx,
                );
            })
            .is_err()
        {
            if let Some(mut orphaned) = slot.take() {
                terminate_and_reap(&mut orphaned);
            }
            self.end_session(FailureCode::SpawnFailed, false);
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
    ///
    /// The one answer this must never give while a child is still coming is `NotRunning`. A
    /// start that has been admitted holds a reservation, so this waits for that reservation
    /// to resolve into a command channel (the child is addressable) or into a terminated
    /// session (no child exists). The wait is bounded by the same outer grace used for a
    /// wedged monitor.
    pub fn request_shutdown(&self) -> ShutdownOutcome {
        let commands = {
            let mut control = lock(&self.gate.control);
            let deadline = Instant::now() + self.config.startup_timeout + OUTER_GRACE;
            loop {
                match control.phase {
                    Phase::Running => {
                        control.phase = Phase::Exiting;
                        match control.commands.clone() {
                            Some(commands) => break commands,
                            None => return ShutdownOutcome::NotRunning,
                        }
                    }
                    Phase::StartReserved => {
                        let remaining = deadline.saturating_duration_since(Instant::now());
                        if remaining.is_zero() {
                            // The reservation never resolved, which no reachable path does.
                            // Containment is the honest answer: never `NotRunning`, which
                            // would tell the desktop there is provably no child to leave.
                            return ShutdownOutcome::Forced;
                        }
                        let (guard, _) = self
                            .gate
                            .resolved
                            .wait_timeout(control, remaining)
                            .unwrap_or_else(|poisoned| poisoned.into_inner());
                        control = guard;
                    }
                    Phase::Idle | Phase::Exiting | Phase::Terminated => {
                        return ShutdownOutcome::NotRunning;
                    }
                }
            }
        };

        let (reply, reply_rx) = mpsc::channel();
        match commands.send(SupervisorCommand::Shutdown { reply }) {
            Ok(()) => match reply_rx.recv_timeout(self.config.shutdown_timeout + OUTER_GRACE) {
                Ok(outcome) => outcome,
                // The monitor owns this deadline; arriving here means it is wedged, and
                // containment is the only safe claim.
                Err(_) => ShutdownOutcome::Forced,
            },
            // The monitor is gone, so the child it owned is gone: nothing to stop.
            Err(_) => ShutdownOutcome::NotRunning,
        }
    }

    /// Claim the one desktop-exit cleanup, returning false for every later claimant.
    ///
    /// The fence for repeated exit events: whoever claims this first performs the graceful
    /// shutdown and the final exit; everyone else does nothing. Claiming it also closes the
    /// session to future starts, which is what stops a background startup thread from
    /// creating a child after the desktop has decided to leave.
    pub fn begin_exit(&self) -> bool {
        lock(&self.gate.control).admit_exit()
    }

    /// A start that cannot proceed: no child was created, so record the failure and release
    /// the reservation, waking anything waiting on it.
    fn end_session(&self, code: FailureCode, restart_required: bool) {
        {
            let mut control = lock(&self.gate.control);
            control.session.mark_failed(code, restart_required);
            control.terminated();
        }
        self.gate.announce();
        publish(&self.gate, &self.listener);
    }
}

/// The whole child's life, on one thread, from the child it was handed to its reap.
///
/// The wrapper owns the only exit from the record: when the thread returns for any reason,
/// the command channel is withdrawn and the phase becomes `terminated`, so a shutdown that
/// arrives afterwards is told the truth — there is no monitor and no child left to address.
fn monitor(
    child: Child,
    stdout: ChildStdout,
    stderr: ChildStderr,
    stdin: Option<ChildStdin>,
    credential: SessionCredential,
    config: SupervisorConfig,
    gate: Arc<Gate>,
    listener: Arc<StateListener>,
    command_rx: Receiver<SupervisorCommand>,
    startup: Sender<StartupResolution>,
) {
    supervise(
        child,
        stdout,
        stderr,
        stdin,
        credential,
        config,
        Arc::clone(&gate),
        Arc::clone(&listener),
        command_rx,
        startup,
    );
    {
        let mut control = lock(&gate.control);
        control.terminated();
    }
    gate.announce();
}

#[allow(clippy::too_many_arguments)]
fn supervise(
    mut child: Child,
    stdout: ChildStdout,
    stderr: ChildStderr,
    stdin: Option<ChildStdin>,
    credential: SessionCredential,
    config: SupervisorConfig,
    gate: Arc<Gate>,
    listener: Arc<StateListener>,
    command_rx: Receiver<SupervisorCommand>,
    startup: Sender<StartupResolution>,
) {
    let (lines_tx, lines_rx) = mpsc::channel();
    let _ = thread::Builder::new()
        .name("dynamisbench-sidecar-stdout".to_string())
        .spawn(move || read_protocol(stdout, lines_tx));
    let _ = thread::Builder::new()
        .name("dynamisbench-sidecar-stderr".to_string())
        .spawn(move || drain(stderr));

    let deadline = Instant::now() + config.startup_timeout;

    // Startup: the first stdout line is either the exact readiness record or a failure.
    loop {
        if let Some(outcome) = pending_shutdown(&command_rx) {
            terminate_and_reap(&mut child);
            {
                let mut control = lock(&gate.control);
                control.session.mark_stopped();
            }
            publish(&gate, &listener);
            let _ = startup.send(StartupResolution::Stopped);
            let _ = outcome.send(ShutdownOutcome::Forced);
            return;
        }

        let remaining = deadline.saturating_duration_since(Instant::now());
        match lines_rx.recv_timeout(remaining.min(POLL_INTERVAL)) {
            Ok(ProtocolEvent::Line(line)) => match parse_readiness(&line) {
                Ok(readiness) => {
                    {
                        let mut control = lock(&gate.control);
                        control.session.mark_ready(
                            readiness.origin(),
                            readiness.api_version.clone(),
                            readiness.protocol_version,
                            credential,
                        );
                    }
                    publish(&gate, &listener);
                    let _ = startup.send(StartupResolution::Ready);
                    serve(child, stdin, command_rx, lines_rx, config, gate, listener);
                    return;
                }
                Err(_) => {
                    terminate_and_reap(&mut child);
                    fail(&gate, &listener, FailureCode::ReadinessProtocolError, false);
                    let _ = startup.send(StartupResolution::Failed(
                        FailureCode::ReadinessProtocolError,
                    ));
                    return;
                }
            },
            Ok(ProtocolEvent::Eof) => {
                terminate_and_reap(&mut child);
                fail(&gate, &listener, FailureCode::SidecarStartupExit, false);
                let _ = startup.send(StartupResolution::Failed(FailureCode::SidecarStartupExit));
                return;
            }
            Ok(ProtocolEvent::Malformed) => {
                terminate_and_reap(&mut child);
                fail(&gate, &listener, FailureCode::ReadinessProtocolError, false);
                let _ = startup.send(StartupResolution::Failed(
                    FailureCode::ReadinessProtocolError,
                ));
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if Instant::now() >= deadline {
                    terminate_and_reap(&mut child);
                    fail(&gate, &listener, FailureCode::StartupTimeout, false);
                    let _ = startup.send(StartupResolution::Failed(FailureCode::StartupTimeout));
                    return;
                }
                if matches!(child.try_wait(), Ok(Some(_))) {
                    terminate_and_reap(&mut child);
                    fail(&gate, &listener, FailureCode::SidecarStartupExit, false);
                    let _ =
                        startup.send(StartupResolution::Failed(FailureCode::SidecarStartupExit));
                    return;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                terminate_and_reap(&mut child);
                fail(&gate, &listener, FailureCode::ReadinessProtocolError, false);
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
    gate: Arc<Gate>,
    listener: Arc<StateListener>,
) {
    let mut stdin = stdin;
    loop {
        match command_rx.try_recv() {
            Ok(SupervisorCommand::Shutdown { reply }) => {
                // The protocol channel is handed to the shutdown rather than abandoned: one
                // readiness line per session holds until the child is reaped, not until the
                // shutdown record is written.
                let (outcome, failure) =
                    graceful_shutdown(&mut child, stdin.take(), &lines_rx, config.shutdown_timeout);
                {
                    let mut control = lock(&gate.control);
                    match failure {
                        None => control.session.mark_stopped(),
                        Some(code) => control.session.mark_failed(code, false),
                    }
                }
                publish(&gate, &listener);
                let _ = reply.send(outcome);
                return;
            }
            Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) => {}
        }

        match lines_rx.recv_timeout(POLL_INTERVAL) {
            Ok(ProtocolEvent::Line(_)) | Ok(ProtocolEvent::Malformed) => {
                terminate_and_reap(&mut child);
                fail(&gate, &listener, FailureCode::ProtocolViolation, true);
                return;
            }
            Ok(ProtocolEvent::Eof) => {
                terminate_and_reap(&mut child);
                fail(&gate, &listener, FailureCode::UnexpectedExit, true);
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    terminate_and_reap(&mut child);
                    fail(&gate, &listener, FailureCode::UnexpectedExit, true);
                    return;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                terminate_and_reap(&mut child);
                fail(&gate, &listener, FailureCode::ProtocolViolation, true);
                return;
            }
        }
    }
}

/// Build the child command: fixed spec, environment-only secrets, piped stdio, no console.
///
/// The one place a process is created. Public so a qualification spawn seam can delegate to
/// the production path instead of re-implementing it; it is not called with anything the
/// WebView can influence.
pub fn spawn_sidecar(spec: &LaunchSpec, credential: &SessionCredential) -> io::Result<Child> {
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

/// Ask through stdin, then wait — watching the child's stdout throughout — for it to exit 0.
///
/// The shutdown does not relax the protocol. It is the same channel the serving phase
/// watches and the same rule it enforces: after readiness, stdout belongs to no one. A
/// second line is still a [`FailureCode::ProtocolViolation`] and is terminated, reaped, and
/// reported as [`ShutdownOutcome::Forced`] however politely the child then exits.
///
/// Two facts about a stopping child arrive independently and in either order — stdout
/// closes, and the process exits — so neither is allowed to decide alone:
///
/// * stdout is only treated as finished on a `ProtocolEvent::Eof` (or the channel
///   disconnecting), which is the reader thread's own report that it has nothing left;
/// * a clean exit is only *graceful* once stdout is finished as well, so a line the child
///   wrote on its way out is still observed and still refused rather than lost in the gap;
/// * if stdout closes first and the child then exits non-zero, the exit decides:
///   `unexpected_exit` / [`ShutdownOutcome::Forced`];
/// * if the deadline passes first, the child is force-terminated, reaped, and recorded as
///   `shutdown_timeout` — unless it had already exited 0, which the process table reports
///   whether or not the pipe was inherited by a grandchild.
fn graceful_shutdown(
    child: &mut Child,
    stdin: Option<ChildStdin>,
    lines_rx: &Receiver<ProtocolEvent>,
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
    let mut stdout_finished = false;
    let mut exit: Option<ExitStatus> = None;

    loop {
        if !stdout_finished {
            let remaining = deadline.saturating_duration_since(Instant::now());
            match lines_rx.recv_timeout(remaining.min(SHUTDOWN_POLL_INTERVAL)) {
                Ok(ProtocolEvent::Line(_)) | Ok(ProtocolEvent::Malformed) => {
                    terminate_and_reap(child);
                    return (
                        ShutdownOutcome::Forced,
                        Some(FailureCode::ProtocolViolation),
                    );
                }
                Ok(ProtocolEvent::Eof) | Err(RecvTimeoutError::Disconnected) => {
                    stdout_finished = true;
                }
                Err(RecvTimeoutError::Timeout) => {}
            }
        }

        if exit.is_none() {
            match child.try_wait() {
                Ok(Some(status)) => exit = Some(status),
                Ok(None) => {}
                Err(_) => {
                    terminate_and_reap(child);
                    return (ShutdownOutcome::Forced, Some(FailureCode::UnexpectedExit));
                }
            }
        }

        match exit {
            Some(status) if status.success() && stdout_finished => {
                return (ShutdownOutcome::Graceful, None);
            }
            Some(status) if status.success() && Instant::now() >= deadline => {
                // The process says it stopped cleanly and the deadline has passed without a
                // final word on stdout. The exit status is a fact about the process; the
                // unanswered protocol question cannot be turned into a failure that would
                // force-kill a child that has already gone.
                return (ShutdownOutcome::Graceful, None);
            }
            Some(_) => {
                return (ShutdownOutcome::Forced, Some(FailureCode::UnexpectedExit));
            }
            None => {}
        }

        if Instant::now() >= deadline {
            terminate_and_reap(child);
            return (ShutdownOutcome::Forced, Some(FailureCode::ShutdownTimeout));
        }
        thread::sleep(SHUTDOWN_POLL_INTERVAL);
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
    gate: &Arc<Gate>,
    listener: &Arc<StateListener>,
    code: FailureCode,
    restart_required: bool,
) {
    {
        let mut control = lock(&gate.control);
        control.session.mark_failed(code, restart_required);
    }
    publish(gate, listener);
}

/// Hand the listener the current snapshot without holding the control lock across the call.
fn publish(gate: &Arc<Gate>, listener: &Arc<StateListener>) {
    let snapshot = lock(&gate.control).snapshot();
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
    use std::io;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::mpsc;
    use std::sync::Arc;
    use std::time::Duration;

    use super::{
        ShutdownOutcome, StartError, Supervisor, SupervisorConfig, ALLOWED_ORIGINS_VARIABLE,
        SESSION_TOKEN_VARIABLE,
    };
    use crate::sidecar::credential::SessionCredential;
    use crate::sidecar::launch::LaunchSpec;
    use crate::sidecar::state::{FailureCode, SessionStatus};

    fn quiet_supervisor() -> Supervisor {
        Supervisor::new(
            SupervisorConfig {
                startup_timeout: Duration::from_millis(250),
                shutdown_timeout: Duration::from_millis(250),
            },
            Arc::new(|_snapshot| {}),
        )
    }

    fn unreachable_spec() -> LaunchSpec {
        LaunchSpec {
            program: "definitely-not-a-real-executable-dynamisbench".into(),
            args: Vec::new(),
            cwd: ".".into(),
            origins: vec!["http://localhost:5173"],
        }
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

        let result = supervisor.start(unreachable_spec());

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

    // ---------------------------------------------------------------------------------
    // The atomic bootstrap capture.
    // ---------------------------------------------------------------------------------

    /// The defect, made deterministic: the two reads this replaces are reproduced against the
    /// real record, with the transition forced into the gap between them.
    ///
    /// There is no timing here. The transition is not raced for — it is placed exactly where
    /// the second read would begin, so the torn pair is a fact about the *composition*, not a
    /// window that has to be caught.
    #[test]
    fn reading_the_snapshot_and_the_credential_separately_straddles_a_transition() {
        let gate = super::Gate::new();
        let credential = SessionCredential::generate().unwrap();

        {
            let mut control = super::lock(&gate.control);
            control.admit_start().expect("the first start is admitted");
            control
                .session
                .mark_ready("http://127.0.0.1:49152".into(), "v1".into(), 1, credential);
        }

        // Read #1, exactly as the bridge used to read it.
        let snapshot = super::lock(&gate.control).snapshot();

        // The monitor's own transition, forced into the gap.
        super::lock(&gate.control).session.mark_stopped();

        // Read #2, exactly as the bridge used to read it.
        let credential = super::lock(&gate.control).bootstrap().credential().cloned();

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
        let bootstrap = super::lock(&gate.control).bootstrap();
        assert_eq!(bootstrap.snapshot().status, SessionStatus::Stopped);
        assert_eq!(bootstrap.snapshot().origin, None);
        assert!(bootstrap.credential().is_none());
    }

    #[test]
    fn a_capture_never_publishes_a_credential_for_a_session_that_is_not_ready() {
        let supervisor = quiet_supervisor();

        let result = supervisor.start(unreachable_spec());
        assert_eq!(result, Err(StartError::Failed(FailureCode::SpawnFailed)));

        let bootstrap = supervisor.session_bootstrap();
        assert_eq!(bootstrap.snapshot().status, SessionStatus::Failed);
        assert_eq!(bootstrap.snapshot().origin, None);
        assert!(bootstrap.credential().is_none());
    }

    // ---------------------------------------------------------------------------------
    // The start/exit fence.
    // ---------------------------------------------------------------------------------

    #[test]
    fn a_start_after_the_exit_claim_is_refused_and_never_spawns() {
        let attempts = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&attempts);
        let published = Arc::new(std::sync::Mutex::new(Vec::new()));
        let recorded = Arc::clone(&published);
        let supervisor = Supervisor::with_spawner(
            SupervisorConfig::default(),
            Arc::new(move |snapshot| {
                recorded
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(snapshot.status)
            }),
            Arc::new(move |_spec, _credential| {
                observed.fetch_add(1, Ordering::SeqCst);
                Err(io::Error::other("the fixture never gets to run"))
            }),
        );

        assert!(supervisor.begin_exit());

        let result = supervisor.start(unreachable_spec());

        assert_eq!(
            result,
            Err(StartError::Stopped),
            "an exit has claimed the session, so this start is stopped rather than failed"
        );
        assert_eq!(
            attempts.load(Ordering::SeqCst),
            0,
            "no spawn may be attempted once the desktop is exiting"
        );
        assert_eq!(
            supervisor.snapshot().status,
            SessionStatus::Stopped,
            "a refused start must not publish a starting session"
        );
        assert!(
            published.lock().unwrap().is_empty(),
            "a refused start must not publish any lifecycle state"
        );
        assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
    }

    #[test]
    fn a_shutdown_inside_a_start_reservation_waits_for_it_instead_of_reporting_nothing() {
        let (entered_tx, entered_rx) = mpsc::channel::<()>();
        let (release_tx, release_rx) = mpsc::channel::<()>();
        // The spawner has to be `Sync` because the supervisor may be shared, so the release
        // handshake lives behind a lock rather than being moved into the closure.
        let release = std::sync::Mutex::new(release_rx);
        let supervisor = Arc::new(Supervisor::with_spawner(
            SupervisorConfig::default(),
            Arc::new(|_snapshot| {}),
            Arc::new(move |_spec, _credential| {
                // Held inside the reservation: the child has not been created, and the
                // command channel does not exist yet.
                let _ = entered_tx.send(());
                let release = release.lock().expect("the release lock is not poisoned");
                let _ = release.recv();
                Err(io::Error::other("the fixture child is never created"))
            }),
        ));

        let starting = Arc::clone(&supervisor);
        let start = std::thread::spawn(move || starting.start(unreachable_spec()));
        entered_rx
            .recv_timeout(Duration::from_secs(10))
            .expect("the start reached its spawn attempt");

        let exiting = Arc::clone(&supervisor);
        let (outcome_tx, outcome_rx) = mpsc::channel();
        std::thread::spawn(move || {
            let _ = outcome_tx.send(exiting.request_shutdown());
        });

        assert!(
            outcome_rx.try_recv().is_err(),
            "the exit must wait: a child is being created and cannot be reported as absent"
        );

        release_tx
            .send(())
            .expect("the start must be released to resolve its reservation");

        let result = start.join().expect("the start thread must not panic");
        let outcome = outcome_rx
            .recv_timeout(Duration::from_secs(10))
            .expect("the exit must resolve once the reservation does");

        assert_eq!(result, Err(StartError::Failed(FailureCode::SpawnFailed)));
        assert_eq!(
            outcome,
            ShutdownOutcome::NotRunning,
            "once the reservation has resolved into a terminated session, and only then, \
             there is provably no child to stop"
        );
    }

    #[test]
    fn a_repeated_shutdown_after_a_terminated_session_still_reports_nothing_to_stop() {
        let supervisor = quiet_supervisor();

        assert_eq!(
            supervisor.start(unreachable_spec()),
            Err(StartError::Failed(FailureCode::SpawnFailed))
        );

        assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
        assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
        assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
    }
}
