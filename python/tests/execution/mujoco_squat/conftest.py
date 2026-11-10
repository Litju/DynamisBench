"""Session fixtures: each fixed squat-model mode runs once in the isolated worker.

RES-622: the eight modes are independent, single-threaded, deterministic processes with no
shared state (each owns a private scratch directory and interpreter). Run one after another
they put about two minutes of wall time on the critical path of the suite. They are therefore
launched together, in a bounded pool, the first time any of them is requested, and only the
modes the *selected* tests actually use are launched. Each mode is still run exactly once,
in its own isolated process, through the same ``run_mode`` and the same assertions; a failure
of one mode fails only the tests that use it. ``DYNAMISBENCH_QA_SQUAT_PARALLEL=1`` restores the
strictly serial behaviour; the default is ``min(4, CPU count)``.
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


def _parallelism() -> int:
    configured = os.environ.get("DYNAMISBENCH_QA_SQUAT_PARALLEL")
    if configured is not None:
        return max(1, int(configured))
    return max(1, min(4, os.cpu_count() or 1))


@pytest.fixture(scope="session")
def _squat_runs(request: pytest.FixtureRequest) -> dict[str, Future[dict[str, Any]]]:
    needed = [
        name
        for name in _MODES
        if any(name in getattr(item, "fixturenames", ()) for item in request.session.items)
    ]
    workers = _parallelism()
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="squat-mode")
    # A pool of one runs the modes strictly in submission order, which is the serial behaviour.
    runs = {name: pool.submit(run_mode, _MODES[name]) for name in needed}
    request.addfinalizer(lambda: pool.shutdown(wait=True))
    return runs


def _observation(name: str, runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    # ``Future.result`` re-raises the mode's own failure (including ``pytest.fail``) here, in
    # the test that needs it.
    return runs[name].result()


@pytest.fixture(scope="session")
def squat_report(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_report", _squat_runs)


@pytest.fixture(scope="session")
def squat_stand(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_stand", _squat_runs)


@pytest.fixture(scope="session")
def squat_perturb(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_perturb", _squat_runs)


@pytest.fixture(scope="session")
def squat_passive(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_passive", _squat_runs)


@pytest.fixture(scope="session")
def squat_flight(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_flight", _squat_runs)


@pytest.fixture(scope="session")
def squat_statics(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_statics", _squat_runs)


@pytest.fixture(scope="session")
def squat_repetition(_squat_runs: dict[str, Future[dict[str, Any]]]) -> dict[str, Any]:
    return _observation("squat_repetition", _squat_runs)


@pytest.fixture(scope="session")
def squat_repetition_timestep(
    _squat_runs: dict[str, Future[dict[str, Any]]],
) -> dict[str, Any]:
    return _observation("squat_repetition_timestep", _squat_runs)
