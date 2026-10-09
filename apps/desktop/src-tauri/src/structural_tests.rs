//! Structural proofs for the security-regression gates RES-376 states.
//!
//! Behaviour tests only see what the code does today; these read the files that *grant*
//! capability, dependency, and process-surface power and assert that the grants are absent.
//! The failures they prevent are silent until used: a capability added "for later", a
//! JavaScript plugin pulled in by a transitive install, an `externalBin` that makes CI
//! require a binary that does not exist yet, or a scientific module imported into the shell.
//!
//! The scan is deliberately simple and exact-substring, over this crate's own sources and
//! the two package manifests. It is a tripwire, not a parser: any new occurrence of a banned
//! construct is a reviewed change.

use std::fs;
use std::path::{Path, PathBuf};

/// This crate's directory (`apps/desktop/src-tauri`).
const MANIFEST_DIR: &str = env!("CARGO_MANIFEST_DIR");

fn read(relative: &str) -> String {
    let path = Path::new(MANIFEST_DIR).join(relative);
    fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("{} must be readable: {error}", path.display()))
}

fn rust_sources(directory: &Path, sources: &mut Vec<PathBuf>) {
    let entries = fs::read_dir(directory)
        .unwrap_or_else(|error| panic!("{} must be readable: {error}", directory.display()));
    for entry in entries {
        let path = entry.expect("a readable directory entry").path();
        if path.is_dir() {
            rust_sources(&path, sources);
        } else if path.extension().is_some_and(|extension| extension == "rs")
            && path
                .file_name()
                .is_some_and(|name| name != "structural_tests.rs")
        {
            sources.push(path);
        }
    }
}

