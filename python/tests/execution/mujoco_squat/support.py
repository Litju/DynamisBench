"""Process helpers and the independent authority of the barbell back-squat qualification.

The physical facts the tests hold the model to are written here, not imported from the code
under test: a 75 kg, 1.75 m athlete, a 20 kg barbell, standard gravity and de Leva's (1996)
male mass fractions. The adapter's own declarations are then checked against them.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Final

import pytest

from tests.execution.mujoco.support import _qualification_environment, worker_python

ATHLETE_MASS_KG: Final = 75.0
STATURE_M: Final = 1.75
BARBELL_MASS_KG: Final = 20.0
GRAVITY_M_S2: Final = 9.80665
SYSTEM_WEIGHT_N: Final = (ATHLETE_MASS_KG + BARBELL_MASS_KG) * GRAVITY_M_S2
BAR_WEIGHT_N: Final = BARBELL_MASS_KG * GRAVITY_M_S2

DE_LEVA_MALE_MASS_FRACTION: Final = {
    "head": 0.0694,
    "torso_upper": 0.1596,
    "torso_middle": 0.1633,
    "pelvis": 0.1117,
    "upper_arm": 0.0271,
    "forearm": 0.0162,
    "hand": 0.0061,
    "thigh": 0.1416,
    "shank": 0.0433,
    "foot": 0.0137,
}
"""de Leva (1996) Table 4, males (the pelvis entry is de Leva's lower trunk)."""

BALANCE_POINT_M: Final = 0.05
"""Declared whole-system centre-of-mass position anterior of the ankle joint line."""

MODULE: Final = "dynamisbench.adapters.mujoco.squat"


def run_mode(mode: str, *, timeout_s: int = 900) -> dict[str, Any]:
    """Run one fixed mode of the squat entry point in the isolated worker interpreter."""
    with tempfile.TemporaryDirectory(prefix="dynamisbench-squat-") as scratch:
        completed = subprocess.run(
            [str(worker_python()), "-I", "-m", MODULE, mode],
            cwd=scratch,
            env=_qualification_environment(Path(scratch)),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    if completed.returncode != 0:
        pytest.fail(f"{MODULE} {mode} exited {completed.returncode}: {completed.stderr[-4000:]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        pytest.fail(f"{MODULE} {mode} did not emit one JSON object: {error}")
    assert isinstance(payload, dict)
    assert payload["schema"] == "dynamisbench.mujoco.squat.observation/1"
    assert payload["mode"] == mode.removeprefix("--")
    assert payload["engine"] == "mujoco"
    return payload


def run_raw(arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run the squat entry point with an arbitrary argument vector (refusal tests)."""
    with tempfile.TemporaryDirectory(prefix="dynamisbench-squat-") as scratch:
        return subprocess.run(
            [str(worker_python()), "-I", "-m", MODULE, *arguments],
            cwd=scratch,
            env=_qualification_environment(Path(scratch)),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


def run_worker_code(code: str, *, timeout_s: int = 900) -> dict[str, Any]:
    """Run a short script in the isolated worker interpreter and parse its last JSON line.

    Used only by the negative-control tests, which must re-run the repetition with a deliberate
    defect. The production entry point has no such modes.
    """
    with tempfile.TemporaryDirectory(prefix="dynamisbench-squat-control-") as scratch:
        completed = subprocess.run(
            [str(worker_python()), "-I", "-c", code],
            cwd=scratch,
            env=_qualification_environment(Path(scratch)),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    if completed.returncode != 0:
        pytest.fail(f"the worker control script failed: {completed.stderr[-4000:]}")
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(payload, dict)
    return payload
