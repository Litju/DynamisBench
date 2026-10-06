"""The sidecar as a real process: stdout is a protocol, and the credential never appears on it.

The gates in ``test_server.py`` hold a real socket and a real Uvicorn server, which is where
the lifecycle properties live. This module covers the things only a separate process can
show:

* **stdout is exactly the handshake.** One line, parseable as protocol v1, carrying the port
  the process is actually listening on, and nothing else before it, beside it or after it. The
  reason this needs a process is the failure it catches: Uvicorn binds its access logger to
  ``sys.stdout`` by default, so a sidecar that logged even one request would interleave a log
  line into a channel a supervisor parses with a single read.
* **A refused configuration fails the process, quietly.** A malformed credential produces the
  configuration exit code, no readiness line, and — the point of the gate — no echo of the
  rejected value anywhere in the output a supervisor will keep.
* **A repeated ``Authorization`` header reaches the server as a repeated header.** Both header
  clients in this project collapse repeated names into one value, so this is the only place
  the two-header request can be put on the wire at all — which is what makes this the gate for
  a credential that must not be admitted because of where one of two copies happened to sit.

HTTP is spoken over the announced socket with ``http.client``, not with the in-process test
client, because the claim under test is that a local process on this machine gets a 401 without
the credential; an in-process client would be talking to itself.

The tests are bounded in both directions. Reading the readiness line is done on a worker thread
with a deadline, so a sidecar that never announces fails instead of hanging, and every child is
killed in a fixture teardown, so no test can leave a listening process behind.
"""

from __future__ import annotations

import base64
import contextlib
import http.client
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator, Mapping

import pytest

from dynamisbench.api.server import Exit, Readiness
from dynamisbench.api.session import ALLOWED_ORIGINS_VARIABLE, SESSION_CREDENTIAL_VARIABLE
from tests.api.factories import CREDENTIAL, session_environment

ANNOUNCE_TIMEOUT_SECONDS = 60.0
SHUTDOWN_TIMEOUT_SECONDS = 30.0

UNAUTHORIZED_BODY = {"error": {"code": "unauthorized", "message": "Authentication required."}}
ALLOWED_ORIGIN = "http://tauri.localhost"
REFUSED_ORIGIN = "http://evil.example"

# A value that is unmistakably a secret and unmistakably not a credential, so a leak of it into
# the output would be found by substring rather than by inspection.
REJECTED_CREDENTIAL = "this-is-the-secret-the-supervisor-must-never-see"

SECRET_VARIABLES = (SESSION_CREDENTIAL_VARIABLE, ALLOWED_ORIGINS_VARIABLE)


def _environment(overrides: Mapping[str, str | None] | None = None) -> dict[str, str]:
    """A child's environment, with the session variables exactly as this test wants them.

    An override of ``None`` removes the variable rather than setting it, which is how a test
    states "the desktop session supplied nothing at all".
    """
    environment = dict(os.environ)
    for name in SECRET_VARIABLES:
        environment.pop(name, None)
    environment.update(session_environment())
    for name, value in (overrides or {}).items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return environment


def _command() -> list[str]:
    return [sys.executable, "-m", "dynamisbench", "api", "serve"]


@contextlib.contextmanager
def _sidecar(overrides: Mapping[str, str | None] | None = None) -> Iterator[subprocess.Popen[str]]:
    """A running sidecar, guaranteed not to outlive the test."""
    child = subprocess.Popen(
        _command(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(overrides),
    )
    try:
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                stream.close()
        child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)


def _failed_to_start(overrides: Mapping[str, str | None]) -> subprocess.CompletedProcess[str]:
    """Run a sidecar that is expected to refuse to start, and collect everything it said."""
    return subprocess.run(
        _command(),
        capture_output=True,
        text=True,
        check=False,
        timeout=SHUTDOWN_TIMEOUT_SECONDS,
        env=_environment(overrides),
    )


