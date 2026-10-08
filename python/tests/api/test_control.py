"""The supervisor's private channel: one record, one EOF, and no second vocabulary.

RES-376 makes stdin the parent→sidecar control channel. What a supervisor needs from it is
narrow enough to state completely: a running sidecar can be asked to stop, through one exact
record, and a sidecar whose parent is gone stops on its own. Everything else about the channel
is a refusal, and the failure that matters is not a missing capability but an extra one — a
malformed record that quietly became an alternate command, or a diagnostic that echoed the
parent's input onto a stream someone keeps.

What is covered:

* **The record is exact, and the model is closed.** A wrong kind, a wrong version, a missing
  field, an extra field, a JSON type that had to be coerced and a line that is not JSON are all
  the same answer: ``None``. Parsing produces a record or nothing — there is no partially
  honoured shape.
* **The record and EOF both mean stop, and nothing else does.** Each requests shutdown exactly
  once; a malformed record never does, and never stops the channel from accepting the real
  record afterwards.
* **Input cannot reach stdout, and diagnostics carry none of it.** The channel's own report is
  written to stderr, at most once per session, and deliberately repeats none of the offending
  content — a token-shaped value in the parent's input must not become a token-shaped value in
  a log.
* **The real process obeys all of it.** A spawned sidecar is sent the record over its actual
  stdin and exits 0 with the port closed; one whose stdin is closed exits 0 the same way; one
  that was sent a malformed record keeps serving, then still shuts down cleanly; and the
  credential appears in neither stream on any of those paths.
"""

from __future__ import annotations

import base64
import contextlib
import http.client
import io
import logging
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from typing import IO

import pytest

from dynamisbench.api.control import (
    CONTROL_PROTOCOL_VERSION,
    MAX_CONTROL_LINE_CHARACTERS,
    SHUTDOWN_KIND,
    ControlChannel,
    ControlRecord,
    parse_control_record,
)
from dynamisbench.api.server import Exit, Readiness
from dynamisbench.api.session import ALLOWED_ORIGINS_VARIABLE, SESSION_CREDENTIAL_VARIABLE
from tests.api.factories import CREDENTIAL, session_environment

SHUTDOWN_LINE = '{"kind":"dynamisbench.api.shutdown","protocol_version":1}\n'
"""The exact bytes RES-376 fixes, written out rather than derived, so the contract is pinned
from the parent's side too: the Rust supervisor sends this string and the Python side parses
it, and a change to either has to fail something."""

MALFORMED_SENTINEL = "this-is-the-supervisor-input-a-diagnostic-must-never-repeat"

SECRET_VARIABLES = (SESSION_CREDENTIAL_VARIABLE, ALLOWED_ORIGINS_VARIABLE)

READINESS_TIMEOUT_SECONDS = 60.0
SHUTDOWN_TIMEOUT_SECONDS = 30.0


def test_the_record_model_serializes_to_the_exact_bytes_the_parent_sends() -> None:
    """The same 43-character discipline as the credential: one canonical spelling.

    The Rust supervisor will serialize the same two fields with serde; this test is what says
    what it must produce. Compact JSON, declaration order, one trailing newline.
    """
    record = ControlRecord(kind=SHUTDOWN_KIND, protocol_version=CONTROL_PROTOCOL_VERSION)

    assert record.model_dump_json() + "\n" == SHUTDOWN_LINE


def test_the_exact_record_parses() -> None:
    record = parse_control_record(SHUTDOWN_LINE)

    assert record == ControlRecord(kind=SHUTDOWN_KIND, protocol_version=CONTROL_PROTOCOL_VERSION)


def test_the_protocol_constants_are_the_published_ones() -> None:
    assert SHUTDOWN_KIND == "dynamisbench.api.shutdown"
    assert CONTROL_PROTOCOL_VERSION == 1


