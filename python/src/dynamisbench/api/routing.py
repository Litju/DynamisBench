"""The versioned HTTP namespace of the local application API.

The version lives in exactly one place. ``API_VERSION`` names it and ``API_V1_PREFIX``
is *derived* from it, so a second version is a second router built the same way rather
than a second hand-written ``"/api/v1"`` scattered through handler decorators where a
typo would surface as a silently different public route.

This module owns the two facts the application boundary is allowed to publish about
itself — the product name and the API version it is speaking — and nothing else. It
reaches no scientific layer: no benchmark release, identity, workspace, evidence, plan,
execution, or simulator (ADR-016, ADR-017). A handler that needed one of those would be
reaching past the boundary it is supposed to describe, so those facts arrive as
parameters from whichever layer owns them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from dynamisbench import __version__

APPLICATION_NAME = "DynamisBench"
"""The product this API serves.

Presentation metadata, owned here rather than imported: the package root publishes the
installed distribution's ``__version__``, which is the one fact that must not be
duplicated, and a name is not something a client can verify.
"""

API_VERSION = "v1"
"""The API version every route in this boundary is published under.

REST/JSON carries commands, metadata and small structured records (ADR-019). A client
that has to be able to talk to a future remote API needs the version to be part of the
path, not a header it may forget.
"""

API_V1_PREFIX = f"/api/{API_VERSION}"
"""The versioned namespace, derived from :data:`API_VERSION` rather than restated."""

v1_router = APIRouter(prefix=API_V1_PREFIX)
"""Every route published under :data:`API_V1_PREFIX`."""


@v1_router.get("/health")
def read_health() -> dict[str, Any]:
    """Report that the application process is serving its versioned API.

    A statement about this process only. It deliberately touches no workspace, no engine
    and no run, because the application boundary has no authority over any of them and a
    health check that could fail on their account would report a failure it is not
    entitled to explain.
    """
    return {
        "status": "ok",
        "application": APPLICATION_NAME,
        "version": __version__,
        "api_version": API_VERSION,
    }


@v1_router.get("/info")
def read_info() -> dict[str, Any]:
    """Report the build identity a client needs before it asks for anything else."""
    return {
        "application": APPLICATION_NAME,
        "version": __version__,
        "api_version": API_VERSION,
    }


__all__ = ["API_VERSION", "API_V1_PREFIX", "APPLICATION_NAME", "read_health", "read_info"]
