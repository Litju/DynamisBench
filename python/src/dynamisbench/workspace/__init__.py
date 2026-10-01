"""The local workspace: where authority lives, and where everything else does not.

A DynamisBench workspace is deliberately boring. It is two independent roots — a
*source* root of version-controlled scientific specifications, and an *evidence* root of
everything execution produces — plus an optional user state root that belongs to neither,
and a declared location for each class of state those roots hold. There is no database,
no control plane, and no file whose contents are required to know what the workspace
means (ADR-004). Opening one reads two directories; nothing more.

The separation is the feature. Source authority and sealed evidence are the only classes
whose loss is a loss of science. Staging is mutable and non-authoritative and is not
disposable, because whether an interrupted execution is preserved or discarded is a
scientific decision (RES-231). Derived query state, cache, and scratch space are
disposable, so deleting them cannot destroy meaning and rebuilding them recovers all of
it (ADR-010). Product preferences are a separate persistence class entirely and are kept
outside scientific authority, so a theme setting can never be filed as evidence and never
contributes to an artifact's identity (ADR-021).

**Moving a workspace must not change any artifact's identity.** A semantic digest is a
function of validated meaning, and a file's location is not meaning. This package
therefore keeps two things apart on purpose: a :class:`LogicalReference`, which is a
portable name with no machine-specific content and is stable across relocation, and an
absolute ``Path``, which is operational state. Absolute paths, drive letters, UNC
prefixes, home directories, usernames, and the name of the workspace directory are never
hashed and never reach :func:`dynamisbench.identity.semantic_sha256`.

Three modules, in the order they build on each other:

* :mod:`dynamisbench.workspace.authority` — the persistence classes, their authority
  contract, the declared directory layout, and the errors. Pure data; touches nothing.
* :mod:`dynamisbench.workspace.workspace` — roots, declared locations, portable
  references, and the read-only open of an existing workspace.
* :mod:`dynamisbench.workspace.paths` — resolving a workspace-relative reference to a
  path that is provably inside its root, failing closed on every escape it can name.

The boundary between the second and third is load-bearing. A caller may ask for any
declared location and read its description, but the only way to obtain a path it will
open is :meth:`Workspace.resolve`, which has already proved containment. That is what
keeps this abstraction from becoming the unrestricted filesystem access the local API is
forbidden to expose (Architecture section 13).

This package implements the *location and boundary* only. Manifests, checksums, run
sealing, atomic staging-to-sealed promotion, and evidence verification belong to DB-1.5
(RES-231), which builds on these locations; there is no DuckDB here, because a rebuildable
projection needs a boundary before it needs a database.
"""

from dynamisbench.workspace.authority import (
    CLASS_LOCATION_SEGMENTS,
    CLASS_SEMANTICS,
    INITIALISED_CLASSES,
    SOURCE_CATEGORY_SEGMENTS,
    ClassSemantics,
    PersistenceClass,
    SourceCategory,
    WorkspaceError,
    WorkspaceRootError,
)
from dynamisbench.workspace.workspace import (
    LogicalReference,
    Workspace,
    WorkspaceLocation,
    WorkspaceReport,
    WorkspaceRoots,
    open_workspace,
)

__all__ = [
    "CLASS_LOCATION_SEGMENTS",
    "CLASS_SEMANTICS",
    "INITIALISED_CLASSES",
    "SOURCE_CATEGORY_SEGMENTS",
    "ClassSemantics",
    "LogicalReference",
    "PersistenceClass",
    "SourceCategory",
    "Workspace",
    "WorkspaceError",
    "WorkspaceLocation",
    "WorkspaceReport",
    "WorkspaceRootError",
    "WorkspaceRoots",
    "open_workspace",
]
