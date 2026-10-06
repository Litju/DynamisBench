"""Shared fixtures for the session-security gates.

One credential, one origin list, and the environment mapping that carries them, defined once
so that every gate in this directory is testing the same thing about the same inputs.

:data:`CREDENTIAL` is a literal rather than something generated per run, so a failure
reported against a test can be reproduced exactly and so that a leaked-looking string in a
test report is obviously a fixture. It is not a credential: it is published in this
repository, which is the entire reason a real one can never be.
"""

from __future__ import annotations

import base64
import json

from dynamisbench.api.session import (
    ALLOWED_ORIGINS_VARIABLE,
    SESSION_CREDENTIAL_VARIABLE,
    RuntimeConfiguration,
    runtime_configuration,
)

CREDENTIAL = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
"""A well-formed credential: 32 bytes, unpadded URL-safe base64, 43 ASCII characters."""

ALLOWED_ORIGINS = ("http://tauri.localhost",)
"""The production desktop origin on Windows, as Architecture §13 records it."""

OTHER_ALLOWED_ORIGINS = ("http://localhost:5173",)
"""A development origin, which is only ever accepted because it was supplied explicitly."""


def session_environment(
    credential: str | None = CREDENTIAL,
    origins: tuple[str, ...] | None = ALLOWED_ORIGINS,
) -> dict[str, str]:
    """The environment a desktop session would hand the sidecar."""
    environment: dict[str, str] = {}
    if credential is not None:
        environment[SESSION_CREDENTIAL_VARIABLE] = credential
    if origins is not None:
        environment[ALLOWED_ORIGINS_VARIABLE] = json.dumps(list(origins))
    return environment


def session_configuration(
    credential: str = CREDENTIAL,
    origins: tuple[str, ...] = ALLOWED_ORIGINS,
) -> RuntimeConfiguration:
    """A configuration built the way the server builds one, through the environment."""
    return runtime_configuration(session_environment(credential, origins))


__all__ = [
    "ALLOWED_ORIGINS",
    "CREDENTIAL",
    "OTHER_ALLOWED_ORIGINS",
    "session_configuration",
    "session_environment",
]
