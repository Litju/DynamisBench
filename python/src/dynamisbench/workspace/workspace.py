"""Roots, declared locations, and the side-effect-free open of a workspace.

This module is the workspace *model*: two independent scientific roots plus an optional
non-scientific one, the declared location of every persistence class, the portable name
each location is known by, and the read-only open of a workspace. Safe resolution of
references inside those locations belongs to :mod:`dynamisbench.workspace.paths`.

**A logical reference is not a filesystem path.** Every location this module describes
carries two things that must never be confused: a :class:`LogicalReference`, which is a
portable class-and-segments name with no machine-specific content, and an absolute
``Path``, which is where that name happens to live right now. The split is the reason an
otherwise identical workspace keeps every artifact's RES-229 semantic digest when it is
moved, renamed, or served from a different drive: only the ``Path`` changes. Absolute
paths, drive letters, UNC prefixes, home directories, usernames, and the name of the
workspace root directory are operational state and are not hashed, because hashing them
would make a benchmark's identity depend on where the machine happened to keep it.

**The roots are trusted; the references are not.** A root is a configuration decision by
the person running the workbench, so it is normalised once — made absolute and resolved
so that its real target, not a link to it, is the authorised directory — and then
required to be an existing directory. Everything a caller later supplies is a
*reference*, and references are untrusted input handled by
:mod:`dynamisbench.workspace.paths`. Keeping that line sharp is what stops this
abstraction from becoming the unrestricted filesystem access the architecture forbids:
the only thing a caller can ask for is a location inside a declared class, and the only
way to obtain a path that will be opened is a resolution that has already proved
containment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

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
from dynamisbench.workspace.paths import resolve_within, validate_logical_reference

__all__ = [
    "LogicalReference",
    "RootInput",
    "Workspace",
    "WorkspaceLocation",
    "WorkspaceReport",
    "WorkspaceRoots",
    "initialize_workspace",
    "open_workspace",
]

type RootInput = str | PathLike[str]
"""Anything :class:`pathlib.Path` accepts as a root.

