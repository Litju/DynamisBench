"""Real MuJoCo execution through the accepted RunSpec → preflight → supervisor boundary."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

from dynamisbench.adapters.mujoco import reference
from dynamisbench.evidence import RunOutcome, verify_sealed_bundle
from dynamisbench.execution import (
    ExecutionDiagnostic,
    PreflightDecision,
    RefusalCode,
    RunLifecycleState,
)
from dynamisbench.workspace import PersistenceClass
from tests.execution.mujoco.support import (
    COM_DISTANCE_M,
    DURATION_S,
    GRAVITY_M_S2,
    INITIAL_ANGLE_RAD,
    INITIAL_ANGULAR_VELOCITY_RAD_S,
    MASS_KG,
    TIMESTEP_S,
    ExecutionFixture,
    adapter_identity,
    execute_fixture,
    native_diagnostic,
    preflight_fixture,
    run_worker_process,
    sealed_root,
    staging_root,
)


def _codes(report) -> set[RefusalCode]:
    return {item.code for item in report.refusals}


def test_a_real_mujoco_run_completes_and_retains_only_a_bounded_diagnostic(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    supervised = execute_fixture(fixture, mujoco_identity)
    result = supervised.result

    assert result.state is RunLifecycleState.COMPLETED
    assert result.successful
    assert result.worker_exit_code == 0
    assert result.worker_pid is not None
    assert result.worker_reaped
    assert result.process_tree_cleaned
    assert result.stdin_delivered
    assert result.diagnostic_reference == "diagnostics.json"
    assert result.log_reference == "logs/worker.stderr.txt"
    assert result.refusals == ()

    diagnostic = native_diagnostic(fixture.workspace, fixture.run_id)
    assert diagnostic.adapter_id == reference.ADAPTER_ID
    assert diagnostic.adapter_version == reference.ADAPTER_VERSION
    assert diagnostic.engine == "mujoco"
    assert diagnostic.engine_version == mujoco_identity["engine_version"]
    assert diagnostic.implementation_digest == mujoco_identity["implementation_digest"]
    assert diagnostic.model_sha256 == reference.MODEL_SHA256
    assert diagnostic.platform == mujoco_identity["platform"]
    assert diagnostic.python_version == mujoco_identity["python_version"]
    assert diagnostic.run_id == fixture.run_id
    assert diagnostic.execution_fingerprint == fixture.fingerprint.hex
    assert diagnostic.benchmark == reference.BENCHMARK_ID
    assert diagnostic.scenario == reference.SCENARIO_ID
    assert diagnostic.realization == reference.REALIZATION_ID
    assert diagnostic.environment_id == fixture.environment.environment_id
    assert diagnostic.seed == 0
    assert diagnostic.outcomes == (reference.OUTCOME,)
    assert diagnostic.control_policy == reference.CONTROL_POLICY
    assert diagnostic.integrator == "RK4"
    assert diagnostic.solver == "Newton"
    assert diagnostic.timestep_s == TIMESTEP_S
    assert diagnostic.duration_s == DURATION_S
    assert diagnostic.steps == 2000
    assert diagnostic.nq == 1
    assert diagnostic.nv == 1
    assert diagnostic.nu == 0
    assert diagnostic.njnt == 1
    assert diagnostic.ngeom == 0
    assert diagnostic.joint_constraints == reference.JOINT_CONSTRAINTS
    assert diagnostic.contact_policy == reference.CONTACT_POLICY
    assert diagnostic.solver_iterations == reference.ITERATIONS
    assert diagnostic.solver_tolerance == reference.TOLERANCE
    assert diagnostic.precision == "float64"
    assert diagnostic.randomness_policy == reference.RANDOMNESS_POLICY
    assert diagnostic.gravity_m_s2 == GRAVITY_M_S2
    assert diagnostic.mass_kg == MASS_KG
    assert diagnostic.com_distance_m == COM_DISTANCE_M
    assert math.isclose(diagnostic.hinge_inertia_kg_m2, 1.001, rel_tol=0.0, abs_tol=1e-15)
    assert diagnostic.initial.angle_rad == INITIAL_ANGLE_RAD
    assert diagnostic.initial.angular_velocity_rad_s == INITIAL_ANGULAR_VELOCITY_RAD_S
    assert math.isclose(diagnostic.final.time_s, DURATION_S, rel_tol=0.0, abs_tol=1e-9)
    assert math.isfinite(diagnostic.final.angle_rad)
    assert math.isfinite(diagnostic.final.angular_velocity_rad_s)
    assert diagnostic.all_finite
    assert diagnostic.stochastic is False
    assert len(diagnostic.trajectory_sha256) == 64
    assert len(diagnostic.checkpoints) == len(reference.CHECKPOINT_TIMES_S)
    for checkpoint, expected_time in zip(
        diagnostic.checkpoints, reference.CHECKPOINT_TIMES_S, strict=True
    ):
        assert math.isclose(checkpoint.time_s, expected_time, rel_tol=0.0, abs_tol=1e-9)
    assert "not canonical or assessment evidence" in diagnostic.claim

    initial_energy = MASS_KG * GRAVITY_M_S2 * COM_DISTANCE_M * (1.0 - math.cos(INITIAL_ANGLE_RAD))
    assert math.isclose(diagnostic.energy_initial_j, initial_energy, rel_tol=0.0, abs_tol=1e-12)
    assert diagnostic.max_relative_energy_drift <= 1e-9
    assert abs(diagnostic.energy_drift_j) <= 1e-12

    staging = staging_root(fixture, fixture.run_id)
    assert (staging / "diagnostics.json").is_file()
    assert (staging / "logs" / "worker.stderr.txt").is_file()
    assert not (staging / "native").exists()
    assert not (staging / "canonical").exists()
    assert not (staging / "assessment.json").exists()
    assert fixture.workspace.source_root.as_posix() not in json.dumps(
        diagnostic.model_dump(mode="json")
    )


def test_the_real_run_seals_only_process_evidence(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    supervised = execute_fixture(fixture, mujoco_identity)
    assert supervised.result.state is RunLifecycleState.COMPLETED

    sealed = supervised.finalize()

    assert sealed.manifest.outcome is RunOutcome.SUCCEEDED
    paths = {entry.relative_path for entry in sealed.manifest.files}
    assert paths == {"diagnostics.json", "logs/worker.stderr.txt"}
    assert not any(path.startswith("native/") for path in paths)
    assert not any(path.startswith("canonical/") for path in paths)
    assert "assessment.json" not in paths

    verification = verify_sealed_bundle(
        fixture.workspace,
        fixture.run_id,
        expected_evidence_digest=sealed.evidence_digest,
    )
    assert verification.is_valid
    assert verification.proves_expected_output
    assert not staging_root(fixture, fixture.run_id).exists()
    assert sealed_root(fixture, fixture.run_id).is_dir()

    persisted = ExecutionDiagnostic.model_validate_json(
        (sealed.path / "diagnostics.json").read_bytes()
    )
    assert persisted.state is RunLifecycleState.COMPLETED
    assert persisted.adapter.engine == "mujoco"
    assert persisted.adapter.engine_version == mujoco_identity["engine_version"]
    assert persisted.refusals == ()


def test_repeated_real_executions_are_bitwise_identical_on_this_environment(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    first = execute_fixture(fixture, mujoco_identity, run_id="run-0000")
    second = execute_fixture(fixture, mujoco_identity, run_id="run-0001")
    assert first.result.state is RunLifecycleState.COMPLETED
    assert second.result.state is RunLifecycleState.COMPLETED

    first_diagnostic = native_diagnostic(fixture.workspace, "run-0000")
    second_diagnostic = native_diagnostic(fixture.workspace, "run-0001")

    assert first_diagnostic.run_id == "run-0000"
    assert second_diagnostic.run_id == "run-0001"
    assert first_diagnostic.execution_fingerprint == second_diagnostic.execution_fingerprint
    assert first_diagnostic.trajectory_sha256 == second_diagnostic.trajectory_sha256
    assert first_diagnostic.initial == second_diagnostic.initial
    assert first_diagnostic.final == second_diagnostic.final
    assert first_diagnostic.checkpoints == second_diagnostic.checkpoints
    assert first_diagnostic.energy_initial_j == second_diagnostic.energy_initial_j
    assert first_diagnostic.energy_final_j == second_diagnostic.energy_final_j
    assert first_diagnostic.max_relative_energy_drift == second_diagnostic.max_relative_energy_drift


def test_an_engine_version_mismatch_is_refused_before_staging(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    substituted = adapter_identity(mujoco_identity).model_copy(update={"engine_version": "3.17.1"})
    admission = preflight_fixture(fixture, mujoco_identity, adapter=substituted)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission.report)
    assert admission.request is None
    staging = fixture.workspace.location(PersistenceClass.STAGING).path
    assert not any(staging.iterdir())
    assert not sealed_root(fixture, fixture.run_id).exists()


def test_a_malformed_request_is_refused_by_the_real_worker(
    mujoco_identity: dict,
) -> None:
    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-malformed-") as scratch:
        completed = run_worker_process((), b"{not json\n", Path(scratch))

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert b"dynamisbench mujoco worker" in completed.stderr
    assert b"protocol v1" in completed.stderr


def test_the_real_worker_refuses_an_unapproved_argument_vector(
    mujoco_identity: dict,
) -> None:
    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-args-") as scratch:
        completed = run_worker_process(("--model", "C:/arbitrary/model.xml"), b"", Path(scratch))

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert b"no arguments except --identity" in completed.stderr
