"""Independent energy oracle and nonzero positive control for RES-640."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.execution.mujoco_squat.support import run_worker_code


def test_energy_symmetry_uses_a_measurement_that_detects_vertical_lift(
    record_testsuite_property: Callable[[str, str], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = (
        Path(__file__).resolve().parents[4] / "evidence/qa/RES-640/analysis/energy_qualification.py"
    )
    receipt = run_worker_code(f"import runpy; runpy.run_path({str(script)!r}, run_name='__main__')")
    encoded = json.dumps(receipt, sort_keys=True)
    record_testsuite_property("RES-640 energy receipt", encoded)
    # JUnit is consumed but not uploaded by quality.yml; preserve detailed controls
    # in the retained job log without adding a diagnostic CI step or artifact.
    with capsys.disabled():
        print("RES640_ENERGY_RECEIPT " + encoded, flush=True)
    assert receipt["environment"]["mujoco"] == "3.17.0"
    assert receipt["disabled_energy_sample"]["mujoco_potential_j"] == 0.0
    assert receipt["baseline"]["mujoco_potential_j"] > 100.0
    assert receipt["expected_lift_energy_j"] > 100.0
    assert len(receipt["yaw_controls"]) == 8
