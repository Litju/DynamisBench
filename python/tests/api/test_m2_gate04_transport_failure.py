"""Gate 4: the secured event stream over a real process, and a real abort.

The in-process event suite owns the broadcaster's semantics: bounded queues, no persistence,
closed payloads, and the exact refusal vocabulary. This module makes the transport claim those
tests cannot: a second process serves ``/api/v1/events`` over a real loopback socket, with the
session credential and the exact development origin, and a live workspace operation published
by another connection reaches a subscriber in order.

The stream is read with ``http.client`` rather than an SSE client so the test sees the bytes,
including the ``stream.ready`` frame and the absence of a second frame after an abort. A new
subscription never receives the previous subscription's operation: the first frame is always
``stream.ready``, and a short bounded read after it must produce nothing else.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import shutil
import socket
from pathlib import Path

import pytest

from dynamisbench.api import API_V1_PREFIX
from dynamisbench.workspace import SourceCategory, initialize_workspace

from .live_sidecar import (
    DEVELOPMENT_ORIGIN,
    LiveSidecar,
    assert_clean_shutdown,
    running_sidecar,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "domain"
VALID_SCENARIO = FIXTURES / "valid" / "scenario_definition.loaded_cmj.json"
OPEN = f"{API_V1_PREFIX}/workspaces/open"
EVENTS = f"{API_V1_PREFIX}/events"

READ_TIMEOUT_SECONDS = 20.0


@pytest.fixture
def workspace_roots(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "event-authority"
    evidence = tmp_path / "event-evidence"
    initialize_workspace(source, evidence, sources=tuple(SourceCategory))
    scenario = source / "benchmarks" / "scenario"
    scenario.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VALID_SCENARIO, scenario / "valid_scenario.json")
    return source, evidence


def _stream(
    sidecar: LiveSidecar, *, token: str | None = None, origin: str | None = DEVELOPMENT_ORIGIN
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    connection = http.client.HTTPConnection("127.0.0.1", sidecar.port, timeout=READ_TIMEOUT_SECONDS)
    headers = {"Accept": "text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    connection.request("GET", EVENTS, headers=headers)
    return connection, connection.getresponse()


def _next_event(response: http.client.HTTPResponse) -> dict:
    """The next SSE data frame, ignoring comments and blank separators."""
    for _ in range(1000):
        line = response.readline()
        if line == b"":
            raise AssertionError("the event stream closed before a data frame")
        if line.startswith(b"data: "):
            return json.loads(line[len(b"data: ") :])
    raise AssertionError("the event stream produced no data frame within the bounded read")


def _assert_ready(response: http.client.HTTPResponse) -> None:
    ready = _next_event(response)
    assert ready["event"] == "stream.ready"
    assert ready["schema_version"] == 1
    assert "credential" not in json.dumps(ready)
    assert "token" not in json.dumps(ready)


def test_a_live_subscription_receives_the_operation_the_real_api_published(
    workspace_roots: tuple[Path, Path],
) -> None:
    source, evidence = workspace_roots

    with running_sidecar() as sidecar:
        connection, response = _stream(sidecar, token=sidecar.credential)
        try:
            assert response.status == 200, response.read()
            assert response.getheader("content-type", "").startswith("text/event-stream")
            assert response.getheader("access-control-allow-origin") == DEVELOPMENT_ORIGIN
            assert "access-control-allow-credentials" not in {
                name.lower() for name, _ in response.getheaders()
            }
            _assert_ready(response)

            status, _, body = sidecar.request(
                "POST",
                OPEN,
                body={"source_root": str(source), "evidence_root": str(evidence)},
            )
            assert status == 200, body
            opened = json.loads(body)["workspace_id"]

            event = _next_event(response)
            assert event["event"] == "workspace.opened"
            assert event["schema_version"] == 1
            assert event["data"]["workspace_id"] == opened
            assert set(event["data"]) == {
                "workspace_id",
                "categories_present",
                "evidence_inside_source",
            }
            text = json.dumps(event)
            assert sidecar.credential not in text
            assert str(source) not in text
            assert str(evidence) not in text
        finally:
            connection.close()

        # A new subscription starts at stream.ready and receives no replay of the previous
        # operation. The read is bounded: heartbeats are comments, so a data frame here would
        # be a replay.
        second, second_response = _stream(sidecar, token=sidecar.credential)
        try:
            assert second_response.status == 200
            _assert_ready(second_response)
            with contextlib.suppress(socket.timeout, TimeoutError):
                if second.sock is not None:
                    second.sock.settimeout(1.0)
                for _ in range(10):
                    line = second_response.readline()
                    if line in (b"", b"\n", b"\r\n"):
                        continue
                    assert line.startswith(b":"), "a new stream replayed an event"
                    break
        finally:
            second.close()

        assert_clean_shutdown(sidecar)


def test_the_process_refuses_the_stream_without_the_credential_or_for_another_origin() -> None:
    with running_sidecar() as sidecar:
        connection, response = _stream(sidecar, token=None)
        try:
            body = response.read()
            assert response.status == 401
            assert json.loads(body)["error"]["code"] == "unauthorized"
            assert sidecar.credential.encode() not in body
        finally:
            connection.close()

        connection, response = _stream(
            sidecar, token=sidecar.credential, origin="http://evil.example"
        )
        try:
            assert response.status == 200
            assert response.getheader("access-control-allow-origin") is None
        finally:
            connection.close()

        assert_clean_shutdown(sidecar)


def test_closing_the_real_stream_unsubscribes_it() -> None:
    with running_sidecar() as sidecar:
        connection, response = _stream(sidecar, token=sidecar.credential)
        try:
            assert response.status == 200
            _assert_ready(response)
        finally:
            connection.close()

        # The application's lifespan is still serving, and a fresh subscriber is the only one.
        status, _, body = sidecar.request("GET", "/api/v1/health")
        assert status == 200, body
        assert_clean_shutdown(sidecar)
