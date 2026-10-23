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
//!   → exactly the declared development origin is admitted by CORS, and no other
//!   → a second start is refused; one session owns one child
//!   → a graceful shutdown request over stdin ends the child with exit code 0
//!   → the port no longer serves anything
//! ```
//!
//! Two bounded failures are also real processes rather than fake children: the locked
//! interpreter exiting before readiness, and a program that cannot be spawned at all. Both
//! are the supervisor's own classification of a real `std::process::Child`, which is the
//! half a scripted reader cannot prove.
//!
//! HTTP is spoken with `TcpStream` rather than an HTTP client crate: the claim is about a
//! socket, a bearer header and an `Origin` header, and adding a client framework to test
//! those would be a dependency the product does not ship. The locked Python environment must
//! exist; run `uv sync --frozen` in `python/` first, exactly as the qualifying jobs do.

use std::ffi::OsString;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use dynamisbench_desktop_lib::sidecar::launch::{development_launch_spec, repository_root};
use dynamisbench_desktop_lib::sidecar::{
    FailureCode, LaunchSpec, SessionSnapshot, SessionStatus, ShutdownOutcome, StartError,
    StateListener, Supervisor, SupervisorConfig,
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

/// One HTTP/1.1 request over a real socket, returning the raw response.
///
/// A closed set of headers rather than a general client: the claim is about a socket, a
/// bearer header and an exact `Origin`, and every header this gate needs is named at the call
/// site so one cannot appear without being read.
fn http_request(port: u16, method: &str, path: &str, headers: &[(&str, &str)]) -> String {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(10))
        .unwrap_or_else(|error| panic!("the sidecar must accept a connection on {port}: {error}"));
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .expect("a read timeout must be settable");
    let mut request =
        format!("{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n");
    for (name, value) in headers {
        request.push_str(&format!("{name}: {value}\r\n"));
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

fn http_get(port: u16, path: &str, authorization: Option<&str>) -> String {
    match authorization {
        Some(credential) => http_request(
            port,
            "GET",
            path,
            &[("Authorization", &format!("Bearer {credential}"))],
        ),
        None => http_request(port, "GET", path, &[]),
    }
}

/// The value of one response header, ignoring case, or `None` when it is absent.
fn header_value<'a>(response: &'a str, name: &str) -> Option<&'a str> {
    let (head, _) = response.split_once("\r\n\r\n")?;
    head.lines().skip(1).find_map(|line| {
        let (header, value) = line.split_once(':')?;
        header
            .trim()
            .eq_ignore_ascii_case(name)
            .then_some(value.trim())
    })
}

fn ready_supervisor() -> (Supervisor, LaunchSpec) {
    let spec = development_launch_spec(&repository_root());
    assert!(
        spec.program.is_file(),
        "this gate needs the locked Python environment; run `uv sync --frozen` in python/ \
         first (missing {})",
        spec.program.display()
    );

    let supervisor = Supervisor::new(SupervisorConfig::default(), listener());
    supervisor
        .start(spec.clone())
        .expect("the real sidecar must announce readiness");
    (supervisor, spec)
}

fn credential_of(supervisor: &Supervisor) -> String {
    supervisor
        .session_bootstrap()
        .credential()
        .map(|credential| credential.expose().to_string())
        .expect("a ready session holds the credential")
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
    let (supervisor, _) = ready_supervisor();

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

    let credential = credential_of(&supervisor);
    assert_eq!(credential.len(), 43);

    let authenticated = http_get(port, "/api/v1/health", Some(&credential));
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

#[test]
fn the_real_api_admits_exactly_the_declared_development_origin() {
    let (supervisor, spec) = ready_supervisor();
    let origin = spec.origins[0];
    assert_eq!(origin, "http://localhost:5173");
    let port = port_of(
        &supervisor
            .snapshot()
            .origin
            .expect("a ready session has an origin"),
    );
    let credential = credential_of(&supervisor);

    let preflight = http_request(
        port,
        "OPTIONS",
        "/api/v1/health",
        &[
            ("Origin", origin),
            ("Access-Control-Request-Method", "GET"),
            ("Access-Control-Request-Headers", "authorization"),
        ],
    );
    assert!(
        preflight.starts_with("HTTP/1.1 200"),
        "the declared origin's preflight must be admitted: {preflight}"
    );
    assert_eq!(
        header_value(&preflight, "access-control-allow-origin"),
        Some(origin),
        "the admitted origin must be echoed exactly"
    );
    let allowed_headers = header_value(&preflight, "access-control-allow-headers")
        .unwrap_or_default()
        .to_ascii_lowercase();
    assert!(
        allowed_headers.contains("authorization"),
        "the one header this API authenticates with must be admitted: {preflight}"
    );
    assert_eq!(
        header_value(&preflight, "access-control-allow-credentials"),
        None,
        "a bearer header is not a cookie and credentials mode must stay off"
    );

    let authenticated = http_request(
        port,
        "GET",
        "/api/v1/health",
        &[
            ("Authorization", &format!("Bearer {credential}")),
            ("Origin", origin),
        ],
    );
    assert!(authenticated.starts_with("HTTP/1.1 200"));
    assert_eq!(
        header_value(&authenticated, "access-control-allow-origin"),
        Some(origin)
    );

    for refused_origin in ["http://evil.example", "http://localhost:5174", "null"] {
        let refused = http_request(
            port,
            "OPTIONS",
            "/api/v1/health",
            &[
                ("Origin", refused_origin),
                ("Access-Control-Request-Method", "GET"),
                ("Access-Control-Request-Headers", "authorization"),
            ],
        );
        assert_eq!(
            header_value(&refused, "access-control-allow-origin"),
            None,
            "an origin other than the declared one must never be admitted: {refused_origin}"
        );
    }

    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Graceful);
}

