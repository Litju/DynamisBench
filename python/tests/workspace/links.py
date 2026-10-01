"""Constructing a directory link the operating system will actually permit.

Windows refuses to create a symbolic link unless Developer Mode is on or the process is
elevated, but a directory *junction* needs neither — so a junction is tried first there,
and a symbolic link everywhere else. Which mechanism was used is reported rather than
assumed, so a test can state exactly what it proved and a silent skip is impossible.

The choice is about test *setup* only. The containment behaviour under test is the
resolver's, and it is proved with whatever link the host allows; on a host that allows
neither, the caller is told so and the qualification report records the limitation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

UNAVAILABLE = "unavailable"
"""Returned by :func:`make_directory_link` when the host permits neither mechanism."""


def make_directory_link(link: Path, target: Path) -> str:
    """Point ``link`` at ``target`` as a directory, and report the mechanism used.

    :returns: ``"junction"``, ``"symlink"``, or :data:`UNAVAILABLE` if the host permits
        neither. The link is created when the host allows it; the return value never
        asserts success on the caller's behalf.
    """
    if sys.platform == "win32":
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode == 0:
            return "junction"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        return UNAVAILABLE
    return "symlink"


DirectoryLinkFactory = Callable[[Path, Path], str]


def require_directory_link(mechanism: str, consequence: str) -> str:
    """Return the mechanism used, or fail the test saying what it left unproved.

    A silently skipped containment test is a qualification gap that reads as a pass, so a
    host that cannot construct the scenario says so out loud instead.
    """
    if mechanism == UNAVAILABLE:
        pytest.fail(
            f"this host permits no directory-link mechanism, so {consequence} is unproved here"
        )
    return mechanism
