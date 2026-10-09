//! DynamisBench desktop shell.
//!
//! Thin Tauri 2 wrapper only (ADR-013): the shell owns window, process, and OS integration
//! and nothing else. All scientific and VVUQ logic lives in the Python core and application
//! API, which this shell supervises as one local sidecar (RES-376); the [`sidecar`] module
//! tree is that supervision, and [`bridge`] is the minimal command/event surface RES-378
//! builds on.
//!
//! Startup never panics over the sidecar: the child is launched on a background thread during
//! setup, the failure is a lifecycle state with a bounded code, and the desktop window is
//! usable either way. Shutdown is the one place the shell blocks on the process boundary: an
//! `ExitRequested` is fenced once, the child is asked to stop through its stdin control
//! channel, and a deadline expiring means force-termination and reaping — containment is
//! recorded as such, and no child outlives the session.
//!
//! The exit claim and the start admission are the same decision, taken under one lock in the
//! supervisor. So an exit either wins before any child exists — in which case the startup
//! thread's `start` is refused and no process is created — or loses to a start whose owner has
//! already been given an address, which the shutdown then reaches. There is no interleaving in
//! which the desktop leaves believing there was nothing to stop.
//!
//! The exit itself waits for the supervisor rather than for a deadline. The process creation
//! on the owner's path is the one call in this crate that another thread cannot bound, so a
//! desktop that leaves while one is in flight could leave an addressable owner behind it; the
//! shell therefore proceeds to `handle.exit(0)` only on a terminal proof — no child was
//! created, the child exited gracefully, or the child was force-terminated and reaped — and
//! never on a wait that merely expired.

pub mod bridge;
pub mod sidecar;

#[cfg(test)]
mod structural_tests;

use std::sync::Arc;

use tauri::{Emitter, Manager, RunEvent};

use crate::sidecar::{
    current_launch_mode, launch_spec, SessionSnapshot, ShutdownOutcome, StartError, StateListener,
    Supervisor, SupervisorConfig,
};

/// Build and run the DynamisBench desktop shell.
pub fn run() {
    let application = tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            let listener: Arc<StateListener> = Arc::new(move |snapshot: &SessionSnapshot| {
                // Targeted at the main WebView, and non-secret by type: the payload is the
                // lifecycle snapshot, which has no credential field.
                let _ = handle.emit_to(bridge::MAIN_WINDOW, bridge::API_STATUS_EVENT, snapshot);
            });
            let supervisor = Arc::new(Supervisor::new(SupervisorConfig::default(), listener));
            app.manage(Arc::clone(&supervisor));

            std::thread::spawn(move || {
                match supervisor.start(launch_spec(current_launch_mode())) {
                    Ok(()) => {}
                    // The desktop claimed its exit before this start was admitted, so the fence
                    // refused it and no child was created. That is the fence working, not a
                    // session failure, and there is nothing to report about it.
                    Err(StartError::Stopped) => {}
                    // A bounded code, never the child's output and never the credential.
                    Err(failure) => {
                        eprintln!("dynamisbench: the API sidecar session is not ready: {failure:?}")
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![bridge::get_api_session])
        .build(tauri::generate_context!())
        .expect("failed to build the DynamisBench desktop shell");

    application.run(|app_handle, event| {
        if let RunEvent::ExitRequested { api, code, .. } = event {
            // `code: None` means the exit was requested by the user (last window closed);
            // an explicit `exit(0)` below arrives as `code: Some(0)` and must not be fenced
            // a second time.
            if code.is_none() {
                api.prevent_exit();
                let supervisor = app_handle.state::<Arc<Supervisor>>().inner().clone();
                if !supervisor.begin_exit() {
                    return;
                }
                let handle = app_handle.clone();
                std::thread::spawn(move || {
                    // Blocks until the supervisor holds one terminal proof about the child —
                    // it does not ask the supervisor "have you finished yet", so a still
                    // in-flight process creation keeps the desktop alive rather than being
                    // declared contained.
                    //
                    // The match is exhaustive on purpose: a fourth outcome would have to be
                    // classified here rather than falling through to an exit by default.
                    match supervisor.request_shutdown() {
                        ShutdownOutcome::Graceful
                        | ShutdownOutcome::Forced
                        | ShutdownOutcome::NotRunning => handle.exit(0),
                    }
                });
            }
        }
    });
}