#[test]
fn one_ready_session_owns_one_child_and_refuses_a_second_start() {
    let (supervisor, spec) = ready_supervisor();
    let first = supervisor
        .snapshot()
        .origin
        .clone()
        .expect("a ready session has an origin");
    let port = port_of(&first);
    let credential = credential_of(&supervisor);

    let second = supervisor.start(spec);
    assert!(
        matches!(second, Err(StartError::Refused(_))),
        "one session must own one child, got {second:?}"
    );
    assert_eq!(supervisor.snapshot().status, SessionStatus::Ready);
    assert_eq!(
        supervisor.snapshot().origin.as_deref(),
        Some(first.as_str()),
        "the refused second start must not replace the serving origin"
    );
    assert!(
        http_get(port, "/api/v1/health", Some(&credential)).starts_with("HTTP/1.1 200"),
        "the first and only sidecar must still serve after the refused start"
    );

    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::Graceful);
    assert!(!port_is_serving(port));
}

#[test]
fn a_real_child_that_exits_before_readiness_is_a_bounded_startup_failure() {
    let spec = development_launch_spec(&repository_root());
    assert!(spec.program.is_file(), "the locked interpreter must exist");
    let failing = LaunchSpec {
        program: spec.program,
        args: vec![
            OsString::from("-c"),
            // A real interpreter and a real exit, with nothing on the protocol channel.
            OsString::from("import sys; sys.exit(23)"),
        ],
        cwd: spec.cwd,
        origins: spec.origins,
    };

    let supervisor = Supervisor::new(SupervisorConfig::default(), listener());
    let started = supervisor.start(failing);

    assert_eq!(
        started,
        Err(StartError::Failed(FailureCode::SidecarStartupExit)),
        "a real child that exits before readiness must be classified, not merely observed"
    );
    let snapshot = supervisor.snapshot();
    assert_eq!(snapshot.status, SessionStatus::Failed);
    assert_eq!(snapshot.failure, Some(FailureCode::SidecarStartupExit));
    assert_eq!(snapshot.origin, None, "a failed session has no address");
    assert!(
        supervisor.session_bootstrap().credential().is_none(),
        "a failed session publishes no credential"
    );
    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
}

#[test]
fn a_program_that_cannot_be_spawned_is_a_bounded_failure_with_no_session() {
    let missing = LaunchSpec {
        program: PathBuf::from("this-program-does-not-exist-anywhere"),
        args: Vec::new(),
        cwd: repository_root(),
        origins: vec!["http://localhost:5173"],
    };

    let supervisor = Supervisor::new(SupervisorConfig::default(), listener());
    let started = supervisor.start(missing);

    assert_eq!(started, Err(StartError::Failed(FailureCode::SpawnFailed)));
    let snapshot = supervisor.snapshot();
    assert_eq!(snapshot.status, SessionStatus::Failed);
    assert_eq!(snapshot.failure, Some(FailureCode::SpawnFailed));
    assert_eq!(snapshot.origin, None);
    assert_eq!(supervisor.request_shutdown(), ShutdownOutcome::NotRunning);
}

#[test]
fn a_replacement_session_is_a_new_credential_on_a_new_supervised_child() {
    let (first, _) = ready_supervisor();
    let first_origin = first
        .snapshot()
        .origin
        .clone()
        .expect("a ready session has an origin");
    let first_port = port_of(&first_origin);
    let first_credential = credential_of(&first);
    assert_eq!(first.request_shutdown(), ShutdownOutcome::Graceful);
    assert!(!port_is_serving(first_port));

    let (second, _) = ready_supervisor();
    let second_origin = second
        .snapshot()
        .origin
        .clone()
        .expect("a replacement session has an origin");
    let second_port = port_of(&second_origin);
    let second_credential = credential_of(&second);

    assert_ne!(
        first_credential, second_credential,
        "each session's proof is generated for that session"
    );
    assert!(
        http_get(second_port, "/api/v1/health", Some(&first_credential))
            .starts_with("HTTP/1.1 401"),
        "the previous session's credential must not open the replacement"
    );
    assert!(
        http_get(second_port, "/api/v1/health", Some(&second_credential))
            .starts_with("HTTP/1.1 200")
    );

    assert_eq!(second.request_shutdown(), ShutdownOutcome::Graceful);
    assert!(!port_is_serving(second_port));
}
