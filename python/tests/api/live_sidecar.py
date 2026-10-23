"""A real secured sidecar process, driven over its real loopback socket.

DB-2.7's live gates are the ones an in-process ``TestClient`` cannot make: a second process
owns the listener, the credential arrives through its environment, the origin policy is applied
by the process that was actually launched, and stopping it means a real pipe and a real exit.
This module is the scaffolding for those gates only; the in-process suites keep their own
clients because they are making different claims.

Nothing here is a production seam. The environment is built from
:func:`tests.api.factories.session_environment`, the command is the same
``python -m dynamisbench api serve`` a supervisor runs, and the HTTP calls use
``http.client`` over ``127.0.0.1``. A child is always stopped in the context manager's exit,
so a failed assertion cannot leave a listening process behind.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.client
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamisbench.api.control import CONTROL_PROTOCOL_VERSION, SHUTDOWN_KIND
from dynamisbench.api.server import Exit, Readiness
from dynamisbench.api.session import ALLOWED_ORIGINS_VARIABLE, SESSION_CREDENTIAL_VARIABLE

from .factories import session_environment

ANNOUNCE_TIMEOUT_SECONDS = 60.0
STOP_TIMEOUT_SECONDS = 30.0

DEVELOPMENT_ORIGIN = "http://localhost:5173"
"""The origin the development desktop session declares, and the one a browser test uses."""

SESSION_VARIABLES = (SESSION_CREDENTIAL_VARIABLE, ALLOWED_ORIGINS_VARIABLE)


def fresh_credential() -> str:
    """A credential shaped like a real one: 32 random bytes, unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def _environment(overrides: Mapping[str, str | None] | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    for name in SESSION_VARIABLES:
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


@dataclass
class LiveSidecar:
    """One running, ready sidecar and the facts its handshake announced."""

    process: subprocess.Popen[str]
    credential: str
    origin: str
    port: int
    api_version: str
    protocol_version: int

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        origin: str | None = None,
        body: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        return request(
            self.port,
            method,
            path,
            token=self.credential if token is None else token,
            origin=origin,
            body=body,
            extra_headers=extra_headers,
        )

    def stop(self) -> int:
        """Ask through the real control channel and return the process's exit code."""
        assert self.process.stdin is not None
        if self.process.poll() is None:
            self.process.stdin.write(
                json.dumps({"kind": SHUTDOWN_KIND, "protocol_version": CONTROL_PROTOCOL_VERSION})
                + "\n"
            )
            self.process.stdin.flush()
            code = self.process.wait(timeout=STOP_TIMEOUT_SECONDS)
        else:
            code = self.process.returncode
        return code


def request(
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = None,
    origin: str | None = None,
    body: Mapping[str, Any] | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One HTTP request over a real socket, with the session's own headers."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    headers.update(extra_headers or {})
    payload: bytes | None = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def _readiness(child: subprocess.Popen[str]) -> str:
    """The first line on stdout, read with a deadline so absence fails instead of hanging."""
    assert child.stdout is not None
    stdout = child.stdout
    announced: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        announced.put(stdout.readline())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(STOP_TIMEOUT_SECONDS)
    if announced.empty():
        child.kill()
        stderr = child.stderr.read() if child.stderr is not None else ""
        raise AssertionError(f"the sidecar announced no port; stderr was {stderr!r}")
    line = announced.get_nowait()
    if not line:
        child.kill()
        stderr = child.stderr.read() if child.stderr is not None else ""
        raise AssertionError(f"the sidecar exited before readiness; stderr was {stderr!r}")
    return line


@contextlib.contextmanager
def running_sidecar(
    *,
    credential: str | None = None,
    origins: tuple[str, ...] = (DEVELOPMENT_ORIGIN,),
) -> Iterator[LiveSidecar]:
    """Start one ready sidecar and guarantee it does not outlive the block."""
    issued = fresh_credential() if credential is None else credential
    overrides = {
        SESSION_CREDENTIAL_VARIABLE: issued,
        ALLOWED_ORIGINS_VARIABLE: json.dumps(list(origins)),
    }
    child = subprocess.Popen(
        _command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=_environment(overrides),
    )
    try:
        readiness = Readiness.model_validate_json(_readiness(child))
        sidecar = LiveSidecar(
            process=child,
            credential=issued,
            origin=f"http://{readiness.host}:{readiness.port}",
            port=readiness.port,
            api_version=readiness.api_version,
            protocol_version=readiness.protocol_version,
        )
        yield sidecar
    finally:
        if child.poll() is None:
            with contextlib.suppress(Exception):
                stdin = child.stdin
                if stdin is not None:
                    stdin.write(
                        json.dumps(
                            {
                                "kind": SHUTDOWN_KIND,
                                "protocol_version": CONTROL_PROTOCOL_VERSION,
                            }
                        )
                        + "\n"
                    )
                    stdin.flush()
                    child.wait(timeout=STOP_TIMEOUT_SECONDS)
            if child.poll() is None:
                child.kill()
                child.wait(timeout=STOP_TIMEOUT_SECONDS)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def assert_clean_shutdown(sidecar: LiveSidecar) -> None:
    """Stop through the control channel and prove the process and port are gone."""
    port = sidecar.port
    assert sidecar.stop() == Exit.CLEAN
    assert sidecar.process.stdout is not None
    assert sidecar.process.stdout.read() == "", "a clean shutdown wrote after the handshake"
    try:
        request(port, "GET", "/api/v1/health", token=sidecar.credential)
    except (OSError, http.client.HTTPException):
        return
    raise AssertionError(f"the stopped sidecar still serves on {port}")


def payload(response: tuple[int, dict[str, str], bytes]) -> Any:
    """The JSON body of a response, decoded exactly."""
    return json.loads(response[2])


def workspace_snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    """Names, content digests, sizes and modification times under one root.

    Directory entries are recorded with a sentinel digest so a created or removed cache
    directory is visible even when it is empty. Symlinks are recorded as links and never
    followed, so a snapshot cannot read the escape target it is meant to detect.
    """
    observed: dict[str, tuple[str, int, int]] = {}
    if not root.exists():
        return observed
    for entry in sorted(root.rglob("*")):
        key = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            observed[key] = ("link", -1, -1)
            continue
        if entry.is_dir():
            observed[key] = ("dir", -1, -1)
            continue
        stat = entry.stat()
        observed[key] = (
            hashlib.sha256(entry.read_bytes()).hexdigest(),
            stat.st_size,
            stat.st_mtime_ns,
        )
    return observed


__all__ = [
    "DEVELOPMENT_ORIGIN",
    "LiveSidecar",
    "assert_clean_shutdown",
    "fresh_credential",
    "payload",
    "request",
    "running_sidecar",
    "workspace_snapshot",
]
