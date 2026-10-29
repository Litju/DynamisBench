"""Adversarial real-worker qualification of the RES-550 reference-authority binding.

Every negative case here starts from a *valid* alternative definition, constructs it with
the domain models, and compiles it through the real planner. The execution fingerprint is
therefore recomputed from the modified meaning, not copied from the accepted run, and
preflight is completed where the modified authority is otherwise admissible. The actual
isolated MuJoCo worker is then launched. The worker must refuse the incompatible experiment
before it advances physics, and the failed process must not become a successful seal.

A direct protocol-valid request with a substituted semantic digest is also exercised, so the
worker's own refusal does not depend on upstream preflight.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel

from dynamisbench.adapters.mujoco import reference
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.realizations import (
    AssetReference,
    ConfigurationEntry,
    RealizationDefinition,
)
from dynamisbench.domain.spec.studies import PointValue, StudyDefinition
from dynamisbench.evidence import RunOutcome, verify_sealed_bundle
from dynamisbench.execution import (
    ExecutionSealError,
    PreflightDecision,
    RefusalCode,
    RunLifecycleState,
    WorkerRequest,
    WorkerStatus,
    canonical_worker_request_bytes,
    execute_preflighted,
    parse_worker_response,
)
from dynamisbench.identity import SemanticDigest
from dynamisbench.planning.runspec import run_spec_fingerprint
from tests.execution.mujoco.support import (
    ExecutionFixture,
    benchmark_release,
    build_mujoco_fixture,
    environment_definition,
    execute_fixture,
    preflight_fixture,
    realization_definition,
    run_worker_process,
    sealed_root,
    staging_root,
    system_under_test,
)


def _revalidated[ModelT: BaseModel](model: ModelT, **updates: object) -> ModelT:
    """Apply domain-valid changes and re-run every validator on the result.

    This is deliberately not a blind ``model_copy``: the changed payload is validated by the
    same Pydantic model that authorizes production definitions, so an alternative used here
    is a genuinely valid definition and planning can resolve it normally.
    """
    payload = model.model_dump(mode="python")
    payload.update(updates)
    return type(model).model_validate(payload)


def _codes(result) -> set[RefusalCode]:
    return {item.code for item in result.refusals}


def _worker_log(fixture: ExecutionFixture, run_id: str) -> str:
    path = staging_root(fixture, run_id) / "logs" / "worker.stderr.txt"
    return path.read_text(encoding="utf-8", errors="replace")


def _benchmark_with_scenario(**scenario_updates: object) -> BenchmarkRelease:
    benchmark = benchmark_release()
    scenario = _revalidated(benchmark.scenarios[0], **scenario_updates)
    return _revalidated(benchmark, scenarios=(scenario.model_dump(mode="python"),))


def _scenario_with_initial_angle(angle_rad: float) -> BenchmarkRelease:
    benchmark = benchmark_release()
    conditions = list(benchmark.scenarios[0].initial_conditions)
    conditions[0] = _revalidated(conditions[0], value=angle_rad)
    scenario = _revalidated(
        benchmark.scenarios[0],
        initial_conditions=tuple(item.model_dump(mode="python") for item in conditions),
    )
    return _revalidated(benchmark, scenarios=(scenario.model_dump(mode="python"),))


def _realization_with_configuration(
    identity: dict,
    *,
    name: str,
    value: str,
) -> RealizationDefinition:
    base = realization_definition(
        asset_sha256=reference.MODEL_SHA256,
        engine_version=identity["engine_version"],
    )
    configuration = tuple(
        entry for entry in base.engine_configuration if str(entry.name) != name
    ) + (ConfigurationEntry(name=name, value=value),)
    return _revalidated(
        base,
        engine_configuration=tuple(entry.model_dump(mode="python") for entry in configuration),
    )


def _realization_with_model(
    identity: dict,
    *,
    asset_sha256: str,
) -> RealizationDefinition:
    base = realization_definition(
        asset_sha256=reference.MODEL_SHA256,
        engine_version=identity["engine_version"],
    )
    asset = AssetReference(
        asset_id="reference-model",
        path=reference.MODEL_SOURCE_PATH,
        description="Self-contained MJCF XML of the reviewed reference pendulum.",
        sha256=asset_sha256,
    )
    return _revalidated(base, assets=(asset.model_dump(mode="python"),))


def _study_with_seed(seed: int) -> StudyDefinition:
    from tests.execution.mujoco.support import study_definition

    study = study_definition(
        environment_definition(
            {"engine_version": reference.ENGINE_VERSION, "python_version": reference.PYTHON_VERSION}
        ).environment_id
    )
    return _revalidated(study, seeds=(seed,))


def _study_with_gravity(value: float) -> StudyDefinition:
    from tests.execution.mujoco.support import study_definition

    study = study_definition(
        environment_definition(
            {"engine_version": reference.ENGINE_VERSION, "python_version": reference.PYTHON_VERSION}
        ).environment_id
    )
    factor = _revalidated(study.factors[0], distribution=PointValue(value=value))
    return _revalidated(study, factors=(factor.model_dump(mode="python"),))


def _assert_worker_refused_the_modified_experiment(
    fixture: ExecutionFixture,
    identity: dict,
    *,
    expected_message: str,
    run_id: str,
) -> None:
    admission = preflight_fixture(fixture, identity, run_id=run_id)
    assert admission.report.decision is PreflightDecision.READY, (
        f"the modified authority was not otherwise admissible: "
        f"{[item.code.value for item in admission.report.refusals]}"
    )
    assert admission.request is not None
    assert admission.request.execution_fingerprint == run_spec_fingerprint(
        admission.request.run_spec
    )

    supervised = execute_preflighted(admission)
    result = supervised.result

    assert result.state is RunLifecycleState.FAILED
    assert RefusalCode.WORKER_FAILED in _codes(result)
    log = _worker_log(fixture, run_id)
    assert expected_message in log
    assert "DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in log

    with pytest.raises(ExecutionSealError, match="ended as failed"):
        supervised.finalize(RunOutcome.SUCCEEDED)
    sealed = supervised.finalize()
    assert sealed.manifest.outcome is RunOutcome.FAILED
    assert sealed_root(fixture, run_id).is_dir()


@pytest.fixture(scope="module")
def sealed_reference(tmp_path_factory, mujoco_identity: dict):
    """One canonical reference run sealed before any adversarial case is constructed."""
    root = tmp_path_factory.mktemp("mujoco-sealed-reference")
    fixture = build_mujoco_fixture(root, identity=mujoco_identity)
    supervised = execute_fixture(fixture, mujoco_identity)
    assert supervised.result.state is RunLifecycleState.COMPLETED
    sealed = supervised.finalize()
    assert sealed.manifest.outcome is RunOutcome.SUCCEEDED
    return fixture, sealed.evidence_digest


def _verify_sealed_reference_is_unchanged(sealed_reference) -> None:
    fixture, digest = sealed_reference
    verification = verify_sealed_bundle(
        fixture.workspace,
        fixture.run_id,
        expected_evidence_digest=digest,
    )
    assert verification.is_valid
    assert verification.proves_expected_output
    assert sealed_root(fixture, fixture.run_id).is_dir()


def test_the_unchanged_reference_still_completes(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    """Positive control: the authority binding must not refuse the accepted experiment."""
    supervised = execute_fixture(mujoco_fixture, mujoco_identity)
    assert supervised.result.state is RunLifecycleState.COMPLETED
    assert supervised.result.refusals == ()
    seals = supervised.finalize()
    assert seals.manifest.outcome is RunOutcome.SUCCEEDED


def test_a_changed_scenario_duration_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    benchmark = _benchmark_with_scenario(duration_s=2.5)
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, benchmark=benchmark)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="benchmark semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_a_changed_scenario_initial_angle_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    benchmark = _scenario_with_initial_angle(0.4)
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, benchmark=benchmark)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="benchmark semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_a_changed_realization_timestep_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    realization = _realization_with_configuration(mujoco_identity, name="timestep", value="0.002")
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, realization=realization)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="realization semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_a_changed_realization_integrator_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    realization = _realization_with_configuration(mujoco_identity, name="integrator", value="Euler")
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, realization=realization)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="realization semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_changed_model_bytes_and_realization_digest_are_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    modified_bytes = reference.model_bytes().replace(b'mass="1"', b'mass="1.1"')
    assert modified_bytes != reference.model_bytes()
    digest = hashlib.sha256(modified_bytes).hexdigest()
    realization = _realization_with_model(mujoco_identity, asset_sha256=digest)
    fixture = build_mujoco_fixture(
        tmp_path,
        identity=mujoco_identity,
        realization=realization,
        asset_bytes=modified_bytes,
    )

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="realization semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_changed_benchmark_content_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    benchmark = _revalidated(
        benchmark_release(),
        description="A changed benchmark definition with the same identifier and version.",
    )
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, benchmark=benchmark)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="benchmark semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_changed_sut_content_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    sut = _revalidated(
        system_under_test(asset_sha256=reference.MODEL_SHA256),
        description="A changed system-under-test description with the same identifiers.",
    )
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, sut=sut)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="system under test semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_changed_environment_content_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    environment = _revalidated(
        environment_definition(mujoco_identity),
        description="A changed environment definition with the same identifier and version.",
    )
    fixture = build_mujoco_fixture(tmp_path, identity=mujoco_identity, environment=environment)

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="environment semantic digest",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_a_changed_seed_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    fixture = build_mujoco_fixture(
        tmp_path,
        identity=mujoco_identity,
        study=_study_with_seed(1),
    )
    assert fixture.run.spec.seed == 1

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="seed",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def test_a_changed_gravity_factor_is_refused_by_the_real_worker(
    tmp_path: Path, mujoco_identity: dict, sealed_reference
) -> None:
    fixture = build_mujoco_fixture(
        tmp_path,
        identity=mujoco_identity,
        study=_study_with_gravity(9.81),
    )
    assert fixture.run.spec.factors[0].value == 9.81

    _assert_worker_refused_the_modified_experiment(
        fixture,
        mujoco_identity,
        expected_message="gravity factor",
        run_id=fixture.run_id,
    )
    _verify_sealed_reference_is_unchanged(sealed_reference)


def _direct_request_with(
    admission,
    **spec_updates: object,
) -> WorkerRequest:
    assert admission.request is not None
    spec = _revalidated(admission.request.run_spec, **spec_updates)
    return WorkerRequest(
        run_id=admission.request.run_id,
        run_spec=spec,
        execution_fingerprint=run_spec_fingerprint(spec),
        environment=spec.environment,
        adapter=admission.request.adapter,
        required_capabilities=admission.request.required_capabilities,
        supported_capabilities=admission.request.supported_capabilities,
        staging_locator=admission.request.staging_locator,
    )


@pytest.mark.parametrize(
    ("field", "expected_message"),
    (
        ("benchmark", "benchmark semantic digest"),
        ("scenario", "scenario semantic digest"),
        ("realization", "realization semantic digest"),
        ("system_under_test", "system under test semantic digest"),
        ("environment", "environment semantic digest"),
    ),
)
def test_a_direct_protocol_request_with_a_substituted_semantic_digest_is_refused(
    mujoco_fixture: ExecutionFixture,
    mujoco_identity: dict,
    field: str,
    expected_message: str,
) -> None:
    """Bypass preflight entirely: the worker itself must still reject the substitution."""
    admission = preflight_fixture(mujoco_fixture, mujoco_identity)
    assert admission.request is not None
    resolved = getattr(admission.request.run_spec, field)
    substituted = resolved.model_copy(update={"semantic_digest": SemanticDigest(hex="1" * 64)})
    request = _direct_request_with(admission, **{field: substituted})

    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-direct-") as scratch:
        completed = run_worker_process(
            (),
            canonical_worker_request_bytes(request) + b"\n",
            Path(scratch),
        )

    assert completed.returncode == 0
    response = parse_worker_response(completed.stdout)
    assert response.status is WorkerStatus.FAILED
    assert expected_message in (response.message or "")
    assert b"DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in completed.stderr


def test_a_direct_protocol_request_with_a_changed_seed_is_refused(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    admission = preflight_fixture(mujoco_fixture, mujoco_identity)
    request = _direct_request_with(admission, seed=1)

    with tempfile.TemporaryDirectory(prefix="dynamisbench-mujoco-direct-") as scratch:
        completed = run_worker_process(
            (),
            canonical_worker_request_bytes(request) + b"\n",
            Path(scratch),
        )

    assert completed.returncode == 0
    response = parse_worker_response(completed.stdout)
    assert response.status is WorkerStatus.FAILED
    assert "seed" in (response.message or "")
    assert b"DYNAMISBENCH_MUJOCO_DIAGNOSTIC" not in completed.stderr
