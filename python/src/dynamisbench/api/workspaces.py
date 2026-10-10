"""The versioned workspace routes: open, discover, inspect — and nothing else.

These three routes are the whole of what this boundary will say about a workspace's source
authority, and what they deliberately do not do is as important as what they do. There is no
route that accepts a path, a logical reference, or a file name and returns its contents. After
``POST /api/v1/workspaces/open``, a client identifies authority only by the opaque
identifiers this application handed it, and the only thing an identifier can resolve to is a
locator that was already recorded — not something a client can construct.

Each route is a *view* of the workspace, produced by one read:

* **open** calls :func:`open_workspace`, which reads two directories and changes nothing. It
  never calls ``initialize_workspace``, so opening a workspace that does not exist cannot be
  the thing that creates it.
* **discovery** rescans the filesystem on every call, because a workspace is a live
  repository and a cached list would be a list that had already stopped being true.
* **inspection** resolves an opaque locator through
  :meth:`Workspace.resolve_source`, re-reads the current bytes, re-parses, re-validates, and
  takes the digest of the *current* meaning. Nothing validated is remembered between
  requests, so memory cannot stand in for the file.

**Every failure is bounded and echoes nothing.** An unknown workspace identifier, an unknown
artifact identifier, and an artifact identifier from another workspace are the same refusal,
because distinguishing them would tell a caller which identifiers are real. Invalid roots
are one fixed refusal with no path in it, because the root that was refused is exactly what
a client probing for a filesystem layout is trying to learn.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Request

from dynamisbench.api.errors import ErrorResponse, refusal_responses
from dynamisbench.api.models import (
    MAX_DIAGNOSTIC_REFERENCE_LENGTH,
    ArtifactDiagnostic,
    ArtifactInspectionResponse,
    ArtifactSummary,
    ArtifactSummaryList,
    OpenWorkspaceRequest,
    OpenWorkspaceResponse,
    SemanticDigestView,
    SourceCategoryStatus,
    WorkspaceDiscoveryResponse,
)
from dynamisbench.api.workspace_registry import WorkspaceRegistry
from dynamisbench.workspace import SourceCategory
from dynamisbench.workspace.authority import WorkspaceError
from dynamisbench.workspace.discovery import DiscoveryIssue, SourceDiscovery, discover_sources
from dynamisbench.workspace.source_authority import (
    SourceDiagnostic,
    SourceInspection,
    ValidationStatus,
    inspect_locator,
)

__all__ = [
    "ARTIFACT_NOT_FOUND",
    "WORKSPACE_NOT_FOUND",
    "WORKSPACE_OPEN_REFUSED",
    "workspace_router",
]

ARTIFACT_NOT_FOUND = "No artifact is registered under that identifier."
"""The one text an unknown artifact identifier ever carries.

Fixed, and the same for an identifier this workspace never minted and for one invented
outright. A message that varied would be a message that distinguished them, and the
distinction is the information a client probing for authority would want.
"""

WORKSPACE_NOT_FOUND = "No workspace is registered under that identifier."
"""The one text an unknown workspace identifier ever carries.

An identifier from a previous application instance arrives here for the same reason as one
that was never minted, which is the restart guarantee stated as a refusal.
"""

WORKSPACE_OPEN_REFUSED = "The declared workspace roots could not be opened."
"""The one text a refused workspace open ever carries.

Fixed and root-free. The refused root is the thing a caller probing the filesystem is
trying to learn, so it is not reported — not as a path, not as a resolved name, and not as
part of the underlying error's message, which is discarded.
"""

workspace_router = APIRouter()
"""The workspace routes, published under :data:`API_V1_PREFIX` by the application factory.

Built without a prefix so that the version namespace still has exactly one source of
truth — ``routing.API_V1_PREFIX`` — and a second version is a second prefix applied there.
"""


def _registry(request: Request) -> WorkspaceRegistry:
    """The application's registry of open workspaces, or a refusal explaining there is none.

    Read from ``app.state`` rather than from a module-level variable, because two
    applications built in one process each have their own. A missing one is an internal
    error rather than a client mistake: it means the registry was not created by the
    factory that built this application.
    """
    registry = getattr(request.app.state, "workspace_registry", None)
    if not isinstance(registry, WorkspaceRegistry):
        raise HTTPException(status_code=500, detail="This application has no workspace registry.")
    return registry


RegisteredWorkspace = Annotated[WorkspaceRegistry, Depends(_registry)]
"""A route parameter that resolves the application's registry, or refuses.