A plain string is included because that is what a CLI argument, an environment variable,
and a configuration file all supply, and because ``os.PathLike`` on its own would make
the most natural call fail type checking while succeeding at runtime.
"""


def _normalise_root(path: RootInput, label: str) -> Path:
    """Make a declared root absolute and resolve it to its real target.

    Resolution happens once, here, for two reasons. It makes the authorised directory the
    directory the root actually names, so a root that is itself a symlink or junction
    cannot later be re-pointed at somewhere else and inherit the authorisation; and it
    gives containment checks a canonical target to compare against.
    """
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as error:
        raise WorkspaceRootError(f"the {label} cannot be resolved: {error}") from error


def _require_directory(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise WorkspaceRootError(f"the {label} is not an existing directory: {path}")
    return path


def _disjoint(left: Path, right: Path) -> bool:
    return not (left == right or left.is_relative_to(right) or right.is_relative_to(left))


def class_location_segments(persistence_class: PersistenceClass) -> tuple[str, ...]:
    """Return the directory segments a persistence class occupies under its root.

    :raises WorkspaceError: for a value that is not a declared class, so that a caller
        passing an unrecognised name from an API boundary is refused rather than handed
        a location nobody defined.
    """
    try:
        return CLASS_LOCATION_SEGMENTS[persistence_class]
    except KeyError:
        raise WorkspaceError(f"unknown persistence class: {persistence_class!r}") from None


def class_semantics(persistence_class: PersistenceClass) -> ClassSemantics:
    """Return the authority contract of a persistence class.

    :raises WorkspaceError: for a value that is not a declared class.
    """
    try:
        return CLASS_SEMANTICS[persistence_class]
    except KeyError:
        raise WorkspaceError(f"unknown persistence class: {persistence_class!r}") from None


def source_category_segments(category: SourceCategory) -> tuple[str, ...]:
    """Return the directory segments a source-authority category occupies.

    :raises WorkspaceError: for a value that is not a declared category.
    """
    try:
        return SOURCE_CATEGORY_SEGMENTS[category]
    except KeyError:
        raise WorkspaceError(f"unknown source category: {category!r}") from None


def _validated_user_state(
    user_state_root: RootInput | None, source: Path, evidence: Path
) -> Path | None:
    """Validate a declared user state root against roots that may not exist yet.

    Product preferences must be outside scientific authority, and that has to be settled
    before any directory is created: discovering the overlap afterwards would leave a
    workspace holding preferences inside authority, which is the one thing this
    separation exists to prevent. Both roots are checked in both directions, so
    preferences may neither sit inside authority nor contain it.
    """
    if user_state_root is None:
        return None
    user_state = _require_directory(
        _normalise_root(user_state_root, "user state root"), "user state root"
    )
    for label, root in (("source", source), ("evidence", evidence)):
        if not _disjoint(user_state, root):
            raise WorkspaceRootError(
                f"the user state root must be outside scientific authority, but "
                f"{user_state} and the {label} root {root} overlap"
            )
    return user_state


@dataclass(frozen=True, slots=True)
class WorkspaceRoots:
    """The three roots a workspace is described by, validated.

    ``source`` and ``evidence`` are the two scientific roots and must be distinct
    directories. They may nest — a repository that keeps its evidence in a gitignored
    subtree is a legitimate layout — but they are never the same directory, because a
    single directory cannot be both version-controlled authority and mutable execution
    space. ``user_state`` is optional and must be disjoint from both, in either
    direction: product preferences may not live inside scientific authority and may not
    contain it, so that no cleanup routine scoped to product state can reach an evidence
    bundle and no preference file can end up contributing to an artifact's identity.
    """

    source: Path
    evidence: Path
    user_state: Path | None = None

    def __post_init__(self) -> None:
        source = _require_directory(_normalise_root(self.source, "source root"), "source root")
        evidence = _require_directory(
            _normalise_root(self.evidence, "evidence root"), "evidence root"
        )
        if source == evidence:
            raise WorkspaceRootError(
                f"the source root and the evidence root must be different directories, "
                f"but both resolve to {source}"
            )
        user_state = _validated_user_state(self.user_state, source, evidence)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "user_state", user_state)


@dataclass(frozen=True, slots=True)
class LogicalReference:
    """A portable name for a location inside a persistence class.

    The name is the class's own directory segments followed by whatever is beneath them,
    spelled with ``/`` and carrying nothing about the machine: no leading separator, no
    drive, no ``..``, no root directory name. It is what may be stored in a read model,
    sent to an API, or compared across workspaces.

    Its purpose is to be the thing that does *not* change when a workspace moves. Two
    workspaces at different absolute paths give byte-identical ``text`` for the same
    artifact, which is what allows an artifact's semantic digest to be independent of
    where it lives. The empty reference is the class's own location, and ``text`` for it
    is the empty string; :attr:`is_root` distinguishes that from a missing name.
    """

    persistence_class: PersistenceClass
    parts: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """The reference as a portable ``/``-separated string."""
        return "/".join(self.parts)

    @property
    def is_root(self) -> bool:
        """Whether this reference names the class's own location rather than a child."""
        return not self.parts

    def child(self, *segments: str) -> LogicalReference:
        """Return a reference one level or more below this one.

        The segments go through the same lexical gate as an incoming reference, so a
        reference built by the platform is never one a request could not have been. That
        matters because a ``LogicalReference`` may be stored in a read model and handed
        back later as if it had arrived from outside.

        :raises PathScopeError: if any segment is not a usable name.
        """
        return LogicalReference(
            self.persistence_class,
            self.parts
            + validate_logical_reference(
                "/".join(segments), persistence_class=self.persistence_class
            ),
        )

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class WorkspaceLocation:
    """One declared location: what it is, what it is called, and where it is.

    ``reference`` is the portable name and ``path`` is the resolved absolute location.
    ``path`` is a *declared* location, not a checked one: use
    :meth:`dynamisbench.workspace.workspace.Workspace.resolve` for any path that will be
    opened, so that containment is proved rather than assumed. The authority flags come
    from :func:`class_semantics` so that a caller asking "may this be deleted and
    regenerated?" reads the same answer here as anywhere else.
    """

    persistence_class: PersistenceClass
    reference: LogicalReference
    root: Path
    path: Path
    semantics: ClassSemantics
    source_category: SourceCategory | None = None

    @property
    def authoritative(self) -> bool:
        """Whether losing this location would lose scientific authority."""
        return self.semantics.authoritative

    @property
    def mutable(self) -> bool:
        """Whether execution or the application may write here."""
        return self.semantics.mutable

    @property
    def disposable(self) -> bool:
        """Whether the contents can be rebuilt or recomputed instead of preserved."""
        return self.semantics.disposable


