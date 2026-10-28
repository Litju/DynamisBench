"""Independent comparison tests for the RES-550 Windows/Linux qualification receipts.

The pair is built from one real isolated-worker receipt and one deliberately synthesised
sibling with the *other* platform's pinned environment and canonical execution fingerprint.
That is enough to exercise the comparator's identity and divergence logic without claiming a
second platform observation that did not happen. CI produces the two real receipts.
"""

from __future__ import annotations

import copy
import hashlib
import math
import os

import pytest
from tools.mujoco_qualification_receipt import build_receipt
from tools.mujoco_receipt_compare import _period_checks, checkout_head, compare

from dynamisbench.adapters.mujoco import qualification_criteria, reference, reference_case
from dynamisbench.execution.contracts import WORKER_PROTOCOL_VERSION
from dynamisbench.identity import canonical_semantic_bytes
from dynamisbench.planning.runspec import run_spec_fingerprint

_TARGETS = {
    "windows-x64": "windows-x86-64",
    "linux-x64": "linux-x86-64",
}


def _as_platform(receipt: dict, target: str) -> dict:
    platform = _TARGETS[target]
    clone = copy.deepcopy(receipt)
    clone["runner"]["target"] = target
    clone["runner"]["platform"] = platform
    clone["runtime"]["platform"] = platform
    clone["authority"]["environment_semantic_digest"] = reference.ENVIRONMENT_SEMANTIC_DIGESTS[
        platform
    ].hex
    clone["authority"]["execution_fingerprint"] = run_spec_fingerprint(
        reference_case.run_spec(platform_tag=platform)
    ).hex
    runtime = clone["runtime"]
    payload = {
        "schema": reference.IMPLEMENTATION_IDENTITY_SCHEMA,
        "adapter_id": runtime["adapter_id"],
        "adapter_version": runtime["adapter_version"],
        "engine": runtime["engine"],
        "engine_version": runtime["engine_version"],
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "capabilities": sorted(runtime["capabilities"]),
        "platform": runtime["platform"],
        "python_version": runtime["python_version"],
        "model_sha256": runtime["model_sha256"],
        "source_manifest": runtime["source_manifest"],
        "dependency_closure": runtime["dependency_closure"],
    }
    runtime["implementation_digest"] = hashlib.sha256(canonical_semantic_bytes(payload)).hexdigest()
    return clone


@pytest.fixture(scope="module")
def receipt_pair(mujoco_identity: dict) -> dict[str, dict]:
    current = "windows-x64" if os.name == "nt" else "linux-x64"
    other = "linux-x64" if current == "windows-x64" else "windows-x64"
    commit = checkout_head()
    receipt = build_receipt(
        target=current,
        tested_commit=commit,
        head_commit=commit,
        ref="test",
        image_os="test",
        image_version="test",
    )
    return {current: receipt, other: _as_platform(receipt, other)}


def _compare(pair: dict[str, dict]) -> dict:
    return compare(
        pair["windows-x64"],
        pair["linux-x64"],
        windows_digest="0" * 64,
        linux_digest="1" * 64,
    )


def _set_observed_period(
    receipt: dict,
    observed_period_s: float,
    *,
    reported_period_error_s: float | None = None,
) -> None:
    """Mutate one receipt's period observation and keep its arithmetic self-consistent."""
    observation = receipt["observation"]
    analytical = float(observation["analytical_period_s"])
    observation["observed_period_s"] = observed_period_s
    observation["period_error_s"] = (
        abs(observed_period_s - analytical)
        if reported_period_error_s is None
        else reported_period_error_s
    )


def test_two_consistent_receipts_pass(receipt_pair: dict[str, dict]) -> None:
    comparison = _compare(receipt_pair)

    assert comparison["verdict"] == "pass", comparison["failed_checks"]
    assert comparison["cross_platform"]["bitwise_equality_required"] is False
    assert comparison["cross_platform"]["trajectory_digest_equal"] is True
    assert comparison["cross_platform"]["observed_period_delta_s"] == 0.0


