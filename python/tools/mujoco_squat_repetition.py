"""Run one back-squat repetition in the isolated worker and write its outputs as plain files.

    uv run python tools/mujoco_squat_repetition.py --output <directory> [--timestep-study]

Writes, into ``<directory>``:

* ``repetition_summary.json`` - plan, phase events, measured phases, extrema, work and energy
  per phase, and the summary metrics;
* ``repetition_timeseries.csv`` - 100 Hz series: phase, depth intent, every joint angle,
  velocity, reference angle and torque, barbell pose and velocity, centre of mass, per-foot
  ground reaction, planned vertical ground reaction, centre of pressure, stability margins
  against the polygon of load-bearing contacts, load-bearing contact count, the normal load at
  each of the ten plantar contact points, per-foot heel load share, actuator power and shelf
  force; every column of a row describes the same instant;
* ``repetition_qpos.csv`` - the full MuJoCo configuration at the same instants (for replay);
* ``timestep_study.json`` (with ``--timestep-study``) - the repetition at the model timestep
  and at half of it, and their largest differences.

These are diagnostic outputs of a model run, not DynamisBench native, canonical or assessment
evidence. The application runtime never imports MuJoCo: the worker interpreter does the work.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from dynamisbench.adapters.mujoco.squat.mjcf import SOLE_POINTS

__all__ = ["main", "run_mode", "write_outputs"]

PYTHON_DIRECTORY: Final = Path(__file__).resolve().parents[1]
MODULE: Final = "dynamisbench.adapters.mujoco.squat"


def worker_python() -> Path:
    configured = os.environ.get("DYNAMISBENCH_MUJOCO_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else PYTHON_DIRECTORY
        / "worker-mujoco"
        / ".venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not candidate.is_file():
        raise RuntimeError(
            f"the isolated MuJoCo worker environment is not provisioned at {candidate}; "
            "run `uv sync --frozen --project worker-mujoco` in python/"
        )
    return candidate


def run_mode(mode: str) -> dict[str, Any]:
    """Run one fixed mode of the squat entry point and return its JSON observation."""
    with tempfile.TemporaryDirectory(prefix="dynamisbench-squat-repetition-") as scratch:
        environment = {"PYTHONHASHSEED": "0", "TMP": scratch, "TEMP": scratch}
        for name in ("SYSTEMROOT", "WINDIR", "PATH", "HOME", "USERPROFILE", "LANG"):
            if name in os.environ:
                environment[name] = os.environ[name]
        completed = subprocess.run(
            [str(worker_python()), "-I", "-m", MODULE, mode],
            cwd=scratch,
            env=environment,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"{MODULE} {mode} failed: {completed.stderr[-2000:]}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{MODULE} {mode} did not emit one JSON object")
    return payload


def _timeseries_rows(repetition: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    samples = repetition["samples"]
    joints = repetition["joint_names"]
    points = [f"{side}_{point}" for side in ("l", "r") for point in SOLE_POINTS]
    header = ["t_s", "sample_index", "phase", "depth_intent_deg"]
    header += [f"{name}_angle_deg" for name in joints]
    header += [f"{name}_velocity_deg_s" for name in joints]
    header += [f"{name}_reference_deg" for name in joints]
    header += [f"{name}_torque_nm" for name in joints]
    header += ["bar_x_m", "bar_y_m", "bar_z_m", "bar_vx_m_s", "bar_vy_m_s", "bar_vz_m_s"]
    header += ["bar_tilt_deg", "com_x_m", "com_y_m", "com_z_m", "com_vx_m_s", "com_vy_m_s"]
    header += ["com_vz_m_s", "pelvis_z_m", "trunk_inclination_deg"]
    header += ["grf_left_x_n", "grf_left_y_n", "grf_left_z_n"]
    header += ["grf_right_x_n", "grf_right_y_n", "grf_right_z_n", "grf_planned_z_n"]
    header += ["cop_x_m", "cop_y_m", "cop_margin_m", "xcom_margin_m", "loaded_contacts"]
    header += [f"contact_{point}_normal_n" for point in points]
    header += ["heel_load_fraction_min_foot", "actuator_power_w", "shelf_force_n"]
    header += ["activation_max"]
    rows = []
    for i, time_s in enumerate(samples["t"]):
        rows.append(
            [time_s, samples["sample_index"][i], samples["phase"][i]]
            + [samples["depth_intent_deg"][i]]
            + list(samples["joint_angle_deg"][i])
            + list(samples["joint_velocity_deg_s"][i])
            + list(samples["reference_angle_deg"][i])
            + list(samples["joint_torque_nm"][i])
            + list(samples["bar_position_m"][i])
            + list(samples["bar_velocity_m_s"][i])
            + [samples["bar_tilt_deg"][i]]
            + list(samples["com_position_m"][i])
            + list(samples["com_velocity_m_s"][i])
            + [samples["pelvis_height_m"][i], samples["trunk_inclination_deg"][i]]
            + list(samples["grf_left_n"][i])
            + list(samples["grf_right_n"][i])
            + [samples["grf_planned_vertical_n"][i]]
            + list(samples["cop_m"][i])
            + [samples["cop_margin_m"][i], samples["xcom_margin_m"][i]]
            + [samples["loaded_contacts"][i]]
            + list(samples["contact_normal_n"][i])
            + [samples["heel_load_fraction"][i]]
            + [samples["actuator_power_w"][i], samples["shelf_force_n"][i]]
            + [samples["activation_max"][i]]
        )
    return header, rows


def write_outputs(output: Path, *, timestep_study: bool) -> list[Path]:
    """Run the repetition (and optionally the timestep study) and write the output files."""
    output.mkdir(parents=True, exist_ok=True)
    payload = run_mode("--repetition")
    repetition = payload["repetition"]
    written = []
    summary = {key: value for key, value in payload.items() if key != "repetition"}
    summary["repetition"] = {
        key: value for key, value in repetition.items() if key not in ("samples", "joint_names")
    }
    path = output / "repetition_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(path)
    header, rows = _timeseries_rows(repetition)
    path = output / "repetition_timeseries.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    written.append(path)
    path = output / "repetition_qpos.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        qpos = repetition["samples"]["qpos"]
        writer.writerow(["t_s"] + [f"qpos_{i}" for i in range(len(qpos[0]))])
        for time_s, row in zip(repetition["samples"]["t"], qpos, strict=True):
            writer.writerow([time_s, *row])
    written.append(path)
    if timestep_study:
        path = output / "timestep_study.json"
        study = run_mode("--repetition-timestep")
        path.write_text(json.dumps(study, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="directory to write into")
    parser.add_argument(
        "--timestep-study", action="store_true", help="also run the timestep comparison"
    )
    arguments = parser.parse_args(argv)
    try:
        written = write_outputs(arguments.output, timestep_study=arguments.timestep_study)
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        sys.stderr.write(f"mujoco_squat_repetition: {error}\n")
        return 1
    sys.stdout.write(json.dumps({"written": [str(path) for path in written]}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
