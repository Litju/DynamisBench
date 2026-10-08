"""The private control channel: one shutdown record, one EOF, and nothing else.

Architecture §13 and RES-376 add a third stream to the sidecar's stdio contract. stdout is the
machine-readable startup handshake, stderr is diagnostics, and stdin — unused until now —
becomes the private parent→sidecar channel *after readiness*. This module is that channel, and
it is deliberately the smallest thing that can be one: a closed record model with exactly two
fields and exactly one accepted value of each.

Three properties are load-bearing:

* **The record is not a command language.** :class:`ControlRecord` is ``extra="forbid"`` and
  ``strict``, and its two fields are literal-typed, so there is no field whose value selects
  behaviour. A record that is not exactly ``{"kind":"dynamisbench.api.shutdown",
  "protocol_version":1}`` is not interpreted, not partially honoured, and never becomes an
  alternate command: it is refused as a whole and the channel keeps listening for the one
  record that is valid. Nothing received here is ever executed, echoed, or turned into an
  operation of its own.
* **EOF is supervisor loss.** The parent owns the write end. When it closes stdin — because it
  is shutting the session down, or because it died — a blocked read returns empty, and the
  sidecar treats that the same as an explicit shutdown: a sidecar whose supervisor is gone has
  no reason to keep serving. There is no third state to be stuck in.
* **Diagnostics are bounded, and the protocol channel stays clean.** A malformed record is
  reported at most once, to stderr only, and the report deliberately repeats none of the
  record's content — the parent's control input may contain whatever a buggy parent put there,
  and a diagnostic that echoed it would be a leak path with no upside. Nothing this module does
  can write to stdout, so control input cannot corrupt the readiness line or produce anything a
  supervisor would parse as one.

The reader runs on a daemon thread rather than in the event loop because the stream it blocks
on is an ordinary pipe: a thread can wait on it without the server's event loop being involved,
and it dies with the process if the sidecar shuts down for some other reason first.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

SHUTDOWN_KIND = "dynamisbench.api.shutdown"
"""The one record kind protocol v1 accepts, and the whole vocabulary."""

CONTROL_PROTOCOL_VERSION = 1
"""The version of this channel's record shape, moving independently of the API version."""

MAX_CONTROL_LINE_CHARACTERS = 4096
"""The longest physical line this channel will hold in memory.

A malformed or hostile parent should not be able to make the sidecar allocate without bound,
and the valid record is smaller than this by two orders of magnitude. A longer physical line is
read to its newline and discarded rather than buffered whole.
"""

logger = logging.getLogger("uvicorn.error")
"""Uvicorn's error logger, so diagnostics land on stderr under the configuration that owns it."""


class ControlRecord(BaseModel):
    """The one control record, as a closed shape with no free-form fields.

    Two fields, both required, both literal: there is no value in this record that could select
    another behaviour if the model were ever extended carelessly. ``strict`` so that
    ``"protocol_version": "1"`` is refused rather than coerced — a supervisor and a sidecar
    that disagree about the version should find out, not have the disagreement papered over.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["dynamisbench.api.shutdown"]
    protocol_version: Literal[1]

    @field_validator("protocol_version", mode="before")
    @classmethod
    def _json_integer(cls, value: object) -> object:
        """Refuse a version that is merely *equal* to 1.

        ``strict`` alone does not close this: in JSON mode pydantic coerces ``1.0`` and
        ``true`` to the integer 1 before the literal is compared, so a record that carried the
        wrong JSON type would be read as though it had carried the right one. A version is an
        integer or it is not this protocol.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("protocol_version must be a JSON integer")
        return value


def parse_control_record(line: str) -> ControlRecord | None:
    """Parse one line as the control record, or return ``None`` for anything else.

    ``None`` is the whole failure surface — there is no exception a caller must distinguish,
    because the caller's response to every invalid input is the same: report at most once and
    keep reading. The record's content is never included in the result or in any error, so a
    malformed line cannot carry information out of this function.
    """
    try:
        return ControlRecord.model_validate_json(line)
    except ValidationError:
        return None


class LineReader(Protocol):
    """The one operation the control channel needs from its stream.

    A protocol rather than ``IO[str]`` so that the channel is testable with a stream that is
    not a file — and so that the channel's dependency on its input is stated as exactly one
    method rather than as the whole file interface it does not use.
    """

    def readline(self, limit: int = -1, /) -> str: ...


class ControlChannel:
    """Read the parent's control records until it asks for shutdown or is gone.

    One instance per sidecar session, started only after readiness. :meth:`run` is the whole
    state machine and is synchronous on purpose: it can be driven from a test with an ordinary
    in-memory stream, and the thread below is a transport detail rather than part of the
    protocol.
    """

    def __init__(self, stream: LineReader, on_shutdown: Callable[[], None]) -> None:
        self._stream = stream
        self._on_shutdown = on_shutdown
        self._diagnosed = False

    def start(self) -> None:
        """Read on a daemon thread, so a blocked read cannot outlive the process."""
        threading.Thread(
            target=self.run,
            name="dynamisbench-api-control",
            daemon=True,
        ).start()

    def run(self) -> None:
        """Read until shutdown is requested, returning exactly once.

        A valid record and an EOF both request shutdown and both end the loop; the loop also
        ends when the stream itself becomes unreadable, because that is the same situation seen
        from a different angle — the parent is no longer talking to this process.
        """
        while True:
            line = self._readline()
            if line is None:
                self._on_shutdown()
                return
            if line == "":
                self._on_shutdown()
                return
            if not line.endswith("\n"):
                if not self._discard_to_newline():
                    self._on_shutdown()
                    return
                self._diagnose()
                continue
            if parse_control_record(line) is None:
                self._diagnose()
                continue
            self._on_shutdown()
            return

    def _readline(self) -> str | None:
        """One line, or ``None`` when the stream cannot be read at all.

        An unreadable stream is not distinguishable, for this protocol's purposes, from one
        that has ended: both mean the parent cannot be heard from again.
        """
        try:
            return self._stream.readline(MAX_CONTROL_LINE_CHARACTERS)
        except (OSError, ValueError):
            return None

    def _discard_to_newline(self) -> bool:
        """Drop the rest of an overlong physical line, reporting whether one was found.

        ``readline(limit)`` returns a partial line when the physical line is longer than the
        limit, so the remainder has to be consumed or it would be misread as the start of a new
        record. Returning ``False`` means the stream ended mid-line.
        """
        while True:
            chunk = self._readline()
            if chunk is None or chunk == "":
                return False
            if chunk.endswith("\n"):
                return True

    def _diagnose(self) -> None:
        """Report the first malformed record, once, without repeating any of it."""
        if self._diagnosed:
            return
        self._diagnosed = True
        logger.warning(
            "Ignoring a malformed API control record on stdin; "
            "the record's content is not reported."
        )


__all__ = [
    "CONTROL_PROTOCOL_VERSION",
    "MAX_CONTROL_LINE_CHARACTERS",
    "SHUTDOWN_KIND",
    "ControlChannel",
    "ControlRecord",
    "LineReader",
    "parse_control_record",
]