def test_the_hosted_reference_period_observation_is_accepted() -> None:
    """The exact numerical period observation from run 40684508355 at 49dd74c remains valid.

    These three values are the ones the qualified Windows and Linux receipts recorded. The
    physical model, solver configuration and tolerances are unchanged, so the corrected
    comparator must still accept them.
    """
    observation = {
        "observed_period_s": 2.0423588797694,
        "analytical_period_s": 2.042358880051493,
        "period_error_s": 2.82093015613327e-10,
    }

    checks = _period_checks(observation)

    assert all(check["passed"] for check in checks), checks


def test_cross_platform_period_divergence_is_detected_from_observed_periods(
    receipt_pair: dict[str, dict],
) -> None:
    """Each platform may pass its own analytical tolerance while disagreeing materially."""
    pair = copy.deepcopy(receipt_pair)
    windows_observation = pair["windows-x64"]["observation"]
    analytical = float(windows_observation["analytical_period_s"])
    baseline = float(windows_observation["observed_period_s"])
    divergent = baseline + 2e-5

    assert abs(baseline - analytical) <= qualification_criteria.PERIOD_TOLERANCE_S
    assert abs(divergent - analytical) <= qualification_criteria.PERIOD_TOLERANCE_S
    _set_observed_period(pair["linux-x64"], divergent)

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "cross_platform_period" in comparison["failed_checks"]
    # The analytical reference is identical by construction, so a comparator that compared
    # it rather than the observations would pass. Neither platform's own period checks may
    # fail here: the rejection is precisely the cross-platform observation comparison.
    assert "period" not in comparison["failed_checks"]
    assert "period_source_values" not in comparison["failed_checks"]
    assert "period_error_report" not in comparison["failed_checks"]
    assert comparison["cross_platform"]["observed_period_delta_s"] == pytest.approx(2e-5, abs=1e-12)
    assert "analytical_period_delta_s" not in comparison["cross_platform"]


def test_a_forged_period_error_is_rejected_by_independent_recomputation(
    receipt_pair: dict[str, dict],
) -> None:
    """A receipt may not pass by self-reporting an error unrelated to its observations."""
    pair = copy.deepcopy(receipt_pair)
    observation = pair["linux-x64"]["observation"]
    baseline = float(observation["observed_period_s"])
    forged_error = float(observation["period_error_s"])
    # Move the observation by less than the cross-platform bound, so only the internal
    # consistency check can reject the receipt.
    _set_observed_period(
        pair["linux-x64"],
        baseline + 5e-6,
        reported_period_error_s=forged_error,
    )

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "period_error_report" in comparison["failed_checks"]
    assert "period" not in comparison["failed_checks"]
    assert "period_source_values" not in comparison["failed_checks"]
    assert "cross_platform_period" not in comparison["failed_checks"]


def test_a_legitimate_small_observed_period_divergence_passes(
    receipt_pair: dict[str, dict],
) -> None:
    pair = copy.deepcopy(receipt_pair)
    observation = pair["windows-x64"]["observation"]
    baseline = float(observation["observed_period_s"])
    _set_observed_period(pair["linux-x64"], baseline + 5e-6)

    comparison = _compare(pair)

    assert comparison["verdict"] == "pass", comparison["failed_checks"]
    assert comparison["cross_platform"]["observed_period_delta_s"] == pytest.approx(5e-6, abs=1e-12)


@pytest.mark.parametrize(
    ("platform", "field", "value", "expected_check"),
    (
        ("windows-x64", "observed_period_s", math.nan, "period_source_values"),
        ("linux-x64", "analytical_period_s", math.inf, "period_source_values"),
        ("windows-x64", "observed_period_s", -math.inf, "period_source_values"),
        ("linux-x64", "analytical_period_s", -1.0, "period_source_values"),
        ("windows-x64", "period_error_s", math.nan, "period_error_report"),
        ("linux-x64", "period_error_s", math.inf, "period_error_report"),
    ),
)
def test_invalid_period_values_fail_closed(
    receipt_pair: dict[str, dict],
    platform: str,
    field: str,
    value: float,
    expected_check: str,
) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair[platform]["observation"][field] = value

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert expected_check in comparison["failed_checks"]


