"""Bounded, read-only receipt of the standing reference's arithmetic-path stability (RES-640).

From python/ with the isolated worker already installed:

    uv run python -m tools.mujoco_squat_reference_stability --output receipt.json

The standing reference is regenerated under several numeric-library dispatches
(``OPENBLAS_CORETYPE``, which changes the BLAS/LAPACK kernels an ``DYNAMIC_ARCH`` OpenBLAS
selects) and the results are compared three ways against the packaged keyframe: raw ``qpos``,
the declared world-frame representative, and the gauge-invariant physical state. The raw
comparison is the pre-RES-640 criterion. The receipt exists to show that a raw difference is a
world heading, not a model difference, and to bound the physical difference.

Diagnostic only. It never writes or repins the MJCF, it changes no acceptance threshold, and a
successful run qualifies nothing. Platforms whose OpenBLAS does not honour ``OPENBLAS_CORETYPE``
simply report identical rows; that is recorded, not treated as a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCHEMA = "dynamisbench.qa.squat-reference-stability/1"
DEFAULT_KERNELS = ("default", "Haswell", "Nehalem", "Sandybridge")


def _comparison(packaged_qpos: Sequence[float], generated_qpos: Sequence[float]) -> dict[str, Any]:
    """Raw, canonical and gauge-invariant agreement of one regenerated state."""
    from dynamisbench.adapters.mujoco.squat import reference  # noqa: PLC0415

    canonical_packaged = reference.canonical_world_frame(packaged_qpos)
    canonical_generated = reference.canonical_world_frame(generated_qpos)
    packaged_physical = reference.physical_state(packaged_qpos)
    generated_physical = reference.physical_state(generated_qpos)
    physical = {
        group: max(
            abs(float(a) - float(b)) for a, b in zip(values, generated_physical[group], strict=True)
        )
        for group, values in packaged_physical.items()
    }
    physical["overall"] = max(physical.values(), default=0.0)
    return {
        "raw_qpos_max_abs_difference": max(
            abs(float(a) - float(b)) for a, b in zip(packaged_qpos, generated_qpos, strict=True)
        ),
        "canonical_qpos_max_abs_difference": max(
            abs(float(a) - float(b))
            for a, b in zip(canonical_packaged, canonical_generated, strict=True)
        ),
        "physical_max_abs_difference": physical,
        "reference_heading_rad": reference.pelvis_heading_rad(generated_qpos),
    }


def _pre_projection_difference(
    packaged_qpos: Sequence[float], generated_qpos: Sequence[float], heading: float
) -> float:
    """The pre-RES-640 raw comparison, reconstructed from the reported heading.

    The generator reports the heading its relaxation landed on before projecting it away, so
    rotating the canonical state back by that heading restores the state the old criterion
    would have compared (exactly, to the rounding of one rotation).
    """
    from dynamisbench.adapters.mujoco.squat import reference  # noqa: PLC0415

    unprojected = reference.rotate_world_frame(list(generated_qpos), heading)
    return max(abs(float(a) - float(b)) for a, b in zip(packaged_qpos, unprojected, strict=True))


def collect(*, kernels: Sequence[str], runs: int) -> dict[str, Any]:
    """Regenerate the reference under each dispatch and compare every result."""
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
        raise ValueError("the packaged model does not match its reviewed SHA-256 identity")
    packaged_qpos, packaged_act = keyframe_of(content)
    rows: list[dict[str, Any]] = []
    for kernel in kernels:
        extra = {} if kernel == "default" else {"OPENBLAS_CORETYPE": kernel}
        for repeat in range(runs):
            observation = generate_keyframe(environment_extra=extra)
            row = {
                "kernel": kernel,
                "repeat": repeat + 1,
                "worker_engine_version": observation.get("engine_version"),
                "worker_python_version": observation.get("python_version"),
                "raw_relaxation_heading_rad": float(
                    observation["relaxation_heading_before_projection_rad"]
                ),
                "act_max_abs_difference": max(
                    abs(float(a) - float(b))
                    for a, b in zip(packaged_act, observation["act"], strict=True)
                ),
                **_comparison(packaged_qpos, observation["qpos"]),
            }
            row["pre_projection_max_abs_difference"] = _pre_projection_difference(
                packaged_qpos,
                observation["qpos"],
                row["raw_relaxation_heading_rad"],
            )
            row["raw_within_tolerance"] = (
                row["raw_qpos_max_abs_difference"] <= KEYFRAME_TOLERANCE
                and row["act_max_abs_difference"] <= KEYFRAME_TOLERANCE
            )
            row["pre_projection_within_tolerance"] = (
                row["pre_projection_max_abs_difference"] <= KEYFRAME_TOLERANCE
                and row["act_max_abs_difference"] <= KEYFRAME_TOLERANCE
            )
            row["canonical_within_tolerance"] = (
                row["canonical_qpos_max_abs_difference"] <= KEYFRAME_TOLERANCE
                and row["act_max_abs_difference"] <= KEYFRAME_TOLERANCE
            )
            rows.append(row)
    return {
        "schema": SCHEMA,
        "claim": "diagnostic_only_not_a_scientific_or_release_qualification",
        "tolerance_unchanged": KEYFRAME_TOLERANCE,
        "packaged_model_sha256": digest,
        "packaged_reference_heading_rad": reference.pelvis_heading_rad(packaged_qpos),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
        },
        "kernels": list(kernels),
        "runs_per_kernel": runs,
        "rows": rows,
        "raw_heading_spread_rad": max(row["raw_relaxation_heading_rad"] for row in rows)
        - min(row["raw_relaxation_heading_rad"] for row in rows),
        "worst_raw_qpos_difference": max(row["raw_qpos_max_abs_difference"] for row in rows),
        "worst_pre_projection_difference": max(
            row["pre_projection_max_abs_difference"] for row in rows
        ),
        "worst_canonical_qpos_difference": max(
            row["canonical_qpos_max_abs_difference"] for row in rows
        ),
        "worst_physical_difference": max(
            row["physical_max_abs_difference"]["overall"] for row in rows
        ),
        "all_raw_within_tolerance": all(row["raw_within_tolerance"] for row in rows),
        "all_pre_projection_within_tolerance": all(
            row["pre_projection_within_tolerance"] for row in rows
        ),
        "all_canonical_within_tolerance": all(row["canonical_within_tolerance"] for row in rows),
        "distinct_raw_relaxation_headings": len(
            {row["raw_relaxation_heading_rad"] for row in rows}
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kernels",
        default=",".join(DEFAULT_KERNELS),
        help="comma-separated OPENBLAS_CORETYPE values, or 'default' for the host dispatch",
    )
    parser.add_argument("--runs", type=int, default=2, help="regenerations per dispatch (1–5)")
    parser.add_argument("--output", type=Path, help="optional JSON file, created without overwrite")
    options = parser.parse_args(argv)
    kernels = tuple(name.strip() for name in options.kernels.split(",") if name.strip())
    if not kernels:
        parser.error("--kernels needs at least one value")
    if not 1 <= options.runs <= 5:
        parser.error("--runs must be between 1 and 5")
    try:
        summary = collect(kernels=kernels, runs=options.runs)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        sys.stderr.write(f"mujoco_squat_reference_stability: {error}\n")
        return 1
    data = json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if options.output is None:
        sys.stdout.write(data)
    else:
        with options.output.open("x", encoding="utf-8") as handle:
            handle.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
