"""Emit one durable numerical-qualification receipt for the RES-550 MuJoCo reference.

The receipt is a CI qualification artifact, not ``native/``, ``canonical/`` or
``assessment.json`` scientific evidence. It records one real isolated-worker observation and
an independent numerical comparison, with the exact authority, runtime, dependency closure,
predeclared tolerances and verdict needed to inspect the claim later.

Run from ``python/`` with the isolated worker environment provisioned:

    uv run python tools/mujoco_qualification_receipt.py --target windows-x64 --output ...

The tool never imports MuJoCo into the application runtime: it runs the qualification module
in the separately locked worker interpreter and parses its bounded JSON observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

import numpy as np
from scipy.integrate import solve_ivp
from scipy.special import ellipk

from dynamisbench.adapters.mujoco import (
    dependencies,
    qualification_criteria,
    reference,
    reference_case,
)
from dynamisbench.adapters.mujoco.diagnostics import ReferenceDiagnostic
from dynamisbench.identity import canonical_semantic_bytes
from dynamisbench.planning.runspec import run_spec_fingerprint

__all__ = ["main"]

PYTHON_DIRECTORY: Final = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT: Final = PYTHON_DIRECTORY.parent
_TARGETS: Final = {
    "windows-x64": "windows-x86-64",
    "linux-x64": "linux-x86-64",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ReceiptError(RuntimeError):
    """A qualification observation could not be established."""


def worker_python() -> Path:
    """Resolve the explicitly provisioned isolated worker interpreter."""
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
        raise ReceiptError(
            f"the isolated MuJoCo worker environment is not provisioned at {candidate}; "
            "run `uv sync --frozen --project worker-mujoco` in python/"
        )
    return candidate


def _worker_environment(scratch: Path) -> dict[str, str]:
    """The minimal, non-inherited environment the qualification interface needs."""
    values = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "TZ": "UTC",
    }
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR"):
            if name in os.environ:
                values[name] = os.environ[name]
        values["TEMP"] = str(scratch)
        values["TMP"] = str(scratch)
    else:
        values["HOME"] = str(scratch)
        values["LANG"] = "C.UTF-8"
        values["LC_ALL"] = "C.UTF-8"
        values["TMPDIR"] = str(scratch)
    return values


def _run_worker_module(module: str, arguments: tuple[str, ...], scratch: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(worker_python()), "-I", "-m", module, *arguments],
        cwd=scratch,
        env=_worker_environment(scratch),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        raise ReceiptError(
            f"the worker module {module} exited {completed.returncode}: {completed.stderr[-4000:]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ReceiptError(
            f"the worker module {module} did not emit one JSON object: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ReceiptError(f"the worker module {module} did not emit a JSON object")
    return payload


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ReceiptError(f"git rev-parse HEAD failed: {completed.stderr[-1000:]}")
    return completed.stdout.strip()


def _check(
    name: str,
    passed: bool,
    observed: object,
    limit: object,
) -> dict[str, object]:
    return {
        "name": name,
        "passed": bool(passed),
        "observed": observed,
        "limit": limit,
    }


def _authority(platform_tag: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return the pinned and independently observed authority digests."""
    observed = reference_case.reference_authority_matches_definitions()
    expected = {
        "benchmark": reference.BENCHMARK_SEMANTIC_DIGEST.hex,
        "scenario": reference.SCENARIO_SEMANTIC_DIGEST.hex,
        "realization": reference.REALIZATION_SEMANTIC_DIGEST.hex,
        "system_under_test": reference.SUT_SEMANTIC_DIGEST.hex,
        "environment_windows_x86_64": reference.ENVIRONMENT_SEMANTIC_DIGESTS["windows-x86-64"].hex,
        "environment_linux_x86_64": reference.ENVIRONMENT_SEMANTIC_DIGESTS["linux-x86-64"].hex,
    }
    if observed != expected:
        raise ReceiptError(
            "the pinned reference authority is stale against the canonical definitions: "
            f"{sorted(key for key in observed if observed[key] != expected.get(key))}"
        )
    return expected, observed


