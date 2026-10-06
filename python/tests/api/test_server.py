"""The sidecar process: one bound socket, one server, one readiness line, explicit outcomes.

RES-375 (Architecture §8/§13) is about the process boundary, so these gates are about things
that are only true of a running process: which address was bound, whether the port was chosen
before or after anything tried to use it, whether the readiness line was written after the
listener existed, and what the process returns when it stops. Each is measured on a real socket
and a real Uvicorn server rather than read from the source, because every one of them has an
implementation that looks correct and is not — a host default, a port probed twice, a line
printed before ``listen``, an exception swallowed into a zero.

What is covered:

* **Configuration is validated before anything binds.** A missing or malformed credential stops
  the process with its own exit code, having opened no socket at all.
* **One socket, bound once.** Exactly one ``bind`` call, to ``127.0.0.1`` with port ``0``, and
  the very object that was bound is the one handed to Uvicorn. There is no reserve/rebind race
  because there is no window between the two.
* **Uvicorn is configured for supervision.** One worker, no reload, no proxy headers, no access
  log, no WebSocket protocol, and a logging configuration in which nothing — including the
  access logger Uvicorn binds to stdout by default — can reach the protocol channel.
* **Readiness means listening, and happens once.** Emitted after Uvicorn's own startup
  returned, once, as a line that parses as protocol v1. A refused ASGI startup emits none.
* **Shutdown is clean and observable.** Asked to stop, the server stops accepting connections,
  closes the socket, runs the ASGI shutdown and returns zero.
* **Outcomes are explicit.** Zero for a clean stop, and a distinct non-zero code for a bad
  configuration and for a failure to start.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from pydantic import ValidationError

import dynamisbench.api.server as server_module
from dynamisbench.api.app import create_app
from dynamisbench.api.server import (
    Exit,
    Readiness,
    Sidecar,
    bind_loopback,
    build_sidecar,
    readiness_for,
    run_sidecar,
    serve,
    stderr_logging_config,
    uvicorn_configuration,
)
from dynamisbench.api.session import (
    ALLOWED_ORIGINS_VARIABLE,
    SESSION_CREDENTIAL_VARIABLE,
    RuntimeConfiguration,
)
from tests.api.factories import CREDENTIAL, session_configuration, session_environment

READY_KIND = "dynamisbench.api.ready"


def _refused_bind() -> socket.socket:
    raise OSError("refused")


def _sidecar_with(application: FastAPI) -> Sidecar:
    """A sidecar serving an application the test supplied, on a real bound socket.

    ``build_sidecar`` composes the application itself, so a test that needs to observe the
    application's own lifespan has to attach the socket the same way and supply the
    application. That is a property of a frozen record, not a seam added for testing.
    """
    listener = bind_loopback()
    return Sidecar(
        configuration=session_configuration(),
        application=application,
        socket=listener,
        port=int(listener.getsockname()[1]),
    )


def _serving(sidecar: Sidecar, on_listening: Callable[[uvicorn.Server], None] | None) -> Exit:
    """Serve ``sidecar`` in a fresh event loop and return the process outcome.

    ``asyncio.run`` rather than a background thread, so the signal handlers Uvicorn installs
    belong to this process's main thread and are restored before the next test runs.
    """
    return _run_capturing_stdout(sidecar, on_listening)[0]


def _run_capturing_stdout(
    sidecar: Sidecar, on_listening: Callable[[uvicorn.Server], None] | None = None
) -> tuple[Exit, str]:
    """Serve ``sidecar`` and return its outcome together with the bytes it wrote to stdout."""

    async def serve_once() -> tuple[Exit, str]:
        with contextlib.redirect_stdout(captured := io.StringIO()):
            outcome = await run_sidecar(sidecar, on_listening)
        return outcome, captured.getvalue()

    return asyncio.run(serve_once())


def _application_recording_its_lifecycle() -> tuple[FastAPI, list[str]]:
    """``create_app()`` with a lifespan that reports when it starts and when it stops.

    The real application rather than a stub, so the shutdown these gates observe is the one a
    supervisor causes on the real thing: a stub would prove that a context manager runs, and
    not that Uvicorn runs it for the application the sidecar serves.
    """
    events: list[str] = []
    application = create_app()

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    application.router.lifespan_context = lifespan
    return application, events


def _application_refusing_to_start() -> FastAPI:
    application = create_app()

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        raise RuntimeError("this application refuses to start")
        yield

    application.router.lifespan_context = lifespan
    return application


@pytest.fixture(autouse=True)
def _no_ambient_session_configuration() -> Iterator[None]:
    """A developer's own environment must not decide what these gates exercise.

    Both variables are cleared for every test here, because a machine that happens to have them
    set would make "a missing credential is refused" pass for the wrong reason, and ``serve()``
    with no argument reads the process environment.
    """
    saved = {
        name: os.environ.pop(name, None)
        for name in (SESSION_CREDENTIAL_VARIABLE, ALLOWED_ORIGINS_VARIABLE)
    }
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def test_the_readiness_record_is_the_whole_protocol() -> None:
    """Five fields, in a fixed order, and nothing else on the line.

    Read off the model rather than off a string constant, because a supervisor parses this line
    and the parsed shape is the contract. The order is part of it: a byte-for-byte comparison
    is the cheapest thing a supervisor can do, and pydantic emits fields in declaration order.
    """
    line = readiness_for(49152).model_dump_json()

    assert json.loads(line) == {
        "kind": READY_KIND,
        "protocol_version": 1,
        "api_version": "v1",
        "host": "127.0.0.1",
        "port": 49152,
    }
    assert list(json.loads(line)) == [
        "kind",
        "protocol_version",
        "api_version",
        "host",
        "port",
    ]


def test_the_readiness_line_is_byte_identical_for_two_ports() -> None:
    """Determinism, so a supervisor may compare the line rather than parse it."""
    first = readiness_for(49152).model_dump_json()
    second = readiness_for(49153).model_dump_json()

    assert first.replace("49152", "") == second.replace("49153", "")


@pytest.mark.parametrize(
    "record",
    [
        {"api_version": "v1", "port": 49152},
        {"api_version": "v1", "port": 0},
        {"api_version": "v1", "port": 70000},
        {"api_version": "v1", "port": "49152"},
        {"api_version": "v1", "port": 49152, "host": "0.0.0.0"},
        {"api_version": "v1", "port": 49152, "protocol_version": 2},
        {"api_version": "v1", "port": 49152, "kind": "dynamisbench.api.ready.v2"},
        {"api_version": "v1", "port": 49152, "token": CREDENTIAL},
        {"api_version": "v1", "port": 49152, "pid": 4242},
    ],
)
def test_the_readiness_record_accepts_nothing_else(record: dict[str, Any]) -> None:
    """A supervisor that can be handed a wider record is a supervisor that can be lied to."""
    with pytest.raises(ValidationError):
        Readiness.model_validate(record)


def test_a_bound_socket_is_loopback_and_ephemeral() -> None:
    """The address is 127.0.0.1 and the port is one the operating system chose.

    Asserted on the socket itself rather than on a configuration value, because the socket is
    the thing a connection will actually be made to.
    """
    listener = bind_loopback()
    try:
        address = listener.getsockname()

        assert listener.family == socket.AF_INET
        assert address[0] == "127.0.0.1"
        assert address[1] != 0, "port 0 was requested and the operating system has not chosen"
        assert 0 < address[1] <= 65535
    finally:
        listener.close()


def test_two_bound_sockets_never_share_a_port() -> None:
    """Ephemeral means ephemeral: the second bind is not refused by the first."""
    first, second = bind_loopback(), bind_loopback()
    try:
        assert first.getsockname()[1] != second.getsockname()[1]
    finally:
        first.close()
        second.close()


def test_the_socket_is_bound_exactly_once_to_an_ephemeral_loopback_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reserve/rebind race is prevented by there being only one bind.

    ``socket.socket.bind`` is counted rather than the source read, so the gate holds however the
    port is obtained — by this module, by Uvicorn, or by a library binding on our behalf. The
    address is asserted as well, because a single bind to ``0.0.0.0:8000`` would satisfy the
    count and none of the purpose.
    """
    bound: list[tuple[Any, ...]] = []
    original = socket.socket.bind

    def counted(self: socket.socket, address: Any) -> None:
        bound.append(address)
        original(self, address)

    monkeypatch.setattr(socket.socket, "bind", counted)

    sidecar = build_sidecar(session_configuration())
    try:
        assert bound == [("127.0.0.1", 0)]
        assert sidecar.port == sidecar.socket.getsockname()[1] != 0
    finally:
        sidecar.socket.close()


