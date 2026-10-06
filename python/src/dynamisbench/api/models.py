"""Typed read models for the local application API.

These are the only things the API is allowed to publish about itself, and they are
deliberately *not* the scientific domain model. A domain definition is validated,
immutable scientific authority whose canonical serialisation is hashed into a semantic
digest (ADR-006); an HTTP read model is a presentation of one fact, chosen for a client
and pinned by the API version it appears under. Reusing ``domain.spec.base.DomainModel``
would make every byte of application metadata claim to be frozen authority, and would let
a future client mistake a response for something whose identity has been digested.

``ApiModel`` therefore repeats the frozen, fail-closed base rather than inheriting it:
the two properties are wanted independently here, and sharing one class would make the
distinction invisible.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base class for every model the API publishes.

    ``frozen`` so a response body cannot be mutated after it is built, and
    ``extra="forbid"`` so a field added later is a deliberate, visible addition to a
    versioned schema rather than something a client can rely on by accident.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class HealthStatus(StrEnum):
    """The only health state the application boundary can report.

    A closed vocabulary, because a client reads this to decide whether to retry and a
    free-form status string cannot be compared against anything. It reports that the
    application process is serving its API and nothing else: not a workspace, not an
    engine, not a run, because the application boundary has no authority over any of
    them and must not appear to have assessed them.
    """

    OK = "ok"


class HealthResponse(ApiModel):
    """``GET /api/v1/health`` — the application is serving its versioned API."""

    status: HealthStatus
    application: str
    version: str
    api_version: str


class ApplicationInfoResponse(ApiModel):
    """``GET /api/v1/info`` — the build identity a client needs before anything else.

    Version, and nothing that would have to be looked up in order to be produced: no
    workspace contents, no engine versions, no release inventory. A client that needs
    those asks the layer that owns them, and receives a read model of that layer's own
    authority rather than a live object from it.
    """

    application: str
    version: str
    api_version: str


__all__ = ["ApiModel", "ApplicationInfoResponse", "HealthResponse", "HealthStatus"]
