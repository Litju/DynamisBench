//! The Tauri session's supervision of the local Python API sidecar.
//!
//! Architecture §8/§13 and RES-376 make one desktop session the owner of exactly one
//! `dbench api serve` child. This module tree is that ownership, split so that each concern
//! can be read and tested on its own:
//!
//! * [`credential`] generates and holds the one per-session secret;
//! * [`protocol`] is the machine-readable contract on the child's streams, in both directions;
//! * [`launch`] resolves the one fixed command each build mode is allowed to run;
//! * [`state`] is the bounded, non-secret lifecycle vocabulary the WebView may see;
//! * [`supervisor`] spawns, watches, stops, and reaps the child.
//!
//! Nothing here knows anything scientific. There is no domain, evidence, planning, or
//! simulator import, no workspace path, and no state that outlives the session — the shell is
//! the process boundary, and the Python API remains the only application boundary.

pub mod credential;
pub mod launch;
pub mod protocol;
pub mod state;

pub use credential::{CredentialError, SessionCredential};
pub use launch::{
    allowed_origins, allowed_origins_json, development_launch_spec, launch_spec,
    packaged_sidecar_path, repository_root, LaunchMode, LaunchSpec,
};
pub use protocol::{parse_readiness, InvalidReadiness, Readiness};
pub use state::{FailureCode, SessionSnapshot, SessionState, SessionStatus};
