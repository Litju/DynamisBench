"""What kind of state a workspace location holds, and where it is allowed to live.

A DynamisBench workspace is two independent roots — a *source* root holding
version-controlled scientific authority, and an *evidence* root holding everything a
run produces — plus an optional *user state* root that belongs to neither. ADR-021
requires those persistence domains to stay separate, ADR-004 makes the source root and
sealed evidence the only scientific authority, and ADR-010 makes the query projection
rebuildable derived state. This module is the vocabulary for saying which of those a
given directory is, so that "the derived DuckDB index" and "sealed evidence" can never
be named interchangeably, and so that an API caller cannot ask for a sealed run
directory and receive a scratch path.

**Location is operational state, never semantic identity.** Everything below is a
filesystem concern: where a class of state lives *on this machine, this session*. None
of it is scientific meaning, so none of it may enter a RES-229 semantic digest. A
benchmark release validated from ``C:\\Users\\x\\ws`` and the identical release validated
from ``/srv/benchmarks`` have one meaning and one digest; only the resolved path differs.
The class names and directory segments declared here are part of the *convention* — they
are how a workspace is laid out everywhere — while a particular machine's absolute paths,
drive letters, UNC prefixes, usernames and root directory names are not, and cannot be,
because they are never hashed.

Seven classes are declared, and the distinctions between them are the whole point.
Each entry below is *class: authority, mutable, disposable — meaning*:

* ``SOURCE_AUTHORITY``: **yes, no, no** — version-controlled benchmark and scientific
  specifications and references.
* ``SEALED_EVIDENCE``: **yes, no, no** — sealed run bundles and future sealed research
  evidence.
* ``STAGING``: **no, yes, no** — mutable, incomplete, non-authoritative execution.
* ``DERIVED``: **no, yes, yes** — rebuildable query and index projections.
* ``CACHE``: **no, yes, yes** — disposable computed data.
* ``TMP``: **no, yes, yes** — disposable scratch space.
* ``USER_STATE``: **no, yes, yes** — product and application preferences.

``STAGING`` is mutable but deliberately *not* disposable. An abandoned staging directory
is incomplete work whose fate is a scientific decision, not a cache entry: DB-1.5
(RES-231) decides whether it is sealed as a failed outcome or discarded, and a layout
that classed it with ``CACHE`` would invite a cleanup routine to delete evidence of what
happened. ``SEALED_EVIDENCE`` is an authority class even though its sealing mechanics
belong to RES-231; this module only fixes where such evidence lives, never whether a
directory qualifies as it.

The tables below are the authoritative layout convention. They are declared as data so
that RES-231, M2, and the workbench read one definition, and so that "which directory
does a class use" is a reviewable fact rather than a literal repeated across modules.

Nothing in this module touches the filesystem. Resolution, containment, and creation
live in :mod:`dynamisbench.workspace.paths` and
:mod:`dynamisbench.workspace.workspace`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "CLASS_LOCATION_SEGMENTS",
    "CLASS_SEMANTICS",
    "INITIALISED_CLASSES",
    "SOURCE_CATEGORY_SEGMENTS",
    "ClassSemantics",
    "PathScopeError",
    "PersistenceClass",
    "SourceCategory",
    "WorkspaceError",
    "WorkspaceRootError",
]


class WorkspaceError(Exception):
    """Base class for every workspace refusal.

    Workspace operations fail closed. A caller that cannot establish which root a path
    belongs to, or that a location violates its declared class, is told so rather than
    handed a best-effort answer: a workspace that guesses is a workspace that can leak
    one project's evidence into another's, and can write outside the directory the user
    authorised.
    """


class WorkspaceRootError(WorkspaceError):
    """A declared root is unusable, so no workspace can be described from it.

    Raised for a root that is missing, is not a directory, resolves to the same
    directory as another scientific root, or — for product preferences — lies inside
    scientific authority.
    """


class PathScopeError(WorkspaceError):
    """A workspace-relative reference would not stay inside the directory it is scoped to.

    This is the failure of every containment check the workspace makes: an absolute or
    drive-qualified path, a ``..`` traversal, a UNC or extended-length prefix, a
    separator trick, a name Windows cannot store, a cross-root or cross-volume target,
    or a symlink or junction inside the workspace that points outside the authorised
    root. The logical reference and the class it was asked of are carried on the error
    so that an API or UI boundary can report which request was refused without being
    handed the resolved path.
    """

    def __init__(
        self,
        message: str,
        *,
        logical_reference: str | None = None,
        persistence_class: PersistenceClass | None = None,
    ) -> None:
        super().__init__(message)
        self.logical_reference = logical_reference
        self.persistence_class = persistence_class


class PersistenceClass(StrEnum):
    """The persistence class of a workspace location (ADR-021).

    The value is the portable name of the class, not a path. It appears in reports and
    error messages so a caller can be told which authority boundary was crossed, and it
    never carries the machine-specific location of that boundary.
    """

    SOURCE_AUTHORITY = "source_authority"
    """Version-controlled benchmark, realization, study, reference, and schema authority."""

    SEALED_EVIDENCE = "sealed_evidence"
    """Sealed run bundles, and future sealed research evidence (ADR-008)."""

    STAGING = "staging"
    """Mutable, incomplete, non-authoritative execution space."""

    DERIVED = "derived"
    """Rebuildable query/index projections such as the DuckDB database (ADR-010)."""

    CACHE = "cache"
    """Disposable computed data."""

    TMP = "tmp"
    """Disposable scratch space."""

    USER_STATE = "user_state"
    """Product and application preferences; never scientific state."""


class SourceCategory(StrEnum):
    """The categories of version-controlled scientific authority under the source root.

    These are the project concepts the source side must accommodate. Each names a
    directory under the source root and carries only source authority, so a benchmark
    specification and a sealed run bundle can never be filed under one another.
    """

    BENCHMARKS = "benchmarks"
    REALIZATIONS = "realizations"
    STUDIES = "studies"
    REFERENCES = "references"
    SCHEMAS = "schemas"


@dataclass(frozen=True, slots=True)
class ClassSemantics:
    """What a persistence class permits, stated once so no two callers can disagree.

    ``authoritative`` marks scientific authority: it is deleted only by a deliberate
    decision recorded in history, never as cleanup. ``mutable`` marks a class a run or
    the application is allowed to write. ``disposable`` marks a class whose loss is
    recoverable by rebuilding or recomputation, which is what makes a cleanup routine
    safe to write against it and what forbids it from ever being the only copy of
    authoritative data (ADR-010).
    """

    authoritative: bool
    mutable: bool
    disposable: bool


CLASS_SEMANTICS: Final[Mapping[PersistenceClass, ClassSemantics]] = MappingProxyType(
    {
        PersistenceClass.SOURCE_AUTHORITY: ClassSemantics(
            authoritative=True, mutable=False, disposable=False
        ),
        PersistenceClass.SEALED_EVIDENCE: ClassSemantics(
            authoritative=True, mutable=False, disposable=False
        ),
        PersistenceClass.STAGING: ClassSemantics(
            authoritative=False, mutable=True, disposable=False
        ),
        PersistenceClass.DERIVED: ClassSemantics(
            authoritative=False, mutable=True, disposable=True
        ),
        PersistenceClass.CACHE: ClassSemantics(authoritative=False, mutable=True, disposable=True),
        PersistenceClass.TMP: ClassSemantics(authoritative=False, mutable=True, disposable=True),
        PersistenceClass.USER_STATE: ClassSemantics(
            authoritative=False, mutable=True, disposable=True
        ),
    }
)
"""The authority contract of each persistence class."""

CLASS_LOCATION_SEGMENTS: Final[Mapping[PersistenceClass, tuple[str, ...]]] = MappingProxyType(
    {
        PersistenceClass.SOURCE_AUTHORITY: (),
        PersistenceClass.SEALED_EVIDENCE: ("runs",),
        PersistenceClass.STAGING: (".staging",),
        PersistenceClass.DERIVED: ("derived",),
        PersistenceClass.CACHE: ("cache",),
        PersistenceClass.TMP: ("tmp",),
        PersistenceClass.USER_STATE: (),
    }
)
"""Where each class lives, as segments under its own root.