def test_the_socket_bound_is_the_socket_served(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-bound object is handed to Uvicorn, not merely an equal one.

    This is the half of the guarantee the count above cannot see. Binding twice to the same
    *number* would still bind twice; what matters is that Uvicorn receives the socket that is
    already bound, so no code path selects a port and then asks for it again.
    """
    served: list[list[socket.socket]] = []

    async def capture(_: uvicorn.Server, sockets: Any = None) -> None:
        served.append(sockets)

    monkeypatch.setattr(uvicorn.Server, "serve", capture)

    sidecar = build_sidecar(session_configuration())
    _serving(sidecar, None)

    assert served == [[sidecar.socket]]


def test_the_sidecar_serves_the_session_secured_application() -> None:
    """The composition is wired, not merely assembled: what is served demands a credential."""
    sidecar = build_sidecar(session_configuration())
    try:
        assert isinstance(sidecar.application, FastAPI)
        assert sidecar.application.openapi() == create_app().openapi(), (
            "securing a session must add no route and change no published schema"
        )
        assert sidecar.configuration.credential.admits(CREDENTIAL)
    finally:
        sidecar.socket.close()


def test_uvicorn_is_configured_for_a_supervised_sidecar() -> None:
    """Stated as a closed set of the properties the protocol depends on.

    Read from the configuration object Uvicorn is actually handed, so a change to a default in
    the dependency cannot quietly turn one of these off.
    """
    sidecar = build_sidecar(session_configuration())
    try:
        configuration = uvicorn_configuration(sidecar)

        assert configuration.workers == 1
        assert configuration.reload is False
        assert configuration.proxy_headers is False
        assert configuration.access_log is False
        assert configuration.ws == "none"
        assert configuration.host == "127.0.0.1"
        assert configuration.port == 0, "the fallback bind must be ephemeral, not a fixed port"
    finally:
        sidecar.socket.close()


def test_no_uvicorn_logger_can_write_to_stdout() -> None:
    """Uvicorn's own default binds its access logger to ``sys.stdout``.

    Overriding it is the only reason the readiness line is safe to parse from a pipe, so it is
    checked rather than assumed: every handler must resolve to stderr, and the access logger
    must have one of them.
    """
    configuration = stderr_logging_config()

    assert set(configuration["handlers"]) == {"stderr"}
    for handler in configuration["handlers"].values():
        assert handler["stream"] == "ext://sys.stderr"
    assert configuration["loggers"]["uvicorn"]["handlers"] == ["stderr"]
    assert configuration["loggers"]["uvicorn.access"]["handlers"] == ["stderr"]


def test_the_logging_configuration_is_not_shared_between_servers() -> None:
    """Uvicorn mutates the dictionary it is handed, so two servers must not share one."""
    assert stderr_logging_config() is not stderr_logging_config()


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {SESSION_CREDENTIAL_VARIABLE: "", ALLOWED_ORIGINS_VARIABLE: "[]"},
        {SESSION_CREDENTIAL_VARIABLE: "not-a-credential", ALLOWED_ORIGINS_VARIABLE: "[]"},
        {SESSION_CREDENTIAL_VARIABLE: CREDENTIAL},
        {ALLOWED_ORIGINS_VARIABLE: '["http://tauri.localhost"]'},
        {ALLOWED_ORIGINS_VARIABLE: '["*"]'},
        {ALLOWED_ORIGINS_VARIABLE: '["null"]'},
        {
            SESSION_CREDENTIAL_VARIABLE: CREDENTIAL,
            ALLOWED_ORIGINS_VARIABLE: "http://tauri.localhost",
        },
    ],
)
def test_a_bad_configuration_is_its_own_outcome(environment: dict[str, str]) -> None:
    """Refused with its own exit code, having reached no socket.

    Checked through the process entry point so that the mapping from refusal to code is the one
    a supervisor sees.
    """
    assert serve(environment) is Exit.INVALID_CONFIGURATION


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {SESSION_CREDENTIAL_VARIABLE: "not-a-credential", ALLOWED_ORIGINS_VARIABLE: '["*"]'},
    ],
)
def test_nothing_is_bound_before_the_configuration_is_valid(
    environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering itself, asserted by making the violation fatal.

    Binding first and validating afterwards would leave a listening port behind for a process
    that is about to exit, and would have told the operating system about a port this session
    has no credential to serve.
    """

    def forbidden() -> socket.socket:
        raise AssertionError("a socket must not be opened before the configuration is valid")

    monkeypatch.setattr(server_module, "bind_loopback", forbidden)

    assert serve(environment) is Exit.INVALID_CONFIGURATION


def test_a_refused_bind_is_its_own_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configuration that is fine but a socket that cannot be bound is a different failure,
    and neither of them is a clean shutdown."""

    def refuse() -> socket.socket:
        raise OSError("refused")

    monkeypatch.setattr(server_module, "bind_loopback", refuse)

    assert serve(session_environment()) is Exit.STARTUP_FAILED


def test_serve_reads_the_process_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default is the process environment, which is where the desktop session puts it."""
    for name, value in session_environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(server_module, "bind_loopback", _refused_bind)

    assert serve() is Exit.STARTUP_FAILED


def test_the_readiness_line_is_written_once_after_the_server_is_listening() -> None:
    """The whole point of the handshake: the port is announced only once it can answer.

    Proven by connecting to the announced port inside the moment it is announced. If the line
    were written before the listener existed, that connection would fail and this test would
    fail with it — which is exactly the race a supervisor would otherwise lose.
    """
    observed: dict[str, Any] = {}
    sidecar = _sidecar_with(create_app())

    def on_listening(server: uvicorn.Server) -> None:
        observed["started"] = server.started
        with socket.create_connection(("127.0.0.1", sidecar.port), timeout=5):
            observed["connected"] = True
        server.should_exit = True

    exit_code, output = _run_capturing_stdout(sidecar, on_listening)

    assert exit_code is Exit.CLEAN
    assert observed == {"started": True, "connected": True}
    lines = output.splitlines()
    assert len(lines) == 1, f"exactly one line is the protocol; got {lines!r}"
    assert Readiness.model_validate_json(lines[0]).port == sidecar.port


def test_a_refused_application_startup_emits_no_readiness() -> None:
    """No listening, no line — and a distinct outcome from a clean stop.

    An ASGI lifespan that fails is the realistic version of this: the socket is bound, the
    application cannot start, and a supervisor already told a port would connect to something
    that will never answer.
    """
    sidecar = _sidecar_with(_application_refusing_to_start())

    exit_code, output = _run_capturing_stdout(sidecar)

    assert exit_code is Exit.STARTUP_FAILED
    assert output == "", "nothing may be announced by a sidecar that never listened"
    assert sidecar.socket.fileno() == -1, "the pre-bound socket must not outlive the process"


def test_a_clean_shutdown_stops_accepting_and_runs_the_application_shutdown() -> None:
    """Asked to exit, the sidecar leaves nothing behind.

    All four properties a supervisor relies on, on one real socket: it stops accepting
    connections, the socket it was bound to is closed, the application's own shutdown runs, and
    the process returns zero.
    """
    application, events = _application_recording_its_lifecycle()
    sidecar = _sidecar_with(application)
    port = sidecar.port

    def on_listening(server: uvicorn.Server) -> None:
        server.should_exit = True

    exit_code, _ = _run_capturing_stdout(sidecar, on_listening)

    assert exit_code is Exit.CLEAN
    assert int(exit_code) == 0
    assert events == ["startup", "shutdown"]
    assert sidecar.socket.fileno() == -1
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_the_outcomes_are_the_four_a_supervisor_distinguishes() -> None:
    """Stated as values, because they are a protocol of their own.

    RES-376 will branch on these, so they are pinned here rather than left to the shape of the
    enum. ``CLEAN`` is the only zero: a failure that exits zero is a supervisor's way of
    learning nothing.
    """
    assert (Exit.CLEAN, Exit.UNEXPECTED, Exit.INVALID_CONFIGURATION, Exit.STARTUP_FAILED) == (
        0,
        1,
        2,
        3,
    )
    assert len(set(Exit)) == 4


def test_the_sidecar_owns_no_scientific_configuration() -> None:
    """What it is handed is a credential and a list of origins.

    Stated over the configuration's own fields, so a future ``workspace`` or ``runs`` field
    would fail here rather than in a test written after it existed.
    """
    configuration: RuntimeConfiguration = session_configuration()

    assert sorted(configuration.__dataclass_fields__) == ["credential", "origins"]


_AUDIT_PROBE = "\n".join(
    [
        "import asyncio, contextlib, io, json, os, sys",
        "observed = []",
        "sys.addaudithook(lambda event, arguments: observed.append((event, arguments)))",
        "import dynamisbench.api.server as server",
        "configuration = server.runtime_configuration(os.environ)",
        "observed.clear()",
        "async def main() -> int:",
        "    sidecar = server.build_sidecar(configuration)",
        "    def on_listening(running) -> None:",
        "        running.should_exit = True",
        "    with contextlib.redirect_stdout(io.StringIO()):",
        "        return int(await server.run_sidecar(sidecar, on_listening))",
        "exit_code = asyncio.run(main())",
        "writes = [m for event, arguments in observed if event == 'open'",
        "          for m in map(str, arguments[1:]) if m[:1] in {'w', 'a', 'x', '+'}]",
        "mutations = sorted({event for event, _ in observed if event in {",
        "    'os.mkdir', 'os.rename', 'os.remove', 'os.rmdir', 'os.link', 'os.symlink',",
        "    'os.truncate', 'os.chmod', 'os.utime', 'shutil.rmtree', 'tempfile.mkdtemp',",
        "}})",
        "print(json.dumps({'exit': exit_code, 'writes': writes, 'mutations': mutations}))",
    ]
)


def test_serving_the_api_writes_nothing_to_the_machine() -> None:
    """Architecture §13: the sidecar owns no workspace and no scientific state.

    Measured through a full serve cycle — build, bind, start, announce, shut down — with a
    syscall audit hook installed before the imports and read after them, so what it reports is
    the serving process's own work. Reading the import graph instead would only prove that no
    module was *imported* that writes files, and the failure this prevents is a line inside a
    handler: the sidecar restarting must not create, move or delete anything a scientific claim
    could rest on.

    Sockets are deliberately absent from the forbidden set: this sidecar opens exactly one, and
    the gates above are what qualify where it is opened.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in (SESSION_CREDENTIAL_VARIABLE, ALLOWED_ORIGINS_VARIABLE)
    }
    environment.update(session_environment())
    result = subprocess.run(
        [sys.executable, "-c", _AUDIT_PROBE],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    observed = json.loads(result.stdout)

    assert observed == {"exit": int(Exit.CLEAN), "writes": [], "mutations": []}
