//! The one command each build mode may run, resolved from fixed locations only.
//!
//! Architecture §13 and RES-376: the WebView must not be able to choose an executable,
//! arguments, a working directory, an environment, a host, or a port. The way that is enforced
//! is not by validating WebView input — there is no input — but by there being exactly one
//! resolution function per mode, taking no caller-supplied strings at all:
//!
//! * **Development** runs the repository's locked Python environment directly:
//!   `<repo>/python/.venv/{Scripts/python.exe | bin/python} -m dynamisbench api serve`. The
//!   task's reference invocation is `uv run --project <repo>/python dbench api serve`; the
//!   interpreter is resolved instead because ``uv`` spawns the interpreter as a *grandchild*
//!   on Windows, and terminating ``uv`` would leave the API server alive as an orphan. Running
//!   the interpreter makes the supervised child the server itself, which is what
//!   "force terminate child → containment" requires. The environment is the repository's
//!   locked one; producing it is `uv sync --frozen`, exactly as for every other gate.
//! * **Packaged** runs a fixed executable identity beside the desktop binary:
//!   `<exe dir>/dbench-api{.exe}`, with no arguments. RES-376 owns this contract; M8 owns
//!   placing the packaged binary there, so nothing here configures `externalBin` and no
//!   current build requires the file to exist.
//!
//! Origins are part of the same decision. The child receives exactly one origin per mode:
//! the Tauri `devUrl` in development, and the platform's real Tauri origin in production —
//! `http://tauri.localhost` on Windows, `tauri://localhost` (the custom protocol) everywhere
//! else. There is no wildcard, no origin list the caller can extend, and no override that
//! travels to the WebView.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// Which of the two fixed launch resolutions applies to this build.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LaunchMode {
    /// A `tauri dev` session: the repository's locked Python environment.
    Development,
    /// A bundled application: the packaged sidecar beside the desktop executable.
    Packaged,
}

/// The development origin: the Tauri `devUrl` this repository configures.
pub const DEVELOPMENT_ORIGIN: &str = "http://localhost:5173";

/// The packaged origin on Windows, where the Tauri custom protocol is `http:`.
pub const WINDOWS_PACKAGED_ORIGIN: &str = "http://tauri.localhost";

/// The packaged origin on Windows and everywhere else: Tauri's real custom-protocol origin.
pub const CUSTOM_PROTOCOL_ORIGIN: &str = "tauri://localhost";

/// The packaged sidecar's fixed file name, without the platform executable suffix.
pub const PACKAGED_SIDECAR_STEM: &str = "dbench-api";

/// One fully-resolved child command. Everything the child will be told is here, and none of
/// it can be influenced from the WebView.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchSpec {
    /// The executable to run.
    pub program: PathBuf,
    /// Its arguments, in order.
    pub args: Vec<OsString>,
    /// Its working directory.
    pub cwd: PathBuf,
    /// The exact browser origins it will be told to allow.
    pub origins: Vec<&'static str>,
}

/// The repository root, from this crate's own compile-time location.
///
/// `CARGO_MANIFEST_DIR` is `<repo>/apps/desktop/src-tauri`, so three parents up is the
/// checkout the desktop shell was built from. A compile-time constant rather than a runtime
/// search: a development session always runs the tree it was built in, and no environment
/// variable can point it at another one.
pub fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
}

/// The interpreter of the repository's locked Python environment.
pub fn locked_interpreter(repo_root: &Path) -> PathBuf {
    let (bin, interpreter) = if cfg!(windows) {
        ("Scripts", "python.exe")
    } else {
        ("bin", "python")
    };
    repo_root
        .join("python")
        .join(".venv")
        .join(bin)
        .join(interpreter)
}

/// The fixed path a packaged build's sidecar must occupy: beside the desktop executable.
pub fn packaged_sidecar_path(executable_dir: &Path) -> PathBuf {
    executable_dir.join(format!(
        "{PACKAGED_SIDECAR_STEM}{}",
        std::env::consts::EXE_SUFFIX
    ))
}

