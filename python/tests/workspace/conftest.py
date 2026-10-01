"""Shared fixtures for the workspace qualification suites.

Nothing here makes scientific assertions; it only supplies the temporary roots and the
host's directory-link capability that every suite needs, in one place, so no individual
test has to decide how to obtain them.
"""

from __future__ import annotations

import pytest

from tests.workspace.links import DirectoryLinkFactory, make_directory_link


@pytest.fixture
def link_maker() -> DirectoryLinkFactory:
    """Create a directory link using whichever mechanism this host permits."""
    return make_directory_link
