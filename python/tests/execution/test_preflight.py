"""Preflight refuses unsafe or unexecutable admissions before any process starts."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.identifiers import EnvironmentId
from dynamisbench.evidence import create_staging_bundle
from dynamisbench.evidence.bundle import BundleNamingError
from dynamisbench.execution import (
    PreflightDecision,
    RefusalCode,
    canonical_preflight_bytes,
    preflight_digest,
    preflight_run,
)
from dynamisbench.identity import SemanticDigest
from dynamisbench.planning.authority import ResolvedEnvironmentRef
from dynamisbench.planning.runspec import ExecutionFingerprint
from dynamisbench.workspace import PersistenceClass
from tests.execution.support import (
    ExecutionFixture,
    adapter_identity,
    asset_realization,
    build_fixture,
    control_environment,
    control_realization,
    preflight,
    seal_control_bundle,
    worker_manifest,
    write_source_asset,
)


def _codes(fixture) -> set[RefusalCode]:
    return {item.code for item in fixture.report.refusals}


def test_ready_preflight_is_deterministic_and_read_only(
    execution_fixture: ExecutionFixture,
) -> None:
    first = preflight(execution_fixture)
    second = preflight(execution_fixture)

    assert first.report.decision is PreflightDecision.READY
    assert first.report.refusals == ()
    assert first.request is not None
    assert first.report.staging_locator == f".staging/{execution_fixture.run_id}"
    assert first.report.request_digest == second.report.request_digest
    assert canonical_preflight_bytes(first.report) == canonical_preflight_bytes(second.report)
    assert preflight_digest(first.report) == preflight_digest(second.report)
    staging = execution_fixture.workspace.location(PersistenceClass.STAGING).path
    sealed = execution_fixture.workspace.location(PersistenceClass.SEALED_EVIDENCE).path
    assert not any(staging.iterdir())
    assert not sealed.exists()


def test_a_refused_report_contains_no_absolute_path(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    manifest = worker_manifest(execution_fixture, program=str(tmp_path / "missing-worker.exe"))
    admission = preflight(execution_fixture, manifest)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.WORKER_PROGRAM_UNRESOLVED in _codes(admission)
    rendered = admission.report.model_dump_json()
    assert str(tmp_path) not in rendered
    assert str(execution_fixture.workspace.source_root) not in rendered


def test_a_fingerprint_that_is_not_the_run_spec_identity_is_refused(
    execution_fixture: ExecutionFixture,
) -> None:
    tampered = execution_fixture.run.model_copy(
        update={"fingerprint": ExecutionFingerprint(hex="0" * 64)}
    )
    admission = preflight_run(
        execution_fixture.run_id,
        tampered,
        realization=execution_fixture.realization,
        environment=execution_fixture.environment,
        manifest=worker_manifest(execution_fixture),
        workspace=execution_fixture.workspace,
    )

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.FINGERPRINT_MISMATCH in _codes(admission)
    assert admission.request is None
    assert admission.report.staging_locator is None


def test_a_substituted_realization_is_refused(execution_fixture: ExecutionFixture) -> None:
    substituted = control_realization(description="A different control realization.")
    admission = preflight_run(
        execution_fixture.run_id,
        execution_fixture.run,
        realization=substituted,
        environment=execution_fixture.environment,
        manifest=worker_manifest(execution_fixture),
        workspace=execution_fixture.workspace,
    )

    assert RefusalCode.REALIZATION_IDENTITY_MISMATCH in _codes(admission)


def test_a_substituted_environment_definition_is_refused(
    execution_fixture: ExecutionFixture,
) -> None:
    substituted = control_environment(description="A different control environment.")
    admission = preflight_run(
        execution_fixture.run_id,
        execution_fixture.run,
        realization=execution_fixture.realization,
        environment=substituted,
        manifest=worker_manifest(execution_fixture),
        workspace=execution_fixture.workspace,
    )

    assert RefusalCode.ENVIRONMENT_IDENTITY_MISMATCH in _codes(admission)


def test_a_manifest_for_another_environment_is_refused(
    execution_fixture: ExecutionFixture,
) -> None:
    other_environment = ResolvedEnvironmentRef(
        identifier=EnvironmentId("env.other.x86-64"),
        version="1.0.0",
        semantic_digest=SemanticDigest(hex="0" * 64),
    )
    manifest = worker_manifest(execution_fixture, environment=other_environment)
    admission = preflight(execution_fixture, manifest)

    assert RefusalCode.ENVIRONMENT_IDENTITY_MISMATCH in _codes(admission)


def test_an_adapter_for_another_engine_is_refused(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        adapter=adapter_identity(execution_fixture.required_capabilities, engine="mujoco"),
    )
    admission = preflight(execution_fixture, manifest)

    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission)


def test_an_unsupported_capability_is_refused(execution_fixture: ExecutionFixture) -> None:
    manifest = worker_manifest(execution_fixture, capabilities=(Capability.FORWARD_DYNAMICS,))
    admission = preflight(execution_fixture, manifest)

    assert RefusalCode.UNSUPPORTED_CAPABILITY in _codes(admission)


def test_an_unknown_capability_in_the_accepted_plan_is_refused(
    execution_fixture: ExecutionFixture,
) -> None:
    from dynamisbench.planning.compatibility import EffectiveCapabilityRequirement

    unrepresentable = EffectiveCapabilityRequirement.model_construct(
        capability="quantum-teleport",
        essential=True,
        demands=(),
    )
    compatibility = execution_fixture.run.capabilities.model_copy(
        update={"requirements": (unrepresentable,)}
    )
    tampered = execution_fixture.run.model_copy(update={"capabilities": compatibility})

    admission = preflight_run(
        execution_fixture.run_id,
        tampered,
        realization=execution_fixture.realization,
        environment=execution_fixture.environment,
        manifest=worker_manifest(execution_fixture),
        workspace=execution_fixture.workspace,
    )

    assert RefusalCode.UNKNOWN_CAPABILITY in _codes(admission)


def test_a_missing_asset_is_refused(tmp_path: Path) -> None:
    realization = asset_realization(path="models/missing.xml", sha256=None)
    fixture = build_fixture(tmp_path, realization=realization)
    admission = preflight(fixture)

    assert RefusalCode.UNSTAGED_ASSET in _codes(admission)


def test_an_asset_digest_mismatch_is_refused(tmp_path: Path) -> None:
    realization = asset_realization(path="models/control.xml", sha256="0" * 64)
    fixture = build_fixture(tmp_path, realization=realization)
    write_source_asset(fixture.workspace, "models/control.xml", b"control-model")

    admission = preflight(fixture)

    assert RefusalCode.ASSET_DIGEST_MISMATCH in _codes(admission)


def test_a_present_asset_without_a_content_identity_is_refused(tmp_path: Path) -> None:
    realization = asset_realization(path="models/control.xml", sha256=None)
    fixture = build_fixture(tmp_path, realization=realization)
    write_source_asset(fixture.workspace, "models/control.xml", b"unidentified-model")

    admission = preflight(fixture)

    assert RefusalCode.UNSTAGED_ASSET in _codes(admission)
    assert admission.request is None


def test_a_present_content_addressed_asset_is_ready(tmp_path: Path) -> None:
    placeholder = build_fixture(tmp_path)
    digest = write_source_asset(placeholder.workspace, "models/control.xml", b"control-model")
    realization = asset_realization(path="models/control.xml", sha256=digest)
    fixture = build_fixture(tmp_path, realization=realization, workspace=placeholder.workspace)

    admission = preflight(fixture)

    assert admission.report.decision is PreflightDecision.READY


def test_an_asset_path_that_escapes_the_source_root_is_refused(tmp_path: Path) -> None:
    from dynamisbench.domain.spec.realizations import AssetReference

    escape = AssetReference.model_construct(
        asset_id="escape",
        path="../outside.xml",
        description="A path that must never reach the filesystem resolver.",
        sha256="0" * 64,
    )
    realization = control_realization(assets=(escape,))
    fixture = build_fixture(tmp_path, realization=realization)
    admission = preflight(fixture)

    assert RefusalCode.FORBIDDEN_PATH in _codes(admission)


def test_a_duplicate_staging_run_is_refused(execution_fixture: ExecutionFixture) -> None:
    create_staging_bundle(execution_fixture.workspace, execution_fixture.run_id)
    admission = preflight(execution_fixture)

    assert RefusalCode.DUPLICATE_EXECUTION in _codes(admission)


def test_an_already_sealed_run_is_refused(execution_fixture: ExecutionFixture) -> None:
    seal_control_bundle(execution_fixture.workspace, execution_fixture.run_id)
    admission = preflight(execution_fixture)

    assert RefusalCode.DUPLICATE_EXECUTION in _codes(admission)


def test_a_worker_program_that_does_not_exist_is_refused(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    manifest = worker_manifest(execution_fixture, program=str(tmp_path / "absent-python.exe"))
    admission = preflight(execution_fixture, manifest)

    assert RefusalCode.WORKER_PROGRAM_UNRESOLVED in _codes(admission)


def test_an_invalid_run_id_is_a_naming_error_not_an_execution(
    execution_fixture: ExecutionFixture,
) -> None:
    with pytest.raises(BundleNamingError):
        preflight_run(
            "..",
            execution_fixture.run,
            realization=execution_fixture.realization,
            environment=execution_fixture.environment,
            manifest=worker_manifest(execution_fixture),
            workspace=execution_fixture.workspace,
        )


def test_a_malformed_run_spec_cannot_be_constructed() -> None:
    from dynamisbench.planning import RunSpec

    with pytest.raises(ValidationError):
        RunSpec.model_validate({"schema_version": "0.1.0"})


@given(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_every_other_well_formed_fingerprint_is_refused(
    execution_fixture: ExecutionFixture, hex_digest: str
) -> None:
    if hex_digest == execution_fixture.fingerprint.hex:
        return
    tampered = execution_fixture.run.model_copy(
        update={"fingerprint": ExecutionFingerprint(hex=hex_digest)}
    )
    admission = preflight_run(
        execution_fixture.run_id,
        tampered,
        realization=execution_fixture.realization,
        environment=execution_fixture.environment,
        manifest=worker_manifest(execution_fixture),
        workspace=execution_fixture.workspace,
    )

    assert RefusalCode.FINGERPRINT_MISMATCH in _codes(admission)
    assert admission.request is None


@given(st.sets(st.sampled_from(list(Capability))))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_every_advertisement_missing_a_requirement_is_refused(
    execution_fixture: ExecutionFixture, advertised: set[Capability]
) -> None:
    if set(execution_fixture.required_capabilities) <= advertised:
        return
    manifest = worker_manifest(execution_fixture, capabilities=tuple(advertised))
    admission = preflight(execution_fixture, manifest)

    assert RefusalCode.UNSUPPORTED_CAPABILITY in _codes(admission)
    assert admission.request is None
