//! The supervisor against real child processes: spawn, readiness, failure, and containment.
//!
//! The unit gates in `sidecar::supervisor` cover the state machine's edges without a process.
//! These gates are the other half: a real child is spawned from a real [`LaunchSpec`], and
//! when readiness, timing, exit codes, and termination are involved, only a process can
//! answer. The children are the repository's locked Python interpreter running short
//! `-c` programs — the same interpreter the development launch uses — so the test exercises
//! the same spawn path without needing the API server itself. The real end-to-end boundary
//! (spawn `dbench api serve`, authenticate, shut down) lives in `sidecar_integration.rs`.
//!
//! Every test is bounded: `wait_for` asserts on a deadline instead of sleeping forever, and
//! every `Supervisor` is either shut down or was failed by the time its test ends.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use dynamisbench_desktop_lib::sidecar::launch::{locked_interpreter, repository_root};
use dynamisbench_desktop_lib::sidecar::{
    FailureCode, LaunchSpec, SessionSnapshot, SessionStatus, ShutdownOutcome, StartError,
    StateListener, Supervisor, SupervisorConfig,
};

const READY: &str = r#"{"kind":"dynamisbench.api.ready","protocol_version":1,"api_version":"v1","host":"127.0.0.1","port":45999}"#;
const SHUTDOWN: &str = r#"{"kind":"dynamisbench.api.shutdown","protocol_version":1}"#;

/// A child that verifies its environment, announces readiness, and exits 0 on the record.
fn ready_then_shutdown_script() -> String {
    format!(
        r#"
import os, sys
token = os.environ.get('DYNAMISBENCH_SESSION_TOKEN', '')
origins = os.environ.get('DYNAMISBENCH_ALLOWED_ORIGINS', '')
if len(token) != 43 or origins != '["http://localhost:5173"]':
    sys.exit(9)
print('{READY}', flush=True)
line = sys.stdin.readline()
sys.exit(0 if line.strip() == '{SHUTDOWN}' else 3)
"#
    )
}

fn interpreter() -> PathBuf {
    let interpreter = locked_interpreter(&repository_root());
    assert!(
        interpreter.is_file(),
        "these gates need the locked Python environment; run `uv sync --frozen` in python/ \
         first (missing {})",
        interpreter.display()
    );
    interpreter
}

/// A launch spec that runs a short Python program in the repository environment.
fn python_spec(script: &str) -> LaunchSpec {
    LaunchSpec {
        program: interpreter(),
        args: vec![OsString::from("-c"), OsString::from(script)],
        cwd: repository_root(),
        origins: vec!["http://localhost:5173"],
    }
}

fn recorder() -> (Arc<Mutex<Vec<SessionSnapshot>>>, Arc<StateListener>) {
    let snapshots = Arc::new(Mutex::new(Vec::new()));
    let recording = Arc::clone(&snapshots);
    let listener: Arc<StateListener> = Arc::new(move |snapshot: &SessionSnapshot| {
        recording
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(snapshot.clone());
    });
    (snapshots, listener)
}

fn supervisor(config: SupervisorConfig) -> (Arc<Supervisor>, Arc<Mutex<Vec<SessionSnapshot>>>) {
    let (snapshots, listener) = recorder();
    (Arc::new(Supervisor::new(config, listener)), snapshots)
}

fn wait_for_status(
    supervisor: &Supervisor,
    status: SessionStatus,
    timeout: Duration,
) -> SessionSnapshot {
    let deadline = Instant::now() + timeout;
    loop {
        let snapshot = supervisor.snapshot();
        if snapshot.status == status {
            return snapshot;
        }
        assert!(
            Instant::now() < deadline,
            "the session never became {status:?}; last snapshot: {snapshot:?}"
        );
        thread::sleep(Duration::from_millis(20));
    }
}

fn wait_for_starting(supervisor: &Supervisor, timeout: Duration) {
    wait_for_status(supervisor, SessionStatus::Starting, timeout);
}

fn fast_config() -> SupervisorConfig {
    SupervisorConfig {
        startup_timeout: Duration::from_secs(10),
        shutdown_timeout: Duration::from_secs(5),
    }
}

