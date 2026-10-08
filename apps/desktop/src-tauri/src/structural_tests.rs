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
}
