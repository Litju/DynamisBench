"""Qualification-only observation of the real MuJoCo reference case.

This module is not part of the production worker and is deliberately excluded from the
adapter implementation identity. It exists so the scientific qualification suite can run
the *same* physics implementation at several timesteps, retain the full nominal trajectory,
and compare it with an independent nonlinear pendulum solution. It accepts no paths, no
model selection and no arbitrary command; the only modes are the fixed qualification run
and the non-finite guard probe.

Run it in the isolated worker environment:

    python -I -m dynamisbench.adapters.mujoco.qualification
    python -I -m dynamisbench.adapters.mujoco.qualification --nonfinite-check
"""

from __future__ import annotations

import sys
from typing import Any

from dynamisbench.adapters.mujoco import physics, reference
from dynamisbench.adapters.mujoco.diagnostics import StateSample
from dynamisbench.adapters.mujoco.identity import build_implementation_identity
from dynamisbench.identity import canonical_semantic_bytes

__all__ = ["main"]

_REFINEMENT_TIMESTEPS_S = (0.01, 0.005, 0.0025, 0.00125)
"""All values divide every reviewed checkpoint and the 2 s horizon exactly."""

_NONFINITE_SCHEMA = "dynamisbench.mujoco.nonfinite-check/1"


def _context(implementation_digest: str) -> physics.RunContext:
    return physics.RunContext(
        run_id="run-0000",
        execution_fingerprint="0" * 64,
        benchmark=reference.BENCHMARK_ID,
        scenario=reference.SCENARIO_ID,
        realization=reference.REALIZATION_ID,
        environment_id=reference.expected_environment_id(),
        seed=0,
        outcomes=(reference.OUTCOME,),
        adapter_version=reference.ADAPTER_VERSION,
        engine_version=physics.engine_version(),
        implementation_digest=implementation_digest,
    )


def _first_zero_crossing(samples: tuple[StateSample, ...]) -> float | None:
    previous = samples[0]
    for sample in samples[1:]:
        if previous.angle_rad > 0.0 >= sample.angle_rad:
            span = previous.angle_rad - sample.angle_rad
            if span == 0.0:
                return sample.time_s
            fraction = previous.angle_rad / span
            return previous.time_s + fraction * (sample.time_s - previous.time_s)
        previous = sample
    return None


def _qualification() -> dict[str, Any]:
    physics.load_model()
    identity = build_implementation_identity(
        engine_version=physics.engine_version(),
        python_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        platform_tag=reference.platform_tag(),
    )
    context = _context(identity.digest)
    nominal = physics.run_reference(context, collect_samples=True)
    crossing = _first_zero_crossing(nominal.samples)
    refinement: list[dict[str, Any]] = []
    for timestep in _REFINEMENT_TIMESTEPS_S:
        run = physics.run_reference(
            context,
            timestep_s=timestep,
            collect_samples=False,
        )
        diagnostic = run.diagnostic
        refinement.append(
            {
                "timestep_s": diagnostic.timestep_s,
                "steps": diagnostic.steps,
                "final": [
                    diagnostic.final.time_s,
                    diagnostic.final.angle_rad,
                    diagnostic.final.angular_velocity_rad_s,
                ],
                "max_relative_energy_drift": diagnostic.max_relative_energy_drift,
                "trajectory_sha256": diagnostic.trajectory_sha256,
            }
        )
    return {
        "schema": reference.QUALIFICATION_SCHEMA,
        "engine_version": physics.engine_version(),
        "platform": reference.platform_tag(),
        "python_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "model_sha256": reference.MODEL_SHA256,
        "implementation_digest": identity.digest,
        "nominal": {
            "diagnostic": nominal.diagnostic.model_dump(mode="json"),
            "first_zero_crossing_s": crossing,
            "samples": [
                [
                    sample.time_s,
                    sample.angle_rad,
                    sample.angular_velocity_rad_s,
                    sample.energy_j,
                ]
                for sample in nominal.samples
            ],
        },
        "refinement": refinement,
    }


def _nonfinite_check() -> dict[str, Any]:
    message = physics.nonfinite_probe()
    return {
        "schema": _NONFINITE_SCHEMA,
        "guard_refused": True,
        "message": message,
    }


def main(argv: list[str] | None = None) -> int:
    """Run exactly one qualification mode, or refuse an unknown argument vector."""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == []:
        payload = _qualification()
    elif arguments == ["--nonfinite-check"]:
        payload = _nonfinite_check()
    else:
        sys.stderr.write(
            "dynamisbench mujoco qualification: no arguments or --nonfinite-check only\n"
        )
        return 2
    sys.stdout.buffer.write(canonical_semantic_bytes(payload) + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
