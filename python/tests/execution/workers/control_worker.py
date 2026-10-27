#!/usr/bin/env python
"""Deterministic, engine-free worker used only to qualify the process contract.

It parses exactly one v1 request, echoes the identities it was given, and states in its
own message that it produced no scientific result. It reads no model, imports no
simulator, writes no file and computes no physical quantity. If this program were ever
mistaken for a MuJoCo execution, the message is the evidence that it is not.
"""

from __future__ import annotations

import json
import sys
from typing import NoReturn

MAX_MESSAGE_BYTES = 1024 * 1024


def _refuse(message: str) -> NoReturn:
    sys.stderr.write(f"control worker: {message}\n")
    raise SystemExit(2)


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES + 1)
    if len(raw) > MAX_MESSAGE_BYTES:
        _refuse("request exceeds the protocol message bound")
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _refuse("request is not one JSON object")
    if not isinstance(request, dict):
        _refuse("request is not one JSON object")

    if request.get("schema_version") != 1 or request.get("protocol_version") != 1:
        _refuse("request is not protocol v1")

    run_id = request.get("run_id")
    fingerprint = request.get("execution_fingerprint")
    environment = request.get("environment")
    adapter = request.get("adapter")
    required = request.get("required_capabilities", [])
    supported = request.get("supported_capabilities", [])
    if not isinstance(run_id, str) or not run_id:
        _refuse("request has no run id")
    if not isinstance(fingerprint, dict):
        _refuse("request has no execution fingerprint")
    if not isinstance(environment, dict) or not isinstance(adapter, dict):
        _refuse("request has no environment or adapter identity")
    if not isinstance(required, list) or not isinstance(supported, list):
        _refuse("request capabilities are not lists")
    if adapter.get("capabilities") != supported:
        _refuse("request support set is not the adapter advertisement")
    if not set(required).issubset(set(supported)):
        _refuse("request requires a capability the adapter does not support")
    if request.get("staging_locator") is None:
        _refuse("request has no controlled staging locator")

    response = {
        "adapter": adapter,
        "environment": environment,
        "execution_fingerprint": fingerprint,
        "message": "engine-free control case completed; no scientific result",
        "protocol_version": 1,
        "run_id": run_id,
        "schema_version": 1,
        "status": "completed",
    }
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
