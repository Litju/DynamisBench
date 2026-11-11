from __future__ import annotations

from unittest.mock import Mock

import pytest

from tests.execution.mujoco_squat import conftest as squat_fixtures


def test_default_squat_mode_is_synchronous_and_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DYNAMISBENCH_QA_SQUAT_PARALLEL", raising=False)
    assert squat_fixtures._parallelism() is None

    expected = {"mode": "--stand"}
    run_mode = Mock(return_value=expected)
    monkeypatch.setattr(squat_fixtures, "run_mode", run_mode)

    result = squat_fixtures._mode_result("squat_stand", "--stand", None)

    assert result is expected
    run_mode.assert_called_once_with("--stand")


@pytest.mark.parametrize(
    ("configured", "cpu_count", "expected"),
    [
        (None, 8, None),
        ("1", 8, 1),
        ("4", 8, 4),
        ("99", 8, 4),
        ("4", 2, 2),
    ],
    ids=[
        "unset-is-synchronous",
        "one-worker-is-explicit",
        "four-worker-opt-in",
        "worker-count-is-capped",
        "worker-count-is-capped-by-cpus",
    ],
)
def test_squat_prewarming_requires_opt_in_and_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
    cpu_count: int,
    expected: int | None,
) -> None:
    if configured is None:
        monkeypatch.delenv("DYNAMISBENCH_QA_SQUAT_PARALLEL", raising=False)
    else:
        monkeypatch.setenv("DYNAMISBENCH_QA_SQUAT_PARALLEL", configured)
    monkeypatch.setattr(squat_fixtures.os, "cpu_count", lambda: cpu_count)

    assert squat_fixtures._parallelism() == expected
