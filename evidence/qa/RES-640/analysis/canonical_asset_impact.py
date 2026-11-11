"""RES-640: what re-expressing the packaged keyframe in the declared world frame would change.

The repair projects the *compared* vectors; it does not rewrite the packaged asset. This script
quantifies the follow-up that would: it canonicalises the packaged keyframe in place, re-renders
and compiles the asset, and compares every diagnostic the qualification suite reads.

Run from ``python/`` with the isolated worker interpreter and ``PYTHONPATH=src``:

    worker-mujoco/.venv/Scripts/python.exe \
        ../evidence/qa/RES-640/analysis/canonical_asset_impact.py

Read-only: it compiles in memory and never writes the asset.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import mujoco
import numpy as np

from dynamisbench.adapters.mujoco.squat import engine, mjcf, reference
from tools.mujoco_squat_model import keyframe_of


def _flatten(prefix: str, value: Any, output: dict[str, float]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), item, output)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        output[prefix] = float(value)
    elif isinstance(value, str):
        return
    else:
        return


def diagnostics(model, qpos, activation) -> tuple[dict[str, float], str]:
    """Every number the squat qualification reads about one keyframe state, and its hash."""
    values: dict[str, Any] = {
        "keyframe": engine.keyframe_diagnostics(model),
        "posture": engine.posture_kinematics(model, qpos),
    }
    equilibrium = engine.static_equilibrium(model, qpos)
    values["static_residual"] = equilibrium.residual
    values["activation"] = [float(value) for value in equilibrium.activation]
    values["torque"] = [float(value) for value in equilibrium.torque]
    values["centre_of_pressure"] = {
        side: [float(v) for v in point] for side, point in equilibrium.centre_of_pressure.items()
    }
    values["shelf_wrench"] = [float(value) for value in equilibrium.shelf_wrench_on_bar]
    summary = engine.simulate(
        model,
        qpos,
        activation,
        controller=engine.controller_for(model, qpos, activation),
        duration_s=1.0,
        sample_period_s=0.1,
    )
    values["standing"] = {
        field: getattr(summary, field)
        for field in (
            "duration_s",
            "steps",
            "all_finite",
            "joint_max_deviation_deg",
            "joint_final_deviation_deg",
            "joint_limit_max_violation_deg",
            "vertical_grf_mean_last_s_n",
            "vertical_grf_min_n",
            "vertical_grf_max_n",
            "min_loaded_sole_contacts",
            "final_loaded_sole_contacts",
            "min_geometric_sole_contacts",
            "min_contact_point_load_n",
            "foot_max_slip_m",
            "weld_max_position_error_m",
            "weld_max_angle_error_deg",
            "grip_max_error_m",
            "shelf_force_mean_last_s_n",
            "max_abs_activation",
            "saturated_fraction",
            "cop_anterior_mean_last_s_m",
            "bar_max_tilt_deg",
            "max_floor_penetration_m",
            "com_max_horizontal_excursion_m",
            "com_min_height_m",
        )
    }
    values["standing_samples"] = [
        {key: sample[key] for key in ("grf_z", "joint_dev_deg", "loaded_contacts")}
        for sample in summary.samples
    ]
    values["trajectory_sha256"] = summary.trajectory_sha256
    values["com_initial"] = [float(value) for value in summary.com_initial]
    values["com_final"] = [float(value) for value in summary.com_final]
    flattened: dict[str, float] = {}
    _flatten("", values, flattened)
    return flattened, summary.trajectory_sha256


def main() -> None:
    content = engine.contract.model_bytes()
    packaged_qpos, packaged_activation = keyframe_of(content)
    qpos = np.array(packaged_qpos, dtype=np.float64)
    activation = np.array(packaged_activation, dtype=np.float64)
    canonical = np.array(reference.canonical_world_frame(packaged_qpos), dtype=np.float64)
    original = mujoco.MjModel.from_xml_string(content.decode("utf-8"))
    canonicalised_bytes = mjcf.render_model_xml(
        [float(value) for value in canonical], [float(value) for value in activation]
    ).encode("utf-8")
    rewritten = mujoco.MjModel.from_xml_string(canonicalised_bytes.decode("utf-8"))

    before, before_hash = diagnostics(original, qpos, activation)
    after, after_hash = diagnostics(rewritten, canonical, activation)
    differences = {
        key: abs(before[key] - after[key]) for key in before if key in after
    }
    changed = {
        key: value
        for key, value in sorted(differences.items(), key=lambda item: -item[1])
        if value > 0.0
    }
    physical_keys = {
        key: value
        for key, value in changed.items()
        if not key.startswith(("keyframe.com_", "posture.com_x", "posture.com_z"))
        and not key.startswith(("posture.bar_x", "posture.knee_x", "posture.toe_x"))
    }
    print(
        json.dumps(
            {
                "schema": "dynamisbench.qa.squat-canonical-asset-impact/1",
                "claim": "diagnostic_only_not_a_scientific_or_release_qualification",
                "packaged_sha256": hashlib.sha256(content).hexdigest(),
                "canonicalised_sha256": hashlib.sha256(canonicalised_bytes).hexdigest(),
                "keyframe_heading_before_rad": reference.pelvis_heading_rad(qpos),
                "keyframe_heading_after_rad": reference.pelvis_heading_rad(canonical),
                "rendered_qpos_change_max_abs": max(
                    abs(a - b) for a, b in zip(qpos, canonical, strict=True)
                ),
                "largest_changes": dict(list(changed.items())[:20]),
                "largest_change_outside_world_frame_coordinates": dict(
                    list(physical_keys.items())[:10]
                ),
                "unchanged_diagnostics": sum(1 for value in differences.values() if value == 0.0),
                "compared_diagnostics": len(differences),
                "trajectory_hash_unchanged": before_hash == after_hash,
                "all_finite": bool(after.get("standing.all_finite", 1.0)),
                "math_isfinite": all(math.isfinite(value) for value in before.values())
                and all(math.isfinite(value) for value in after.values()),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