fn concatenated_sources(relative: &str) -> String {
    let mut sources = Vec::new();
    rust_sources(&Path::new(MANIFEST_DIR).join(relative), &mut sources);
    assert!(!sources.is_empty(), "{relative} must contain Rust sources");
    sources
        .iter()
        .map(|path| {
            fs::read_to_string(path)
                .unwrap_or_else(|error| panic!("{} must be readable: {error}", path.display()))
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// A module's production code, with its documentation comments and tests removed.
///
/// The assertions below are about what the shipped surface *is*. Comments are stripped so
/// prose cannot satisfy a gate, and the test module is dropped so a test that uses the same
/// names cannot break one — the point is that the *code* has no other way in.
fn module_source(relative: &str) -> String {
    let contents = read(relative);
    let production: &str = contents
        .split_once("#[cfg(test)]")
        .map_or(contents.as_str(), |(head, _)| head);
    production
        .lines()
        .filter(|line| !line.trim_start().starts_with("//"))
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn the_capability_file_grants_no_permission_at_all() {
    let capabilities = read("capabilities/default.json");
    let parsed: serde_json::Value =
        serde_json::from_str(&capabilities).expect("the capability file must be valid JSON");
    let permissions = parsed["permissions"]
        .as_array()
        .expect("the capability file must carry a permissions array");

    assert!(
        permissions.is_empty(),
        "the desktop shell requests no permission; got {permissions:?}"
    );
    let serialized = serde_json::to_string(permissions).unwrap();
    for banned in ["shell", "process", "spawn", "execute"] {
        assert!(
            !serialized.contains(banned),
            "the capability grant mentions {banned}: {serialized}"
        );
    }
}

#[test]
fn no_javascript_shell_or_process_plugin_is_installed() {
    for manifest in ["../package.json", "../../workbench/package.json"] {
        let contents = read(manifest);
        for banned in ["@tauri-apps/plugin-shell", "@tauri-apps/plugin-process"] {
            assert!(!contents.contains(banned), "{manifest} depends on {banned}");
        }
    }
}

#[test]
fn no_external_binary_is_configured() {
    let configuration = read("tauri.conf.json");

    assert!(
        !configuration.contains("externalBin"),
        "RES-376 defines the packaged sidecar path contract without making a build require \
         the packaged file; externalBin belongs to M8"
    );
}

#[test]
fn the_rust_tree_names_no_simulator_or_scientific_layer() {
    let sources = concatenated_sources("src").to_lowercase();

    for banned in [
        "mujoco",
        "opensim",
        "simtk",
        "gymnasium",
        "duckdb",
        "dynamisbench::domain",
        "dynamisbench::evidence",
        "dynamisbench::planning",
    ] {
        assert!(
            !sources.contains(banned),
            "the desktop shell must stay scientifically ignorant; found {banned}"
        );
    }
}

#[test]
fn the_supervision_tree_persists_nothing() {
    let sources = concatenated_sources("src/sidecar");

    for banned in [
        "std::fs::write",
        "fs::write(",
        "File::create",
        "OpenOptions",
        "create_dir",
        "remove_file",
        "std::env::set_var",
        "println!(",
        "print!(",
    ] {
        assert!(
            !sources.contains(banned),
            "the sidecar supervisor must not write, create, remove, or print; found {banned}"
        );
    }
}

#[test]
fn the_command_surface_is_the_one_bootstrap_command() {
    let sources = concatenated_sources("src");

    assert!(
        sources.contains("pub fn get_api_session"),
        "the bridge must expose exactly the command RES-378 needs"
    );
    assert_eq!(
        sources.matches("#[tauri::command]").count(),
        1,
        "one command, so the surface cannot grow without this gate noticing"
    );
    assert!(
        sources.contains("pub fn get_api_session(supervisor: State<'_, Arc<Supervisor>>)"),
        "the command takes the supervisor and nothing else: no launch specification, no \
         executable, no argument a WebView could choose"
    );
}

#[test]
fn the_bootstrap_response_cannot_be_assembled_from_two_reads() {
    let bridge = module_source("src/bridge.rs");

    assert!(
        bridge.contains("supervisor.session_bootstrap()"),
        "the response must come from one capture of snapshot and credential together"
    );
    for banned in [
        "supervisor.snapshot()",
        "supervisor.credential()",
        "SessionState",
        "Mutex",
    ] {
        assert!(
            !bridge.contains(banned),
            "the bridge must not read the session twice or reach its lock; found {banned}"
        );
    }
}

#[test]
fn the_supervisor_offers_the_credential_only_through_the_atomic_capture() {
    let supervisor = module_source("src/sidecar/supervisor.rs");

    assert!(
        supervisor.contains("pub fn session_bootstrap(&self) -> SessionBootstrap"),
        "the one way out of the session state is the atomic capture"
    );
    for banned in ["pub fn credential(", "pub fn snapshot_and_credential"] {
        assert!(
            !supervisor.contains(banned),
            "no accessor may pair a snapshot with a separately read credential; found {banned}"
        );
    }
}

#[test]
fn the_start_and_exit_fence_is_one_mutex_not_several_independent_facts() {
    let supervisor = module_source("src/sidecar/supervisor.rs");

    assert!(
        supervisor.contains("struct Gate"),
        "the lifecycle record and the start/exit decision share one gate"
    );
    for banned in [
        "AtomicBool",
        "Ordering::SeqCst",
        "thread::sleep(Duration::from_millis(1",
        "retry",
    ] {
        assert!(
            !supervisor.contains(banned),
            "the fence must be one critical section, not an independent atomic or a retry; \
             found {banned}"
        );
    }
}

/// The containment contract RES-376's exit path rests on: a final desktop exit may proceed
/// only on a proof that no child was created, that it exited gracefully, or that it was
/// force-terminated and reaped.
#[test]
fn no_wait_in_the_supervisor_can_expire_into_a_containment_claim() {
    let supervisor = module_source("src/sidecar/supervisor.rs");

    // The previous shape answered `Forced` when `wait_timeout` expired, which is how a
    // reservation deadline could report containment about a process that did not exist.
    assert!(
        !supervisor.contains("wait_timeout"),
        "an expired wait is evidence about a clock, not about a process; the supervisor must \
         wait for the owner's proof rather than bound the wait"
    );
    assert!(
        supervisor.contains("reply_rx.recv()"),
        "a shutdown waits for the owner's answer"
    );
    assert!(
        supervisor.contains("fn recorded_proof"),
        "and when the command cannot be delivered it waits for the conclusion the owner \
         recorded"
    );
    assert!(
        supervisor.contains("pub fn terminal_proof"),
        "the proof is readable, so an exit can be gated on it"
    );
}

/// The preferred design the review asked for: the owner performs the process creation, not
/// the caller, so a shutdown that arrives mid-creation has an owner to address.
#[test]
fn the_process_creation_is_owned_not_performed_by_the_caller() {
    let supervisor = module_source("src/sidecar/supervisor.rs");

    let start = supervisor
        .split_once("pub fn start(&self")
        .map(|(_, tail)| tail.split("pub fn").next().unwrap_or_default())
        .unwrap_or_default();
    assert!(
        !start.contains("(spawner)("),
        "`start` must not create the process itself: a caller that spawns before publishing \
         the owner leaves a creation nothing can address"
    );
    assert!(
        start.contains("control.established(commands)"),
        "the owner's channel is published while the start is admitted, in one critical section"
    );
    assert!(
        supervisor.contains("Owned(Sender<SupervisorCommand>)"),
        "the channel lives in the phase, so being addressable and being the owner cannot \
         disagree"
    );
    assert!(
        !supervisor.contains("commands: Option<Sender<SupervisorCommand>>"),
        "a channel beside the phase could be withdrawn without withdrawing addressability"
    );
}
