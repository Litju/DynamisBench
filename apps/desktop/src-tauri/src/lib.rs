//! DynamisBench desktop shell.
//!
//! Thin Tauri 2 wrapper only (ADR-013): the shell owns window, process, and OS
//! integration and nothing else. All scientific and VVUQ logic lives in the Python
//! core and application API, which later milestones launch as a sidecar.

/// Build and run the DynamisBench desktop shell.
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("failed to run the DynamisBench desktop shell");
}