An empty tuple means the root itself. The two authority roots are the source root and
the evidence root respectively; ``USER_STATE`` has its own root, supplied by the caller.

``STAGING`` is a dot-directory so that it reads as internal machinery rather than
authority at a glance, and so that a recursive copy of the evidence root can exclude it
with one conventional rule.
"""

SOURCE_CATEGORY_SEGMENTS: Final[Mapping[SourceCategory, tuple[str, ...]]] = MappingProxyType(
    {category: (category.value,) for category in SourceCategory}
)
"""Where each source-authority category lives, as segments under the source root."""

INITIALISED_CLASSES: Final[tuple[PersistenceClass, ...]] = (
    PersistenceClass.STAGING,
    PersistenceClass.DERIVED,
    PersistenceClass.CACHE,
    PersistenceClass.TMP,
)
"""The classes an explicit initialization creates.

Only mutable, non-authoritative working directories are created. Three absences are
deliberate:

* ``SEALED_EVIDENCE`` is not created, because an empty ``runs/`` directory is not
  evidence and the directory that first becomes authoritative is the one DB-1.5
  (RES-231) atomically promotes into it. Creating it here would imply a layout that
  holds authority before anything is authoritative.
* ``SOURCE_AUTHORITY`` is not created wholesale, because version-controlled content is
  added by a repository, not by an application; a category is created only when the
  caller explicitly asks for it.
* ``USER_STATE`` is not created, because the product owns that directory and DB-1.4
  supplies only the boundary that keeps it outside scientific authority.
"""
