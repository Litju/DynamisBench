"""Adversarial real-process qualification of the MuJoCo reference adapter."""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from dynamisbench.domain.spec.capability import (
    Capability,
    CapabilityRequirement,
)
from dynamisbench.evidence import RunOutcome, verify_sealed_bundle
from dynamisbench.execution import (
    ExecutionSealError,
    PreflightDecision,
    RefusalCode,
    RunLifecycleState,
    WorkerCommand,
    WorkerRequest,
    WorkerStatus,
    canonical_worker_request_bytes,
    execute_preflighted,
    parse_worker_response,
)
from dynamisbench.planning.compatibility import assess_capabilities
from dynamisbench.planning.errors import IncompatibleCapabilityError
from dynamisbench.planning.runspec import ExecutionFingerprint, run_spec_fingerprint
from dynamisbench.workspace import PersistenceClass
from tests.execution.mujoco.support import (
    MODEL_SOURCE_PATH,
    ExecutionFixture,
    adapter_identity,
    execute_fixture,
    preflight_fixture,
    run_worker_process,
    sealed_root,
    staging_root,
)


def _codes(admission) -> set[RefusalCode]:
    return {item.code for item in admission.report.refusals}


def _model_path(fixture: ExecutionFixture) -> Path:
    return fixture.workspace.source_root.joinpath(*MODEL_SOURCE_PATH.split("/"))


def _worker_log(fixture: ExecutionFixture, run_id: str) -> str:
    path = staging_root(fixture, run_id) / "logs" / "worker.stderr.txt"
    return path.read_text(encoding="utf-8", errors="replace")


