"""Discovering which source-authority documents a workspace currently holds.

Discovery is the read-only half of :mod:`dynamisbench.workspace.source_authority`: that
module knows what one document *is*, and this one finds candidates and hands them over
in a fixed order. Everything returned here is a :class:`SourceLocator`, never a
document. Reading and validating one is a separate, explicit step, so a caller that only
wants to list a workspace never pays for parsing it, and a caller that wants to inspect
one re-reads it at that moment rather than trusting a list built earlier.

Three rules shape the walk.

**Only declared locations are walked, and nothing else is even listed.** The traversal
starts at each :class:`SourceCategory`'s location and descends into the kind directories
that category declares. It never reads the evidence root, ``runs``, ``.staging``,
``derived``, ``cache``, ``tmp``, or any user-state directory: none of those holds source
authority, and a reader that surfaced their contents would be offering the application
boundary a view of execution state it has no business publishing.

**Links are reported, not followed.** A kind directory that is a symbolic link or a
Windows junction, and a document that is a link resolving outside the source root, are
bounded structural issues rather than traversal. Following either would mean a link
authored inside a workspace decides what that workspace exposes, which is the escape
this package exists to prevent. Reporting is what makes the refusal visible: a client can
see that something was there and was not read, and cannot tell where it points.

**Order is stated, not incidental.** Artifacts come back sorted by their portable logical
reference, and the categories and kinds are visited in declaration order — never a
directory listing's. Two discoveries of the same workspace therefore produce the same
sequence, which is what lets a caller diff one against the other and what keeps an opaque
identifier stable between calls.

Nothing here writes, creates, normalises, or touches anything. Discovery is a description
of the workspace as it is right now, and it is safe to run on a workspace that was never
initialised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dynamisbench.workspace.authority import SourceCategory
from dynamisbench.workspace.source_authority import (
    CATEGORY_KINDS,
    MAX_DISCOVERY_ISSUES,
    DiagnosticCode,
    SourceDiagnostic,
    SourceLocator,
    diagnostic,
    format_of_suffix,
)
from dynamisbench.workspace.workspace import Workspace

__all__ = [
    "CategoryStatus",
    "DiscoveryIssue",
    "SourceDiscovery",
    "discover_sources",
]


@dataclass(frozen=True, slots=True)
class CategoryStatus:
    """Whether one declared source category currently exists on disk.

    A boolean and a name, and no path. A client learns *that* a category is absent — a
    normal state for a workspace that has not been given every category — without
    learning where the workspace lives.
    """

    category: SourceCategory
    exists: bool


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    """One structural finding about a workspace, in portable terms.

    ``reference`` is the portable logical reference of the entry involved, or the
    declared name of the category or kind directory, and never an absolute path. A
    client can act on it — fix the file, remove the link — without being handed a path,
    and a path is the one thing an application boundary is not allowed to publish.
    """

    diagnostic: SourceDiagnostic
    category: SourceCategory
    reference: str


@dataclass(frozen=True, slots=True)
class SourceDiscovery:
    """One read-only pass over a workspace's source authority.

    ``categories`` reports every declared category whether or not it exists, in
    declaration order, so a client can tell "absent" from "not looked at". ``locators``
    are the authoring documents found, ordered by portable logical reference; nothing
    here has been read or validated yet. ``issues`` are the structural findings, capped
    at :data:`MAX_DISCOVERY_ISSUES`, and ``issues_truncated`` says so when the cap was
    reached — because a silently shortened list reads as a complete one.
    """

    categories: tuple[CategoryStatus, ...]
    locators: tuple[SourceLocator, ...]
    issues: tuple[DiscoveryIssue, ...]
    issues_truncated: bool = False


_UNREADABLE_ENTRIES: tuple[()] = ()
"""What an unlistable directory yields.

