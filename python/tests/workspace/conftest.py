"""Shared fixtures for the workspace qualification suites.

Nothing here makes scientific assertions; it only supplies the temporary roots and the
host's directory-link capability that every suite needs, in one place, so no individual
test has to decide how to obtain them.
"""

from __future__ import annotations

import pytest

from tests.workspace.links import DirectoryLinkFactory, make_directory_link


@pytest.fixture(scope="module")
def link_maker() -> DirectoryLinkFactory:
    """Create a directory link using whichever mechanism this host permits.

    Module-scoped because it is a plain function over no state, and a Hypothesis property
    that plants links would otherwise trip the function-scoped-fixture health check for no
    reason.
    """
    return make_directory_link