def _readiness(child: subprocess.Popen[str]) -> str:
    """The sidecar's first line on stdout, or a failure naming what it said instead.

    Read on a worker thread with a deadline, so a sidecar that exits or never starts fails the
    test instead of hanging the suite.
    """
    assert child.stdout is not None
    stdout = child.stdout
    announced: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        announced.put(stdout.readline())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(SHUTDOWN_TIMEOUT_SECONDS)
    if announced.empty():
        child.kill()
        raise AssertionError(
            "the sidecar announced no port; stderr was "
            f"{child.stderr.read() if child.stderr is not None else ''!r}"
        )
    return announced.get_nowait()


def _request(
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = None,
    origin: str | None = None,
    preflight: bool = False,
) -> tuple[int, dict[str, str], bytes]:
    """One HTTP request to the announced port, spoken over a real socket."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    if preflight:
        headers["Access-Control-Request-Method"] = "GET"
        headers["Access-Control-Request-Headers"] = "authorization"
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def _answered(port: int, token: str) -> int | None:
    """The status the port answers with, or ``None`` if nothing answered at all.

    Deliberately not "does the port refuse a connection". On Windows a completed request leaves
    the closed port in a state where the kernel completes a new connection and then resets it,
    so accepting a TCP connection is not evidence of a surviving sidecar. What has to be true
    is that the port no longer *serves* anything.
    """
    try:
        status, _, _ = _request(port, "GET", "/api/v1/health", token=token)
    except (OSError, http.client.HTTPException):
        return None
    return status


def _request_repeating_a_header(
    port: int, path: str, name: str, *values: str
) -> tuple[int, dict[str, str], bytes]:
    """One request carrying the same header more than once, spoken over a real socket.

    ``putrequest`` and ``putheader`` are used instead of ``request`` because ``request`` takes
    a mapping and joins repeated names into one value — the very normalization under test. This
    is the only way to put two ``Authorization`` headers on the wire from this process.
    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        connection.putrequest("GET", path, skip_accept_encoding=True)
        for value in values:
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "tokens",
    [
        ("correct", "wrong"),
        ("wrong", "correct"),
        ("correct", "correct"),
    ],
)
def test_the_process_refuses_a_repeated_authorization_header(tokens: tuple[str, str]) -> None:
    """Over a real socket, in both orders, and with the right credential present twice.

    The header is written twice on the wire and the second copy is not discarded anywhere on
    the way in, so this is the condition the credential contract has to hold under: a request
    carrying two ``Authorization`` headers is refused whichever one of them is correct. A
    server that read the first header it saw would answer 401 for one of these two orderings
    and 200 for the other, and a caller who tried both would have a way in.
    """
    issued = {
        "correct": CREDENTIAL,
        "wrong": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
    }

    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port

        status, headers, body = _request_repeating_a_header(
            port,
            "/api/v1/health",
            "Authorization",
            *(f"Bearer {issued[name]}" for name in tokens),
        )

    assert status == 401, tokens
    assert json.loads(body) == UNAUTHORIZED_BODY
    assert headers["www-authenticate"] == "Bearer"


def test_the_process_announces_its_port_and_nothing_else() -> None:
    """One line, protocol v1, and stdout empty after it.

    The remainder of stdout is drained only once the child has stopped, after several real
    requests have been answered, so a log line emitted *later* — an access record, say — fails
    this as well as one emitted earlier. Draining it while the child is alive would block on a
    pipe that legitimately has no end yet.
    """
    with _sidecar() as child:
        line = _readiness(child)

        assert line.endswith("\n")
        record = Readiness.model_validate_json(line)
        assert json.loads(line) == {
            "kind": "dynamisbench.api.ready",
            "protocol_version": 1,
            "api_version": "v1",
            "host": "127.0.0.1",
            "port": record.port,
        }
        assert record.host == "127.0.0.1"
        assert 0 < record.port <= 65535

        assert _request(record.port, "GET", "/api/v1/health", token=CREDENTIAL)[0] == 200
        assert _request(record.port, "GET", "/api/v1/health")[0] == 401

        child.terminate()
        child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        assert child.stdout is not None
        assert child.stdout.read() == "", "stdout carried something other than the handshake"


