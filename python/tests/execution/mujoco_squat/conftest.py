"""Session fixtures for the fixed squat-model modes.

With no opt-in setting, each mode runs synchronously when its fixture is first requested,
matching the original on-demand behavior. Set DYNAMISBENCH_QA_SQUAT_PARALLEL to an integer
to opt into eager prewarming of selected modes in a bounded pool. A value of 1 reproduces
the historical one-worker matrix condition; it is not equivalent to the original scheduling.
"""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest

from tests.execution.mujoco_squat.support import run_mode

# Longest-running first, so the pool's critical path is the slowest single mode.
_MODES: Final = {
    "squat_repetition_timestep": "--repetition-timestep",
    "squat_repetition": "--repetition",
    "squat_perturb": "--perturb",
    "squat_stand": "--stand",
    "squat_statics": "--squat",
    "squat_passive": "--passive",
    "squat_report": "--report",
    "squat_flight": "--flight",
}
_MAX_PREWARM_WORKERS: Final = 4


def _parallelism() -> int | None:
    configured = os.environ.get("DYNAMISBENCH_QA_SQUAT_PARALLEL")
    if configured is None:
        return None

    requested = max(1, int(configured))
    available = max(1, min(_MAX_PREWARM_WORKERS, os.cpu_count() or 1))
    return min(requested, available)


@pytest.fixture(scope="session")
def _squat_runs(
    request: pytest.FixtureRequest,
) -> dict[str, Future[dict[str, Any]]] | None:
    workers = _parallelism()
    if workers is None:
        return None

    needed = [
        name
        for name in _MODES
        if any(name in getattr(item, "fixturenames", ()) for item in request.session.items)
    ]
    if not needed:
        return {}

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="squat-mode")
    runs = {name: pool.submit(run_mode, _MODES[name]) for name in needed}
    request.addfinalizer(lambda: pool.shutdown(wait=True))
    return runs


def _observation(name: str, runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    # Future.result re-raises the mode's own failure in the test that needs it.
    return runs[name].result()


def _mode_result(
    name: str,
    mode: str,
    runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    if runs is None:
        return run_mode(mode)
    return _observation(name, runs)


@pytest.fixture(scope="session")
def squat_report(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_report", "--report", _squat_runs)


@pytest.fixture(scope="session")
def squat_stand(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_stand", "--stand", _squat_runs)


@pytest.fixture(scope="session")
def squat_perturb(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_perturb", "--perturb", _squat_runs)


@pytest.fixture(scope="session")
def squat_passive(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_passive", "--passive", _squat_runs)


@pytest.fixture(scope="session")
def squat_flight(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_flight", "--flight", _squat_runs)


@pytest.fixture(scope="session")
def squat_statics(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_statics", "--squat", _squat_runs)


@pytest.fixture(scope="session")
def squat_repetition(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_repetition", "--repetition", _squat_runs)


@pytest.fixture(scope="session")
def squat_repetition_timestep(
    _squat_runs: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    return _mode_result("squat_repetition_timestep", "--repetition-timestep", _squat_runs)