@pytest.mark.parametrize(
    "line",
    [
        "",
        "\n",
        "null",
        "[]",
        "{}",
        '"dynamisbench.api.shutdown"',
        '{"kind":"dynamisbench.api.shutdown"}',
        '{"protocol_version":1}',
        '{"kind":"dynamisbench.api.other","protocol_version":1}',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":2}',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":"1"}',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1.0}',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":true}',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1,"token":"' + CREDENTIAL + '"}',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1,"command":"rm -rf /"}',
        "not json at all",
        "rm -rf /",
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1} trailing',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1}{"kind":"dynamisbench.api.shutdown"}',
        '{"kind" : "dynamisbench.api.shutdown", "protocol_version" : 1, }',
    ],
)
def test_everything_that_is_not_the_exact_record_parses_to_nothing(line: str) -> None:
    """A closed shape, and no coercion: ``None`` is the whole failure surface.

    The extra-field rows carry a token and something that looks like a command, because the
    property under test is that neither becomes meaningful. The model never returns a partly
    valid record, so there is no field for a caller to fall back on.
    """
    assert parse_control_record(line) is None


def _channel(text: str) -> tuple[ControlChannel, io.StringIO, list[int]]:
    stream = io.StringIO(text)
    requested: list[int] = []
    return (
        ControlChannel(stream, on_shutdown=lambda: requested.append(1)),
        stream,
        requested,
    )


def test_the_exact_record_asks_for_shutdown_exactly_once() -> None:
    channel, _, requested = _channel(SHUTDOWN_LINE)

    channel.run()

    assert requested == [1]


def test_eof_at_the_start_of_the_channel_asks_for_shutdown() -> None:
    """A parent that closed the pipe before writing anything is a parent that is gone."""
    channel, _, requested = _channel("")

    channel.run()

    assert requested == [1]


def test_eof_after_an_unterminated_line_asks_for_shutdown() -> None:
    """A line the parent never finished is not a record, but the EOF behind it is loss."""
    channel, _, requested = _channel('{"kind":"dynamisbench.api.shutdown","protocol_version":1}')

    channel.run()

    assert requested == [1]


@pytest.mark.parametrize(
    "malformed",
    [
        "not json\n",
        '{"kind":"dynamisbench.api.other","protocol_version":1}\n',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":2}\n',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1,"token":"' + CREDENTIAL + '"}\n',
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1,"command":"shutdown -s"}\n',
        "\n",
    ],
)
def test_a_malformed_record_is_not_a_command_and_does_not_stop_the_channel(
    malformed: str,
) -> None:
    """The malformed record is skipped, not honoured and not fatal.

    The valid record at the end is the point, and the stream's position is how this test knows
    it was reached: a channel that treated malformed input as a shutdown would stop at the
    end of the malformed line and never consume the valid one. Nothing here executes anything
    — the only effect a record can have is the one ``on_shutdown`` callback.
    """
    channel, stream, requested = _channel(malformed + SHUTDOWN_LINE)

    channel.run()

    assert requested == [1]
    assert stream.tell() == len(malformed) + len(SHUTDOWN_LINE), (
        "the channel must read past a malformed record to the valid one"
    )


class _PositionedStream:
    """An in-memory line stream that records how much has been consumed."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self.position = 0

    def readline(self, limit: int = -1, /) -> str:
        if not self._lines:
            return ""
        line = self._lines.pop(0)
        self.position += len(line)
        return line


def test_malformed_records_alone_request_nothing() -> None:
    """Only the EOF behind them requests shutdown, never the malformed content.

    The callback records the stream position at the moment it runs. If a malformed record had
    been treated as a command, the position would be at the end of that record; it is at the
    end of the stream instead, which is where the empty read happens.
    """
    stream = _PositionedStream(["first malformed\n", "second malformed\n"])
    positions: list[int] = []
    channel = ControlChannel(stream, on_shutdown=lambda: positions.append(stream.position))

    channel.run()

    assert positions == [stream.position]
    assert stream.position == len("first malformed\nsecond malformed\n")


def test_the_first_malformed_record_is_reported_once_without_its_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bounded diagnostics: one report, no repetition, and none of the input in it."""
    text = (
        f"first malformed {MALFORMED_SENTINEL}\n"
        f"second malformed {MALFORMED_SENTINEL}\n"
        f"third malformed {MALFORMED_SENTINEL}\n" + SHUTDOWN_LINE
    )
    channel, _, requested = _channel(text)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        channel.run()

    assert requested == [1]
    reports = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(reports) == 1
    assert "malformed" in reports[0].getMessage().lower()
    assert MALFORMED_SENTINEL not in caplog.text