An empty tuple rather than an exception: a workspace whose ``schemas/`` directory exists
but cannot be listed by this process holds no readable authority in it, and turning that
into an error would make discovery of every other category depend on one directory's
permissions.
"""


def _entries(directory: Path) -> tuple[os.DirEntry[str], ...]:
    """The entries of one directory, sorted by name, or none when unlistable."""
    try:
        with os.scandir(directory) as found:
            return tuple(sorted(found, key=lambda entry: entry.name))
    except OSError:
        return _UNREADABLE_ENTRIES


def _resolves_outside(path: Path, root: Path) -> bool:
    """Whether ``path`` resolves outside ``root``.

    Resolution may fail — a broken link, a permission refusal, a loop — and every
    failure counts as *outside*. The only question asked about a link here is whether
    following it is safe, and a link that cannot be shown to be safe is not safe.
    """
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return True
    return not resolved.is_relative_to(root)


def _is_link(entry: os.DirEntry[str]) -> bool:
    """Whether one directory entry is a symbolic link or a Windows junction.

    Checked before any ``is_dir`` or ``is_file`` in this module, and those calls all
    pass ``follow_symlinks=False``: a junction is not a symbolic link as the standard
    library reports it, and a default ``is_dir`` would answer "yes" for either kind of
    link and the walk would then descend into it.
    """
    if entry.is_symlink():
        return True
    is_junction = getattr(entry, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _issue_limit_reached(issues: list[DiscoveryIssue]) -> bool:
    return len(issues) >= MAX_DISCOVERY_ISSUES


def _collect_issues(
    issues: list[DiscoveryIssue],
    code: DiagnosticCode,
    category: SourceCategory,
    reference: str,
) -> bool:
    """Append one bounded issue, reporting whether the cap has now been reached.

    The diagnostic is built by code alone, through
    :func:`dynamisbench.workspace.source_authority.diagnostic`, so no caller can put text
    of its own into one. That is how rejected values and absolute paths stay out of a
    published finding: there is no parameter through which they could arrive.
    """
    if _issue_limit_reached(issues):
        return True
    issues.append(
        DiscoveryIssue(diagnostic=diagnostic(code), category=category, reference=reference)
    )
    return _issue_limit_reached(issues)


def _walk_kind_directory(
    workspace: Workspace,
    category: SourceCategory,
    kind: str,
    prefix: str,
    locators: list[SourceLocator],
    issues: list[DiscoveryIssue],
) -> bool:
    """Collect every authoring document beneath one declared kind directory.

    Recursive, because the declared layout is ``benchmark/**/*.yaml``: the segments
    between the kind directory and the document are repository structure, not part of the
    model's meaning, and a definition filed two levels down is as authoritative as one
    filed at the top. What is *not* negotiable is that no link is ever followed, so a
    recursive walk cannot leave the root however deep it goes.
    """
    location = workspace.source_location(category)
    pending: list[tuple[Path, tuple[str, ...]]] = [(location.path / kind, (kind,))]
    truncated = False

    while pending:
        directory, segments = pending.pop(0)
        for entry in _entries(directory):
            name = entry.name
            child_segments = (*segments, name)
            portable = f"{prefix}/{'/'.join(child_segments)}"

            if _is_link(entry):
                code = (
                    DiagnosticCode.PATH_SCOPE_VIOLATION
                    if _resolves_outside(Path(entry.path), location.root)
                    else DiagnosticCode.UNSUPPORTED_ENTRY
                )
                truncated |= _collect_issues(issues, code, category, portable)
                continue
            if entry.is_dir(follow_symlinks=False):
                if name in NON_SOURCE_DIRECTORIES:
                    truncated |= _collect_issues(
                        issues, DiagnosticCode.UNSUPPORTED_ENTRY, category, portable
                    )
                    continue
                pending.append((Path(entry.path), child_segments))
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if format_of_suffix(os.path.splitext(name)[1]) is None:
                truncated |= _collect_issues(
                    issues, DiagnosticCode.UNSUPPORTED_ENTRY, category, portable
                )
                continue
            locators.append(SourceLocator(category=category, kind=kind, segments=child_segments))

    return truncated


def _walk_category(
    workspace: Workspace,
    category: SourceCategory,
    locators: list[SourceLocator],
    issues: list[DiscoveryIssue],
) -> bool:
    """Report the entries of one category that are not declared kind directories.

    A ``.json`` sitting directly under ``schemas/`` is the specific mistake this catches:
    the file is an authoring document, but its directory is not one this workspace declares,
    so nothing downstream could say which model it validates against. Reporting it is the
    only honest answer, because guessing a kind from its file name is exactly what the
    layout forbids everywhere else.
    """
    location = workspace.source_location(category)
    prefix = location.reference.text
    truncated = False
    for entry in _entries(location.path):
        name = entry.name
        is_kind = name in CATEGORY_KINDS[category]
        if _is_link(entry):
            code = (
                DiagnosticCode.PATH_SCOPE_VIOLATION
                if _resolves_outside(Path(entry.path), location.root)
                else DiagnosticCode.UNSUPPORTED_ENTRY
            )
            truncated |= _collect_issues(issues, code, category, f"{prefix}/{name}")
        elif not is_kind:
            truncated |= _collect_issues(issues, DiagnosticCode.UNSUPPORTED_ENTRY, category, name)
    return truncated


def discover_sources(workspace: Workspace) -> SourceDiscovery:
    """Walk the declared source categories and describe what they currently hold.

    Read-only and side-effect free: it stats and lists directories, opens no document,
    and creates nothing. Every candidate it reports is a locator, so inspection re-resolves
    it through :meth:`Workspace.resolve_source` rather than trusting this walk — a path
    that came from a directory listing has not been authorised by anything.

    A *category* that is itself a link is refused before it is listed, which is the one
    case a directory walk cannot see: the category path is not a child of anything this
    module scanned, so nothing downstream would have asked whether it stayed inside the
    root.

    :returns: the categories that exist, the authoring documents found in a deterministic
        order, and the bounded structural issues found along the way.
    """
    report = workspace.inspect()
    existing = report.existing_sources
    statuses: tuple[CategoryStatus, ...] = tuple(
        CategoryStatus(category=category, exists=category in existing)
        for category in SourceCategory
    )

    locators: list[SourceLocator] = []
    issues: list[DiscoveryIssue] = []
    truncated = False
    for category in SourceCategory:
        if category not in existing:
            continue
        location = workspace.source_location(category)
        if _resolves_outside(location.path, location.root):
            truncated |= _collect_issues(
                issues, DiagnosticCode.PATH_SCOPE_VIOLATION, category, location.reference.text
            )
            continue
        truncated |= _walk_category(workspace, category, locators, issues)
        for kind in CATEGORY_KINDS[category]:
            truncated |= _walk_kind_directory(
                workspace, category, kind, location.reference.text, locators, issues
            )

    return SourceDiscovery(
        categories=statuses,
        locators=tuple(sorted(locators, key=lambda locator: locator.logical_reference)),
        issues=tuple(issues),
        issues_truncated=truncated,
    )


NON_SOURCE_DIRECTORIES: frozenset[str] = frozenset({"runs", ".staging", "derived", "cache", "tmp"})
"""Persistence-class directory names that never hold source authority.

Published so a qualification gate can assert the walk never reaches any of them, rather
than relying on the fact that it only starts at source categories. They are evidence,
staging, or rebuildable application state, and a reader that surfaced their contents
would be publishing execution state through a source-authority route.
"""
