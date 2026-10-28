"""Independent comparison tests for the RES-550 Windows/Linux qualification receipts.

The pair is built from one real isolated-worker receipt and one deliberately synthesised
sibling with the *other* platform's pinned environment and canonical execution fingerprint.
That is enough to exercise the comparator's identity and divergence logic without claiming a
second platform observation that did not happen. CI produces the two real receipts.
"""

from __future__ import annotations

import copy
import hashlib
import os

import pytest
from tools.mujoco_qualification_receipt import build_receipt
from tools.mujoco_receipt_compare import checkout_head, compare

from dynamisbench.adapters.mujoco import reference, reference_case
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


def test_two_consistent_receipts_pass(receipt_pair: dict[str, dict]) -> None:
    comparison = _compare(receipt_pair)

    assert comparison["verdict"] == "pass", comparison["failed_checks"]
    assert comparison["cross_platform"]["bitwise_equality_required"] is False
    assert comparison["cross_platform"]["trajectory_digest_equal"] is True


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