def test_an_overlong_physical_line_is_discarded_whole_before_the_next_record() -> None:
    """The limit bounds memory without letting one long line become two short ones."""
    overlong = "x" * (MAX_CONTROL_LINE_CHARACTERS + 64)
    channel, _, requested = _channel(overlong + "\n" + SHUTDOWN_LINE)

    channel.run()

    assert requested == [1]


def test_an_overlong_line_at_eof_is_supervisor_loss() -> None:
    channel, _, requested = _channel("x" * (MAX_CONTROL_LINE_CHARACTERS + 64))

    channel.run()

    assert requested == [1]


def test_the_channel_writes_nothing_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """Whatever arrives, the protocol channel stays empty: control cannot corrupt readiness."""
    channel, _, requested = _channel("not a record\n" + SHUTDOWN_LINE)

    channel.run()

    assert requested == [1]
    assert capsys.readouterr().out == ""


class _UnreadableStream:
    """A stream that refuses to be read, the way a closed or detached one does."""

    def readline(self, limit: int = -1, /) -> str:
        raise ValueError("I/O operation on closed file")


def test_a_stream_that_cannot_be_read_is_supervisor_loss() -> None:
    requested: list[int] = []
    channel = ControlChannel(_UnreadableStream(), on_shutdown=lambda: requested.append(1))

    channel.run()

    assert requested == [1]


def test_start_reads_on_a_daemon_thread_and_returns_without_blocking() -> None:
    """The transport: a sidecar that is just serving is not blocked on a channel thread."""
    requested = threading.Event()
    channel = ControlChannel(
        io.StringIO(SHUTDOWN_LINE),
        on_shutdown=requested.set,
    )

    channel.start()

    assert requested.wait(timeout=5), "the channel thread must deliver the record"


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in SECRET_VARIABLES:
        environment.pop(name, None)
    environment.update(session_environment())
    return environment


def _command() -> list[str]:
    return [sys.executable, "-m", "dynamisbench", "api", "serve"]


def _readiness(child: subprocess.Popen[str]) -> str:
    """The sidecar's first stdout line, read with a deadline so a hung child fails the test."""
    assert child.stdout is not None
    stdout = child.stdout
    announced: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        announced.put(stdout.readline())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(READINESS_TIMEOUT_SECONDS)
    if announced.empty():
        child.kill()
        raise AssertionError(
            "the sidecar announced no port; stderr was "
            f"{child.stderr.read() if child.stderr is not None else ''!r}"
        )
    return announced.get_nowait()


