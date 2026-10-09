//! One supervised child: spawn, watch, stop, reap — without a runtime and without a leak.
//!
//! RES-376 gives each desktop session exactly one `dbench api serve` child. This module owns
//! that child's whole life on a dedicated OS thread — the *owner*:
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
//! Three properties are structural here rather than conventional, and all three are the same
//! property seen from different sides: **the child is only ever reachable through an owner
//! that can be addressed**.
//!
//! * **The owner performs the process creation, not its caller.** [`Supervisor::start`] admits
//!   the session, publishes the owner's command channel, and *then* starts the owner thread —
//!   so by the time anything can be created, there is already a thread an exit can address.
//!   The caller never holds a child and never has one.
//! * **A start and a desktop exit cannot both be in flight.** [`Supervisor::admit_start`]
//!   refuses a start once the desktop has claimed its exit, and
//!   [`Supervisor::request_shutdown`] waits out a start that has already been admitted instead
//!   of reporting that there is nothing to stop.
//! * **A requested shutdown does not stop watching stdout.** The protocol channel stays
//!   observed from the moment the shutdown record is written until the child is reaped, so
//!   "exactly one readiness line per session" is enforced during shutdown too. A child that
//!   writes a second line and *then* exits 0 is a protocol violation that was force-contained,
//!   not a graceful shutdown.
//!
//! The consequence that governs the exit path: **[`ShutdownOutcome`] is a proof, not a
//! summary.** Every value this module returns is one of
//!
//! ```text
//! no child was created  |  the child exited gracefully  |  the child was force-terminated and reaped
//! ```
//!
//! and there is no deadline anywhere in the production path that can produce one of those
//! without the corresponding fact being true. The only bounds in this module are the owner's
//! own two — [`SupervisorConfig::startup_timeout`] and [`SupervisorConfig::shutdown_timeout`] —
//! and both are enforced by the thread that owns the process.
//!
//! In particular the operating system's process creation cannot be bounded from another
//! thread, so an exit that arrives while one is in flight waits for the owner rather than
//! timing out: a wait that has expired is evidence about a clock, not about a process. See
//! [`Gate::resolved`] and [`Supervisor::terminal_proof`].
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
///
/// Every variant is a terminal *proof* about the one child, established before it is
/// returned. Nothing here can be produced by a wait that merely expired: an expired deadline
/// is a statement about elapsed time, and the only claims this type makes are about a
/// process.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShutdownOutcome {
    /// The child exited 0 after being asked through the control channel, having written
    /// nothing further to the protocol channel.
    Graceful,
    /// The child was force-terminated and reaped, and that kill and reap had happened before
    /// this was reported.
    ///
    /// This is the one outcome that must never be a fallback. A deadline that expires while an
    /// admitted start is still creating a process proves nothing about that process, so a
    /// caller that cannot yet establish containment waits for the owner rather than reporting
    /// this — see [`Supervisor::request_shutdown`].
    Forced,
    /// The child was never created, or it was already gone when the request was answered.
    ///
    /// In both cases there is provably nothing left to stop, which is why a request that finds
    /// the session already concluded answers this and not the proof the session recorded.
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
/// hold a start at the process-creation call, count spawn attempts, and return a real child
/// from a forced interleaving — it is not a configuration surface: the [`LaunchSpec`] still
/// comes from the fixed launch resolution, no WebView input reaches it, and nothing about the
/// launch becomes caller-chosen.
pub type SpawnSidecar = dyn Fn(&LaunchSpec, &SessionCredential) -> io::Result<Child> + Send + Sync;

/// Where a session is in the supervisor's own lifecycle.
///
/// This is not the vocabulary the WebView sees — that is [`crate::sidecar::SessionStatus`] —
/// but the authority for two questions that the public state alone cannot answer: may a start
/// proceed, and is there an owner a shutdown can be addressed to.
///
/// The command channel lives *inside* the phase rather than beside it, so "addressable" and
/// "which phase" cannot disagree: a caller that can see a channel can also see that it is
/// the owner, and every transition that withdraws the channel withdraws the addressability
/// with it.
#[derive(Debug, Clone)]
enum Phase {
    /// No start has been admitted and none is in flight.
    Idle,
    /// A start has been admitted and the owner is being established. Nothing is created and
    /// nothing can block here: the window is two critical sections wide.
    StartReserved,
    /// The owner exists and is addressable through the channel it was handed. The child may
    /// still be in the middle of being created — that is the point: from here an exit reaches
    /// the thread that performs the spawn rather than waiting on a caller that has none.
    Owned(Sender<SupervisorCommand>),
    /// A shutdown has been delivered to the owner and the session is ending. A second caller
    /// waits here for the first one's proof instead of being told nothing is running.
    Exiting,
    /// The child is gone and one terminal proof has been recorded with the transition.
    Terminated,
}

