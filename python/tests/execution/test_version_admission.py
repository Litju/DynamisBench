"""Preflight integration of engine-version admission.

The pure evaluator is qualified in ``test_versions.py``. These tests prove that the
admission boundary actually uses it against both independently authored constraints: the
realization's engine binding and the selected environment's ENGINE requirement.
"""

from __future__ import annotations

from pathlib import Path

from dynamisbench.domain.spec.capability import EngineBinding
from dynamisbench.domain.spec.environment import ComponentKind, EnvironmentRequirement
from dynamisbench.domain.spec.identifiers import Comparator, VersionClause, VersionSpecifier
from dynamisbench.execution import PreflightDecision, RefusalCode
from tests.execution.support import (
    CONTROL_ENGINE,
    CONTROL_ENGINE_VERSION,
    ExecutionFixture,
    adapter_identity,
    asset_realization,
    build_fixture,
    control_environment,
    control_realization,
    preflight,
    worker_manifest,
    write_source_asset,
)


def _specifier(*clauses: tuple[Comparator, str]) -> VersionSpecifier:
    return VersionSpecifier(
        clauses=tuple(
            VersionClause(comparator=comparator, version=version) for comparator, version in clauses
        )
    )


def _engine(version: str, comparator: Comparator = Comparator.EXACT) -> EngineBinding:
    return EngineBinding(engine=CONTROL_ENGINE, specifier=_specifier((comparator, version)))


def _environment(
    control_specifier: VersionSpecifier,
):
    return control_environment(
        requirements=(
            EnvironmentRequirement(
                component=CONTROL_ENGINE,
                kind=ComponentKind.ENGINE,
                specifier=control_specifier,
            ),
            EnvironmentRequirement(
                component="python",
                kind=ComponentKind.RUNTIME,
                specifier=_specifier((Comparator.GREATER_THAN_OR_EQUAL, "3.12.0")),
            ),
        )
    )


def _fixture(tmp_path: Path, *, realization, environment) -> ExecutionFixture:
    return build_fixture(tmp_path, realization=realization, environment=environment)


def _codes(admission) -> set[RefusalCode]:
    return {item.code for item in admission.report.refusals}


def test_a_matching_version_and_environment_are_ready(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine(CONTROL_ENGINE_VERSION)),
        environment=_environment(_specifier((Comparator.EXACT, CONTROL_ENGINE_VERSION))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(
                fixture.required_capabilities, engine_version=CONTROL_ENGINE_VERSION
            ),
        ),
    )

    assert admission.report.decision is PreflightDecision.READY


def test_a_realization_version_mismatch_is_refused(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=_environment(_specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, engine_version="1.0.1"),
        ),
    )

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission)


def test_an_environment_version_mismatch_is_refused(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=_environment(_specifier((Comparator.GREATER_THAN_OR_EQUAL, "2.0.0"))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, engine_version="1.0.0"),
        ),
    )

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission)


def test_build_metadata_is_an_artifact_difference_for_an_exact_clause(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=_environment(_specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, engine_version="1.0.0+build.1"),
        ),
    )

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission)


def test_not_equal_and_ordered_clauses_admit_a_different_version(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(
            engine=EngineBinding(
                engine=CONTROL_ENGINE,
                specifier=_specifier((Comparator.NOT_EQUAL, "1.0.0")),
            )
        ),
        environment=_environment(_specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, engine_version="1.0.1"),
        ),
    )

    assert admission.report.decision is PreflightDecision.READY


def test_a_prerelease_below_the_required_release_is_refused(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0", Comparator.GREATER_THAN_OR_EQUAL)),
        environment=_environment(_specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, engine_version="1.0.0-alpha"),
        ),
    )

    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission)


def test_a_prerelease_above_the_required_release_is_admitted_by_precedence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0", Comparator.GREATER_THAN_OR_EQUAL)),
        environment=_environment(_specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"))),
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, engine_version="1.1.0-beta"),
        ),
    )

    assert admission.report.decision is PreflightDecision.READY


def test_a_compatible_environment_constraint_is_unresolvable(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=_environment(_specifier((Comparator.COMPATIBLE, "1.0.0"))),
    )
    admission = preflight(fixture)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in _codes(admission)


def test_a_malformed_environment_version_is_unresolvable(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=_environment(_specifier((Comparator.GREATER_THAN, "not-a-version"))),
    )
    admission = preflight(fixture)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in _codes(admission)


def test_contradictory_environment_constraints_are_unresolvable(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=_environment(
            _specifier(
                (Comparator.GREATER_THAN_OR_EQUAL, "2.0.0"),
                (Comparator.LESS_THAN, "2.0.0"),
            )
        ),
    )
    admission = preflight(fixture)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in _codes(admission)


def test_an_environment_without_an_engine_requirement_is_refused(tmp_path: Path) -> None:
    environment = control_environment(
        requirements=(
            EnvironmentRequirement(
                component="python",
                kind=ComponentKind.RUNTIME,
                specifier=_specifier((Comparator.GREATER_THAN_OR_EQUAL, "3.12.0")),
            ),
        )
    )
    fixture = _fixture(
        tmp_path,
        realization=control_realization(engine=_engine("1.0.0")),
        environment=environment,
    )
    admission = preflight(fixture)

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ENVIRONMENT_IDENTITY_MISMATCH in _codes(admission)


def test_a_realization_asset_requires_an_adapter_implementation_identity(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(
        tmp_path, realization=asset_realization(path="models/control.xml", sha256=None)
    )
    digest = write_source_asset(fixture.workspace, "models/control.xml", b"control-model")
    realization = asset_realization(path="models/control.xml", sha256=digest)
    fixture = build_fixture(
        tmp_path,
        realization=realization,
        workspace=fixture.workspace,
    )
    admission = preflight(
        fixture,
        worker_manifest(
            fixture,
            adapter=adapter_identity(fixture.required_capabilities, implementation_digest=None),
        ),
    )

    assert admission.report.decision is PreflightDecision.REFUSED
    assert RefusalCode.ADAPTER_ENGINE_MISMATCH in _codes(admission)
