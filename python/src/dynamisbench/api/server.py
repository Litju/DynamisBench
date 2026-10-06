"""The supervised localhost API process: one bound socket, one server, one readiness line.

Architecture §8/§13 and RES-375 put a process boundary between the desktop session and the
application. This module is that boundary, and it is the only place in the project that
opens a socket or starts a server. Everything about it is chosen so that the supervising
shell never has to guess:

* **One socket, bound once, handed on.** :func:`bind_loopback` opens the listener and binds it
  to ``127.0.0.1:0``, and that exact object is given to a single Uvicorn ``Server``. The
  familiar alternative — ask the OS for a free port, close the socket, then ask Uvicorn to
  bind that number — has a window in which another process takes it, and on a machine
  running an unrelated application that window is not theoretical. There is no host option
  and no ``0.0.0.0``: a desktop sidecar has no reason to be reachable from the network, and
  an address it cannot be given is one it cannot be misconfigured into.
* **Readiness means listening.** :class:`_SidecarServer` writes the single readiness record
  after Uvicorn's own ``startup`` has returned, which is the first point at which a client
  can connect and be answered. A supervisor that read the port from a line emitted earlier
  would race the listener it is about to use.
* **stdout is the protocol.** Uvicorn's default logging configuration sends *access* logs to
  stdout, which would corrupt the only channel the supervisor reads, so the log configuration
  here is replaced with one that sends everything to stderr. Nothing else in this package
  writes to stdout, and the record carries no path, no process id, no timestamp and no
  credential — a supervisor needs four facts and a leaked one cannot be taken back.
* **Outcomes are explicit.** :class:`Exit` is the whole vocabulary: zero for a shutdown that
  was asked for, and three distinct non-zero codes for the three ways this process can fail
  before or during serving. A failure that exits zero is indistinguishable from a healthy
  sidecar that stopped, so none of them does.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Literal

import uvicorn
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp

from dynamisbench.api.routing import API_VERSION
from dynamisbench.api.session import (
    RuntimeConfiguration,
    SessionConfigurationError,
    runtime_configuration,
    secured_application,
)

LOOPBACK_HOST = "127.0.0.1"
"""The one address this sidecar may bind.

A literal rather than a default: there is no code path that replaces it, so the way to serve
on anything else is to edit this line in review rather than to pass a flag.
"""

logger = logging.getLogger("uvicorn.error")
"""Deliberately Uvicorn's own error logger.

Every log record this process writes must land on stderr under the one configuration that
owns its handlers, and this logger already does. A module logger of our own would inherit
whatever the root logger happened to be configured with, which is not a property this
protocol can rely on.
"""


class Exit(IntEnum):
    """Process outcomes, so a supervisor can tell them apart without reading a log.

    Stable, because a supervisor branches on them: RES-376 will map these to a sidecar's
    lifecycle, and changing a value would change behaviour in a component that is not in
    this repository.
    """

    CLEAN = 0
    """A shutdown that was asked for completed."""

    UNEXPECTED = 1
    """The server failed in a way this process did not anticipate."""

    INVALID_CONFIGURATION = 2
    """The runtime configuration was missing or malformed, so nothing was started."""

    STARTUP_FAILED = 3
    """The socket or the ASGI application could not be started, so nothing was served."""


class Readiness(BaseModel):
    """The one record the sidecar writes to stdout, and the whole protocol v1.

    Five fields, a closed shape, no defaults, and literal types for the four a supervisor does
    not get to choose. Every field is required so that a record which forgot to state one is
    refused rather than read with the model's own value filled in — a supervisor that infers a
    handshake version is a supervisor that can be told which one to infer. ``strict`` for the
    same reason: ``"port": "49152"`` is not this protocol, however willing the coercion would
    be.

    ``api_version`` is the one field this sidecar does not decide, and it is always taken from
    :data:`dynamisbench.api.routing.API_VERSION` so it cannot drift from the version the routes
    are actually published under. The handshake's own ``protocol_version`` is separate and
    moves separately: a v2 API served under protocol v1 is a client change, while a v2
    protocol is a supervisor change.

    What is absent is as load-bearing as what is present. No credential, no process id, no
    timestamp, no hostname, no username, no working directory, no workspace path — a
    supervisor needs five facts, and every one of the others is something that would have to
    be redacted before this line could be logged by anyone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["dynamisbench.api.ready"]
    protocol_version: Literal[1]
    api_version: str
    host: Literal["127.0.0.1"]
    port: int = Field(gt=0, le=65535)


