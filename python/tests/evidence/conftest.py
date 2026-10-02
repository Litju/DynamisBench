"""Shared fixtures for the evidence qualification suites.

The evidence suite needs exactly two things from its host: an initialized workspace whose
roots are temporary, and whichever link mechanisms this host permits. Both are supplied here
so that no individual test decides how to obtain them, and so that a test which needs a link
says so loudly when the host cannot create one instead of skipping.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from dynamisbench.workspace import PersistenceClass, Workspace, initialize_workspace
from tests.evidence.links import FileLinkFactory, HardLinkFactory, make_file_link, make_hard_link
from tests.workspace.links import DirectoryLinkFactory, make_directory_link


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    """Two independent temporary directories standing in for the two scientific roots."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    source.mkdir()
    evidence.mkdir()
    return source, evidence


@pytest.fixture
def workspace(roots: tuple[Path, Path]) -> Iterator[Workspace]:
    """An initialized workspace, created fresh for each test.

    Every test gets its own temporary roots, so no test can read or damage a developer's
    real evidence directory, and a test that mutates a bundle cannot affect another.
    """
    source, evidence = roots
    yield initialize_workspace(source, evidence)


@pytest.fixture
def staging_path(workspace: Workspace) -> Path:
    """The declared staging location, for tests that plant a bundle without the API."""
    return workspace.location(PersistenceClass.STAGING).path


@pytest.fixture
def runs_path(workspace: Workspace) -> Path:
    """The declared sealed-evidence location, which initialization deliberately skips."""
    return workspace.location(PersistenceClass.SEALED_EVIDENCE).path


@pytest.fixture(scope="module")
def link_maker() -> DirectoryLinkFactory:
    """Create a directory link using whichever mechanism this host permits.

    Module-scoped because it holds no state, and a Hypothesis property that plants links
    would otherwise trip the function-scoped-fixture health check for no reason.
    """
    return make_directory_link


@pytest.fixture(scope="module")
def file_link_maker() -> FileLinkFactory:
    """Create a *file* link using whichever mechanism this host permits."""
    return make_file_link


@pytest.fixture(scope="module")
def hard_link_maker() -> HardLinkFactory:
    """Create a second directory entry for the same file record, if this host permits it."""
    return make_hard_link