Resolved through the dependency rather than read inside each handler, so a route that
forgets to declare it cannot silently start against an empty store."""


def _summary(artifact_id: str, inspection: SourceInspection) -> ArtifactSummary:
    """Assemble one artifact read model from one inspection, with nothing else in it.

    Assembly rather than direct construction, so the two routes that publish a summary
    cannot drift apart, and so the "all three of these or none" rule about identity,
    version and digest exists exactly once. The rule is structural: validity decides all
    three fields at the same time, and a caller that gets a digest always got the human
    identity with it (ADR-006).
    """
    locator = inspection.locator
    identity = inspection.identity if inspection.valid else None
    return ArtifactSummary(
        artifact_id=artifact_id,
        category=locator.category,
        kind=locator.kind,
        logical_reference=locator.logical_reference,
        authoring_format=inspection.authoring_format,
        validation_status=ValidationStatus.VALID if inspection.valid else ValidationStatus.INVALID,
        identifier=identity.identifier if identity is not None else None,
        version=identity.version if identity is not None else None,
        semantic_digest=(
            None
            if identity is None
            else SemanticDigestView(algorithm="sha256", hex=identity.digest.hex)
        ),
        diagnostics=tuple(_diagnostic(entry) for entry in inspection.diagnostics),
    )


@workspace_router.post(
    "/workspaces/open",
    response_model=OpenWorkspaceResponse,
    responses=refusal_responses(
        {400: {"model": ErrorResponse, "description": WORKSPACE_OPEN_REFUSED}}
    ),
)
def open_workspace_route(
    request: OpenWorkspaceRequest,
    registry: RegisteredWorkspace,
) -> OpenWorkspaceResponse:
    """Open an existing workspace and return the identifier the API will know it by.

    The only route that accepts absolute operational paths, and the only one that accepts
    them *because* the root-selection decision is the user's: which repository is authority
    and which directory is evidence are both configuration choices, not names this
    application can invent.

    :raises HTTPException: 400 with :data:`WORKSPACE_OPEN_REFUSED` for roots that do not
        describe an existing workspace. The underlying message is discarded, because it
        would echo the path that was refused.
    """
    try:
        registration = registry.open(request.source_root, request.evidence_root)
    except WorkspaceError:
        raise HTTPException(status_code=400, detail=WORKSPACE_OPEN_REFUSED) from None

    workspace = registration.workspace
    report = workspace.inspect()
    return OpenWorkspaceResponse(
        workspace_id=registration.identifier,
        evidence_inside_source=workspace.evidence_is_inside_source,
        source_categories=tuple(
            SourceCategoryStatus(category=category, exists=category in report.existing_sources)
            for category in SourceCategory
        ),
    )


@workspace_router.get(
    "/workspaces/{workspace_id}/artifacts",
    response_model=WorkspaceDiscoveryResponse,
    responses=refusal_responses(
        {404: {"model": ErrorResponse, "description": WORKSPACE_NOT_FOUND}}
    ),
)
def read_artifacts(
    workspace_id: str,
    registry: RegisteredWorkspace,
) -> WorkspaceDiscoveryResponse:
    """Rescan a workspace's source categories and describe what they currently hold.

    Scans on every call rather than reporting what a previous call found, because a
    workspace is a live repository and a stale list would answer a question that had already
    stopped being the one asked.

    :raises HTTPException: 404 with :data:`WORKSPACE_NOT_FOUND`.
    """
    try:
        registered = registry.registration(workspace_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=WORKSPACE_NOT_FOUND) from None

    workspace = registered.workspace
    discovery = discover_sources(workspace)
    identifiers = registry.record_discovery(workspace_id, discovery.locators)

    summaries: list[ArtifactSummary] = []
    for artifact_id, locator in zip(identifiers, discovery.locators, strict=True):
        inspection = inspect_locator(workspace, locator)
        summaries.append(_summary(artifact_id=artifact_id, inspection=inspection))

    return WorkspaceDiscoveryResponse(
        workspace_id=workspace_id,
        categories=_category_statuses(discovery),
        artifacts=ArtifactSummaryList(artifacts=tuple(summaries)),
        issues=tuple(_discovery_diagnostic(issue) for issue in discovery.issues),
        issues_truncated=discovery.issues_truncated,
    )


@workspace_router.get(
    "/workspaces/{workspace_id}/artifacts/{artifact_id}",
    response_model=ArtifactInspectionResponse,
    responses=refusal_responses({404: {"model": ErrorResponse, "description": ARTIFACT_NOT_FOUND}}),
)
def read_artifact(
    workspace_id: str,
    artifact_id: str,
    registry: RegisteredWorkspace,
) -> ArtifactInspectionResponse:
    """Re-read and revalidate the current bytes of one located artifact.

    The route resolves an opaque locator, hands it to the workspace to be resolved to a
    path proved inside the source root, reads those bytes now, and validates and digests
    what is there now. It does this every time; nothing validated is retained between calls,
    so the answer a client gets is the answer the file would give.

    No route in this application accepts a path, a logical reference, or a file name, which
    is why this handler has no parameter that could carry one.

    :raises HTTPException: 404 with :data:`ARTIFACT_NOT_FOUND` for an artifact identifier
        this workspace did not mint — including one stolen from another workspace.
    """
    try:
        workspace, locator = registry.artifact(workspace_id, artifact_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=ARTIFACT_NOT_FOUND) from None

    inspection = inspect_locator(workspace, locator)
    summary = _summary(artifact_id=artifact_id, inspection=inspection)

    return ArtifactInspectionResponse(
        **summary.model_dump(),
        content=inspection.content if inspection.valid else None,
    )


_REFERENCE_OVERFLOW_MARKER: Final = "\u2026"
"""What a bounded reference ends with, so "this name was longer" is visible.

