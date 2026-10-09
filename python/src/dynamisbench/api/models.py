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

**What a read model is not allowed to carry.** No absolute path, no drive letter, no
workspace root, no credential, and no rejected input value. Every field a workspace read
model publishes is either a portable name, a bounded status, or a diagnostic chosen from a
closed vocabulary — because a model that could hold a path would be a model that eventually
did, and the client is a browser (ADR-022). A semantic digest is in by name only: it is a
64-character hex string and the algorithm that produced it, and a client compares it rather
than decoding it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dynamisbench.workspace.authority import SourceCategory
from dynamisbench.workspace.source_authority import AuthoringFormat, ValidationStatus


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


__all__ = [
    "ApiModel",
    "ApplicationInfoResponse",
    "ArtifactDiagnostic",
    "ArtifactInspectionResponse",
    "ArtifactSummary",
    "ArtifactSummaryList",
    "AuthoringFormat",
    "HealthResponse",
    "HealthStatus",
    "OpenWorkspaceRequest",
    "OpenWorkspaceResponse",
    "SemanticDigestView",
    "SourceCategoryStatus",
    "ValidationStatus",
    "WorkspaceDiscoveryResponse",
]


class SemanticDigestView(ApiModel):
    """The SHA-256 digest of a validated definition's meaning, as recorded reference.

    The algorithm travels with the hex on purpose (ADR-006): comparing two digests without
    knowing which algorithm produced them is not a comparison. Nothing here lets a client
    decode the digest into a path, a name, or the bytes it was taken over.
    """

    algorithm: Literal["sha256"]
    hex: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactDiagnostic(ApiModel):
    """One bounded reason a source document is not valid authority.

    A closed ``code``, a fixed ``message``, and optionally where in the document and which
    validation category refused it. There is no field for the rejected value, the rejected
    text, or an absolute path — the record is structurally incapable of carrying one, which
    is what lets it be served to a browser (ADR-022).
    """

    code: str
    message: str
    reference: str | None = Field(default=None, max_length=256)
    location: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=64)


class ArtifactSummary(ApiModel):
    """What one source-authority artifact is, in portable terms.

    ``artifact_id`` is the opaque handle this application minted for it; ``logical_reference``
    is the document's portable name inside the source root, which is identical in two
    workspaces at different absolute paths. The two are deliberately different things: the
    reference says *where in the layout* an artifact is, and the identifier says *which of
    this application's handles* names it.

    Identity and digest are present only for a valid artifact, because there is nothing else
    for them to say. A client that sees ``identifier`` is told a human name; a client that
    sees ``semantic_digest`` is told what the artifact *means*, in the one form the meaning
    can be compared in across machines.
    """

    artifact_id: str
    category: SourceCategory
    kind: str
    logical_reference: str
    authoring_format: AuthoringFormat
    validation_status: ValidationStatus
    identifier: str | None = None
    version: str | None = None
    semantic_digest: SemanticDigestView | None = None
    diagnostics: tuple[ArtifactDiagnostic, ...] = ()


class ArtifactSummaryList(ApiModel):
    """A discovery response's list of artifacts, bounded and in the walk's own order.

    ``truncated`` exists because a discovery that silently returned the first N artifacts
    would read as a complete list. The order is the documented one — the portable logical
    reference — so two calls agree and a client can diff them.
    """

    artifacts: tuple[ArtifactSummary, ...]
    truncated: bool


class SourceCategoryStatus(ApiModel):
    """Whether one declared source category currently exists — and nothing about where.

    A category's directory is a declared location, so reporting whether it exists tells a
    client whether this workspace has been given authority in that category at all. The
    location itself is operational state and is absent by design.
    """

    category: SourceCategory
    exists: bool


class OpenWorkspaceRequest(ApiModel):
    """The two declared roots of an existing workspace.

    The only request in this API that carries absolute operational paths, and only because
    this is the explicit root-selection operation: a person running the workbench says which
    repository and which evidence directory to use. Everything after this identifies the
    workspace by the opaque identifier handed back, so the roots appear in exactly one
    request and never in a response.
    """

    source_root: str
    evidence_root: str


class OpenWorkspaceResponse(ApiModel):
    """The opaque identifier to use, plus a read-only description of the opened workspace.

    ``evidence_inside_source`` is the one directional fact the workspace layer reports about
    the roots: a repository keeping its evidence in a gitignored subtree is legitimate, but
    it means a broad clean or a careless ignore rule can take the evidence with it. Not
    echoed: either root, in any form, including the resolved directory name.
    """

    workspace_id: str
    evidence_inside_source: bool
    source_categories: tuple[SourceCategoryStatus, ...]


class WorkspaceDiscoveryResponse(ApiModel):
    """One read-only pass over a workspace's source authority.

    Categories come first so a client can see which declared locations this workspace has
    at all; artifacts follow, in the documented order; issues are the bounded structural
    findings — a directory that is not a declared kind, a link that would leave the root,
    a document whose suffix declares no authoring format. An issue names a portable
    reference and says which of the closed codes it hit, and never a path.
    """

    workspace_id: str
    categories: tuple[SourceCategoryStatus, ...] = ()
    artifacts: ArtifactSummaryList
    issues: tuple[ArtifactDiagnostic, ...] = ()


class ArtifactInspectionResponse(ApiModel):
    """One artifact, re-read and revalidated just now, plus its validated read model.

    Everything in an artifact summary, and ``content`` for a valid one: the validated
    domain model serialised in JSON mode. That is *not* the raw source file, and the
    difference is the point — the client receives meaning that has passed through
    validation, in a form a future schema version can change, and never the authoring text
    it was written in.

    Inspection re-reads on every call, so a file edited between two responses changes this
    response. That is what makes memory disposable.
    """

    artifact_id: str
    category: SourceCategory
    kind: str
    logical_reference: str
    authoring_format: AuthoringFormat
    validation_status: ValidationStatus
    identifier: str | None = None
    version: str | None = None
    semantic_digest: SemanticDigestView | None = None
    diagnostics: tuple[ArtifactDiagnostic, ...] = ()
    content: dict[str, Any] | None = None