@dataclass(frozen=True)
class Sidecar:
    """One configuration, one already-bound socket, one application to serve on it.

    A record of things that exist, not a handle that starts them. Building one is the last
    step before serving and the first step after validating the configuration, so it is the
    point at which a test can hold a real socket without a server attached to it.
    """

    configuration: RuntimeConfiguration
    application: ASGIApp
    socket: socket.socket
    port: int


def bind_loopback() -> socket.socket:
    """Open the one socket this session will serve on, bound once, for keeps.

    ``SO_EXCLUSIVEADDRUSE`` on Windows and nothing at all elsewhere: it is what stops another
    process on the machine from taking this port out from under a server that is about to
    use it, and ``SO_REUSEADDR`` — which Uvicorn's own binder sets — does the opposite. The
    socket is returned still bound and not listening, because listening is Uvicorn's job once
    it owns the socket.

    Closed on failure. A half-built sidecar that leaks a descriptor is the kind of defect that
    only shows up as "the port was in use" on somebody else's machine.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((LOOPBACK_HOST, 0))
    except OSError:
        listener.close()
        raise
    return listener


def build_sidecar(configuration: RuntimeConfiguration) -> Sidecar:
    """Build the application and bind the socket it will be served on, in that order.

    The order is the point: by the time a socket exists, the credential has already been
    validated and the origin list accepted, so a configuration mistake cannot leave a
    listening port behind for a process that is about to exit.
    """
    application = secured_application(configuration.credential, configuration.origins)
    listener = bind_loopback()
    return Sidecar(
        configuration=configuration,
        application=application,
        socket=listener,
        port=int(listener.getsockname()[1]),
    )


def stderr_logging_config() -> dict[str, Any]:
    """A Uvicorn logging configuration in which nothing can reach stdout.

    Uvicorn's own default binds its access logger to ``ext://sys.stdout``. That is a
    reasonable default for a server run from a terminal and it is exactly wrong here, where
    stdout is a machine-readable protocol channel a supervisor parses. Access logging is
    also switched off outright, so this is belt and braces on one invariant rather than two
    independent protections: with one log record on stdout the channel is corrupt whether or
    not that record was ever about the credential.

    Built per call because Uvicorn mutates the dictionary it is given.
    """
    formatter = {"()": "uvicorn.logging.DefaultFormatter", "fmt": "%(levelprefix)s %(message)s"}
    handler = {
        "class": "logging.StreamHandler",
        "formatter": "default",
        "stream": "ext://sys.stderr",
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": formatter, "access": formatter},
        "handlers": {"stderr": handler},
        "loggers": {
            "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        },
    }


def uvicorn_configuration(sidecar: Sidecar) -> uvicorn.Config:
    """Uvicorn, configured for a supervised desktop sidecar rather than for a web server.

    One process and one worker, no reload, no proxy headers (there is no trusted upstream to
    take headers from, and trusting ``X-Forwarded-For`` from a loopback peer is how a client
    ends up believing it came from somewhere it did not), no access log, and no WebSocket
    protocol: ADR-019 keeps WebSocket for genuine bidirectional interaction and M2 has none,
    so the transport is not enabled before there is something to send over it.

    ``host`` and ``port`` are set to the loopback address and to zero even though the socket
    is handed over ready-bound, because they are Uvicorn's fallback. A fallback must be
    loopback and ephemeral too, or an unexpected code path could bind a fixed port that some
    other process already owns.
    """
    return uvicorn.Config(
        sidecar.application,
        host=LOOPBACK_HOST,
        port=0,
        workers=1,
        reload=False,
        proxy_headers=False,
        access_log=False,
        ws="none",
        lifespan="on",
        server_header=False,
        use_colors=False,
        log_config=stderr_logging_config(),
    )


def readiness_for(port: int) -> Readiness:
    """The record for a port the operating system has already chosen.

    Every value is stated explicitly, which is the point of a handshake: the supervisor may
    compare this line against what it expects, and a field the model filled in would be a field
    the supervisor did not learn anything from.
    """
    return Readiness(
        kind="dynamisbench.api.ready",
        protocol_version=1,
        api_version=API_VERSION,
        host=LOOPBACK_HOST,
        port=port,
    )


def announce(port: int) -> None:
    """Write the one readiness line and flush it.

    One line, one flush, no trailing commentary: a supervisor reads a single line from a
    pipe and acts on it, so anything else on the channel — a second line, a log, a progress
    message — is a protocol violation. Flushing separately matters because the supervisor is
    a pipe reader waiting for exactly this, and a buffered write would look like a hung
    process.
    """
    sys.stdout.write(f"{readiness_for(port).model_dump_json()}\n")
    sys.stdout.flush()


class _SidecarServer(uvicorn.Server):
    """Uvicorn, plus the one thing this sidecar adds: readiness after listening.

    Overriding ``startup`` rather than polling ``started`` is what makes "only after
    listening" structural. Uvicorn calls ``sys.exit`` from inside that method when the ASGI
    lifespan or the listener fails, so a startup failure leaves the announcement uncalled
    without a single conditional here.
    """

    def __init__(
        self,
        config: uvicorn.Config,
        port: int,
        on_listening: Callable[[uvicorn.Server], None] | None = None,
    ) -> None:
        super().__init__(config)
        self._port = port
        self._on_listening = on_listening

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        announce(self._port)
        if self._on_listening is not None:
            self._on_listening(self)


async def run_sidecar(
    sidecar: Sidecar,
    on_listening: Callable[[uvicorn.Server], None] | None = None,
) -> Exit:
    """Serve ``sidecar`` on the socket it already owns, until asked to stop.

    ``on_listening`` receives the running server, which is how a caller asks for shutdown:
    setting ``should_exit`` on it makes Uvicorn stop accepting connections, close the socket
    it was handed, run the ASGI shutdown and return. It is called after the readiness line,
    so a caller that shuts down in the callback is still a caller that was told the port.

    Every failure becomes an :class:`Exit`, because this is a supervised process: an
    exception that escapes here reaches a supervisor as an unhandled traceback and a code
    that means "crashed", which is a worse answer than a code that means which of the three
    things went wrong.
    """
    server = _SidecarServer(uvicorn_configuration(sidecar), sidecar.port, on_listening)
    try:
        await server.serve(sockets=[sidecar.socket])
        return Exit.CLEAN
    except SystemExit:
        # Uvicorn exits this way when the listener or the ASGI lifespan refuses to start,
        # having already logged why. There is no readiness line to withdraw.
        logger.error("The API sidecar could not start.")
        return Exit.STARTUP_FAILED
    except Exception:
        logger.exception("The API sidecar stopped with an unexpected failure.")
        return Exit.UNEXPECTED
    finally:
        # Uvicorn closes the sockets it was handed during a normal shutdown, and closing an
        # already-closed socket is a no-op. Doing it here as well means no path out of this
        # function — success, refused startup, or an unexpected failure part-way through
        # serving — can leave the port bound by a process that is about to exit.
        sidecar.socket.close()


def serve(environment: Mapping[str, str] | None = None) -> Exit:
    """``dbench api serve``: read the session's configuration, then be the sidecar.

    Configuration is read from the process environment, so the credential is inherited by
    this process and appears in neither the argument vector nor the log. A configuration
    problem is reported by naming the variable that is wrong, never its value.
    """
    source = os.environ if environment is None else environment
    try:
        configuration = runtime_configuration(source)
    except SessionConfigurationError as failure:
        logger.error("%s", failure)
        return Exit.INVALID_CONFIGURATION

    try:
        sidecar = build_sidecar(configuration)
    except OSError:
        logger.error("The API sidecar could not bind %s.", LOOPBACK_HOST)
        return Exit.STARTUP_FAILED

    return asyncio.run(run_sidecar(sidecar))


__all__ = [
    "LOOPBACK_HOST",
    "Exit",
    "Readiness",
    "Sidecar",
    "announce",
    "bind_loopback",
    "build_sidecar",
    "readiness_for",
    "run_sidecar",
    "serve",
    "stderr_logging_config",
    "uvicorn_configuration",
]
