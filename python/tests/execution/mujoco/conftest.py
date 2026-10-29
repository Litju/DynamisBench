"""Shared real-MuJoCo fixtures for RES-550 qualification."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.execution.mujoco.support import (
    ExecutionFixture,
    assert_identity_is_the_reviewed_environment,
    build_mujoco_fixture,
    run_nonfinite_probe,
    run_qualification,
    run_worker_identity,
)


@pytest.fixture(scope="session")
def mujoco_identity() -> dict:
    """One installed-worker identity for this qualification session."""
    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-identity-") as scratch:
        identity = run_worker_identity(Path(scratch))
    assert_identity_is_the_reviewed_environment(identity)
    return identity


@pytest.fixture(scope="session")
def mujoco_qualification() -> dict:
    """One full fixed-reference qualification observation for the session."""
    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-qualification-") as scratch:
        return run_qualification(Path(scratch))


@pytest.fixture(scope="session")
def mujoco_nonfinite_probe() -> dict:
    """One real-MuJoCo non-finite guard probe for the session."""
    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-nonfinite-") as scratch:
        return run_nonfinite_probe(Path(scratch))


@pytest.fixture
def mujoco_fixture(tmp_path: Path, mujoco_identity: dict) -> ExecutionFixture:
    """A fresh workspace and planned reference run for one test."""
    return build_mujoco_fixture(tmp_path, identity=mujoco_identity)
