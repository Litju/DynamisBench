"""Collect bounded, read-only squat keyframe regeneration diagnostics (RES-640).

From python/ with the isolated worker already installed:

    uv run python -m tools.mujoco_squat_keyframe_probe --runs 3 --output keyframe-probe.json

The probe never regenerates, overwrites, or repins the canonical MJCF. Its output is
DIAGNOSTIC ONLY: a successful probe process does not qualify numerical reproducibility.
The existing keyframe check, acceptance threshold, and CI gate remain unchanged.

Two comparisons are reported for every run, and the difference between them is the point.
``versus_packaged`` compares raw ``qpos`` vectors. ``canonical_versus_packaged`` first removes
the model's exact world-frame gauge (a rigid rotation about the vertical axis, which no
physical quantity of this model depends on) from both vectors. ``physical_versus_packaged``
compares the gauge-invariant state directly: hinge angles, pelvis height and tilt, and the
barbell's pose in the pelvis frame. Raw ``qpos`` drift that is not accompanied by physical
drift is a heading, not a model difference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.keyframe_metrics import vector_diagnostics

SCHEMA = "dynamisbench.qa.squat-keyframe-probe/2"
MAX_RUNS = 5


def _max_abs_difference(
    reference_state: Mapping[str, Any], observed: Mapping[str, Any]
) -> dict[str, float]:
    """Largest absolute difference in each gauge-invariant group, and overall."""
    groups: dict[str, float] = {}
    for group, values in reference_state.items():
        observed_values = observed[group]
        if len(values) != len(observed_values):
            raise ValueError(f"the physical group {group} changed length")
        groups[group] = max(
            (abs(float(a) - float(b)) for a, b in zip(values, observed_values, strict=True)),
            default=0.0,
        )
    groups["overall"] = max(groups.values(), default=0.0)
    return groups


def summarize_observations(
    packaged_qpos: Sequence[float],
    packaged_act: Sequence[float],
    observations: Sequence[Mapping[str, Any]],
    *,
    tolerance: float,
    model_sha256: str,
    packaged_physical: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare generated states against the pinned one and one another, without mutation."""
    if not observations or len(observations) > MAX_RUNS:
        raise ValueError("the probe requires one to five observations")
    from dynamisbench.adapters.mujoco.squat import reference  # noqa: PLC0415

    if packaged_physical is None:
        packaged_physical = reference.physical_state(packaged_qpos)
    canonical_packaged = reference.canonical_world_frame(packaged_qpos)
    report: list[dict[str, Any]] = []
    first_qpos = observations[0]["qpos"]
    first_act = observations[0]["act"]
    first_static_qpos = observations[0]["static_solution_qpos"]
    first_static_act = observations[0]["static_solution_act"]
    first_canonical = reference.canonical_world_frame(first_qpos)
    for index, observation in enumerate(observations):
        qpos = observation["qpos"]
        act = observation["act"]
        canonical = reference.canonical_world_frame(qpos)
        heading = reference.pelvis_heading_rad(qpos)
        raw_heading = float(observation["relaxation_heading_before_projection_rad"])
        if not (math.isfinite(heading) and math.isfinite(raw_heading)):
            raise ValueError("generated headings must be finite")
        qpos_comparison = vector_diagnostics(packaged_qpos, qpos, tolerance=tolerance)
        act_comparison = vector_diagnostics(packaged_act, act, tolerance=tolerance)
        canonical_qpos = vector_diagnostics(canonical_packaged, canonical, tolerance=tolerance)
        pair_qpos = vector_diagnostics(first_qpos, qpos, tolerance=tolerance)
        pair_act = vector_diagnostics(first_act, act, tolerance=tolerance)
        canonical_pair = vector_diagnostics(first_canonical, canonical, tolerance=tolerance)
        # Zero means bitwise-identical inputs, not an adopted scientific tolerance.
        static_qpos = vector_diagnostics(
            first_static_qpos, observation["static_solution_qpos"], tolerance=0.0
        )
        static_act = vector_diagnostics(
            first_static_act, observation["static_solution_act"], tolerance=0.0
        )
        speed = float(observation["relaxation_final_max_speed"])
        if not (0 <= speed < float("inf")):
            raise ValueError("generated relaxation speed must be finite and nonnegative")
        report.append(
            {
                "run_index": index + 1,
                "worker_engine_version": observation.get("engine_version"),
                "worker_python_version": observation.get("python_version"),
                "relaxation_final_max_speed": speed,
                "relaxation_heading_before_projection_rad": raw_heading,
                "reference_heading_rad": heading,
                "static_solution_heading_rad": reference.pelvis_heading_rad(
                    observation["static_solution_qpos"]
                ),
                # Raw coordinate comparison: includes the world heading.
                "versus_packaged": {"qpos": qpos_comparison, "act": act_comparison},
                # The same criterion applied to the declared world-frame representative.
                "canonical_versus_packaged": {"qpos": canonical_qpos, "act": act_comparison},
                # Directly gauge-invariant: what the model actually is.
                "physical_versus_packaged": _max_abs_difference(
                    packaged_physical, reference.physical_state(qpos)
                ),
                "versus_first_run": {"qpos": pair_qpos, "act": pair_act},
                "canonical_versus_first_run": {"qpos": canonical_pair, "act": pair_act},
                "static_solution_versus_first": {
                    "qpos": static_qpos,
                    "act": static_act,
                },
            }
        )
    return {
        "schema": SCHEMA,
        "claim": "diagnostic_only_not_a_scientific_or_release_qualification",
        "sample_count": len(report),
        "tolerance_unchanged": tolerance,
        "packaged_model_sha256": model_sha256,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        # The initial static solve is distinct from the final forward-dynamics relaxation.
        # Retain raw first-run vectors to enable direct cross-platform comparison.
        "first_run_static_solution": {
            "qpos": list(first_static_qpos),
            "act": list(first_static_act),
        },
        "first_run_relaxed_state": {"qpos": list(first_qpos), "act": list(first_act)},
        "first_run_canonical_state": {"qpos": list(first_canonical), "act": list(first_act)},
        "first_run_physical_state": reference.physical_state(first_qpos),
        "first_run_headings": {
            "relaxation_before_projection_rad": report[0][
                "relaxation_heading_before_projection_rad"
            ],
            "reference_rad": report[0]["reference_heading_rad"],
            "static_solution_rad": report[0]["static_solution_heading_rad"],
        },
        "all_within_current_tolerance": all(
            row["versus_packaged"][kind]["within_tolerance"]
            for row in report
            for kind in ("qpos", "act")
        ),
        "all_canonical_within_current_tolerance": all(
            row["canonical_versus_packaged"][kind]["within_tolerance"]
            for row in report
            for kind in ("qpos", "act")
        ),
        "runs": report,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="1–5 isolated regeneration runs")
    parser.add_argument("--output", type=Path, help="optional JSON file, created without overwrite")
    options = parser.parse_args(argv)
    if not 1 <= options.runs <= MAX_RUNS:
        parser.error(f"--runs must be between 1 and {MAX_RUNS}")

    # Delayed import keeps analysis helpers usable without MuJoCo or a worker environment.
    from tools.mujoco_squat_model import (  # noqa: PLC0415
        ASSET,
        KEYFRAME_TOLERANCE,
        generate_keyframe,
        keyframe_of,
    )

    from dynamisbench.adapters.mujoco.squat import contract, reference  # noqa: PLC0415

    content = ASSET.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != contract.MODEL_SHA256:
        parser.error("the packaged model does not match its reviewed SHA-256 identity")
    qpos, act = keyframe_of(content)
    observed = [generate_keyframe() for _ in range(options.runs)]
    summary = summarize_observations(
        qpos,
        act,
        observed,
        tolerance=KEYFRAME_TOLERANCE,
        model_sha256=digest,
        packaged_physical=reference.physical_state(qpos),
    )
    data = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if options.output is None:
        sys.stdout.write(data)
    else:
        # No replace/overwrite: diagnostic evidence is intentionally append-only by filename.
        with options.output.open("x", encoding="utf-8") as handle:
            handle.write(data)
    return 0  # collection succeeded; verdict is reported, NOT silently accepted


if __name__ == "__main__":
    raise SystemExit(main())
