"""Turning a workspace-relative reference into a path that is provably inside its root.

A location's declared path says where a class of state lives. It does not say that a
*caller's* reference stays there, and the difference is the whole security surface of this
package. Every reference that arrives from an API, a read model, a run identifier, a UI
field, or a future remote client is untrusted input, and ``../../other-project/file`` must
never become a valid reference to anything. So resolution is one operation with two
independent defences, and it fails closed if either is unsure.

**The lexical gate rejects the form before anything is touched.** A reference is refused
for carrying an absolute anchor, a drive, a UNC or extended-length prefix, a ``..`` or
``.`` segment, an empty segment, a separator trick, or a name that cannot round-trip on
both supported platforms. Both Windows and POSIX path grammars are consulted for every
reference regardless of the host platform, so ``C:\\Windows\\System32`` is refused on
Linux and ``/etc`` is refused on Windows: a reference validated on one platform is
accepted on the other, and a language that only one platform can resolve is not a
language at all. Percent-encoding is *not* decoded — this is not a URL boundary — so a
reference that reached here still encoded had already been decoded by the layer that
received it, and ``%2e%2e`` is the literal file name it looks like.

**The structural gate proves containment, structurally.** Containment is decided by
``Path.is_relative_to``, which compares path *components* under the host's own case
rules. It is never a string prefix test: ``C:\\ws`` does not contain ``C:\\ws-evil``,
whereas a prefix comparison would say it does. Both the location being resolved *and* the
result are resolved first, so a symlink or junction anywhere along the way — including
one sitting on ``.staging`` itself — is followed to its target and then checked, and a
link that leaves the root is refused even though every component of the request was
legitimate. A refusal reports the reference and the class and does not echo the resolved
path, so declining to serve a path does not hand it over.

The two gates answer different questions and neither is redundant. The lexical gate is
what stops a traversal from being *requested*; the structural gate is what stops an
honest-looking reference from *arriving* somewhere else, which is the only way an escape
can happen on a filesystem that supports links.

A backslash is accepted as a separator and an interior space is accepted as a name
character. Both are ordinary characters in a POSIX file name and both mean the same thing
on Windows, so treating them consistently keeps one reference language across platforms.
The risk of splitting on a backslash is that ``a\\b`` stops being one literal name and
becomes a directory and a file; that is the safe direction, because the alternative would
mean a reference whose meaning depends on which platform is reading it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final

from dynamisbench.workspace.authority import PathScopeError, PersistenceClass

MAX_LOGICAL_REFERENCE_LENGTH: Final = 1024
"""The longest reference accepted.

Generous for a specification path or a run identifier, and comfortably inside what
Windows and POSIX both store without extended-length prefixes, so a reference never
needs a platform-specific escape hatch to be expressed.
"""

_SEPARATOR: Final = re.compile(r"[\\/]")
"""Both separators, on every platform.

A backslash is an ordinary file-name character on POSIX and a separator on Windows, so a
reference containing one is not portable and is refused by splitting on it everywhere.
Accepting it on Linux and refusing it on Windows would mean the same workspace accepted
different references on different machines.
"""

_WINDOWS_TRAILING: Final = " ."
"""Characters Windows removes from the end of a name.

A file called ``report.`` is stored as ``report`` and a file called ``report `` is stored
as ``report``, on every platform that shares the filesystem. A reference naming either
would therefore name one file and resolve to another, so the reference language excludes
them rather than letting a silent normalisation decide what was meant.
"""

_WINDOWS_ILLEGAL: Final = frozenset('<>"|?*:')
"""Characters Windows cannot store in a file name.

``:`` earns its place twice over: it is illegal in a name, and it is how NTFS addresses an
alternate data stream, so ``run.json:stream`` would be a second, invisible file inside a
run bundle rather than the file it appears to name. Excluding them keeps the accepted
reference language identical on Windows and Linux, which is what lets a workspace be
relocated between them without its authority changing (ADR-023).
"""

_DOS_DEVICE_NAMES: Final = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
"""Names Windows reserves for devices, with or without an extension.

