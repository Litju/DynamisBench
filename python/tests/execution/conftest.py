"""Shared fixtures for the execution qualification suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.execution.support import ExecutionFixture, build_fixture


@pytest.fixture
def execution_fixture(tmp_path: Path) -> ExecutionFixture:
    """One initialized workspace and one planned engine-free control run."""
    return build_fixture(tmp_path)