def test_a_substituted_adapter_version_fails_at_the_worker_and_cannot_be_success_sealed(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    substituted = adapter_identity(mujoco_identity).model_copy(update={"adapter_version": "9.9.9"})
    admission = preflight_fixture(fixture, mujoco_identity, adapter=substituted)
    assert admission.report.decision is PreflightDecision.READY

    supervised = execute_preflighted(admission)
    result = supervised.result

    assert result.state is RunLifecycleState.FAILED
    assert RefusalCode.WORKER_FAILED in {item.code for item in result.refusals}
    log = _worker_log(fixture, fixture.run_id)
    assert "adapter version" in log
    assert "DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in log

    with pytest.raises(ExecutionSealError, match="ended as failed"):
        supervised.finalize(RunOutcome.SUCCEEDED)
    sealed = supervised.finalize()
    assert sealed.manifest.outcome is RunOutcome.FAILED


def test_a_substituted_implementation_digest_fails_at_the_worker(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    substituted = adapter_identity(mujoco_identity).model_copy(
        update={"implementation_digest": "0" * 64}
    )
    admission = preflight_fixture(fixture, mujoco_identity, adapter=substituted)
    assert admission.report.decision is PreflightDecision.READY

    result = execute_preflighted(admission).result

    assert result.state is RunLifecycleState.FAILED
    assert "implementation digest" in _worker_log(fixture, fixture.run_id)
    assert "DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in _worker_log(fixture, fixture.run_id)


def test_an_over_advertised_capability_fails_at_the_worker(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    over_advertised = adapter_identity(mujoco_identity).model_copy(
        update={
            "capabilities": (
                Capability.FORWARD_DYNAMICS,
                Capability.INVERSE_DYNAMICS,
            )
        }
    )
    admission = preflight_fixture(fixture, mujoco_identity, adapter=over_advertised)
    assert admission.report.decision is PreflightDecision.READY

    result = execute_preflighted(admission).result

    assert result.state is RunLifecycleState.FAILED
    assert "capability advertisement" in _worker_log(fixture, fixture.run_id)


def test_a_substituted_realization_is_refused_before_staging(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    substituted = fixture.realization.model_copy(
        update={"description": "A substituted realization that was never qualified."}
    )
    admission = preflight_fixture(fixture, mujoco_identity, realization=substituted)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.REALIZATION_IDENTITY_MISMATCH in _codes(admission)
    assert admission.request is None
    staging = fixture.workspace.location(PersistenceClass.STAGING).path
    assert not any(staging.iterdir())


def test_a_substituted_environment_is_refused_before_staging(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    substituted = fixture.environment.model_copy(
        update={"description": "A substituted environment that was never qualified."}
    )
    admission = preflight_fixture(fixture, mujoco_identity, environment=substituted)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ENVIRONMENT_IDENTITY_MISMATCH in _codes(admission)
    assert admission.request is None


def test_a_missing_model_asset_is_refused(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    _model_path(fixture).unlink()
    admission = preflight_fixture(fixture, mujoco_identity)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.UNSTAGED_ASSET in _codes(admission)
    assert admission.request is None


def test_a_modified_model_asset_is_refused(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    path = _model_path(fixture)
    path.write_bytes(path.read_bytes() + b"\n")
    admission = preflight_fixture(fixture, mujoco_identity)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ASSET_DIGEST_MISMATCH in _codes(admission)
    assert admission.request is None


def test_post_preflight_asset_mutation_is_refused_before_launch(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    admission = preflight_fixture(fixture, mujoco_identity)
    assert admission.report.decision is PreflightDecision.READY

    path = _model_path(fixture)
    path.write_bytes(path.read_bytes() + b"\n")
    supervised = execute_preflighted(admission)
    result = supervised.result

    assert result.state is RunLifecycleState.REFUSED
    assert RefusalCode.ASSET_DIGEST_MISMATCH in {item.code for item in result.refusals}
    assert result.worker_pid is None
    assert result.worker_reaped is False
    assert result.stdin_delivered is False
    assert result.process_tree_cleaned is False
    assert result.log_reference is None
    # The launch-time admission re-check happens before staging is created, so this refusal
    # leaves no staging bundle at all. That is stronger than a staged failed diagnostic.
    assert not staging_root(fixture, fixture.run_id).exists()

    with pytest.raises(ExecutionSealError, match="no staging bundle"):
        supervised.finalize(RunOutcome.SUCCEEDED)
    with pytest.raises(ExecutionSealError, match="no staging bundle"):
        supervised.finalize()


def test_a_duplicate_run_id_is_refused(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    first = execute_fixture(fixture, mujoco_identity, run_id="run-0000")
    assert first.result.state is RunLifecycleState.COMPLETED

    duplicate = preflight_fixture(fixture, mujoco_identity, run_id="run-0000")

    assert duplicate.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.DUPLICATE_EXECUTION in _codes(duplicate)
    assert duplicate.request is None


def test_a_tampered_fixed_launch_vector_is_refused(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    admission = preflight_fixture(fixture, mujoco_identity)
    assert admission.report.decision is PreflightDecision.READY

    tampered_manifest = admission.manifest.model_copy(
        update={
            "command": WorkerCommand(
                program=sys.executable,
                arguments=("-c", "print('not the selected worker')"),
            )
        }
    )
    tampered = replace(admission, manifest=tampered_manifest)
    supervised = execute_preflighted(tampered)

    assert supervised.result.state is RunLifecycleState.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in {item.code for item in supervised.result.refusals}
    assert supervised.result.worker_pid is None
    staging = fixture.workspace.location(PersistenceClass.STAGING).path
    assert not any(staging.iterdir())


def test_a_tampered_request_fingerprint_is_refused_before_staging(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    admission = preflight_fixture(fixture, mujoco_identity)
    assert admission.request is not None

    tampered_request = admission.request.model_copy(
        update={"execution_fingerprint": ExecutionFingerprint(hex="0" * 64)}
    )
    tampered = replace(admission, request=tampered_request)
    supervised = execute_preflighted(tampered)

    assert supervised.result.state is RunLifecycleState.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in {item.code for item in supervised.result.refusals}
    assert supervised.result.worker_pid is None
    staging = fixture.workspace.location(PersistenceClass.STAGING).path
    assert not any(staging.iterdir())


def test_a_failed_run_does_not_mutate_previous_sealed_evidence(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    first = execute_fixture(fixture, mujoco_identity, run_id="run-0000")
    sealed = first.finalize()
    original_digest = sealed.evidence_digest

    substituted = adapter_identity(mujoco_identity).model_copy(
        update={"implementation_digest": "1" * 64}
    )
    second = execute_fixture(
        fixture,
        mujoco_identity,
        run_id="run-0001",
        adapter=substituted,
    )
    assert second.result.state is RunLifecycleState.FAILED
    failed_seal = second.finalize()
    assert failed_seal.manifest.outcome is RunOutcome.FAILED

    verification = verify_sealed_bundle(
        fixture.workspace,
        "run-0000",
        expected_evidence_digest=original_digest,
    )
    assert verification.is_valid
    assert verification.proves_expected_output
    assert sealed_root(fixture, "run-0000").is_dir()


def _direct_worker_response(admission, **spec_updates: object):
    assert admission.request is not None
    spec = admission.request.run_spec.model_copy(update=spec_updates)
    request = WorkerRequest(
        run_id=admission.request.run_id,
        run_spec=spec,
        execution_fingerprint=run_spec_fingerprint(spec),
        environment=admission.request.environment,
        adapter=admission.request.adapter,
        required_capabilities=admission.request.required_capabilities,
        supported_capabilities=admission.request.supported_capabilities,
        staging_locator=admission.request.staging_locator,
    )
    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-direct-") as scratch:
        completed = run_worker_process(
            (),
            canonical_worker_request_bytes(request) + b"\n",
            Path(scratch),
        )
    assert completed.returncode == 0
    return parse_worker_response(completed.stdout), completed.stderr


def test_the_real_worker_refuses_a_valid_request_with_a_different_outcome(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    admission = preflight_fixture(mujoco_fixture, mujoco_identity)
    response, stderr = _direct_worker_response(admission, outcomes=("other-outcome",))

    assert response.status is WorkerStatus.FAILED
    assert "outcomes" in (response.message or "")
    assert b"outcomes" in stderr
    assert b"DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in stderr


def test_the_real_worker_refuses_a_valid_request_without_the_gravity_factor(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    admission = preflight_fixture(mujoco_fixture, mujoco_identity)
    response, stderr = _direct_worker_response(admission, factors=())

    assert response.status is WorkerStatus.FAILED
    assert "factor" in (response.message or "")
    assert b"factor" in stderr
    assert b"DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in stderr


def test_planning_refuses_an_unimplemented_inverse_dynamics_capability(
    mujoco_fixture: ExecutionFixture,
) -> None:
    fixture = mujoco_fixture
    study = fixture.study.model_copy(
        update={
            "required_capabilities": (
                CapabilityRequirement(
                    capability=Capability.INVERSE_DYNAMICS,
                    essential=True,
                    rationale="This capability is not implemented by the reference adapter.",
                ),
            )
        }
    )

    with pytest.raises(IncompatibleCapabilityError):
        assess_capabilities(
            study=study,
            scenario=fixture.benchmark.scenarios[0],
            system_under_test=fixture.system_under_test,
            realization=fixture.realization,
        )
