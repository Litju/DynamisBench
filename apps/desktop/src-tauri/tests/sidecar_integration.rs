//! The real boundary: a supervised `dbench api serve`, authenticated over loopback.
//!
//! Everything else in this crate's test surface uses fake children, because a fake child is
//! how a failure path can be reached on purpose. This gate is the opposite: it spawns the
//! repository's actual application through the actual [`LaunchSpec`] a development session
//! resolves, and proves the claims that only the real pair can prove:
//!
//! ```text
//! spawn real `dbench api serve`
//!   → receive a valid readiness record
//!   → the origin is 127.0.0.1 on an operating-system-chosen port
//!   → GET /api/v1/health with the generated credential answers 200
//!   → GET /api/v1/health without it answers 401
//!   → a graceful shutdown request over stdin ends the child with exit code 0
//!   → the port no longer serves anything
//! ```
//!
//! HTTP is spoken with `TcpStream` rather than an HTTP client crate: the claim is about a
//! socket and a bearer header, and adding a client framework to test one request would be a
//! dependency the product does not ship. The locked Python environment must exist; run
//! `uv sync --frozen` in `python/` first, exactly as the qualifying jobs do.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::Arc;
use std::time::Duration;

use dynamisbench_desktop_lib::sidecar::launch::{development_launch_spec, repository_root};
use dynamisbench_desktop_lib::sidecar::{
    SessionSnapshot, SessionStatus, ShutdownOutcome, StateListener, Supervisor, SupervisorConfig,
};

fn listener() -> Arc<StateListener> {
    Arc::new(|_snapshot: &SessionSnapshot| {})
}

fn port_of(origin: &str) -> u16 {
    origin
        .rsplit(':')
        .next()
        .and_then(|port| port.parse().ok())
        .unwrap_or_else(|| panic!("the origin must end in a port: {origin}"))
}

/// One HTTP/1.1 GET over a real socket, returning the raw response.
fn http_get(port: u16, path: &str, authorization: Option<&str>) -> String {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(10))
        .unwrap_or_else(|error| panic!("the sidecar must accept a connection on {port}: {error}"));
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .expect("a read timeout must be settable");
    let mut request =
        format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n");
    if let Some(credential) = authorization {
        request.push_str(&format!("Authorization: Bearer {credential}\r\n"));
    }
    request.push_str("\r\n");
    stream
        .write_all(request.as_bytes())
        .expect("the request must reach the sidecar");
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .expect("the sidecar must answer the request");
    response
}

/// Whether the port still serves an HTTP response, as opposed to merely accepting a socket.
///
/// Windows completes a connection to a recently closed port and then resets it, so a
/// successful `connect` is not evidence of a surviving server; a well-formed HTTP answer is.
fn port_is_serving(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(format!("GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").as_bytes())
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    match stream.read_to_string(&mut response) {
        Ok(_) => response.starts_with("HTTP/"),
        Err(_) => false,
    }
}

#[test]
fn a_real_dbench_api_serve_session_is_reachable_authenticated_and_stopped_cleanly() {
    let spec = development_launch_spec(&repository_root());
    assert!(
        spec.program.is_file(),
        "this gate needs the locked Python environment; run `uv sync --frozen` in python/ \
         first (missing {})",
        spec.program.display()
    );

    let supervisor = Supervisor::new(SupervisorConfig::default(), listener());
    supervisor
        .start(spec)
        .expect("the real sidecar must announce readiness");

    let ready = supervisor.snapshot();
    assert_eq!(ready.status, SessionStatus::Ready);
    let origin = ready.origin.clone().expect("a ready session has an origin");
    assert!(
        origin.starts_with("http://127.0.0.1:"),
        "the sidecar must bind loopback: {origin}"
    );
    let port = port_of(&origin);
    assert!(port > 1023, "the port must be an ephemeral one: {port}");
    assert_eq!(ready.api_version.as_deref(), Some("v1"));
    assert_eq!(ready.protocol_version, Some(1));

    let credential = supervisor
        .credential()
        .expect("a ready session holds the credential");
    assert_eq!(credential.expose().len(), 43);

    let authenticated = http_get(port, "/api/v1/health", Some(credential.expose()));
    assert!(
        authenticated.starts_with("HTTP/1.1 200"),
        "the generated credential must authenticate against the real API: {authenticated}"
    );

    let refused = http_get(port, "/api/v1/health", None);
    assert!(
        refused.starts_with("HTTP/1.1 401"),
        "the real API must refuse an unauthenticated request: {refused}"
    );

    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Graceful);
    assert_eq!(supervisor.snapshot().status, SessionStatus::Stopped);
    assert!(
        !port_is_serving(port),
        "the listener must not outlive the supervised child"
    );
}