def test_the_announced_port_is_the_port_the_process_is_listening_on() -> None:
    """The handshake is not a prediction: the process answers on exactly that port."""
    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port

        assert _request(port, "GET", "/api/v1/health", token=CREDENTIAL)[0] == 200


@pytest.mark.parametrize(
    ("path", "token"),
    [
        ("/api/v1/health", None),
        ("/api/v1/health", "not-the-credential"),
        ("/api/v1/info", None),
        ("/openapi.json", None),
        ("/docs", None),
        ("/redoc", None),
    ],
)
def test_the_process_refuses_every_route_without_the_credential(
    path: str, token: str | None
) -> None:
    """Over a real socket, from another process, on a port anyone could have found."""
    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port

        status, headers, body = _request(port, "GET", path, token=token)

    assert status == 401
    assert json.loads(body) == UNAUTHORIZED_BODY
    assert headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/info", "/openapi.json"])
def test_the_process_answers_the_same_routes_with_the_credential(path: str) -> None:
    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port

        status, _, body = _request(port, "GET", path, token=CREDENTIAL)

    assert status == 200, body


def test_a_preflight_may_proceed_without_the_credential_and_a_refused_origin_may_not() -> None:
    """CORS over a real socket: the one exception to authentication, and its boundary."""
    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port

        allowed, allowed_headers, _ = _request(
            port, "OPTIONS", "/api/v1/health", origin=ALLOWED_ORIGIN, preflight=True
        )
        refused, refused_headers, _ = _request(
            port, "OPTIONS", "/api/v1/health", origin=REFUSED_ORIGIN, preflight=True
        )
        permitted_but_unauthenticated, _, _ = _request(
            port, "GET", "/api/v1/health", origin=ALLOWED_ORIGIN
        )
        permitted_and_authenticated, authenticated_headers, _ = _request(
            port, "GET", "/api/v1/health", origin=ALLOWED_ORIGIN, token=CREDENTIAL
        )

    assert allowed == 200
    assert allowed_headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "authorization" in allowed_headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in allowed_headers
    assert "access-control-allow-origin" not in refused_headers
    assert permitted_but_unauthenticated == 401
    assert permitted_and_authenticated == 200
    assert authenticated_headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_the_credential_appears_in_neither_stream() -> None:
    """The claim the whole protocol rests on, checked on both streams a supervisor keeps."""
    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port
        _request(port, "GET", "/api/v1/health", token=CREDENTIAL)
        _request(port, "GET", "/api/v1/health")
        _request(port, "OPTIONS", "/api/v1/health", origin=ALLOWED_ORIGIN, preflight=True)
        child.terminate()
        child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        assert child.stdout is not None and child.stderr is not None
        written = child.stdout.read() + child.stderr.read()

    assert CREDENTIAL not in written