@dataclass(frozen=True, slots=True)
class WorkspaceReport:
    """A read-only description of which declared locations currently exist.

    Produced by :meth:`Workspace.inspect`, which touches nothing: it stats the declared
    locations and returns what it found. The report is the honest answer to "is this
    workspace set up yet", and answering it must not be the act of setting it up.
    """

    roots: WorkspaceRoots
    locations: tuple[WorkspaceLocation, ...]
    source_locations: tuple[WorkspaceLocation, ...]
    existing_classes: frozenset[PersistenceClass]
    existing_sources: frozenset[SourceCategory]

    @property
    def missing_classes(self) -> tuple[PersistenceClass, ...]:
        """Declared persistence classes whose location does not exist yet."""
        return tuple(
            location.persistence_class
            for location in self.locations
            if location.persistence_class not in self.existing_classes
        )

    @property
    def missing_sources(self) -> tuple[SourceCategory, ...]:
        """Declared source categories whose directory does not exist yet."""
        return tuple(
            category for category in SourceCategory if category not in self.existing_sources
        )


@dataclass(frozen=True, slots=True)
class Workspace:
    """An opened workspace: two independent scientific roots and a declared layout.

    Construct one with :func:`open_workspace` rather than directly, so the roots are
    validated. Everything a workspace exposes is a *declared* location derived from the
    roots and the layout tables; nothing here creates, removes, or writes anything, and
    no method hands out a path for I/O.
    """

    roots: WorkspaceRoots

    @property
    def source_root(self) -> Path:
        """The absolute, resolved source root holding version-controlled authority."""
        return self.roots.source

    @property
    def evidence_root(self) -> Path:
        """The absolute, resolved evidence root holding everything a run produces."""
        return self.roots.evidence

    @property
    def user_state_root(self) -> Path | None:
        """The absolute, resolved product-preference root, when one was declared."""
        return self.roots.user_state

    @property
    def evidence_is_inside_source(self) -> bool:
        """Whether the evidence root sits within the source root.

        Permitted — a repository may keep its evidence in a gitignored subtree — but it
        is worth a surface reporting, because it means evidence files are inside the
        working tree and a careless clean or a broad ignore rule can take them.
        """
        return self.roots.evidence.is_relative_to(self.roots.source)

    def location(self, persistence_class: PersistenceClass) -> WorkspaceLocation:
        """Return the declared location of a persistence class.

        :raises WorkspaceError: for a class that is not declared.
        :raises WorkspaceRootError: for :attr:`PersistenceClass.USER_STATE` when this
            workspace declared no user state root, because inventing a preferences
            location would put product state somewhere the caller did not choose.
        """
        segments = class_location_segments(persistence_class)
        if persistence_class is PersistenceClass.SOURCE_AUTHORITY:
            root = self.roots.source
        elif persistence_class is PersistenceClass.USER_STATE:
            if self.roots.user_state is None:
                raise WorkspaceRootError(
                    "this workspace declares no user state root, so it has no "
                    f"{PersistenceClass.USER_STATE.value} location"
                )
            root = self.roots.user_state
        else:
            root = self.roots.evidence
        return WorkspaceLocation(
            persistence_class=persistence_class,
            reference=LogicalReference(persistence_class, segments),
            root=root,
            path=root.joinpath(*segments),
            semantics=class_semantics(persistence_class),
        )

    def source_location(self, category: SourceCategory) -> WorkspaceLocation:
        """Return the declared location of a source-authority category.

        :raises WorkspaceError: for a category that is not declared.
        """
        segments = source_category_segments(category)
        root = self.roots.source
        return WorkspaceLocation(
            persistence_class=PersistenceClass.SOURCE_AUTHORITY,
            reference=LogicalReference(PersistenceClass.SOURCE_AUTHORITY, segments),
            root=root,
            path=root.joinpath(*segments),
            semantics=class_semantics(PersistenceClass.SOURCE_AUTHORITY),
            source_category=category,
        )

    def resolve(self, persistence_class: PersistenceClass, logical: str) -> Path:
        """Resolve a reference inside a persistence class to a path safe to open.

        This is the only method that hands out a path a caller will open, and the only
        door through which a reference from outside reaches the filesystem. The result is
        absolute, canonical, and proved to be inside the class's root — so a reference
        may not address another class, another root, or anywhere at all outside them.

        A reference that does not exist yet resolves successfully; resolution is how a
        caller names a file it is about to create.

        :raises PathScopeError: if the reference is not a well-formed relative reference
            or resolves outside the class's root.
        """
        location = self.location(persistence_class)
        return resolve_within(
            location.path,
            logical,
            authorized_roots=(location.root,),
            persistence_class=persistence_class,
        )

    def resolve_source(self, category: SourceCategory, logical: str) -> Path:
        """Resolve a reference inside a source-authority category to a path safe to open.

        The counterpart of :meth:`resolve` for version-controlled authority, and scoped
        the same way: a reference may name something inside one category and nothing
        else, so a benchmark specification cannot be read through the realizations
        category or the other way round.

        :raises PathScopeError: if the reference is not a well-formed relative reference
            or resolves outside the source root.
        """
        location = self.source_location(category)
        return resolve_within(
            location.path,
            logical,
            authorized_roots=(self.roots.source,),
            persistence_class=PersistenceClass.SOURCE_AUTHORITY,
        )

    def inspect(self) -> WorkspaceReport:
        """Describe which declared locations exist, without changing anything.

        Only the declared locations are stat'ed. No directory is created, no file is
        read, and no state is cached, so calling this on a workspace that has never been
        initialized leaves that workspace exactly as uninitialised as it was.
        """
        locations = tuple(
            self.location(persistence_class)
            for persistence_class in PersistenceClass
            if persistence_class is not PersistenceClass.USER_STATE
            or self.roots.user_state is not None
        )
        source_locations = tuple(self.source_location(category) for category in SourceCategory)
        return WorkspaceReport(
            roots=self.roots,
            locations=locations,
            source_locations=source_locations,
            existing_classes=frozenset(
                location.persistence_class for location in locations if location.path.is_dir()
            ),
            existing_sources=frozenset(
                category
                for category, location in zip(SourceCategory, source_locations, strict=True)
                if location.path.is_dir()
            ),
        )


