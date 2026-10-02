"""Constructing a *file* link, which the evidence suite needs for its own scenarios.

The workspace suite already solves the harder problem of creating a directory link on a
host that forbids symbolic links, by using a Windows junction. That solution does not
transfer: a junction can only point at a directory, and the evidence seal has to refuse a
linked *file* as well as a linked directory, because a payload artifact that resolves
elsewhere is not portable evidence however it is spelled.

A hard link is the third case, and it is refused for a different reason — it resolves nowhere,
but it means the same file record has a second pathname the bundle cannot see — so it is
built separately rather than folded into the symlink helper. It is also the one mechanism
that Windows does not gate behind Developer Mode, so on the primary platform it normally
works and the qualification is not silently reduced to a skip.

Every helper here follows the same rule: try the host's native mechanism, report which one
was used, and return :data:`~tests.workspace.links.UNAVAILABLE` rather than raising when the
host permits none. Callers pass the result to :func:`require_file_link`, which fails the
test out loud — a silently skipped link-rejection test is a qualification gap that reads as a
pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.workspace.links import UNAVAILABLE

FILE_SYMLINK = "file_symlink"
"""Reported when the link was created as a symbolic link to a file."""

HARD_LINK = "hard_link"
"""Reported when the link was created as a second directory entry for the same file record."""


def make_file_link(link: Path, target: Path) -> str:
    """Point ``link`` at ``target`` as a file, and report the mechanism used.

    Windows symbolic links need Developer Mode or elevation, so the native ``mklink``
    without ``/J`` is tried first and a symbolic link everywhere else.

    :returns: :data:`FILE_SYMLINK`, or :data:`~tests.workspace.links.UNAVAILABLE` if the
        host permits neither. The return value never asserts success on the caller's
        behalf; the link exists only if the host allowed it.
    """
    if sys.platform == "win32":
        native = subprocess.run(
            ["cmd", "/c", "mklink", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if native.returncode == 0:
            return FILE_SYMLINK
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        return UNAVAILABLE
    return FILE_SYMLINK


FileLinkFactory = Callable[[Path, Path], str]


def make_hard_link(link: Path, target: Path) -> str:
    """Point ``link`` at the same file record as ``target``, and report the mechanism used.

    ``os.link`` is the platform's own hard-link call on Windows and POSIX alike, so there is
    no ``mklink`` fallback to reach for and no privilege to arrange first: Windows does not
    put hard links behind Developer Mode the way it does symbolic links. It can still be
    refused — a filesystem mounted without link support, or a container policy — so the
    failure is reported rather than raised, exactly as the symbolic-link helper reports its
    own.

    :returns: :data:`HARD_LINK`, or :data:`~tests.workspace.links.UNAVAILABLE` if the host
        permits none. The return value never asserts success on the caller's behalf; the link
        exists only if the host allowed it.
    """
    try:
        os.link(target, link)
    except (OSError, NotImplementedError, AttributeError):
        return UNAVAILABLE
    return HARD_LINK


HardLinkFactory = Callable[[Path, Path], str]


def require_file_link(mechanism: str, consequence: str) -> str:
    """Return the mechanism used, or fail the test saying what it left unproved.

    Serves both file-link mechanisms — the symbolic link and the hard link — because the
    thing being demanded is identical: that the host could actually build the thing the test
    is about. A silently skipped link-rejection test is a qualification gap that reads as a
    pass, so a host that cannot construct the scenario says so out loud instead.
    """
    if mechanism == UNAVAILABLE:
        pytest.fail(f"this host permits no file-link mechanism, so {consequence} is unproved here")
    return mechanism