#[test]
fn a_ready_session_reports_the_announced_origin_and_stops_on_the_record() {
    let (supervisor, snapshots) = supervisor(fast_config());

    supervisor
        .start(python_spec(&ready_then_shutdown_script()))
        .expect("the child announces readiness immediately");

    let ready = supervisor.snapshot();
    assert_eq!(ready.status, SessionStatus::Ready);
    assert_eq!(ready.origin.as_deref(), Some("http://127.0.0.1:45999"));
    assert_eq!(ready.api_version.as_deref(), Some("v1"));
    assert_eq!(ready.protocol_version, Some(1));
    assert!(!ready.restart_required);
    let credential = supervisor
        .session_bootstrap()
        .credential()
        .cloned()
        .expect("a ready session holds its credential");
    assert_eq!(credential.expose().len(), 43);

    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Graceful);
    assert_eq!(
        supervisor.request_shutdown(),
        ShutdownOutcome::NotRunning,
        "a repeated shutdown is a no-op, not a second record"
    );

    let stopped = supervisor.snapshot();
    assert_eq!(stopped.status, SessionStatus::Stopped);
    assert!(
        stopped.origin.is_none(),
        "a stopped session reports no address"
    );
    assert!(
        supervisor.session_bootstrap().credential().is_none(),
        "the credential dies with the session"
    );

    let recorded: Vec<SessionStatus> = snapshots
        .lock()
        .unwrap()
        .iter()
        .map(|snapshot| snapshot.status)
        .collect();
    assert_eq!(
        recorded,
        vec![
            SessionStatus::Starting,
            SessionStatus::Ready,
            SessionStatus::Stopped
        ]
    );
}

#[test]
fn a_second_start_is_refused_while_the_session_is_ready() {
    let (supervisor, _) = supervisor(fast_config());

    supervisor
        .start(python_spec(&ready_then_shutdown_script()))
        .expect("ready");

    let second = supervisor.start(supervisor_spec_for_second_attempt());

    assert!(matches!(second, Err(StartError::Refused(_))));
    assert_eq!(supervisor.snapshot().status, SessionStatus::Ready);

    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Graceful);
}

#[test]
fn a_child_that_never_announces_readiness_is_a_bounded_startup_timeout() {
    let (supervisor, _) = supervisor(SupervisorConfig {
        startup_timeout: Duration::from_millis(700),
        shutdown_timeout: Duration::from_secs(2),
    });

    let started = Instant::now();
    let result = supervisor.start(python_spec("import time; time.sleep(60)"));

    assert_eq!(result, Err(StartError::Failed(FailureCode::StartupTimeout)));
    assert!(
        started.elapsed() < Duration::from_secs(10),
        "a startup deadline must be enforced, not merely intended"
    );
    let failed = supervisor.snapshot();
    assert_eq!(failed.status, SessionStatus::Failed);
    assert_eq!(failed.failure, Some(FailureCode::StartupTimeout));
    assert!(!failed.restart_required);
    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
}

#[test]
fn a_first_line_that_is_not_the_protocol_is_a_readiness_protocol_error() {
    let (supervisor, _) = supervisor(fast_config());

    let result = supervisor.start(python_spec(
        "import time; print('hello there', flush=True); time.sleep(60)",
    ));

    assert_eq!(
        result,
        Err(StartError::Failed(FailureCode::ReadinessProtocolError))
    );
    assert_eq!(
        supervisor.snapshot().failure,
        Some(FailureCode::ReadinessProtocolError)
    );
}

#[test]
fn a_child_that_exits_before_readiness_is_a_startup_exit() {
    let (supervisor, _) = supervisor(fast_config());

    let result = supervisor.start(python_spec("import sys; sys.exit(7)"));

    assert_eq!(
        result,
        Err(StartError::Failed(FailureCode::SidecarStartupExit))
    );
    let failed = supervisor.snapshot();
    assert_eq!(failed.failure, Some(FailureCode::SidecarStartupExit));
    assert!(!failed.restart_required);
}

#[test]
fn a_child_that_dies_after_readiness_requires_a_restart() {
    let (supervisor, _) = supervisor(fast_config());
    let script = format!(
        r#"
import sys, time
print('{READY}', flush=True)
time.sleep(0.4)
sys.exit(0)
"#
    );

    supervisor.start(python_spec(&script)).expect("ready");

    let failed = wait_for_status(&supervisor, SessionStatus::Failed, Duration::from_secs(10));

    assert_eq!(failed.failure, Some(FailureCode::UnexpectedExit));
    assert!(failed.restart_required);
    assert!(supervisor.session_bootstrap().credential().is_none());
}

#[test]
fn a_second_stdout_line_after_readiness_is_a_protocol_violation() {
    let (supervisor, _) = supervisor(fast_config());
    let script = format!(
        r#"
import time
print('{READY}', flush=True)
print('an unexpected second line', flush=True)
time.sleep(60)
"#
    );

    supervisor.start(python_spec(&script)).expect("ready");

    let failed = wait_for_status(&supervisor, SessionStatus::Failed, Duration::from_secs(10));

    assert_eq!(failed.failure, Some(FailureCode::ProtocolViolation));
    assert!(failed.restart_required);
}