def test_the_readiness_line_carries_no_environment() -> None:
    """The port, and none of the things a log would want.

    Checked against this machine's own identity, because "the line does not contain the
    username" is only a claim if the test knows what the username is.
    """
    with _sidecar() as child:
        line = _readiness(child)

    forbidden = [
        CREDENTIAL,
        os.getcwd(),
        os.path.sep,
        socket.gethostname(),
        os.environ.get("USERNAME", ""),
        os.environ.get("USER", ""),
    ]

    for disclosure in [value for value in forbidden if value]:
        assert disclosure not in line, f"the readiness line disclosed {disclosure!r}"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({SESSION_CREDENTIAL_VARIABLE: None}, "absent"),
        ({SESSION_CREDENTIAL_VARIABLE: ""}, "empty"),
        ({SESSION_CREDENTIAL_VARIABLE: REJECTED_CREDENTIAL}, "malformed"),
        ({SESSION_CREDENTIAL_VARIABLE: "A" * 44}, "wrong length"),
        ({SESSION_CREDENTIAL_VARIABLE: "A" * 42}, "short"),
        ({ALLOWED_ORIGINS_VARIABLE: None}, "no origins"),
        ({ALLOWED_ORIGINS_VARIABLE: "[]"}, "empty origin list"),
        ({ALLOWED_ORIGINS_VARIABLE: '["*"]'}, "wildcard origin"),
        ({ALLOWED_ORIGINS_VARIABLE: '["null"]'}, "null origin"),
        ({ALLOWED_ORIGINS_VARIABLE: "http://tauri.localhost"}, "not a JSON array"),
    ],
)
def test_a_refused_configuration_fails_the_process_without_announcing(
    overrides: Mapping[str, str | None], reason: str
) -> None:
    """Its own exit code, no readiness line, and nothing at all on stdout."""
    refused = _failed_to_start(overrides)

    assert refused.returncode == Exit.INVALID_CONFIGURATION, f"{reason}: {refused.stderr}"
    assert refused.stdout == "", f"{reason} produced output on the protocol channel"
    assert REJECTED_CREDENTIAL not in refused.stderr, f"{reason} echoed the credential"


def test_a_refused_configuration_says_which_variable_is_wrong() -> None:
    """The supervisor's only diagnostic: the variable's name, and never its value."""
    refused = _failed_to_start({SESSION_CREDENTIAL_VARIABLE: REJECTED_CREDENTIAL})

    assert SESSION_CREDENTIAL_VARIABLE in refused.stderr
    assert REJECTED_CREDENTIAL not in refused.stderr


def test_a_valid_credential_is_not_disclosed_by_a_failure_about_something_else() -> None:
    """The credential is already in this process when the *origins* are refused.

    The interesting failure is the one that happens after the credential has been accepted: a
    diagnostic written at that point has the credential in scope, and a supervisor's log is
    exactly where it must not arrive.
    """
    refused = _failed_to_start({ALLOWED_ORIGINS_VARIABLE: '["*"]'})

    assert refused.returncode == Exit.INVALID_CONFIGURATION
    assert ALLOWED_ORIGINS_VARIABLE in refused.stderr
    assert CREDENTIAL not in refused.stderr
    assert CREDENTIAL not in refused.stdout


def test_a_stopped_sidecar_leaves_nothing_serving() -> None:
    """Whatever a supervisor does to the process, the port does not keep serving it.

    Terminating is what a Windows supervisor can actually do — ``TerminateProcess`` gives the
    child no chance to run a handler — so this asserts the property that holds even then, while
    the graceful path is qualified in ``test_server.py`` against a real running server.
    """
    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port
        assert _answered(port, CREDENTIAL) == 200

        child.terminate()
        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) is not None

    assert _answered(port, CREDENTIAL) != 200


def test_two_sessions_never_collide() -> None:
    """Two sidecars, two ports, both serving: what "ephemeral" has to mean for two processes."""
    with _sidecar() as first:
        first_port = Readiness.model_validate_json(_readiness(first)).port
        with _sidecar() as second:
            second_port = Readiness.model_validate_json(_readiness(second)).port

            assert first_port != second_port
            assert _request(first_port, "GET", "/api/v1/health", token=CREDENTIAL)[0] == 200
            assert _request(second_port, "GET", "/api/v1/health", token=CREDENTIAL)[0] == 200


def test_the_sidecar_serves_only_the_credential_it_was_given() -> None:
    """The property that makes the credential a session proof rather than a shared password.

    It is generated per session and validated per process, so one session's token is not
    another's. Both sides of that are here: this process answers for its own token and refuses
    another well-formed one.
    """
    other = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    with _sidecar() as child:
        port = Readiness.model_validate_json(_readiness(child)).port

        assert _request(port, "GET", "/api/v1/health", token=CREDENTIAL)[0] == 200
        assert _request(port, "GET", "/api/v1/health", token=other)[0] == 401