/// The exact origins the child is allowed to accept, by mode and platform.
pub fn allowed_origins(mode: LaunchMode) -> Vec<&'static str> {
    match mode {
        LaunchMode::Development => vec![DEVELOPMENT_ORIGIN],
        LaunchMode::Packaged if cfg!(windows) => vec![WINDOWS_PACKAGED_ORIGIN],
        LaunchMode::Packaged => vec![CUSTOM_PROTOCOL_ORIGIN],
    }
}

/// The origins as the deterministic JSON array the child's environment carries.
pub fn allowed_origins_json(mode: LaunchMode) -> String {
    serde_json::to_string(&allowed_origins(mode))
        .expect("a vector of strings cannot fail to serialize")
}

/// The development command: the locked interpreter, `-m dynamisbench api serve`, at the root.
pub fn development_launch_spec(repo_root: &Path) -> LaunchSpec {
    LaunchSpec {
        program: locked_interpreter(repo_root),
        args: vec![
            OsString::from("-m"),
            OsString::from("dynamisbench"),
            OsString::from("api"),
            OsString::from("serve"),
        ],
        cwd: repo_root.to_path_buf(),
        origins: allowed_origins(LaunchMode::Development),
    }
}

/// The packaged command: the fixed sidecar identity beside the desktop executable.
pub fn packaged_launch_spec(executable_dir: &Path) -> LaunchSpec {
    LaunchSpec {
        program: packaged_sidecar_path(executable_dir),
        args: Vec::new(),
        cwd: executable_dir.to_path_buf(),
        origins: allowed_origins(LaunchMode::Packaged),
    }
}

/// Which mode this binary is: a development build or a bundled one.
///
/// `tauri::is_dev()` reports whether the `custom-protocol` feature is off, which is exactly
/// the difference between `tauri dev` and `tauri build`.
pub fn current_launch_mode() -> LaunchMode {
    if tauri::is_dev() {
        LaunchMode::Development
    } else {
        LaunchMode::Packaged
    }
}