/// How a session ended, beside the proof that ending earned.
///
/// Split in three because the distinction is a reporting requirement, not a convenience:
/// only an *unsolicited* failure of an *established* session means `restart_required`. A
/// session that was asked to stop did not crash, and a session that never served has nothing
/// to restart.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionEnd {
    /// A requested shutdown completed, or no child ever ran.
    Stopped,
    /// A bounded failure of a session that either never served or was asked to stop.
    Failed(FailureCode),
    /// A bounded failure of a serving session that nobody asked to stop: the only kind that
    /// sets `restart_required`.
    Crash(FailureCode),
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
    proof: ShutdownOutcome,
}

impl Control {
    fn new() -> Self {
        Self {
            session: SessionState::stopped(),
            phase: Phase::Idle,
            exit_claimed: false,
            // Read only once `phase` is `terminated`, which is the only moment it is a proof
            // about a process rather than a placeholder for one.
            proof: ShutdownOutcome::NotRunning,
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

    /// Publish the owner's command channel: the session is now addressable.
    ///
    /// Called before the owner thread exists, and before anything can be created, so there is
    /// no window in which a child is being brought into existence that nobody could reach.
    fn established(&mut self, commands: Sender<SupervisorCommand>) {
        self.phase = Phase::Owned(commands);
    }

    /// The session is over: nothing is addressable, no start may follow, and the one terminal
    /// proof about the child is recorded here rather than invented later.
    fn concluded(&mut self, proof: ShutdownOutcome) {
        self.phase = Phase::Terminated;
        self.proof = proof;
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
/// before the owner is established — or while another caller is already performing the
/// shutdown — waits for the proof that follows instead of reporting that there is nothing to
/// stop. It is the wait, not a sleep and not a retry, that makes "exit wins before spawn" and
/// "start wins before exit" the only two possible orders.
///
/// There is no timed wait anywhere in this module. [`Condvar::wait_timeout`] was the previous
/// shape and it was wrong: when its bound expired it answered [`ShutdownOutcome::Forced`]
/// about a process that had never been shown to exist, and the desktop then exited on that.
/// An OS process creation cannot be bounded from another thread, so the honest answer to a
/// wait that has not finished is to keep waiting.
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
    /// be reached from the WebView. It exists so "the exit won, so no child was spawned",
    /// "the exit arrived while the spawn was still in flight", and "the spawn returned a child
    /// the exit then had to contain" can each be forced as an exact ordering rather than hunted
    /// for.
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

    /// The terminal proof this supervisor holds about the child, or `None` while one is owed.
    ///
    /// This is the only thing a final desktop exit may rest on, and it is `None` in exactly
    /// the situation that matters: a start has been admitted, the owner exists and is
    /// addressable, but the child may still be in the middle of being created — so nothing is
    /// yet true about the process. `Idle` answers `NotRunning` because nothing was ever
    /// admitted and nothing can appear.
    ///
    /// It is deliberately not what [`Supervisor::request_shutdown`] returns: that is what *a
    /// given request* achieved, so a request arriving after the session concluded is told
    /// `NotRunning` rather than replaying the proof an earlier request earned.
    pub fn terminal_proof(&self) -> Option<ShutdownOutcome> {
        held_proof(&self.gate)
    }

    /// Admit the start, hand the owner an address, and block until readiness resolves.
    ///
    /// The ordering here is the fix for the defect this module used to have. Admission and
    /// the owner's command channel are taken in one critical section, *before* the owner
    /// thread is started and therefore before anything can be created:
    ///
    /// ```text
    /// admit start → establish monitor/control ownership → the owner performs the spawn
    /// ```
    ///
    /// rather than a caller spawning first and publishing an address afterwards, which left a
    /// window where a process creation was in flight and no exit could reach it. A shutdown
    /// arriving after this point has a thread to address even if the process creation that
    /// thread is about to perform never returns.
    ///
    /// `Ok` means the session is ready and the credential is held; `Err` means the session is
    /// failed, was refused, or the desktop claimed its exit first — in which case no child was
    /// created.
    ///
    /// The wait has no deadline of its own: the owner reports every outcome exactly once,
    /// including the one that follows a process creation the operating system took its time
    /// over, so a bound here could only ever report the absence of a report.
    pub fn start(&self, spec: LaunchSpec) -> Result<(), StartError> {
        let (commands, command_rx) = mpsc::channel();
        {
            let mut control = lock(&self.gate.control);
            control.admit_start()?;
            control.established(commands);
        }
        self.gate.announce();
        publish(&self.gate, &self.listener);

        let (startup_tx, startup_rx) = mpsc::channel();
        let gate = Arc::clone(&self.gate);
        let listener = Arc::clone(&self.listener);
        let config = self.config;
        let spawner = Arc::clone(&self.spawn_sidecar);
        if thread::Builder::new()
            .name("dynamisbench-sidecar-owner".to_string())
            .spawn(move || {
                own(
                    spec, spawner, config, gate, listener, command_rx, startup_tx,
                );
            })
            .is_err()
        {
            // No owner means no process: nothing was created and nothing can appear later.
            conclude(
                &self.gate,
                &self.listener,
                SessionEnd::Failed(FailureCode::SpawnFailed),
                ShutdownOutcome::NotRunning,
            );
            return Err(StartError::Failed(FailureCode::SpawnFailed));
        }

        // There is no deadline here either, and the reason is the same as in the exit path:
        // every exit from `own` sends exactly one resolution, so a bound added to this wait
        // could only ever report the absence of a *report*. The owner's own startup deadline
        // is what ends a start that is not going to succeed.
        match startup_rx.recv() {
            Ok(StartupResolution::Ready) => Ok(()),
            Ok(StartupResolution::Failed(code)) => Err(StartError::Failed(code)),
            Ok(StartupResolution::Stopped) => Err(StartError::Stopped),
            // The owner ended without reporting one, which no path it takes does. There is no
            // session to report as ready, and no deadline that may be passed off as a reason.
            Err(_) => Err(StartError::Failed(FailureCode::SpawnFailed)),
        }
    }

    /// Ask the child to stop, wait for it, and contain it if it will not go.
    ///
    /// Idempotent in the sense that matters: every caller is told something true. The first
    /// caller performs the shutdown; a caller that arrives while it is in progress waits for
    /// the same conclusion rather than being told there is nothing to stop; a caller that
    /// arrives after the session concluded is told there is nothing left to stop. There is no
    /// second record and no second child.
    ///
    /// The one answer this must never give while a child could still appear is any outcome at
    /// all. A start that has been admitted is addressable from the moment it is admitted, so
    /// this does not wait for a child to exist — it waits for the *owner* to report:
    ///
    /// ```text
    /// a shutdown that arrives before the child exists
    ///     → owner proves no child can appear            → NotRunning
    /// a shutdown that arrives while the creation is in flight and the creation fails
    ///     → owner proves no child exists                → NotRunning
    /// a shutdown that arrives while the creation is in flight and it returns a child
    ///     → owner terminates and reaps it immediately   → Forced
    /// ```
    ///
    /// There is no deadline here and therefore no way for a clock to stand in for a fact about
    /// a process. If the owner cannot yet establish which of those three it is, this keeps
    /// waiting: a cosmetically bounded close is worth less than an honest one.
    pub fn request_shutdown(&self) -> ShutdownOutcome {
        let commands = {
            let mut control = lock(&self.gate.control);
            loop {
                match control.phase.clone() {
                    // Nothing was ever admitted, so nothing can appear now or later.
                    Phase::Idle => return ShutdownOutcome::NotRunning,
                    Phase::Owned(commands) => {
                        control.phase = Phase::Exiting;
                        break commands;
                    }
                    // An admitted start that has not published its owner yet, or a shutdown
                    // another caller is already performing. Both resolve into a terminal
                    // proof, and neither is bounded: an owner that has not concluded has not
                    // yet told the truth about its child, and this thread cannot supply it.
                    Phase::StartReserved | Phase::Exiting => {
                        control = self
                            .gate
                            .resolved
                            .wait(control)
                            .unwrap_or_else(PoisonError::into_inner);
                    }
                    // The session has ended, so its child was either never created or was
                    // terminated and reaped before the record said so. Nothing is left to stop.
                    Phase::Terminated => return ShutdownOutcome::NotRunning,
                }
            }
        };

        let (reply, reply_rx) = mpsc::channel();
        if commands.send(SupervisorCommand::Shutdown { reply }).is_ok() {
            if let Ok(proof) = reply_rx.recv() {
                return proof;
            }
        }
        // The owner is gone, so the command cannot be delivered or was never read. The owner's
        // own conclusion is the only proof that can exist: every exit from it runs
        // `conclude`, so the record reaches `terminated` with the proof beside it. There is no
        // bound on this wait either, because a proof that has not been recorded cannot be
        // replaced by a guess.
        self.recorded_proof()
    }

    /// Wait until the session has concluded, and take the proof it concluded with.
    fn recorded_proof(&self) -> ShutdownOutcome {
        let mut control = lock(&self.gate.control);
        while !matches!(control.phase, Phase::Terminated) {
            control = self
                .gate
                .resolved
                .wait(control)
                .unwrap_or_else(PoisonError::into_inner);
        }
        control.proof
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
}

/// The thread that owns the session, from before the child exists to after its reap.
///
/// Every way out of this function runs [`conclude`], so the owner cannot end without having
/// recorded one terminal proof about the child. That is what lets an exit wait for the proof
/// with no deadline: the thread being waited on cannot finish early, and the one call on this
/// path that cannot be bounded from outside — the operating system's process creation — sits
/// behind a command channel that was published before this function was entered.
#[allow(clippy::too_many_arguments)]
fn own(
    spec: LaunchSpec,
    spawner: Arc<SpawnSidecar>,
    config: SupervisorConfig,
    gate: Arc<Gate>,
    listener: Arc<StateListener>,
    command_rx: Receiver<SupervisorCommand>,
    startup: Sender<StartupResolution>,
) {
    // An exit that arrives before anything exists still ends the session, and there is
    // provably nothing to stop: no credential, no child, nothing that can appear.
    if let Some(reply) = pending_shutdown(&command_rx) {
        conclude(
            &gate,
            &listener,
            SessionEnd::Stopped,
            ShutdownOutcome::NotRunning,
        );
        let _ = startup.send(StartupResolution::Stopped);
        let _ = reply.send(ShutdownOutcome::NotRunning);
        return;
    }

    // The credential is generated here, immediately before the spawn, because the child's
    // environment is the first and only thing that needs it; an entropy failure is a bounded
    // `credential_unavailable` session failure rather than an error the caller must handle,
    // and it still cannot leave a child behind.
    let credential = match SessionCredential::generate() {
        Ok(credential) => credential,
        Err(_) => {
            conclude(
                &gate,
                &listener,
                SessionEnd::Failed(FailureCode::CredentialUnavailable),
                ShutdownOutcome::NotRunning,
            );
            let _ = startup.send(StartupResolution::Failed(
                FailureCode::CredentialUnavailable,
            ));
            return;
        }
    };

    // The only process creation in this crate, and the only call on the owner's path that
    // cannot be bounded from another thread. It is performed *here*, behind a published
    // command channel, so an exit that arrives while it is in flight is delivered rather than
    // timed out against.
    let mut child = match (spawner)(&spec, &credential) {
        Ok(child) => child,
        Err(_) => {
            // The operating system created no process. That is the proof an in-flight exit has
            // been waiting for; which of the two endings to record beside it depends only on
            // whether somebody asked.
            if let Some(reply) = pending_shutdown(&command_rx) {
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Stopped,
                    ShutdownOutcome::NotRunning,
                );
                let _ = startup.send(StartupResolution::Stopped);
                let _ = reply.send(ShutdownOutcome::NotRunning);
            } else {
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Failed(FailureCode::SpawnFailed),
                    ShutdownOutcome::NotRunning,
                );
                let _ = startup.send(StartupResolution::Failed(FailureCode::SpawnFailed));
            }
            return;
        }
    };

    // The creation returned a real child, and an exit may already be waiting for it. That
    // child has never been addressed by anyone and must not outlive a desktop that is already
    // leaving, so containment is immediate and the proof is earned by the kill and reap below.
    if let Some(reply) = pending_shutdown(&command_rx) {
        terminate_and_reap(&mut child);
        conclude(
            &gate,
            &listener,
            SessionEnd::Stopped,
            ShutdownOutcome::Forced,
        );
        let _ = startup.send(StartupResolution::Stopped);
        let _ = reply.send(ShutdownOutcome::Forced);
        return;
    }

    let (Some(stdout), Some(stderr), Some(stdin)) =
        (child.stdout.take(), child.stderr.take(), child.stdin.take())
    else {
        // Cannot happen with `Stdio::piped`, and if it did, nothing can be supervised. The
        // child did exist, so the proof is containment rather than absence.
        terminate_and_reap(&mut child);
        conclude(
            &gate,
            &listener,
            SessionEnd::Failed(FailureCode::SpawnFailed),
            ShutdownOutcome::Forced,
        );
        let _ = startup.send(StartupResolution::Failed(FailureCode::SpawnFailed));
        return;
    };

    supervise(
        child,
        stdout,
        stderr,
        Some(stdin),
        credential,
        config,
        gate,
        listener,
        command_rx,
        startup,
    );
}

/// From the child the owner now holds to its reap: the startup watch, then the serving watch.
///
/// `Ok(StartupResolution::…)` is how the session's own caller is told; the proof a *shutdown*
/// caller is told is the reply on its own channel, and the record holds the same value from
/// the moment [`conclude`] runs.
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
        if let Some(reply) = pending_shutdown(&command_rx) {
            terminate_and_reap(&mut child);
            conclude(
                &gate,
                &listener,
                SessionEnd::Stopped,
                ShutdownOutcome::Forced,
            );
            let _ = startup.send(StartupResolution::Stopped);
            let _ = reply.send(ShutdownOutcome::Forced);
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
                    conclude(
                        &gate,
                        &listener,
                        SessionEnd::Failed(FailureCode::ReadinessProtocolError),
                        ShutdownOutcome::NotRunning,
                    );
                    let _ = startup.send(StartupResolution::Failed(
                        FailureCode::ReadinessProtocolError,
                    ));
                    return;
                }
            },
            Ok(ProtocolEvent::Eof) => {
                terminate_and_reap(&mut child);
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Failed(FailureCode::SidecarStartupExit),
                    ShutdownOutcome::NotRunning,
                );
                let _ = startup.send(StartupResolution::Failed(FailureCode::SidecarStartupExit));
                return;
            }
            Ok(ProtocolEvent::Malformed) => {
                terminate_and_reap(&mut child);
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Failed(FailureCode::ReadinessProtocolError),
                    ShutdownOutcome::NotRunning,
                );
                let _ = startup.send(StartupResolution::Failed(
                    FailureCode::ReadinessProtocolError,
                ));
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if Instant::now() >= deadline {
                    terminate_and_reap(&mut child);
                    conclude(
                        &gate,
                        &listener,
                        SessionEnd::Failed(FailureCode::StartupTimeout),
                        ShutdownOutcome::NotRunning,
                    );
                    let _ = startup.send(StartupResolution::Failed(FailureCode::StartupTimeout));
                    return;
                }
                if matches!(child.try_wait(), Ok(Some(_))) {
                    terminate_and_reap(&mut child);
                    conclude(
                        &gate,
                        &listener,
                        SessionEnd::Failed(FailureCode::SidecarStartupExit),
                        ShutdownOutcome::NotRunning,
                    );
                    let _ =
                        startup.send(StartupResolution::Failed(FailureCode::SidecarStartupExit));
                    return;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                terminate_and_reap(&mut child);
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Failed(FailureCode::ReadinessProtocolError),
                    ShutdownOutcome::NotRunning,
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
#[allow(clippy::too_many_arguments)]
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
                let (proof, failure) =
                    graceful_shutdown(&mut child, stdin.take(), &lines_rx, config.shutdown_timeout);
                let end = match failure {
                    None => SessionEnd::Stopped,
                    Some(code) => SessionEnd::Failed(code),
                };
                conclude(&gate, &listener, end, proof);
                let _ = reply.send(proof);
                return;
            }
            Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) => {}
        }

        match lines_rx.recv_timeout(POLL_INTERVAL) {
            Ok(ProtocolEvent::Line(_)) | Ok(ProtocolEvent::Malformed) => {
                terminate_and_reap(&mut child);
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Crash(FailureCode::ProtocolViolation),
                    ShutdownOutcome::NotRunning,
                );
                return;
            }
            Ok(ProtocolEvent::Eof) => {
                terminate_and_reap(&mut child);
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Crash(FailureCode::UnexpectedExit),
                    ShutdownOutcome::NotRunning,
                );
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    terminate_and_reap(&mut child);
                    conclude(
                        &gate,
                        &listener,
                        SessionEnd::Crash(FailureCode::UnexpectedExit),
                        ShutdownOutcome::NotRunning,
                    );
                    return;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                terminate_and_reap(&mut child);
                conclude(
                    &gate,
                    &listener,
                    SessionEnd::Crash(FailureCode::ProtocolViolation),
                    ShutdownOutcome::NotRunning,
                );
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