#[test]
fn a_child_that_ignores_the_record_is_force_killed_and_reaped() {
    let (supervisor, _) = supervisor(SupervisorConfig {
        startup_timeout: Duration::from_secs(10),
        shutdown_timeout: Duration::from_millis(700),
    });
    let pid_file = std::env::temp_dir().join(format!(
        "dynamisbench-res376-shutdown-timeout-{}.pid",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&pid_file);
    let script = format!(
        r#"
import os, sys, time
print('{READY}', flush=True)
with open(r'{pid}', 'w') as handle:
    handle.write(str(os.getpid()))
time.sleep(60)
"#,
        pid = pid_file.display()
    );

    supervisor.start(python_spec(&script)).expect("ready");
    let pid = wait_for_pid_file(&pid_file, Duration::from_secs(10));
    assert!(process_is_alive(pid), "the fixture child must be running");

    let started = Instant::now();
    let outcome = supervisor.request_shutdown();

    assert_eq!(
        outcome,
        ShutdownOutcome::Forced,
        "containment is not graceful"
    );
    assert!(
        started.elapsed() < Duration::from_secs(10),
        "the containment deadline must be enforced"
    );
    let failed = supervisor.snapshot();
    assert_eq!(failed.status, SessionStatus::Failed);
    assert_eq!(failed.failure, Some(FailureCode::ShutdownTimeout));
    assert!(!failed.restart_required);
    wait_until_dead(pid, Duration::from_secs(10));
    let _ = std::fs::remove_file(&pid_file);
}

#[test]
fn a_shutdown_requested_while_starting_contains_the_child_and_stops_the_session() {
    let (supervisor, _) = supervisor(SupervisorConfig {
        startup_timeout: Duration::from_secs(30),
        shutdown_timeout: Duration::from_secs(2),
    });
    let starting = Arc::clone(&supervisor);

    let handle = thread::spawn(move || starting.start(python_spec("import time; time.sleep(60)")));

    wait_for_starting(&supervisor, Duration::from_secs(10));
    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Forced);

    let result = handle.join().expect("the start thread must not panic");
    assert_eq!(result, Err(StartError::Stopped));
    assert_eq!(supervisor.snapshot().status, SessionStatus::Stopped);
    assert!(supervisor.session_bootstrap().credential().is_none());
}

// =====================================================================================
// The atomic bootstrap capture: one read, one state version.
// =====================================================================================

#[test]
fn the_bootstrap_capture_never_straddles_a_lifecycle_transition() {
    let (supervisor, _) = supervisor(fast_config());

    supervisor
        .start(python_spec(&ready_then_shutdown_script()))
        .expect("ready");

    let ready = supervisor.session_bootstrap();
    assert_eq!(ready.snapshot().status, SessionStatus::Ready);
    assert_eq!(
        ready.snapshot().origin.as_deref(),
        Some("http://127.0.0.1:45999")
    );
    assert_eq!(ready.snapshot().api_version.as_deref(), Some("v1"));
    let credential = ready
        .credential()
        .cloned()
        .expect("a ready capture carries the credential it captured with it");
    assert_eq!(credential.expose().len(), 43);

    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Graceful);

    let stopped = supervisor.session_bootstrap();
    assert_eq!(stopped.snapshot().status, SessionStatus::Stopped);
    assert_eq!(stopped.snapshot().origin, None);
    assert_eq!(stopped.snapshot().api_version, None);
    assert_eq!(stopped.snapshot().protocol_version, None);
    assert!(
        stopped.credential().is_none(),
        "the ended session reports neither an address nor a credential, which is the pair \
         the torn response used to split across two reads"
    );

    // The transition that followed did not reach back into the earlier capture.
    assert_eq!(ready.snapshot().status, SessionStatus::Ready);
    assert_eq!(credential.expose().len(), 43);
}

fn supervisor_spec_for_second_attempt() -> LaunchSpec {
    // Never spawned: the refusal is checked before anything runs. A real interpreter keeps
    // the spec honest if the refusal ever regresses.
    python_spec("import sys; sys.exit(1)")
}

// =====================================================================================
// The protocol contract holds through a requested shutdown, not up to it.
// =====================================================================================