/// Resolve the one command this session may run, with no input from anywhere.
///
/// Infallible on purpose: if the executable directory cannot be determined for a packaged
/// build, the path is simply unresolvable and the spawn fails, which the supervisor already
/// reports as `spawn_failed`. There is no path on which start-up can panic over a missing
/// sidecar.
pub fn launch_spec(mode: LaunchMode) -> LaunchSpec {
    match mode {
        LaunchMode::Development => development_launch_spec(&repository_root()),
        LaunchMode::Packaged => {
            let directory = std::env::current_exe()
                .ok()
                .and_then(|executable| executable.parent().map(Path::to_path_buf))
                .unwrap_or_default();
            packaged_launch_spec(&directory)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;
    use std::path::{Path, PathBuf};

    use super::{
        allowed_origins, allowed_origins_json, development_launch_spec, launch_spec,
        locked_interpreter, packaged_launch_spec, packaged_sidecar_path, repository_root,
        LaunchMode, CUSTOM_PROTOCOL_ORIGIN, DEVELOPMENT_ORIGIN, PACKAGED_SIDECAR_STEM,
        WINDOWS_PACKAGED_ORIGIN,
    };

    #[test]
    fn the_development_spec_is_the_exact_fixed_command() {
        let repository = Path::new("C:/example/repo");
        let spec = development_launch_spec(repository);

        assert_eq!(spec.program, locked_interpreter(repository));
        assert_eq!(
            spec.args,
            vec![
                OsString::from("-m"),
                OsString::from("dynamisbench"),
                OsString::from("api"),
                OsString::from("serve"),
            ]
        );
        assert_eq!(spec.cwd, repository);
        assert_eq!(spec.origins, vec![DEVELOPMENT_ORIGIN]);
    }

    #[test]
    fn the_locked_interpreter_is_the_repository_environment_and_nothing_else() {
        let repository = Path::new("C:/example/repo");
        let interpreter = locked_interpreter(repository);

        if cfg!(windows) {
            assert_eq!(
                interpreter,
                repository
                    .join("python")
                    .join(".venv")
                    .join("Scripts")
                    .join("python.exe")
            );
        } else {
            assert_eq!(
                interpreter,
                repository
                    .join("python")
                    .join(".venv")
                    .join("bin")
                    .join("python")
            );
        }
        assert!(interpreter.starts_with(repository));
    }

    #[test]
    fn the_packaged_spec_is_the_fixed_executable_identity_beside_the_desktop_binary() {
        let directory = Path::new("C:/example/app");
        let spec = packaged_launch_spec(directory);

        assert_eq!(
            spec.program,
            PathBuf::from(directory).join(format!(
                "{PACKAGED_SIDECAR_STEM}{}",
                std::env::consts::EXE_SUFFIX
            ))
        );
        assert_eq!(packaged_sidecar_path(directory), spec.program);
        assert!(
            spec.args.is_empty(),
            "the packaged sidecar takes no arguments"
        );
        assert_eq!(spec.cwd, directory);
        assert_eq!(spec.origins, allowed_origins(LaunchMode::Packaged));
    }

    #[test]
    fn the_packaged_sidecar_is_a_sibling_of_the_desktop_executable() {
        let directory = Path::new("/opt/dynamisbench");
        let path = packaged_sidecar_path(directory);

        assert_eq!(path.parent(), Some(directory));
        assert!(path
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with(PACKAGED_SIDECAR_STEM));
    }

    #[test]
    fn development_always_runs_the_exact_tauri_dev_url_and_nothing_else() {
        assert_eq!(
            allowed_origins(LaunchMode::Development),
            vec!["http://localhost:5173"]
        );
        assert_eq!(
            allowed_origins_json(LaunchMode::Development),
            r#"["http://localhost:5173"]"#
        );
    }

    #[test]
    fn packaged_origins_are_the_platforms_real_tauri_origin() {
        if cfg!(windows) {
            assert_eq!(
                allowed_origins(LaunchMode::Packaged),
                vec!["http://tauri.localhost"]
            );
            assert_eq!(
                allowed_origins_json(LaunchMode::Packaged),
                r#"["http://tauri.localhost"]"#
            );
        } else {
            assert_eq!(
                allowed_origins(LaunchMode::Packaged),
                vec!["tauri://localhost"]
            );
            assert_eq!(
                allowed_origins_json(LaunchMode::Packaged),
                r#"["tauri://localhost"]"#
            );
        }
    }

    #[test]
    fn no_origin_is_a_wildcard_or_a_pattern() {
        for mode in [LaunchMode::Development, LaunchMode::Packaged] {
            for origin in allowed_origins(mode) {
                assert!(!origin.contains('*'), "{origin} must be an exact origin");
                assert_ne!(origin, "null");
                assert!(origin.starts_with("http://") || origin.starts_with("tauri://"));
            }
            assert!(!allowed_origins_json(mode).contains('*'));
        }
    }

    #[test]
    fn the_origin_constants_are_the_published_ones() {
        assert_eq!(DEVELOPMENT_ORIGIN, "http://localhost:5173");
        assert_eq!(WINDOWS_PACKAGED_ORIGIN, "http://tauri.localhost");
        assert_eq!(CUSTOM_PROTOCOL_ORIGIN, "tauri://localhost");
    }

    #[test]
    fn the_resolved_spec_is_the_same_on_every_call() {
        let first = launch_spec(LaunchMode::Development);
        let second = launch_spec(LaunchMode::Development);

        assert_eq!(
            first, second,
            "launch resolution must not vary between calls"
        );
        assert!(first.program.starts_with(repository_root()));
    }
}
