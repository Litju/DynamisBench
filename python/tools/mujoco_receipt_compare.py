"""Independently compare the Windows and Linux RES-550 MuJoCo qualification receipts.

The comparator does not trust a receipt's own ``verdict``. It recomputes the pinned reference
authority, the canonical execution fingerprint, the approved dependency closure from
``worker-mujoco/uv.lock``, and every numerical acceptance criterion. It then checks that the
two platform receipts describe the same experiment with platform-specific environments, and
that any cross-platform numerical divergence is within the predeclared bound.

Run from ``python/``:

    uv run python tools/mujoco_receipt_compare.py \
        --windows evidence/windows/mujoco-qualification-windows-x64.json \
        --linux evidence/linux/mujoco-qualification-linux-x64.json \
        --output evidence/mujoco-receipt-comparison.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

from dynamisbench.adapters.mujoco import (
    dependencies,
    qualification_criteria,
    reference,
    reference_case,
)
from dynamisbench.execution.contracts import WORKER_PROTOCOL_VERSION
from dynamisbench.identity import canonical_semantic_bytes
from dynamisbench.planning.runspec import run_spec_fingerprint

__all__ = ["main"]

PYTHON_DIRECTORY: Final = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT: Final = PYTHON_DIRECTORY.parent
ADAPTER_DIRECTORY: Final = PYTHON_DIRECTORY / "src" / "dynamisbench" / "adapters" / "mujoco"
LOCKFILE: Final = PYTHON_DIRECTORY / "worker-mujoco" / "uv.lock"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TARGETS: Final = {
    "windows-x64": "windows-x86-64",
    "linux-x64": "linux-x86-64",
}


class ComparisonError(RuntimeError):
    """A receipt pair could not be compared as two qualified observations."""


def _check(name: str, passed: bool, observed: object, limit: object) -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "observed": observed, "limit": limit}


def _finite_number(value: object) -> float | None:
    """A finite JSON number, or ``None`` for anything that is not one.

    Receipt fields are JSON numbers, so only ``int`` and ``float`` are numerical. A boolean,
    string, null, NaN or infinity is not a measurement, and must fail closed rather than be
    coerced or silently skipped.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_magnitude(value: object) -> float | None:
    """A finite, nonnegative error magnitude, or ``None`` when the field is not one."""
    number = _finite_number(value)
    return number if number is not None and number >= 0.0 else None


def _finite_positive(value: object) -> float | None:
    """A finite, strictly positive duration, or ``None`` when the field is not one."""
    number = _finite_number(value)
    return number if number is not None and number > 0.0 else None


def _magnitude_check(name: str, value: object, limit: float) -> dict[str, object]:
    magnitude = _finite_magnitude(value)
    return _check(name, magnitude is not None and magnitude <= limit, value, limit)


