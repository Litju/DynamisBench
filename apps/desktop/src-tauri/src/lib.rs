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

pub mod bridge;
pub mod sidecar;

#[cfg(test)]
mod structural_tests;

use std::sync::Arc;

use tauri::{Emitter, Manager, RunEvent};

use crate::sidecar::{
    current_launch_mode, launch_spec, SessionSnapshot, StateListener, Supervisor, SupervisorConfig,
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
                if let Err(failure) = supervisor.start(launch_spec(current_launch_mode())) {
                    // A bounded code, never the child's output and never the credential.
                    eprintln!("dynamisbench: the API sidecar session is not ready: {failure:?}");
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
                    supervisor.request_shutdown();
                    handle.exit(0);
                });
            }
        }
    });
}