``NUL.txt`` is the device, not a file. Such a name also does not survive a copy to POSIX,
so accepting it would create a workspace whose layout is not portable.
"""

_TRAVERSAL_SEGMENTS: Final = frozenset({".", ".."})


def validate_logical_reference(
    logical: str, *, persistence_class: PersistenceClass | None = None
) -> tuple[str, ...]:
    """Return the segments of a workspace-relative reference, or refuse it.

    The reference must be relative, free of traversal and empty segments, spelled with
    ``/`` or ``\\``, and made only of names that mean the same thing on Windows and POSIX.
    The returned segments contain no separator, so joining them onto an absolute location
    cannot re-anchor the path.

    :raises PathScopeError: for every rejection below, carrying the reference and, when
        the caller knows it, the class that was asked for.
    """
    if not isinstance(logical, str):
        raise PathScopeError(
            f"a workspace reference must be a string, not {type(logical).__name__}"
        )
    if not logical:
        raise PathScopeError("a workspace reference must not be empty")

    def refuse(reason: str) -> PathScopeError:
        return PathScopeError(
            f"the reference {logical!r} {reason}",
            logical_reference=logical,
            persistence_class=persistence_class,
        )

    if len(logical) > MAX_LOGICAL_REFERENCE_LENGTH:
        raise refuse(f"is longer than {MAX_LOGICAL_REFERENCE_LENGTH} characters")
    if any(character == "\x00" or not character.isprintable() for character in logical):
        raise refuse("contains a NUL or control character")

    windows = PureWindowsPath(logical)
    if windows.drive:
        raise refuse(f"is drive-qualified ({windows.drive}), not relative to its root")
    if windows.root or PurePosixPath(logical).root:
        raise refuse("is anchored to a filesystem root, not relative to its root")

    segments = tuple(_SEPARATOR.split(logical))
    if any(segment == "" for segment in segments):
        raise refuse("contains an empty path segment")
    for segment in segments:
        _refuse_unusable_segment(segment, refuse)
    return segments


def _refuse_unusable_segment(segment: str, refuse: Callable[[str], PathScopeError]) -> None:
    """Refuse one path segment, treating Windows normalisation as authoritative.

    Windows removes trailing dots and spaces from every component before it compares
    anything, so ``.. `` and ``a. `` are ``..`` and ``a`` to the operating system. A
    lexical check that compared segments literally would classify ``.. `` as an ordinary
    name and hand the operating system something that is not one.
    """
    if segment in _TRAVERSAL_SEGMENTS:
        raise refuse(f"contains a {segment!r} segment")
    if segment != segment.rstrip(_WINDOWS_TRAILING):
        raise refuse(
            f"contains the segment {segment!r}, which ends in a dot or space that Windows "
            "removes, so the reference would not name the file it appears to name"
        )
    if not segment.strip():
        raise refuse(f"contains the whitespace-only segment {segment!r}")
    illegal = sorted(set(segment) & _WINDOWS_ILLEGAL)
    if illegal:
        raise refuse(f"contains characters no file name can hold on Windows: {illegal}")
    if segment.split(".", 1)[0].lower() in _DOS_DEVICE_NAMES:
        raise refuse(f"contains {segment!r}, which names a reserved device, not a file")


def _resolve(path: Path, logical: str, persistence_class: PersistenceClass | None) -> Path:
    """Resolve a path, treating any filesystem failure as a refusal rather than a guess."""
    try:
        return path.resolve()
    except (OSError, RuntimeError) as error:
        raise PathScopeError(
            f"the reference {logical!r} cannot be resolved: {error}",
            logical_reference=logical,
            persistence_class=persistence_class,
        ) from error


def _require_contained(
    resolved: Path,
    authorized_roots: tuple[Path, ...],
    logical: str,
    persistence_class: PersistenceClass | None,
    subject: str,
) -> None:
    """Refuse a resolved path that is not below one of the authorised roots.

    The test is ``is_relative_to``, which compares whole path components under the
    platform's case rules and never a string prefix. That is what makes ``C:\\ws`` and
    ``C:\\ws-evil`` different answers, and what makes a case-different spelling of a path
    inside the root the same answer on Windows while remaining correctly distinct on a
    case-sensitive filesystem.
    """
    for root in authorized_roots:
        if resolved.is_relative_to(root):
            return
    named = f"{persistence_class.value} " if persistence_class is not None else ""
    roots = "root" if len(authorized_roots) == 1 else "roots"
    raise PathScopeError(
        f"the {subject} of {logical!r} leaves the authorised {named}{roots} of this class",
        logical_reference=logical,
        persistence_class=persistence_class,
    )


def resolve_within(
    location: Path,
    logical: str,
    *,
    authorized_roots: tuple[Path, ...],
    persistence_class: PersistenceClass | None = None,
) -> Path:
    """Resolve ``logical`` under ``location``, refusing anything that leaves the roots.

    Both the location and the result are resolved before containment is checked, so a
    symlink or junction on the way — including one replacing the location directory
    itself — is followed and then refused rather than trusted. Resolving the location
    first also means the returned path is absolute and canonical, which is what a caller
    opening a file wants and what containment has to be measured against.

    A reference that does not yet exist resolves fine: resolution is how a caller names a
    file it is about to create, and a missing final component has no link to follow.

    :raises PathScopeError: if the reference is not a well-formed relative reference, if
        it cannot be resolved, or if either the location or the result falls outside
        ``authorized_roots``.
    """
    segments = validate_logical_reference(logical, persistence_class=persistence_class)
    resolved_location = _resolve(location, logical, persistence_class)
    _require_contained(resolved_location, authorized_roots, logical, persistence_class, "location")
    resolved = _resolve(resolved_location.joinpath(*segments), logical, persistence_class)
    _require_contained(resolved, authorized_roots, logical, persistence_class, "reference")
    return resolved