#[test]
fn a_second_stdout_line_after_the_shutdown_record_is_a_protocol_violation() {
    let (supervisor, _) = supervisor(fast_config());
    let script = format!(
        r#"
import sys
print('{READY}', flush=True)
line = sys.stdin.readline()
if line.strip() != '{SHUTDOWN}':
    sys.exit(3)
print('a forbidden second line after readiness', flush=True)
sys.exit(0)
"#
    );

    supervisor.start(python_spec(&script)).expect("ready");

    let outcome = supervisor.request_shutdown();

    assert_eq!(
        outcome,
        ShutdownOutcome::Forced,
        "exit code 0 does not excuse writing to the protocol channel"
    );
    let failed = supervisor.snapshot();
    assert_eq!(failed.status, SessionStatus::Failed);
    assert_eq!(failed.failure, Some(FailureCode::ProtocolViolation));
    assert!(!failed.restart_required);
    assert_eq!(failed.origin, None);
    assert!(supervisor.session_bootstrap().credential().is_none());
}

#[test]
fn a_child_that_closes_stdout_before_exiting_zero_after_the_record_is_graceful() {
    let (supervisor, _) = supervisor(fast_config());
    let pid_file = std::env::temp_dir().join(format!(
        "dynamisbench-res376-eof-before-exit-{}.pid",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&pid_file);
    // stdout is closed strictly before the process ends, which is the ordering the shutdown
    // has to survive: EOF first, exit second, and neither may decide alone.
    let script = format!(
        r#"
import os, sys, time
print('{READY}', flush=True)
with open(r'{pid}', 'w') as handle:
    handle.write(str(os.getpid()))
line = sys.stdin.readline()
if line.strip() != '{SHUTDOWN}':
    sys.exit(3)
sys.stdout.close()
time.sleep(0.4)
sys.exit(0)
"#,
        pid = pid_file.display()
    );

    supervisor.start(python_spec(&script)).expect("ready");
    let pid = wait_for_pid_file(&pid_file, Duration::from_secs(10));
    assert!(process_is_alive(pid), "the fixture child must be running");

    let outcome = supervisor.request_shutdown();

    assert_eq!(outcome, ShutdownOutcome::Graceful);
    let stopped = supervisor.snapshot();
    assert_eq!(stopped.status, SessionStatus::Stopped);
    assert_eq!(stopped.failure, None);
    wait_until_dead(pid, Duration::from_secs(10));
    let _ = std::fs::remove_file(&pid_file);
}

#[test]
fn a_child_that_exits_non_zero_after_the_record_is_an_unexpected_exit() {
    let (supervisor, _) = supervisor(fast_config());
    let script = format!(
        r#"
import sys
print('{READY}', flush=True)
line = sys.stdin.readline()
if line.strip() != '{SHUTDOWN}':
    sys.exit(3)
sys.stdout.close()
sys.exit(7)
"#
    );

    supervisor.start(python_spec(&script)).expect("ready");

    let outcome = supervisor.request_shutdown();

    assert_eq!(outcome, ShutdownOutcome::Forced);
    let failed = supervisor.snapshot();
    assert_eq!(failed.status, SessionStatus::Failed);
    assert_eq!(failed.failure, Some(FailureCode::UnexpectedExit));
    assert!(
        !failed.restart_required,
        "a session that was asked to stop and did not stop cleanly is not a crash"
    );
}

fn wait_for_pid_file(path: &Path, timeout: Duration) -> u32 {
    let deadline = Instant::now() + timeout;
    loop {
        if let Ok(contents) = std::fs::read_to_string(path) {
            if let Ok(pid) = contents.trim().parse::<u32>() {
                return pid;
            }
        }
        assert!(
            Instant::now() < deadline,
            "the fixture child never wrote its pid to {}",
            path.display()
        );
        thread::sleep(Duration::from_millis(20));
    }
}

fn wait_until_dead(pid: u32, timeout: Duration) {
    let deadline = Instant::now() + timeout;
    while process_is_alive(pid) {
        assert!(
            Instant::now() < deadline,
            "the child survived containment; pid {pid} is still alive"
        );
        thread::sleep(Duration::from_millis(20));
    }
}

fn process_is_alive(pid: u32) -> bool {
    #[cfg(windows)]
    {
        let output = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/NH", "/FO", "CSV"])
            .output();
        match output {
            Ok(output) => String::from_utf8_lossy(&output.stdout).contains(&pid.to_string()),
            Err(_) => false,
        }
    }
    #[cfg(not(windows))]
    {
        Command::new("kill")
            .args(["-0", &pid.to_string()])
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    }
}