def open_workspace(
    source_root: RootInput,
    evidence_root: RootInput,
    *,
    user_state_root: RootInput | None = None,
) -> Workspace:
    """Open an existing workspace without modifying anything.

    Reads the declared roots, resolves them, checks they are distinct directories, and
    returns the workspace. It creates no directory, writes no file, and reads no
    artifact, so opening a workspace is safe to do speculatively, repeatedly, or merely to
    decide whether the workspace is the one the user meant.

    :raises WorkspaceRootError: if either scientific root is missing or is not a
        directory, if they resolve to the same directory, or if a declared user state
        root is missing or overlaps scientific authority.
    """
    return Workspace(
        WorkspaceRoots(
            source=Path(source_root),
            evidence=Path(evidence_root),
            user_state=None if user_state_root is None else Path(user_state_root),
        )
    )


def _requested_categories(sources: Iterable[SourceCategory]) -> tuple[SourceCategory, ...]:
    """Return the requested source categories deduplicated, in canonical order.

    Deduplication and canonical ordering mean the result does not depend on how the
    caller happened to list them, so initialising a workspace twice with the same
    request is the same operation.
    """
    requested = list(sources)
    undeclared = [category for category in requested if not isinstance(category, SourceCategory)]
    if undeclared:
        names = ", ".join(sorted(repr(category) for category in undeclared))
        raise WorkspaceError(f"unknown source categories: {names}")
    return tuple(category for category in SourceCategory if category in set(requested))