def _reference_solution(times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Solve the independent nonlinear pendulum equation at the requested times."""
    spring = (
        reference.MASS_KG
        * reference.GRAVITY_M_S2
        * reference.COM_DISTANCE_M
        / reference.HINGE_INERTIA_KG_M2
    )

    def derivative(_time: float, state: np.ndarray) -> tuple[float, float]:
        theta, omega = state
        return omega, -spring * math.sin(theta)

    solution = solve_ivp(
        derivative,
        (0.0, float(times[-1])),
        (reference.INITIAL_ANGLE_RAD, reference.INITIAL_ANGULAR_VELOCITY_RAD_S),
        t_eval=times,
        method="DOP853",
        rtol=1e-12,
        atol=1e-14,
    )
    if not solution.success or solution.y.shape[1] != len(times):
        raise ReceiptError("the independent nonlinear pendulum solve did not complete")
    return solution.y[0], solution.y[1]


def _energy(theta: np.ndarray, omega: np.ndarray) -> np.ndarray:
    return 0.5 * reference.HINGE_INERTIA_KG_M2 * omega**2 + (
        reference.MASS_KG
        * reference.GRAVITY_M_S2
        * reference.COM_DISTANCE_M
        * (1.0 - np.cos(theta))
    )


def _first_ratio(errors: list[float]) -> list[float | None]:
    return [
        (coarser / finer) if finer > 0.0 else None
        for coarser, finer in zip(errors, errors[1:], strict=False)
    ]


def _observation(
    qualification: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, object]], dict[str, Any]]:
    """Compare one worker observation with the independent numerical reference."""
    diagnostic = ReferenceDiagnostic.model_validate(qualification["nominal"]["diagnostic"])
    samples = np.asarray(qualification["nominal"]["samples"], dtype=float)
    if samples.ndim != 2 or samples.shape[1] != 4:
        raise ReceiptError("the qualification observation did not contain four-column samples")
    times, theta, omega, observed_energy = (
        samples[:, 0],
        samples[:, 1],
        samples[:, 2],
        samples[:, 3],
    )
    theta_reference, omega_reference = _reference_solution(times)
    angle_error = float(np.max(np.abs(theta - theta_reference)))
    velocity_error = float(np.max(np.abs(omega - omega_reference)))

    independent_energy = _energy(theta, omega)
    energy_reconstruction = float(np.max(np.abs(independent_energy - observed_energy)))
    initial_energy = float(independent_energy[0])
    if initial_energy == 0.0:
        raise ReceiptError("the reference initial energy is zero, so relative drift is undefined")
    relative_drift = float(
        np.max(np.abs(independent_energy - initial_energy)) / abs(initial_energy)
    )

    gradient = np.gradient(theta, times)
    interior = slice(2, -2)
    velocity_consistency = float(np.max(np.abs(gradient[interior] - omega[interior])))

    crossing = qualification["nominal"]["first_zero_crossing_s"]
    if crossing is None:
        raise ReceiptError("the qualification observation has no first zero crossing")
    observed_period = 4.0 * float(crossing)
    elliptic_parameter = math.sin(reference.INITIAL_ANGLE_RAD / 2.0) ** 2
    analytical_period = (
        4.0
        * math.sqrt(
            reference.HINGE_INERTIA_KG_M2
            / (reference.MASS_KG * reference.GRAVITY_M_S2 * reference.COM_DISTANCE_M)
        )
        * float(ellipk(elliptic_parameter))
    )
    period_error = abs(observed_period - analytical_period)

    refinement: list[dict[str, object]] = []
    errors: list[float] = []
    for entry in qualification["refinement"]:
        final_time, final_theta, _final_omega = entry["final"]
        theta_reference_at_end, _ = _reference_solution(np.asarray([0.0, float(final_time)]))
        error = abs(float(final_theta) - float(theta_reference_at_end[-1]))
        errors.append(error)
        refinement.append(
            {
                "timestep_s": float(entry["timestep_s"]),
                "steps": int(entry["steps"]),
                "final_time_s": float(final_time),
                "final_angle_rad": float(final_theta),
                "error_rad": error,
                "convergence_ratio": None,
                "max_relative_energy_drift": float(entry["max_relative_energy_drift"]),
                "trajectory_sha256": str(entry["trajectory_sha256"]),
            }
        )
    ratios = _first_ratio(errors)
    for position, ratio in enumerate(ratios):
        refinement[position]["convergence_ratio"] = ratio

    final_time_error = abs(diagnostic.final.time_s - reference.DURATION_S)
    observation = {
        "initial_state": diagnostic.initial.model_dump(mode="json"),
        "final_state": diagnostic.final.model_dump(mode="json"),
        "final_time_error_s": final_time_error,
        "trajectory_sha256": diagnostic.trajectory_sha256,
        "trajectory_sample_count": int(len(times)),
        "max_angle_error_rad": angle_error,
        "max_angular_velocity_error_rad_s": velocity_error,
        "max_velocity_consistency_error_rad_s": velocity_consistency,
        "energy_reconstruction_max_abs_j": energy_reconstruction,
        "relative_energy_drift": relative_drift,
        "diagnostic_relative_energy_drift": diagnostic.max_relative_energy_drift,
        "analytical_period_s": analytical_period,
        "observed_period_s": observed_period,
        "period_error_s": period_error,
        "refinement": refinement,
    }
    checks: list[dict[str, object]] = [
        _check(
            "final_time",
            final_time_error <= qualification_criteria.FINAL_TIME_TOLERANCE_S,
            final_time_error,
            qualification_criteria.FINAL_TIME_TOLERANCE_S,
        ),
        _check(
            "maximum_angle_error",
            angle_error <= qualification_criteria.ANGLE_TOLERANCE_RAD,
            angle_error,
            qualification_criteria.ANGLE_TOLERANCE_RAD,
        ),
        _check(
            "maximum_angular_velocity_error",
            velocity_error <= qualification_criteria.ANGULAR_VELOCITY_TOLERANCE_RAD_S,
            velocity_error,
            qualification_criteria.ANGULAR_VELOCITY_TOLERANCE_RAD_S,
        ),
        _check(
            "velocity_consistency",
            velocity_consistency <= qualification_criteria.VELOCITY_CONSISTENCY_TOLERANCE_RAD_S,
            velocity_consistency,
            qualification_criteria.VELOCITY_CONSISTENCY_TOLERANCE_RAD_S,
        ),
        _check(
            "energy_reconstruction",
            energy_reconstruction <= qualification_criteria.ENERGY_RECONSTRUCTION_TOLERANCE_J,
            energy_reconstruction,
            qualification_criteria.ENERGY_RECONSTRUCTION_TOLERANCE_J,
        ),
        _check(
            "relative_energy_drift",
            relative_drift <= qualification_criteria.ENERGY_RELATIVE_TOLERANCE,
            relative_drift,
            qualification_criteria.ENERGY_RELATIVE_TOLERANCE,
        ),
        _check(
            "diagnostic_relative_energy_drift",
            diagnostic.max_relative_energy_drift
            <= qualification_criteria.ENERGY_RELATIVE_TOLERANCE,
            diagnostic.max_relative_energy_drift,
            qualification_criteria.ENERGY_RELATIVE_TOLERANCE,
        ),
        _check(
            "finite_amplitude_period",
            period_error <= qualification_criteria.PERIOD_TOLERANCE_S,
            period_error,
            qualification_criteria.PERIOD_TOLERANCE_S,
        ),
    ]
    if not errors:
        raise ReceiptError("the qualification observation has no refinement entries")
    checks.append(
        _check(
            "refinement_final_error",
            errors[-1] <= qualification_criteria.REFINEMENT_FINAL_TOLERANCE_RAD,
            errors[-1],
            qualification_criteria.REFINEMENT_FINAL_TOLERANCE_RAD,
        )
    )
    for index, ratio in enumerate(ratios):
        checks.append(
            _check(
                f"refinement_ratio_{index}",
                ratio is not None and ratio >= qualification_criteria.REFINEMENT_MIN_RATIO,
                ratio,
                qualification_criteria.REFINEMENT_MIN_RATIO,
            )
        )
    return observation, checks, diagnostic.model_dump(mode="json")


def _identity_checks(identity: dict[str, Any], platform_tag: str) -> list[dict[str, object]]:
    payload = {key: value for key, value in identity.items() if key != "implementation_digest"}
    recomputed = hashlib.sha256(canonical_semantic_bytes(payload)).hexdigest()
    closure = identity.get("dependency_closure", {})
    packages = tuple(tuple(item) for item in closure.get("packages", ()))
    return [
        _check(
            "adapter_identity_recomputable",
            recomputed == identity.get("implementation_digest"),
            recomputed,
            identity.get("implementation_digest"),
        ),
        _check(
            "adapter_id",
            identity.get("adapter_id") == reference.ADAPTER_ID,
            identity.get("adapter_id"),
            reference.ADAPTER_ID,
        ),
        _check(
            "adapter_version",
            identity.get("adapter_version") == reference.ADAPTER_VERSION,
            identity.get("adapter_version"),
            reference.ADAPTER_VERSION,
        ),
        _check(
            "engine",
            identity.get("engine") == reference.ENGINE,
            identity.get("engine"),
            reference.ENGINE,
        ),
        _check(
            "engine_version",
            identity.get("engine_version") == reference.ENGINE_VERSION,
            identity.get("engine_version"),
            reference.ENGINE_VERSION,
        ),
        _check(
            "python_version",
            identity.get("python_version") == reference.PYTHON_VERSION,
            identity.get("python_version"),
            reference.PYTHON_VERSION,
        ),
        _check(
            "platform",
            identity.get("platform") == platform_tag,
            identity.get("platform"),
            platform_tag,
        ),
        _check(
            "model_sha256",
            identity.get("model_sha256") == reference.MODEL_SHA256,
            identity.get("model_sha256"),
            reference.MODEL_SHA256,
        ),
        _check(
            "capabilities",
            tuple(identity.get("capabilities", ())) == (reference.CAPABILITIES[0].value,),
            identity.get("capabilities"),
            [capability.value for capability in reference.CAPABILITIES],
        ),
        _check(
            "dependency_closure_lockfile",
            closure.get("lockfile_sha256") == dependencies.LOCKFILE_SHA256,
            closure.get("lockfile_sha256"),
            dependencies.LOCKFILE_SHA256,
        ),
        _check(
            "dependency_closure_packages",
            packages == dependencies.APPROVED_DEPENDENCIES,
            [list(item) for item in packages],
            [list(item) for item in dependencies.APPROVED_DEPENDENCIES],
        ),
        _check(
            "dependency_closure_digest",
            closure.get("digest")
            == dependencies.closure_digest(dependencies.APPROVED_DEPENDENCIES),
            closure.get("digest"),
            dependencies.closure_digest(dependencies.APPROVED_DEPENDENCIES),
        ),
    ]


def _configuration_checks(diagnostic: dict[str, Any]) -> list[dict[str, object]]:
    return [
        _check(
            "timestep",
            diagnostic["timestep_s"] == reference.TIMESTEP_S,
            diagnostic["timestep_s"],
            reference.TIMESTEP_S,
        ),
        _check(
            "duration",
            diagnostic["duration_s"] == reference.DURATION_S,
            diagnostic["duration_s"],
            reference.DURATION_S,
        ),
        _check(
            "steps", diagnostic["steps"] == reference.STEPS, diagnostic["steps"], reference.STEPS
        ),
        _check(
            "integrator",
            diagnostic["integrator"] == reference.INTEGRATOR,
            diagnostic["integrator"],
            reference.INTEGRATOR,
        ),
        _check(
            "solver",
            diagnostic["solver"] == reference.SOLVER,
            diagnostic["solver"],
            reference.SOLVER,
        ),
        _check(
            "solver_iterations",
            diagnostic["solver_iterations"] == reference.ITERATIONS,
            diagnostic["solver_iterations"],
            reference.ITERATIONS,
        ),
        _check(
            "solver_tolerance",
            diagnostic["solver_tolerance"] == reference.TOLERANCE,
            diagnostic["solver_tolerance"],
            reference.TOLERANCE,
        ),
        _check(
            "gravity",
            diagnostic["gravity_m_s2"] == reference.GRAVITY_M_S2,
            diagnostic["gravity_m_s2"],
            reference.GRAVITY_M_S2,
        ),
        _check(
            "initial_angle",
            diagnostic["initial"]["angle_rad"] == reference.INITIAL_ANGLE_RAD,
            diagnostic["initial"]["angle_rad"],
            reference.INITIAL_ANGLE_RAD,
        ),
        _check(
            "initial_angular_velocity",
            diagnostic["initial"]["angular_velocity_rad_s"]
            == reference.INITIAL_ANGULAR_VELOCITY_RAD_S,
            diagnostic["initial"]["angular_velocity_rad_s"],
            reference.INITIAL_ANGULAR_VELOCITY_RAD_S,
        ),
        _check("seed", diagnostic["seed"] == reference.SEED, diagnostic["seed"], reference.SEED),
        _check(
            "outcomes",
            tuple(diagnostic["outcomes"]) == (reference.OUTCOME,),
            diagnostic["outcomes"],
            [reference.OUTCOME],
        ),
        _check("all_finite", diagnostic["all_finite"] is True, diagnostic["all_finite"], True),
        _check("stochastic", diagnostic["stochastic"] is False, diagnostic["stochastic"], False),
        _check("nq", diagnostic["nq"] == 1, diagnostic["nq"], 1),
        _check("nv", diagnostic["nv"] == 1, diagnostic["nv"], 1),
        _check("nu", diagnostic["nu"] == 0, diagnostic["nu"], 0),
        _check("njnt", diagnostic["njnt"] == 1, diagnostic["njnt"], 1),
        _check("ngeom", diagnostic["ngeom"] == 0, diagnostic["ngeom"], 0),
    ]


def build_receipt(
    *,
    target: str,
    tested_commit: str,
    head_commit: str,
    ref: str,
    image_os: str,
    image_version: str,
) -> dict[str, Any]:
    """Run one real observation and return its receipt, whether it passed or failed."""
    if target not in _TARGETS:
        raise ReceiptError(f"unknown qualification target {target!r}")
    platform_tag = _TARGETS[target]
    if reference.platform_tag() != platform_tag:
        raise ReceiptError(
            f"the receipt target {target!r} does not match this host's qualified platform "
            f"{reference.platform_tag()!r}"
        )
    if not _COMMIT.fullmatch(tested_commit) or not _COMMIT.fullmatch(head_commit):
        raise ReceiptError("the receipt requires full 40-character Git commit identities")

    expected_authority, _observed_authority = _authority(platform_tag)
    canonical_spec = reference_case.run_spec(platform_tag=platform_tag)
    execution_fingerprint = run_spec_fingerprint(canonical_spec).hex

    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-receipt-") as scratch:
        scratch_path = Path(scratch)
        identity = _run_worker_module(
            "dynamisbench.adapters.mujoco",
            ("--identity",),
            scratch_path,
        )
        qualification = _run_worker_module(
            "dynamisbench.adapters.mujoco.qualification",
            (),
            scratch_path,
        )

    checks = _identity_checks(identity, platform_tag)
    diagnostics = qualification["nominal"]["diagnostic"]
    diagnostic = ReferenceDiagnostic.model_validate(diagnostics)
    checks.extend(_configuration_checks(diagnostic.model_dump(mode="json")))
    checks.append(
        _check(
            "worker_implementation_matches_identity",
            diagnostic.implementation_digest == identity.get("implementation_digest"),
            diagnostic.implementation_digest,
            identity.get("implementation_digest"),
        )
    )
    checks.append(
        _check(
            "worker_model_matches_identity",
            diagnostic.model_sha256 == reference.MODEL_SHA256,
            diagnostic.model_sha256,
            reference.MODEL_SHA256,
        )
    )
    checks.append(
        _check(
            "worker_engine_matches_identity",
            diagnostic.engine_version == identity.get("engine_version"),
            diagnostic.engine_version,
            identity.get("engine_version"),
        )
    )
    checks.append(
        _check(
            "nonempty_execution_fingerprint",
            bool(_SHA256.fullmatch(execution_fingerprint)),
            execution_fingerprint,
            "64 lowercase hex characters",
        )
    )

    observation, numerical_checks, _diagnostic_payload = _observation(qualification)
    checks.extend(numerical_checks)

    verdict = "pass" if all(item["passed"] for item in checks) else "fail"
    return {
        "schema": qualification_criteria.RECEIPT_SCHEMA,
        "kind": "ci-numerical-solution-verification",
        "authority_issue": "RES-550",
        "claim": (
            "Numerical solution verification of the fixed MuJoCo planar-pendulum reference "
            f"on {platform_tag}."
        ),
        "claim_limit": qualification_criteria.CLAIM_LIMIT,
        "git": {
            "tested_commit": tested_commit,
            "head_commit": head_commit,
            "ref": ref,
        },
        "runner": {
            "target": target,
            "platform": platform_tag,
            "image_os": image_os,
            "image_version": image_version,
            "python_executable": "isolated worker-mujoco environment",
        },
        "authority": {
            "benchmark_semantic_digest": expected_authority["benchmark"],
            "scenario_semantic_digest": expected_authority["scenario"],
            "realization_semantic_digest": expected_authority["realization"],
            "system_under_test_semantic_digest": expected_authority["system_under_test"],
            "environment_semantic_digest": expected_authority[
                f"environment_{platform_tag.replace('-', '_')}"
            ],
            "execution_fingerprint": execution_fingerprint,
            "pins_match_canonical_definitions": True,
        },
        "runtime": {
            "python_version": identity.get("python_version"),
            "engine": identity.get("engine"),
            "engine_version": identity.get("engine_version"),
            "adapter_id": identity.get("adapter_id"),
            "adapter_version": identity.get("adapter_version"),
            "implementation_digest": identity.get("implementation_digest"),
            "model_sha256": identity.get("model_sha256"),
            "platform": identity.get("platform"),
            "capabilities": identity.get("capabilities"),
            "dependency_closure": identity.get("dependency_closure"),
            "source_manifest": identity.get("source_manifest"),
        },
        "configuration": {
            "timestep_s": diagnostic.timestep_s,
            "duration_s": diagnostic.duration_s,
            "steps": diagnostic.steps,
            "integrator": diagnostic.integrator,
            "solver": diagnostic.solver,
            "iterations": diagnostic.solver_iterations,
            "tolerance": diagnostic.solver_tolerance,
            "gravity_m_s2": diagnostic.gravity_m_s2,
            "initial_angle_rad": diagnostic.initial.angle_rad,
            "initial_angular_velocity_rad_s": diagnostic.initial.angular_velocity_rad_s,
            "seed": diagnostic.seed,
            "outcomes": list(diagnostic.outcomes),
            "precision": diagnostic.precision,
        },
        "observation": observation,
        "tolerances": dict(qualification_criteria.TOLERANCES),
        "checks": checks,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=sorted(_TARGETS))
    parser.add_argument("--tested-sha", default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--ref", default="local")
    parser.add_argument("--image-os", default="local")
    parser.add_argument("--image-version", default="local")
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    tested = arguments.tested_sha or _git_head()
    head = arguments.head_sha or tested
    receipt = build_receipt(
        target=arguments.target,
        tested_commit=tested,
        head_commit=head,
        ref=arguments.ref,
        image_os=arguments.image_os,
        image_version=arguments.image_version,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    failed = [item["name"] for item in receipt["checks"] if not item["passed"]]
    sys.stdout.write(
        json.dumps(
            {
                "schema": receipt["schema"],
                "verdict": receipt["verdict"],
                "output": str(arguments.output),
                "failed_checks": failed,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if receipt["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