def test_a_negative_period_error_is_rejected(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["linux-x64"]["observation"]["period_error_s"] = -1e-6

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "period_error_report" in comparison["failed_checks"]


@pytest.mark.parametrize(
    ("field", "value", "expected_check"),
    (
        ("final_time_error_s", math.nan, "final_time"),
        ("max_angle_error_rad", math.inf, "maximum_angle_error"),
        ("max_angular_velocity_error_rad_s", -math.inf, "maximum_angular_velocity_error"),
        ("max_velocity_consistency_error_rad_s", math.nan, "velocity_consistency"),
        ("energy_reconstruction_max_abs_j", math.inf, "energy_reconstruction"),
        ("relative_energy_drift", -math.inf, "relative_energy_drift"),
        ("diagnostic_relative_energy_drift", math.nan, "diagnostic_relative_energy_drift"),
    ),
)
def test_nonfinite_numerical_observations_fail_closed(
    receipt_pair: dict[str, dict],
    field: str,
    value: float,
    expected_check: str,
) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["windows-x64"]["observation"][field] = value

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert expected_check in comparison["failed_checks"]


@pytest.mark.parametrize(
    ("field", "expected_check"),
    (
        ("final_time_error_s", "final_time"),
        ("max_angle_error_rad", "maximum_angle_error"),
        ("max_angular_velocity_error_rad_s", "maximum_angular_velocity_error"),
        ("max_velocity_consistency_error_rad_s", "velocity_consistency"),
        ("energy_reconstruction_max_abs_j", "energy_reconstruction"),
        ("relative_energy_drift", "relative_energy_drift"),
        ("diagnostic_relative_energy_drift", "diagnostic_relative_energy_drift"),
    ),
)
def test_negative_numerical_error_magnitudes_fail_closed(
    receipt_pair: dict[str, dict],
    field: str,
    expected_check: str,
) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["windows-x64"]["observation"][field] = -1e-12

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert expected_check in comparison["failed_checks"]


def test_malformed_numerical_types_fail_closed(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["windows-x64"]["observation"]["observed_period_s"] = "2.0423588797694"
    pair["windows-x64"]["observation"]["final_time_error_s"] = None

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "period_source_values" in comparison["failed_checks"]
    assert "final_time" in comparison["failed_checks"]


def test_an_integer_too_large_for_a_double_fails_closed(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["windows-x64"]["observation"]["final_time_error_s"] = 10**400

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "final_time" in comparison["failed_checks"]


def test_nonfinite_refinement_values_fail_closed(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    refinement = pair["windows-x64"]["observation"]["refinement"]
    refinement[-1]["error_rad"] = math.nan
    refinement[0]["convergence_ratio"] = math.inf

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "refinement_final_error" in comparison["failed_checks"]
    assert "refinement_ratio_0" in comparison["failed_checks"]


def test_a_substituted_environment_digest_fails(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["linux-x64"]["authority"]["environment_semantic_digest"] = (
        reference.ENVIRONMENT_SEMANTIC_DIGESTS["windows-x86-64"].hex
    )

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "environment_authority" in comparison["failed_checks"]
    assert "distinct_platform_environment" in comparison["failed_checks"]


def test_a_numerical_tolerance_violation_fails(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["windows-x64"]["observation"]["max_angle_error_rad"] = 1e-3

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "maximum_angle_error" in comparison["failed_checks"]


def test_a_cross_platform_divergence_beyond_the_declared_bound_fails(
    receipt_pair: dict[str, dict],
) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["linux-x64"]["observation"]["final_state"]["angle_rad"] += 1e-3

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "cross_platform_final_angle" in comparison["failed_checks"]
    assert comparison["cross_platform"]["trajectory_digest_equal"] is True


def test_two_different_head_commits_fail(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["linux-x64"]["git"]["head_commit"] = "c" * 40

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "same_head_commit" in comparison["failed_checks"]


def test_two_different_tested_commits_fail(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["linux-x64"]["git"]["tested_commit"] = "d" * 40

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "same_tested_commit" in comparison["failed_checks"]


def test_a_stale_dependency_lock_fails(receipt_pair: dict[str, dict]) -> None:
    pair = copy.deepcopy(receipt_pair)
    pair["windows-x64"]["runtime"]["dependency_closure"]["lockfile_sha256"] = "d" * 64

    comparison = _compare(pair)

    assert comparison["verdict"] == "fail"
    assert "dependency_lockfile" in comparison["failed_checks"]