def _make_directory(path: Path) -> None:
    """Create one declared directory, refusing to report a filesystem failure as success."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise WorkspaceRootError(
            f"cannot create the workspace directory {path}: {error}"
        ) from error


def _refuse_non_directory_root(path: Path, label: str) -> None:
    """Refuse a root path already occupied by something that is not a directory.

    A root that does not exist yet is normal — that is what initialisation is for — but
    one that exists as a file can never become a root, so it is settled before anything is
    created rather than discovered halfway through.
    """
    if path.exists() and not path.is_dir():
        raise WorkspaceRootError(f"the {label} exists but is not a directory: {path}")


def initialize_workspace(
    source_root: RootInput,
    evidence_root: RootInput,
    *,
    user_state_root: RootInput | None = None,
    sources: Iterable[SourceCategory] = (),
) -> Workspace:
    """Explicitly create a workspace's declared mutable structure, then open it.

    This is the only operation in the package that creates directories, and it is explicit
    by design: opening or inspecting a workspace must never be the hidden cause of a
    filesystem change, so the caller who wants a workspace to exist says so here and
    nowhere else. It creates the two roots, the mutable working directories
    (``.staging``, ``derived``, ``cache``, ``tmp``), and any source categories the caller
    names — nothing else, so "what does a DynamisBench workspace consist of" has an
    answer that is a list rather than a convention.

    Every root is validated before anything is created, so a request that cannot produce a
    valid workspace leaves the filesystem exactly as it found it rather than half-built.
    Re-running is safe: existing directories are accepted unchanged, so calling it again
    with an extra category is how a workspace grows.

    Three things are deliberately not created. ``runs/`` is not created, because an empty
    directory is not sealed evidence and the first authoritative bundle arrives by the
    atomic promotion DB-1.5 (RES-231) owns. The source categories are not created
    wholesale, because version-controlled content is added by a repository rather than by
    an application, so only the categories named here appear. A user state root is never
    created, because the product owns it and this issue supplies only the boundary that
    keeps it outside scientific authority.

    :raises WorkspaceRootError: if the two roots would be the same directory, if a
        declared root cannot be used, or if a directory cannot be created.
    :raises WorkspaceError: if ``sources`` names anything that is not a source category.
    """
    source = _normalise_root(source_root, "source root")
    evidence = _normalise_root(evidence_root, "evidence root")
    if source == evidence:
        raise WorkspaceRootError(
            f"the source root and the evidence root must be different directories, "
            f"but both resolve to {source}"
        )
    categories = _requested_categories(sources)
    user_state = _validated_user_state(user_state_root, source, evidence)
    _refuse_non_directory_root(source, "source root")
    _refuse_non_directory_root(evidence, "evidence root")

    _make_directory(source)
    _make_directory(evidence)
    for persistence_class in INITIALISED_CLASSES:
        _make_directory(evidence.joinpath(*class_location_segments(persistence_class)))
    for category in categories:
        _make_directory(source.joinpath(*source_category_segments(category)))

    return open_workspace(source, evidence, user_state_root=user_state)