A single character rather than an ellipsis of three: the prefix is what carries the
portable location, and every character spent on the marker is one taken from it.
"""


def _bounded_reference(reference: str) -> str:
    """``reference`` shortened to the ceiling a portable logical reference may reach.

    Called on a discovery reference, which unlike a locator's is not guaranteed to be one
    the reference language will express: an unsupported file sitting in a declared kind
    directory is reported whatever it is called, and a filesystem will happily store a
    name longer than any portable reference. Rounding it here — rather than letting the
    read model refuse it — keeps the finding published and the request successful.

    The result is the longest prefix of the name that fits, with the marker appended in
    place of what was cut. It stays a prefix of the same relative name, so it cannot
    become an absolute path, a drive, or a UNC or extended-length prefix, and nothing is
    read from the filesystem to produce it.
    """
    if len(reference) <= MAX_DIAGNOSTIC_REFERENCE_LENGTH:
        return reference
    return reference[: MAX_DIAGNOSTIC_REFERENCE_LENGTH - len(_REFERENCE_OVERFLOW_MARKER)] + (
        _REFERENCE_OVERFLOW_MARKER
    )


def _discovery_diagnostic(issue: DiscoveryIssue) -> ArtifactDiagnostic:
    """One structural finding, with the portable reference it was found at.

    The reference is the entry's portable logical name, or the declared name of the
    directory or category it sits in. It is never an absolute path, and the target a
    refused link pointed at is never reported at all — not in the reference, not in the
    message, and not in a second field: there is nothing there for it to be.

    ``reference`` is bounded to the workspace's own logical-reference ceiling before the
    model is constructed rather than by the model's field. Discovery reports entries the
    reference language never promised to express — an unsupported file name is not a
    reference anything will resolve — so a name longer than that ceiling has to be
    rounded deliberately, here, or it turns a successful discovery into a failed response.
    The bound is a prefix plus a marker, so the published text stays the portable name it
    came from and never becomes a filesystem path.
    """
    return ArtifactDiagnostic(
        code=issue.diagnostic.code,
        message=str(issue.diagnostic.message),
        reference=_bounded_reference(issue.reference),
        location=issue.diagnostic.location,
        category=issue.diagnostic.category,
    )


def _category_statuses(discovery: SourceDiscovery) -> tuple[SourceCategoryStatus, ...]:
    """The categories a discovery walked, restated as the API's own read model.

    Restated rather than passed through, for the same reason a diagnostic is: the read
    model is the API's versioned surface and the workspace's record is not. If the
    workspace's category status ever grows a field, adding it here is a decision about the
    API version, which is where the decision belongs.
    """
    return tuple(
        SourceCategoryStatus(category=status.category, exists=status.exists)
        for status in discovery.categories
    )


def _diagnostic(entry: SourceDiagnostic) -> ArtifactDiagnostic:
    """Map one workspace diagnostic to its read model.

    A named function rather than a ``model_validate`` call at each site so that a future
    field added to the workspace's diagnostic has to be added here, where the rule "nothing
    beyond a closed code, a fixed message, a bounded location and a bounded category" is
    applied once and can be read.
    """
    return ArtifactDiagnostic(
        code=entry.code,
        message=str(entry.message),
        location=entry.location,
        category=entry.category,
    )