def _mapping(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _authority() -> dict[str, str]:
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
        raise ComparisonError(
            "the pinned reference authority is stale against the canonical definitions"
        )
    return expected


def _lock_closure() -> tuple[str, tuple[tuple[str, str], ...]]:
    raw = LOCKFILE.read_bytes()
    document: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    packages = tuple(
        sorted(
            (
                dependencies.normalise_distribution_name(str(package["name"])),
                str(package["version"]),
            )
            for package in document["package"]
            if "virtual" not in (package.get("source") or {})
        )
    )
    return hashlib.sha256(raw).hexdigest(), packages


def _load(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ComparisonError(f"{path} is not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ComparisonError(f"{path} is not one JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def checkout_head() -> str:
    """The commit this comparator checkout actually contains."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ComparisonError(f"git rev-parse HEAD failed: {completed.stderr[-1000:]}")
    return completed.stdout.strip()


def _source_content_mismatches(
    source_manifest: tuple[dict[str, Any], ...],
) -> list[str]:
    """Re-hash the adapter files at the tested checkout and name every disagreement.

    The receipt records the implementation source manifest the worker observed. The
    comparison job checks out the exact tested commit, so it can independently read those
    files and prove that the recorded hashes are the bytes in this repository — not merely
    hashes the receipt reported about itself.
    """
    mismatches: list[str] = []
    for entry in source_manifest:
        relative = str(entry.get("path", ""))
        expected = str(entry.get("sha256", ""))
        try:
            content = (ADAPTER_DIRECTORY / relative).read_bytes()
        except OSError:
            mismatches.append(f"{relative}: unreadable")
            continue
        observed = hashlib.sha256(content).hexdigest()
        if observed != expected:
            mismatches.append(f"{relative}: {observed} != {expected}")
    return mismatches


def _runtime_checks(
    receipt: dict[str, Any],
    platform_tag: str,
    pin: dict[str, str],
    lockfile_sha256: str,
    lock_packages: tuple[tuple[str, str], ...],
) -> list[dict[str, object]]:
    authority = receipt.get("authority", {})
    runtime = receipt.get("runtime", {})
    closure = runtime.get("dependency_closure", {})
    packages = tuple(tuple(item) for item in closure.get("packages", ()))
    source_manifest = tuple(runtime.get("source_manifest", ()))
    manifest_paths = {str(entry.get("path")) for entry in source_manifest}
    manifest_hashes_valid = all(
        re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))) is not None
        for entry in source_manifest
    )
    identity_payload = {
        "schema": reference.IMPLEMENTATION_IDENTITY_SCHEMA,
        "adapter_id": runtime.get("adapter_id"),
        "adapter_version": runtime.get("adapter_version"),
        "engine": runtime.get("engine"),
        "engine_version": runtime.get("engine_version"),
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "capabilities": sorted(runtime.get("capabilities", ())),
        "platform": runtime.get("platform"),
        "python_version": runtime.get("python_version"),
        "model_sha256": runtime.get("model_sha256"),
        "source_manifest": list(source_manifest),
        "dependency_closure": closure,
    }
    recomputed_implementation = hashlib.sha256(
        canonical_semantic_bytes(identity_payload)
    ).hexdigest()
    source_content_mismatches = _source_content_mismatches(source_manifest)
    try:
        model_content_digest = hashlib.sha256(
            (ADAPTER_DIRECTORY / reference.MODEL_ASSET_PATH).read_bytes()
        ).hexdigest()
    except OSError:
        model_content_digest = "unreadable"
    expected_spec = reference_case.run_spec(platform_tag=platform_tag)
    expected_fingerprint = run_spec_fingerprint(expected_spec).hex
    return [
        _check(
            "schema",
            receipt.get("schema") == qualification_criteria.RECEIPT_SCHEMA,
            receipt.get("schema"),
            qualification_criteria.RECEIPT_SCHEMA,
        ),
        _check(
            "kind",
            receipt.get("kind") == "ci-numerical-solution-verification",
            receipt.get("kind"),
            "ci-numerical-solution-verification",
        ),
        _check(
            "git_commit",
            bool(_COMMIT.fullmatch(str(receipt.get("git", {}).get("head_commit", "")))),
            receipt.get("git", {}).get("head_commit"),
            "40-character Git commit",
        ),
        _check(
            "benchmark_authority",
            authority.get("benchmark_semantic_digest") == pin["benchmark"],
            authority.get("benchmark_semantic_digest"),
            pin["benchmark"],
        ),
        _check(
            "scenario_authority",
            authority.get("scenario_semantic_digest") == pin["scenario"],
            authority.get("scenario_semantic_digest"),
            pin["scenario"],
        ),
        _check(
            "realization_authority",
            authority.get("realization_semantic_digest") == pin["realization"],
            authority.get("realization_semantic_digest"),
            pin["realization"],
        ),
        _check(
            "sut_authority",
            authority.get("system_under_test_semantic_digest") == pin["system_under_test"],
            authority.get("system_under_test_semantic_digest"),
            pin["system_under_test"],
        ),
        _check(
            "environment_authority",
            authority.get("environment_semantic_digest")
            == pin[f"environment_{platform_tag.replace('-', '_')}"],
            authority.get("environment_semantic_digest"),
            pin[f"environment_{platform_tag.replace('-', '_')}"],
        ),
        _check(
            "execution_fingerprint",
            authority.get("execution_fingerprint") == expected_fingerprint,
            authority.get("execution_fingerprint"),
            expected_fingerprint,
        ),
        _check(
            "engine",
            runtime.get("engine") == reference.ENGINE,
            runtime.get("engine"),
            reference.ENGINE,
        ),
        _check(
            "engine_version",
            runtime.get("engine_version") == reference.ENGINE_VERSION,
            runtime.get("engine_version"),
            reference.ENGINE_VERSION,
        ),
        _check(
            "python_version",
            runtime.get("python_version") == reference.PYTHON_VERSION,
            runtime.get("python_version"),
            reference.PYTHON_VERSION,
        ),
        _check(
            "platform",
            runtime.get("platform") == platform_tag,
            runtime.get("platform"),
            platform_tag,
        ),
        _check(
            "adapter_id",
            runtime.get("adapter_id") == reference.ADAPTER_ID,
            runtime.get("adapter_id"),
            reference.ADAPTER_ID,
        ),
        _check(
            "adapter_version",
            runtime.get("adapter_version") == reference.ADAPTER_VERSION,
            runtime.get("adapter_version"),
            reference.ADAPTER_VERSION,
        ),
        _check(
            "model_sha256",
            runtime.get("model_sha256") == reference.MODEL_SHA256,
            runtime.get("model_sha256"),
            reference.MODEL_SHA256,
        ),
        _check(
            "capabilities",
            tuple(runtime.get("capabilities", ())) == (reference.CAPABILITIES[0].value,),
            runtime.get("capabilities"),
            [capability.value for capability in reference.CAPABILITIES],
        ),
        _check(
            "dependency_lockfile",
            closure.get("lockfile_sha256") == lockfile_sha256,
            closure.get("lockfile_sha256"),
            lockfile_sha256,
        ),
        _check(
            "dependency_packages",
            packages == lock_packages,
            [list(item) for item in packages],
            [list(item) for item in lock_packages],
        ),
        _check(
            "dependency_digest",
            closure.get("digest") == dependencies.closure_digest(lock_packages),
            closure.get("digest"),
            dependencies.closure_digest(lock_packages),
        ),
        _check(
            "source_manifest_paths",
            manifest_paths == set(reference.ADAPTER_SOURCE_FILES),
            sorted(manifest_paths),
            sorted(reference.ADAPTER_SOURCE_FILES),
        ),
        _check(
            "source_manifest_hashes",
            bool(source_manifest) and manifest_hashes_valid,
            len(source_manifest),
            "nonempty manifest with 64-hex SHA-256 values",
        ),
        _check(
            "source_manifest_content",
            not source_content_mismatches,
            source_content_mismatches,
            [],
        ),
        _check(
            "model_asset_content",
            model_content_digest == runtime.get("model_sha256") == reference.MODEL_SHA256,
            model_content_digest,
            reference.MODEL_SHA256,
        ),
        _check(
            "implementation_digest_recomputable",
            recomputed_implementation == runtime.get("implementation_digest"),
            recomputed_implementation,
            runtime.get("implementation_digest"),
        ),
    ]


def _configuration_checks(receipt: dict[str, Any]) -> list[dict[str, object]]:
    configuration = receipt.get("configuration", {})
    expected = {
        "timestep_s": reference.TIMESTEP_S,
        "duration_s": reference.DURATION_S,
        "steps": reference.STEPS,
        "integrator": reference.INTEGRATOR,
        "solver": reference.SOLVER,
        "iterations": reference.ITERATIONS,
        "tolerance": reference.TOLERANCE,
        "gravity_m_s2": reference.GRAVITY_M_S2,
        "initial_angle_rad": reference.INITIAL_ANGLE_RAD,
        "initial_angular_velocity_rad_s": reference.INITIAL_ANGULAR_VELOCITY_RAD_S,
        "seed": reference.SEED,
        "precision": "float64",
    }
    checks = [
        _check(
            f"configuration_{key}", configuration.get(key) == value, configuration.get(key), value
        )
        for key, value in expected.items()
    ]
    checks.append(
        _check(
            "configuration_outcomes",
            tuple(configuration.get("outcomes", ())) == (reference.OUTCOME,),
            configuration.get("outcomes"),
            [reference.OUTCOME],
        )
    )
    return checks


def _period_checks(observation: dict[str, Any]) -> list[dict[str, object]]:
    """Independently verify the period fields of one receipt.

    Three distinct facts are checked, and success in one never implies another:

    * both source periods are real, finite, positive durations;
    * the error computed from those two values is within the platform tolerance; and
    * the receipt's recorded error is finite, nonnegative and agrees with that computation.

    The receipt's own ``period_error_s`` is therefore evidence to be cross-checked, never the
    condition that grants a pass.
    """
    observed = _finite_positive(observation.get("observed_period_s"))
    analytical = _finite_positive(observation.get("analytical_period_s"))
    source_ok = observed is not None and analytical is not None
    computed = (
        abs(observed - analytical) if observed is not None and analytical is not None else None
    )
    computed_ok = computed is not None and math.isfinite(computed) and computed >= 0.0
    reported = _finite_magnitude(observation.get("period_error_s"))
    difference = abs(reported - computed) if reported is not None and computed is not None else None
    agreement = (
        difference is not None
        and difference <= qualification_criteria.PERIOD_ERROR_REPORT_AGREEMENT_S
    )
    source = {
        "observed_period_s": observation.get("observed_period_s"),
        "analytical_period_s": observation.get("analytical_period_s"),
    }
    return [
        _check(
            "period_source_values",
            source_ok,
            source,
            "finite positive observed and analytical periods",
        ),
        _check(
            "period",
            computed_ok
            and computed is not None
            and computed <= qualification_criteria.PERIOD_TOLERANCE_S,
            {
                "computed_period_error_s": computed,
                "reported_period_error_s": observation.get("period_error_s"),
            },
            qualification_criteria.PERIOD_TOLERANCE_S,
        ),
        _check(
            "period_error_report",
            agreement,
            {
                "reported_period_error_s": observation.get("period_error_s"),
                "computed_period_error_s": computed,
                "absolute_difference_s": difference,
            },
            {
                "agreement_tolerance_s": qualification_criteria.PERIOD_ERROR_REPORT_AGREEMENT_S,
                "nonnegative_finite_magnitude": True,
            },
        ),
    ]


def _numerical_checks(receipt: dict[str, Any]) -> list[dict[str, object]]:
    observation = _mapping(receipt.get("observation"))
    if observation is None:
        return [_check("observation", False, receipt.get("observation"), "one JSON object")]
    checks = [
        _magnitude_check(
            "final_time",
            observation.get("final_time_error_s"),
            qualification_criteria.FINAL_TIME_TOLERANCE_S,
        ),
        _magnitude_check(
            "maximum_angle_error",
            observation.get("max_angle_error_rad"),
            qualification_criteria.ANGLE_TOLERANCE_RAD,
        ),
        _magnitude_check(
            "maximum_angular_velocity_error",
            observation.get("max_angular_velocity_error_rad_s"),
            qualification_criteria.ANGULAR_VELOCITY_TOLERANCE_RAD_S,
        ),
        _magnitude_check(
            "velocity_consistency",
            observation.get("max_velocity_consistency_error_rad_s"),
            qualification_criteria.VELOCITY_CONSISTENCY_TOLERANCE_RAD_S,
        ),
        _magnitude_check(
            "energy_reconstruction",
            observation.get("energy_reconstruction_max_abs_j"),
            qualification_criteria.ENERGY_RECONSTRUCTION_TOLERANCE_J,
        ),
        _magnitude_check(
            "relative_energy_drift",
            observation.get("relative_energy_drift"),
            qualification_criteria.ENERGY_RELATIVE_TOLERANCE,
        ),
        _magnitude_check(
            "diagnostic_relative_energy_drift",
            observation.get("diagnostic_relative_energy_drift"),
            qualification_criteria.ENERGY_RELATIVE_TOLERANCE,
        ),
    ]
    checks.extend(_period_checks(observation))
    refinement = observation.get("refinement")
    if not isinstance(refinement, (list, tuple)) or not refinement:
        checks.append(_check("refinement_present", False, refinement, "at least one entry"))
        return checks
    entries = [entry if isinstance(entry, dict) else None for entry in refinement]
    for index, entry in enumerate(entries):
        if entry is None:
            checks.append(
                _check(f"refinement_entry_{index}", False, refinement[index], "one JSON object")
            )
    errors = [
        _finite_magnitude(entry.get("error_rad")) if entry is not None else None
        for entry in entries
    ]
    final_error = errors[-1]
    checks.append(
        _check(
            "refinement_final_error",
            final_error is not None
            and final_error <= qualification_criteria.REFINEMENT_FINAL_TOLERANCE_RAD,
            entries[-1].get("error_rad") if entries[-1] is not None else None,
            qualification_criteria.REFINEMENT_FINAL_TOLERANCE_RAD,
        )
    )
    for index, entry in enumerate(entries[:-1]):
        ratio = _finite_magnitude(entry.get("convergence_ratio")) if entry is not None else None
        checks.append(
            _check(
                f"refinement_ratio_{index}",
                ratio is not None and ratio >= qualification_criteria.REFINEMENT_MIN_RATIO,
                entry.get("convergence_ratio") if entry is not None else None,
                qualification_criteria.REFINEMENT_MIN_RATIO,
            )
        )
    return checks


def _declared_tolerances_match(receipt: dict[str, Any]) -> bool:
    return receipt.get("tolerances") == qualification_criteria.TOLERANCES


def _cross_platform_checks(
    windows: dict[str, Any],
    linux: dict[str, Any],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    windows_observation = _mapping(windows.get("observation"))
    linux_observation = _mapping(linux.get("observation"))
    windows_final = (
        _mapping(windows_observation.get("final_state")) if windows_observation else None
    )
    linux_final = _mapping(linux_observation.get("final_state")) if linux_observation else None
    windows_angle = _finite_number(windows_final.get("angle_rad")) if windows_final else None
    linux_angle = _finite_number(linux_final.get("angle_rad")) if linux_final else None
    windows_velocity = (
        _finite_number(windows_final.get("angular_velocity_rad_s")) if windows_final else None
    )
    linux_velocity = (
        _finite_number(linux_final.get("angular_velocity_rad_s")) if linux_final else None
    )
    angle_delta = (
        abs(windows_angle - linux_angle)
        if windows_angle is not None and linux_angle is not None
        else None
    )
    velocity_delta = (
        abs(windows_velocity - linux_velocity)
        if windows_velocity is not None and linux_velocity is not None
        else None
    )
    # Cross-platform period agreement is about the periods the two platforms actually
    # measured. The analytical reference is identical by construction and comparing it would
    # always pass, hiding a materially different observation.
    windows_observed_period = (
        _finite_positive(windows_observation.get("observed_period_s"))
        if windows_observation
        else None
    )
    linux_observed_period = (
        _finite_positive(linux_observation.get("observed_period_s")) if linux_observation else None
    )
    period_delta = (
        abs(windows_observed_period - linux_observed_period)
        if windows_observed_period is not None and linux_observed_period is not None
        else None
    )
    windows_trajectory = (
        windows_observation.get("trajectory_sha256") if windows_observation else None
    )
    linux_trajectory = linux_observation.get("trajectory_sha256") if linux_observation else None
    trajectory_equal = (
        isinstance(windows_trajectory, str)
        and isinstance(linux_trajectory, str)
        and bool(windows_trajectory)
        and windows_trajectory == linux_trajectory
    )
    checks = [
        _check(
            "same_head_commit",
            windows["git"]["head_commit"] == linux["git"]["head_commit"],
            linux["git"]["head_commit"],
            windows["git"]["head_commit"],
        ),
        _check(
            "same_tested_commit",
            windows["git"]["tested_commit"] == linux["git"]["tested_commit"],
            linux["git"]["tested_commit"],
            windows["git"]["tested_commit"],
        ),
        _check(
            "same_benchmark_authority",
            windows["authority"]["benchmark_semantic_digest"]
            == linux["authority"]["benchmark_semantic_digest"],
            linux["authority"]["benchmark_semantic_digest"],
            windows["authority"]["benchmark_semantic_digest"],
        ),
        _check(
            "same_scenario_authority",
            windows["authority"]["scenario_semantic_digest"]
            == linux["authority"]["scenario_semantic_digest"],
            linux["authority"]["scenario_semantic_digest"],
            windows["authority"]["scenario_semantic_digest"],
        ),
        _check(
            "same_realization_authority",
            windows["authority"]["realization_semantic_digest"]
            == linux["authority"]["realization_semantic_digest"],
            linux["authority"]["realization_semantic_digest"],
            windows["authority"]["realization_semantic_digest"],
        ),
        _check(
            "same_sut_authority",
            windows["authority"]["system_under_test_semantic_digest"]
            == linux["authority"]["system_under_test_semantic_digest"],
            linux["authority"]["system_under_test_semantic_digest"],
            windows["authority"]["system_under_test_semantic_digest"],
        ),
        _check(
            "distinct_platform_environment",
            windows["authority"]["environment_semantic_digest"]
            != linux["authority"]["environment_semantic_digest"],
            linux["authority"]["environment_semantic_digest"],
            "different from the Windows environment digest",
        ),
        _check(
            "distinct_execution_fingerprint",
            windows["authority"]["execution_fingerprint"]
            != linux["authority"]["execution_fingerprint"],
            linux["authority"]["execution_fingerprint"],
            "different from the Windows execution fingerprint",
        ),
        _check(
            "same_engine_version",
            windows["runtime"]["engine_version"] == linux["runtime"]["engine_version"],
            linux["runtime"]["engine_version"],
            windows["runtime"]["engine_version"],
        ),
        _check(
            "same_python_version",
            windows["runtime"]["python_version"] == linux["runtime"]["python_version"],
            linux["runtime"]["python_version"],
            windows["runtime"]["python_version"],
        ),
        _check(
            "same_dependency_lock",
            windows["runtime"]["dependency_closure"]["lockfile_sha256"]
            == linux["runtime"]["dependency_closure"]["lockfile_sha256"],
            linux["runtime"]["dependency_closure"]["lockfile_sha256"],
            windows["runtime"]["dependency_closure"]["lockfile_sha256"],
        ),
        _check(
            "same_dependency_digest",
            windows["runtime"]["dependency_closure"]["digest"]
            == linux["runtime"]["dependency_closure"]["digest"],
            linux["runtime"]["dependency_closure"]["digest"],
            windows["runtime"]["dependency_closure"]["digest"],
        ),
        _check(
            "same_configuration",
            windows["configuration"] == linux["configuration"],
            linux["configuration"],
            windows["configuration"],
        ),
        _check(
            "same_tolerances",
            windows["tolerances"] == linux["tolerances"],
            linux["tolerances"],
            windows["tolerances"],
        ),
        _check(
            "cross_platform_final_angle",
            angle_delta is not None
            and angle_delta <= qualification_criteria.CROSS_PLATFORM_FINAL_ANGLE_DIVERGENCE_RAD,
            angle_delta,
            qualification_criteria.CROSS_PLATFORM_FINAL_ANGLE_DIVERGENCE_RAD,
        ),
        _check(
            "cross_platform_final_angular_velocity",
            velocity_delta is not None
            and velocity_delta
            <= qualification_criteria.CROSS_PLATFORM_FINAL_ANGULAR_VELOCITY_DIVERGENCE_RAD_S,
            velocity_delta,
            qualification_criteria.CROSS_PLATFORM_FINAL_ANGULAR_VELOCITY_DIVERGENCE_RAD_S,
        ),
        _check(
            "cross_platform_period",
            period_delta is not None
            and period_delta <= qualification_criteria.CROSS_PLATFORM_PERIOD_DIVERGENCE_S,
            period_delta,
            qualification_criteria.CROSS_PLATFORM_PERIOD_DIVERGENCE_S,
        ),
    ]
    divergence = {
        "trajectory_digest_equal": trajectory_equal,
        "bitwise_equality_required": False,
        "final_angle_delta_rad": angle_delta,
        "final_angular_velocity_delta_rad_s": velocity_delta,
        "windows_observed_period_s": windows_observed_period,
        "linux_observed_period_s": linux_observed_period,
        "observed_period_delta_s": period_delta,
    }
    return checks, divergence


def compare(
    windows: dict[str, Any],
    linux: dict[str, Any],
    *,
    windows_digest: str,
    linux_digest: str,
) -> dict[str, Any]:
    """Compare two receipts and return one comparison record."""
    pin = _authority()
    lockfile_sha256, lock_packages = _lock_closure()
    if lockfile_sha256 != dependencies.LOCKFILE_SHA256 or lock_packages != tuple(
        sorted(
            (
                dependencies.normalise_distribution_name(name),
                version,
            )
            for name, version in dependencies.APPROVED_DEPENDENCIES
        )
    ):
        raise ComparisonError(
            "the approved dependency closure is stale against worker-mujoco/uv.lock"
        )

    windows_platform = _TARGETS["windows-x64"]
    linux_platform = _TARGETS["linux-x64"]
    checkout = checkout_head()
    checks: list[dict[str, object]] = []
    checks.append(
        _check(
            "checkout_is_tested_commit",
            checkout
            == windows.get("git", {}).get("tested_commit")
            == linux.get("git", {}).get("tested_commit"),
            checkout,
            [
                windows.get("git", {}).get("tested_commit"),
                linux.get("git", {}).get("tested_commit"),
            ],
        )
    )
    checks.extend(_runtime_checks(windows, windows_platform, pin, lockfile_sha256, lock_packages))
    checks.extend(_runtime_checks(linux, linux_platform, pin, lockfile_sha256, lock_packages))
    checks.extend(_configuration_checks(windows))
    checks.extend(_configuration_checks(linux))
    checks.extend(_numerical_checks(windows))
    checks.extend(_numerical_checks(linux))
    checks.append(
        _check(
            "windows_verdict",
            windows.get("verdict") == "pass",
            windows.get("verdict"),
            "pass",
        )
    )
    checks.append(
        _check("linux_verdict", linux.get("verdict") == "pass", linux.get("verdict"), "pass")
    )
    checks.append(
        _check(
            "windows_tolerances_declared",
            _declared_tolerances_match(windows),
            windows.get("tolerances"),
            qualification_criteria.TOLERANCES,
        )
    )
    checks.append(
        _check(
            "linux_tolerances_declared",
            _declared_tolerances_match(linux),
            linux.get("tolerances"),
            qualification_criteria.TOLERANCES,
        )
    )
    checks.append(
        _check(
            "windows_reported_checks",
            all(item.get("passed") is True for item in windows.get("checks", ())),
            [item.get("name") for item in windows.get("checks", ()) if not item.get("passed")],
            "every reported check passed",
        )
    )
    checks.append(
        _check(
            "linux_reported_checks",
            all(item.get("passed") is True for item in linux.get("checks", ())),
            [item.get("name") for item in linux.get("checks", ()) if not item.get("passed")],
            "every reported check passed",
        )
    )
    cross_checks, divergence = _cross_platform_checks(windows, linux)
    checks.extend(cross_checks)

    failed = [item["name"] for item in checks if not item["passed"]]
    return {
        "schema": qualification_criteria.COMPARISON_SCHEMA,
        "authority_issue": "RES-550",
        "claim": (
            "Independent cross-platform comparison of the RES-550 MuJoCo numerical "
            "solution-verification receipts."
        ),
        "claim_limit": qualification_criteria.CLAIM_LIMIT,
        "git": {
            "windows_head_commit": windows.get("git", {}).get("head_commit"),
            "linux_head_commit": linux.get("git", {}).get("head_commit"),
        },
        "receipts": {
            "windows": {"sha256": windows_digest, "verdict": windows.get("verdict")},
            "linux": {"sha256": linux_digest, "verdict": linux.get("verdict")},
        },
        "cross_platform": divergence,
        "checks": checks,
        "failed_checks": failed,
        "verdict": "pass" if not failed else "fail",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", required=True, type=Path)
    parser.add_argument("--linux", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    windows, windows_digest = _load(arguments.windows)
    linux, linux_digest = _load(arguments.linux)
    comparison = compare(
        windows,
        linux,
        windows_digest=windows_digest,
        linux_digest=linux_digest,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        json.dumps(
            {
                "schema": comparison["schema"],
                "verdict": comparison["verdict"],
                "output": str(arguments.output),
                "failed_checks": comparison["failed_checks"],
                "cross_platform": comparison["cross_platform"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if comparison["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
