#!/usr/bin/env python
"""A test-only worker that misbehaves in exactly one declared way.

The mode is a *fixed command argument* supplied by the environment manifest, not a field
of the request. That keeps the misbehaviour out of the production protocol: a run input
cannot ask a worker to sleep, crash or flood.

Modes: ``sleep``, ``crash``, ``flood``, ``invalid``, ``wrong-identity``, ``failed``,
``stderr``. Every mode still reads and validates the request first, so a failure is a
failure of the declared behaviour rather than of request parsing.
"""

from __future__ import annotations

import json
import sys
import time
from typing import NoReturn

MAX_MESSAGE_BYTES = 1024 * 1024
MODES = ("sleep", "crash", "flood", "invalid", "wrong-identity", "failed", "stderr")


def _refuse(message: str) -> NoReturn:
    sys.stderr.write(f"misbehaving worker: {message}\n")
    raise SystemExit(2)


def _request() -> dict:
    raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES + 1)
    if len(raw) > MAX_MESSAGE_BYTES:
        _refuse("request exceeds the protocol message bound")
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _refuse("request is not one JSON object")
    if not isinstance(request, dict) or request.get("protocol_version") != 1:
        _refuse("request is not protocol v1")
    return request


def _response(request: dict, *, status: str = "completed", message: str | None = None) -> dict:
    return {
        "adapter": request["adapter"],
        "environment": request["environment"],
        "execution_fingerprint": request["execution_fingerprint"],
        "message": message,
        "protocol_version": 1,
        "run_id": request["run_id"],
        "schema_version": 1,
        "status": status,
    }


def _write(response: dict) -> None:
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "completed"
    if mode not in MODES and mode != "completed":
        _refuse(f"unknown mode {mode!r}")
    request = _request()

    if mode == "sleep":
        time.sleep(60)
        return 0
    if mode == "crash":
        sys.stderr.write("misbehaving worker: deliberate abnormal exit\n")
        sys.stderr.flush()
        raise SystemExit(7)
    if mode == "flood":
        sys.stdout.write("x" * (MAX_MESSAGE_BYTES + 4096))
        sys.stdout.flush()
        return 0
    if mode == "invalid":
        sys.stdout.write("{this is not a worker response}\n")
        sys.stdout.flush()
        return 0
    if mode == "wrong-identity":
        response = _response(request)
        response["run_id"] = "run-other"
        _write(response)
        return 0
    if mode == "failed":
        _write(_response(request, status="failed", message="control worker reported a failure"))
        return 0
    if mode == "stderr":
        sys.stderr.write("e" * 4096)
        sys.stderr.flush()
        _write(_response(request))
        return 0

    _write(_response(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