/// Read protocol lines until EOF, handing each one to the owner.
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

/// A pending shutdown request, taken non-blockingly from the owner's command channel.
///
/// Checked before the credential, immediately after the process creation, and once per turn of
/// the startup watch, so a request is observed at the earliest point its answer can be a
/// proof rather than a hope.
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
///
/// Every return is a proof: the child has exited 0, or it has been killed and reaped, before
/// the answer is produced.
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
/// Nothing is reported as [`ShutdownOutcome::Forced`] without this having run.
fn terminate_and_reap(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

/// End the session and record its terminal proof, in one critical section, before publishing.
///
/// The three properties that matter about a conclusion, all of them structural:
///
/// * the public state, the phase, and the proof move together, so a caller that observes the
///   published snapshot — or the `StartError` that resolved a failed start — cannot then be
///   told the owner is still addressable;
/// * the owner's command channel is withdrawn by dropping the phase, so there is no way to
///   reach an owner that has ended;
/// * the proof is a parameter, so a caller cannot publish a conclusion whose proof it has
///   not actually established.
fn conclude(
    gate: &Arc<Gate>,
    listener: &Arc<StateListener>,
    end: SessionEnd,
    proof: ShutdownOutcome,
) {
    {
        let mut control = lock(&gate.control);
        match end {
            SessionEnd::Stopped => control.session.mark_stopped(),
            SessionEnd::Failed(code) => control.session.mark_failed(code, false),
            SessionEnd::Crash(code) => control.session.mark_failed(code, true),
        }
        control.concluded(proof);
    }
    gate.announce();
    publish(gate, listener);
}

/// Hand the listener the current snapshot without holding the control lock across the call.
fn publish(gate: &Arc<Gate>, listener: &Arc<StateListener>) {
    let snapshot = lock(&gate.control).snapshot();
    listener(&snapshot);
}

/// The terminal proof the record currently holds, or `None` while one is still owed.
///
/// `Idle` answers `NotRunning` because nothing was ever admitted and nothing can appear. Every
/// other phase that has not concluded owes a proof, which is the statement that an admitted
/// start may still be inside its process creation.
fn held_proof(gate: &Gate) -> Option<ShutdownOutcome> {
    let control = lock(&gate.control);
    match control.phase {
        Phase::Idle => Some(ShutdownOutcome::NotRunning),
        Phase::StartReserved | Phase::Owned(_) | Phase::Exiting => None,
        Phase::Terminated => Some(control.proof),
    }
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
    use std::sync::{Arc, Mutex, PoisonError};
    use std::time::{Duration, Instant};

    use super::{
        conclude, lock, Gate, Phase, SessionEnd, ShutdownOutcome, StartError, StateListener,
        Supervisor, SupervisorConfig, ALLOWED_ORIGINS_VARIABLE, SESSION_TOKEN_VARIABLE,
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
        assert_eq!(
            supervisor.terminal_proof(),
            Some(ShutdownOutcome::NotRunning),
            "no start was ever admitted, so no child can appear and that is already a proof"
        );
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
        assert_eq!(
            supervisor.terminal_proof(),
            Some(ShutdownOutcome::NotRunning),
            "no process was created, so absence is proven rather than assumed"
        );
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
    // The start/exit fence and the terminal proof.
    // ---------------------------------------------------------------------------------

    #[test]
    fn a_start_after_the_exit_claim_is_refused_and_never_spawns() {
        let attempts = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&attempts);
        let published = Arc::new(Mutex::new(Vec::new()));
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

    /// The reservation defect, now fixed by construction: the spawn seam holds the process
    /// creation, and the exit that arrives while it is held is still waiting when it is
    /// inspected. Nothing is claimed, because nothing has been proved.
    #[test]
    fn a_shutdown_while_the_spawn_is_in_flight_waits_instead_of_reporting_nothing() {
        let (entered_tx, entered_rx) = mpsc::channel::<()>();
        let (release_tx, release_rx) = mpsc::channel::<()>();
        // The spawner has to be `Sync` because the supervisor may be shared, so the release
        // handshake lives behind a lock rather than being moved into the closure.
        let release = Mutex::new(release_rx);
        let supervisor = Arc::new(Supervisor::with_spawner(
            SupervisorConfig::default(),
            Arc::new(|_snapshot| {}),
            Arc::new(move |_spec, _credential| {
                // Held inside the process creation: no child exists, and the command channel
                // that an exit needs has been published for the whole of this call.
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
            .expect("the owner reached its process creation");

        let exiting = Arc::clone(&supervisor);
        let (outcome_tx, outcome_rx) = mpsc::channel();
        std::thread::spawn(move || {
            let _ = outcome_tx.send(exiting.request_shutdown());
        });

        assert!(
            outcome_rx.try_recv().is_err(),
            "the exit must wait: a process creation is in flight and the child it may produce \
             cannot be reported as absent"
        );
        assert_eq!(
            supervisor.terminal_proof(),
            None,
            "and it has no desktop-terminal proof to fall back on"
        );

        release_tx
            .send(())
            .expect("the owner must be released to finish the creation");

        let result = start.join().expect("the start thread must not panic");
        let outcome = outcome_rx
            .recv_timeout(Duration::from_secs(10))
            .expect("the exit must resolve once the creation does");

        assert_eq!(
            outcome,
            ShutdownOutcome::NotRunning,
            "the creation failed, so no child exists and that is proven rather than assumed"
        );
        assert_eq!(
            supervisor.terminal_proof(),
            Some(ShutdownOutcome::NotRunning)
        );
        // Which ending the session recorded is not this gate's subject, and it is genuinely
        // order-dependent: the owner checks for a pending exit both before the credential and
        // again after a failed creation, so a request that arrived in between is answered as a
        // stopped session and one that arrived after it is answered as a spawn failure. Both
        // say the same true thing — no child was ever created. The endings are pinned
        // individually, with the ordering forced, in the two blocked-creation gates in
        // `sidecar_supervision`.
        assert!(
            matches!(
                result,
                Err(StartError::Failed(FailureCode::SpawnFailed)) | Err(StartError::Stopped)
            ),
            "a creation that produced no child reports exactly one of the two honest endings, \
             got {result:?}"
        );
        assert!(supervisor.session_bootstrap().credential().is_none());
    }

    /// The record owes a proof in exactly one situation, and this is it.
    ///
    /// Checked against the bare gate rather than through a supervisor so every state is
    /// reachable without a process: the phases that address an owner are precisely the ones
    /// that must report no proof, because a child may still be coming.
    #[test]
    fn the_record_owes_a_proof_exactly_while_an_owner_is_addressable() {
        let gate = Arc::new(Gate::new());
        let listener: Arc<StateListener> = Arc::new(|_snapshot| {});

        assert_eq!(
            super::held_proof(&gate),
            Some(ShutdownOutcome::NotRunning),
            "a fresh record admits no start, so nothing can appear"
        );

        {
            let mut control = lock(&gate.control);
            control.admit_start().expect("the first start is admitted");
        }
        assert_eq!(
            super::held_proof(&gate),
            None,
            "an admitted start owes a proof: its child may still be coming"
        );

        {
            let mut control = lock(&gate.control);
            control.established(mpsc::channel().0);
        }
        assert_eq!(
            super::held_proof(&gate),
            None,
            "an addressable owner still owes a proof: it may be inside the process creation"
        );

        {
            let mut control = lock(&gate.control);
            control.phase = Phase::Exiting;
        }
        assert_eq!(
            super::held_proof(&gate),
            None,
            "a shutdown in progress still owes a proof"
        );

        conclude(
            &gate,
            &listener,
            SessionEnd::Stopped,
            ShutdownOutcome::Forced,
        );
        assert_eq!(
            super::held_proof(&gate),
            Some(ShutdownOutcome::Forced),
            "and the conclusion discharges the debt"
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

    /// A start that resolved as failed has already ended its session, so the record must not
    /// still be offering the owner to the caller that is told about it.
    ///
    /// This is the ordering a failed start loses if the session's own transition and the phase
    /// transition are separate critical sections: `start` returns as soon as it has read its
    /// resolution, which is before the owner thread has finished unwinding, so a shutdown
    /// called immediately afterwards finds a channel nobody is reading and waits out its whole
    /// grace period. The phase has to move with the session, not after it.
    #[test]
    fn a_start_that_failed_leaves_nothing_to_address() {
        for _ in 0..16 {
            let supervisor = quiet_supervisor();

            let result = supervisor.start(unreachable_spec());
            assert_eq!(result, Err(StartError::Failed(FailureCode::SpawnFailed)));

            let started = Instant::now();
            assert_eq!(
                supervisor.request_shutdown(),
                ShutdownOutcome::NotRunning,
                "the child was never created, so the record must already say so"
            );
            assert!(
                started.elapsed() < Duration::from_secs(2),
                "the answer must be immediate: an owner that has ended needs no waiting"
            );
        }
    }

    /// No conclusion may leave the record offering an owner that is gone.
    ///
    /// Checked at the moment the snapshot is published rather than after the calling thread has
    /// finished unwinding: a listener runs outside the critical section, so it can read the
    /// phase that accompanies the snapshot, and anything that reacts to that snapshot — the
    /// WebView, or the `start` call waiting on the resolution — must already see a concluded
    /// record. This is deterministic; the failure it prevents was a lost thread race.
    #[test]
    fn every_conclusion_withdraws_the_owner_before_publishing() {
        let conclusions: [(&str, SessionEnd, ShutdownOutcome); 4] = [
            (
                "never created",
                SessionEnd::Failed(FailureCode::SpawnFailed),
                ShutdownOutcome::NotRunning,
            ),
            (
                "asked to stop",
                SessionEnd::Stopped,
                ShutdownOutcome::Forced,
            ),
            (
                "stopped cleanly",
                SessionEnd::Stopped,
                ShutdownOutcome::Graceful,
            ),
            (
                "force-contained",
                SessionEnd::Failed(FailureCode::ShutdownTimeout),
                ShutdownOutcome::Forced,
            ),
        ];

        for (label, end, proof) in conclusions {
            let gate = Arc::new(Gate::new());
            let seen = Arc::new(Mutex::new(Vec::new()));
            let observed = Arc::clone(&seen);
            let inspected = Arc::clone(&gate);
            let listener: Arc<StateListener> = Arc::new(move |snapshot| {
                observed
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .push((snapshot.status, lock(&inspected.control).phase.clone()));
            });

            {
                let mut control = lock(&gate.control);
                control.admit_start().expect("the first start is admitted");
                control.session.mark_ready(
                    "http://127.0.0.1:49152".into(),
                    "v1".into(),
                    1,
                    SessionCredential::generate().unwrap(),
                );
                // A channel nobody will ever read, exactly like an owner that has just ended.
                control.established(mpsc::channel().0);
            }
            assert!(matches!(lock(&gate.control).phase, Phase::Owned(_)));

            conclude(&gate, &listener, end, proof);

            let published = seen
                .lock()
                .expect("the observation lock is not poisoned")
                .clone();
            assert_eq!(
                published.len(),
                1,
                "{label}: the terminal snapshot must be published exactly once"
            );
            assert!(
                matches!(published[0].1, Phase::Terminated),
                "{label}: a caller reacting to the published snapshot must not find an owner \
                 still addressable"
            );
            let control = lock(&gate.control);
            assert!(
                matches!(control.phase, Phase::Terminated),
                "{label}: and the channel is withdrawn with the phase"
            );
            assert_eq!(
                control.proof, proof,
                "{label}: the proof is recorded with the transition, not after it"
            );
        }
    }

    /// The old defect's other half: a session that was asked to stop and did so is not a
    /// crash, so nothing about it sets `restart_required`.
    #[test]
    fn only_an_unsolicited_failure_of_a_serving_session_asks_for_a_restart() {
        for (end, restart_required) in [
            (SessionEnd::Stopped, false),
            (SessionEnd::Failed(FailureCode::ShutdownTimeout), false),
            (SessionEnd::Failed(FailureCode::SpawnFailed), false),
            (SessionEnd::Crash(FailureCode::UnexpectedExit), true),
            (SessionEnd::Crash(FailureCode::ProtocolViolation), true),
        ] {
            let gate = Arc::new(Gate::new());
            let published = Arc::new(Mutex::new(Vec::new()));
            let observed = Arc::clone(&published);
            let listener: Arc<StateListener> = Arc::new(move |snapshot| {
                observed
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .push(snapshot.clone());
            });
            {
                let mut control = lock(&gate.control);
                control.admit_start().expect("the first start is admitted");
                control.session.mark_ready(
                    "http://127.0.0.1:49152".into(),
                    "v1".into(),
                    1,
                    SessionCredential::generate().unwrap(),
                );
            }

            conclude(&gate, &listener, end, ShutdownOutcome::NotRunning);

            let snapshot = published
                .lock()
                .expect("the observation lock is not poisoned")
                .pop()
                .expect("the conclusion publishes exactly one snapshot");
            assert_eq!(snapshot.restart_required, restart_required, "{end:?}");
        }
    }
}