def _answered(port: int) -> int | None:
    """The status the port answers with, or ``None`` if nothing answered at all."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "GET", "/api/v1/health", headers={"Authorization": f"Bearer {CREDENTIAL}"}
        )
        response = connection.getresponse()
        response.read()
        return int(response.status)
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()


@contextlib.contextmanager
def _running_sidecar() -> Iterator[tuple[subprocess.Popen[str], int]]:
    """A running sidecar whose stdin is a pipe this test owns, killed if it outlives the test.

    stdout and stderr are deliberately left open at teardown: the child has exited (or been
    killed) and reaped by the time the context is left, so a test can read what it wrote after
    the ``with`` block rather than competing with a live pipe. stdin is closed because a
    parent that keeps its write end open after the test is over is a parent this protocol
    would keep waiting on.
    """
    child = subprocess.Popen(
        _command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(),
    )
    try:
        yield child, Readiness.model_validate_json(_readiness(child)).port
    finally:
        if child.poll() is None:
            child.kill()
        if child.stdin is not None and not child.stdin.closed:
            child.stdin.close()
        child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)


def _send(stream: IO[str] | None, text: str) -> None:
    assert stream is not None
    stream.write(text)
    stream.flush()


def test_the_real_process_accepts_the_exact_record_and_exits_zero() -> None:
    """The supervisor's shutdown path, end to end, on the process's own stdin."""
    with _running_sidecar() as (child, port):
        assert _answered(port) == 200

        _send(child.stdin, SHUTDOWN_LINE)
        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) == int(Exit.CLEAN)

        assert _answered(port) != 200, "the listener must not outlive the process"

    assert child.stdout is not None
    assert child.stdout.read() == "", "stdout carried something other than the handshake"


def test_the_real_process_treats_stdin_eof_after_readiness_as_supervisor_loss() -> None:
    with _running_sidecar() as (child, port):
        assert _answered(port) == 200

        assert child.stdin is not None
        child.stdin.close()

        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) == int(Exit.CLEAN)
        assert _answered(port) != 200

    assert child.stdout is not None
    assert child.stdout.read() == ""


def test_the_real_process_survives_malformed_control_and_then_shuts_down() -> None:
    """A malformed record is neither a command nor a reason to stop serving."""
    malformed = (
        '{"kind":"dynamisbench.api.shutdown","protocol_version":1,'
        f'"note":"{MALFORMED_SENTINEL}"}}\n'
    )
    with _running_sidecar() as (child, port):
        _send(child.stdin, malformed)
        _send(child.stdin, "not json at all\n")
        time.sleep(0.5)
        assert child.poll() is None, "a malformed record must not stop the sidecar"
        assert _answered(port) == 200

        _send(child.stdin, SHUTDOWN_LINE)
        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) == int(Exit.CLEAN)

    assert child.stdout is not None and child.stderr is not None
    written = child.stdout.read() + child.stderr.read()
    assert MALFORMED_SENTINEL not in written, "a diagnostic must not repeat the input"
    assert CREDENTIAL not in written
    assert written.count("Ignoring a malformed API control record") == 1


def test_the_real_process_emits_nothing_on_stdout_after_readiness() -> None:
    """The full exchange — malformed input, then the record — leaves the handshake alone."""
    with _running_sidecar() as (child, _):
        _send(child.stdin, "a malformed record\n")
        _send(child.stdin, SHUTDOWN_LINE)
        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) == int(Exit.CLEAN)

    assert child.stdout is not None
    remainder = child.stdout.read()

    assert remainder == "", f"stdout carried something other than the handshake: {remainder!r}"


def test_the_credential_never_appears_on_any_stream_across_control_paths() -> None:
    """The non-leakage claim, restated for the channel RES-376 adds.

    Both paths are exercised in one process: a malformed record that embeds the real
    credential, and the valid record that ends the session. Neither stream may carry it.
    """
    with _running_sidecar() as (child, port):
        _send(
            child.stdin,
            f'{{"kind":"dynamisbench.api.shutdown","protocol_version":1,"token":"{CREDENTIAL}"}}\n',
        )
        assert _answered(port) == 200
        _send(child.stdin, SHUTDOWN_LINE)
        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) == int(Exit.CLEAN)

    assert child.stdout is not None and child.stderr is not None
    assert CREDENTIAL not in child.stdout.read()
    assert CREDENTIAL not in child.stderr.read()


def test_a_second_record_after_the_first_changes_nothing() -> None:
    """After the first valid record the channel is done; a second one changes nothing.

    Sent back to back, both on one write, the first record ends the session. There is no
    acknowledged/ignored distinction and no second command to be found by keeping the pipe
    open: the channel's vocabulary has one word.
    """
    with _running_sidecar() as (child, port):
        _send(child.stdin, SHUTDOWN_LINE + SHUTDOWN_LINE)
        assert child.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS) == int(Exit.CLEAN)
        assert _answered(port) != 200


def test_the_record_carries_no_credential_and_no_state() -> None:
    """The whole record, stated over its own fields, so a future field would fail here."""
    record = ControlRecord(kind=SHUTDOWN_KIND, protocol_version=CONTROL_PROTOCOL_VERSION)

    assert sorted(ControlRecord.model_fields) == ["kind", "protocol_version"]
    serialized = record.model_dump_json()
    assert CREDENTIAL not in serialized
    assert base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=") not in serialized
