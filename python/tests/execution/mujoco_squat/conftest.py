"""Session fixtures: each fixed squat-model mode runs once in the isolated worker."""

from __future__ import annotations

from typing import Any

import pytest

from tests.execution.mujoco_squat.support import run_mode


@pytest.fixture(scope="session")
def squat_report() -> dict[str, Any]:
    return run_mode("--report")


@pytest.fixture(scope="session")
def squat_stand() -> dict[str, Any]:
    return run_mode("--stand")


@pytest.fixture(scope="session")
def squat_perturb() -> dict[str, Any]:
    return run_mode("--perturb")


@pytest.fixture(scope="session")
def squat_passive() -> dict[str, Any]:
    return run_mode("--passive")


@pytest.fixture(scope="session")
def squat_flight() -> dict[str, Any]:
    return run_mode("--flight")


@pytest.fixture(scope="session")
def squat_statics() -> dict[str, Any]:
    return run_mode("--squat")


@pytest.fixture(scope="session")
def squat_repetition() -> dict[str, Any]:
    return run_mode("--repetition")


@pytest.fixture(scope="session")
def squat_repetition_timestep() -> dict[str, Any]:
    return run_mode("--repetition-timestep")
