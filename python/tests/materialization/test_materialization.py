"""DB-3.3A canonical manifest, identity binding and deterministic materialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamisbench.identity import semantic_sha256
from dynamisbench.materialization import (
    InputManifest,
    InputManifestDigest,
    MaterializationError,
    MaterializationRefusalCode,
    canonical_input_manifest_bytes,
    input_manifest_digest,
    materialize_inputs,
    parse_input_manifest,
)
from dynamisbench.materialization.schema import (
    MAX_PATH_SEGMENTS,
    DefinitionKind,
    ExecutionInputRefs,
    ManifestLimits,
)
from dynamisbench.planning import run_spec_fingerprint
from tests.materialization.conftest import ReferenceBundle, build_reference_bundle


def test_materializes_exactly_five_definitions_and_declared_asset(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    manifest = result.manifest

    assert [item.kind for item in manifest.definitions] == [
        DefinitionKind.BENCHMARK,
        DefinitionKind.ENVIRONMENT,
        DefinitionKind.REALIZATION,
        DefinitionKind.SCENARIO,
        DefinitionKind.SYSTEM_UNDER_TEST,
    ]
    assert len(manifest.assets) == 1
    asset = manifest.assets[0]
    assert asset.asset_id == "reference-model"
    assert asset.declared_sha256 == asset.observed_sha256
    assert asset.size_bytes > 0
    assert manifest.execution_refs == ExecutionInputRefs(
        benchmark=reference_bundle.run_spec.benchmark,
        scenario=reference_bundle.run_spec.scenario,
        realization=reference_bundle.run_spec.realization,
        system_under_test=reference_bundle.run_spec.system_under_test,
        environment=reference_bundle.run_spec.environment,
    )


def test_manifest_round_trips_through_canonical_bytes(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    canonical = canonical_input_manifest_bytes(result.manifest)
    digest = input_manifest_digest(result.manifest)

    assert canonical_input_manifest_bytes(parse_input_manifest(canonical)) == canonical
    assert digest == InputManifestDigest(hex=result.manifest_digest.hex)
    assert len(canonical) <= result.manifest.limits.max_manifest_bytes
    assert result.manifest_locator == f"manifests/{digest.hex}.json"


def test_manifest_is_relocation_invariant(tmp_path: Path) -> None:
    first = build_reference_bundle(tmp_path / "first")
    second = build_reference_bundle(tmp_path / "second")
    first_result = first.materialize()
    second_result = second.materialize()

    assert first_result.manifest_digest == second_result.manifest_digest
    assert canonical_input_manifest_bytes(first_result.manifest) == canonical_input_manifest_bytes(
        second_result.manifest
    )
    assert str(first.workspace.source_root) not in canonical_input_manifest_bytes(
        first_result.manifest
    ).decode("utf-8")
    assert str(first.workspace.evidence_root) not in canonical_input_manifest_bytes(
        first_result.manifest
    ).decode("utf-8")


def test_manifest_digest_is_not_the_execution_fingerprint(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    fingerprint = run_spec_fingerprint(reference_bundle.run_spec)

    assert result.manifest_digest.hex != fingerprint.hex
    assert result.manifest_digest.algorithm == fingerprint.algorithm  # same SHA-256 vocabulary


def test_same_asset_bytes_at_two_logical_paths_share_one_object(tmp_path: Path) -> None:
    bundle = build_reference_bundle(tmp_path)
    original = bundle.realization.assets[0]
    duplicate_path = "models/reference/pendulum-copy.xml"
    duplicate_file = bundle.workspace.source_root / duplicate_path
    duplicate_file.write_bytes((bundle.workspace.source_root / original.path).read_bytes())
    realization = bundle.realization.model_copy(
        update={
            "assets": (
                original,
                original.model_copy(
                    update={"asset_id": "reference-model-copy", "path": duplicate_path}
                ),
            )
        }
    )
    updated_spec = bundle.run_spec.model_copy(
        update={
            "realization": bundle.run_spec.realization.model_copy(
                update={"semantic_digest": semantic_sha256(realization)}
            )
        }
    )
    result = materialize_inputs(
        bundle.workspace,
        updated_spec,
        benchmark=bundle.benchmark,
        scenario=bundle.scenario,
        realization=realization,
        system_under_test=bundle.system_under_test,
        environment=bundle.environment,
    )

    assert len(result.manifest.assets) == 2
    assert len({asset.object for asset in result.manifest.assets}) == 1
    assert result.manifest.assets[0].observed_sha256 == result.manifest.assets[1].observed_sha256


def test_changed_definition_is_refused_before_a_manifest(
    reference_bundle: ReferenceBundle,
) -> None:
    changed = reference_bundle.benchmark.model_copy(update={"label": "changed label"})
    with pytest.raises(MaterializationError) as caught:
        materialize_inputs(
            reference_bundle.workspace,
            reference_bundle.run_spec,
            benchmark=changed,
            scenario=reference_bundle.scenario,
            realization=reference_bundle.realization,
            system_under_test=reference_bundle.system_under_test,
            environment=reference_bundle.environment,
        )
    assert caught.value.code is MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH
    assert not list(
        (reference_bundle.workspace.evidence_root / "cache" / "inputs" / "manifests").glob("*.json")
    )


@pytest.mark.parametrize(
    ("definition_name", "changed"),
    (
        ("benchmark", lambda bundle: bundle.benchmark.model_copy(update={"label": "changed"})),
        ("scenario", lambda bundle: bundle.scenario.model_copy(update={"label": "changed"})),
        ("realization", lambda bundle: bundle.realization.model_copy(update={"label": "changed"})),
        (
            "system_under_test",
            lambda bundle: bundle.system_under_test.model_copy(update={"label": "changed"}),
        ),
        (
            "environment",
            lambda bundle: bundle.environment.model_copy(update={"label": "changed"}),
        ),
    ),
)
def test_each_of_the_five_definitions_must_match_the_runspec(
    reference_bundle: ReferenceBundle,
    definition_name: str,
    changed: object,
) -> None:
    argument = changed(reference_bundle)  # type: ignore[operator]
    arguments = {
        "benchmark": reference_bundle.benchmark,
        "scenario": reference_bundle.scenario,
        "realization": reference_bundle.realization,
        "system_under_test": reference_bundle.system_under_test,
        "environment": reference_bundle.environment,
        definition_name: argument,
    }
    with pytest.raises(MaterializationError) as caught:
        materialize_inputs(
            reference_bundle.workspace,
            reference_bundle.run_spec,
            **arguments,
        )
    assert caught.value.code is MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH


def test_scenario_must_be_embedded_in_the_selected_benchmark(
    reference_bundle: ReferenceBundle,
) -> None:
    other = reference_bundle.scenario.model_copy(update={"label": "another scenario"})
    with pytest.raises(MaterializationError) as caught:
        materialize_inputs(
            reference_bundle.workspace,
            reference_bundle.run_spec,
            benchmark=reference_bundle.benchmark,
            scenario=other,
            realization=reference_bundle.realization,
            system_under_test=reference_bundle.system_under_test,
            environment=reference_bundle.environment,
        )
    assert caught.value.code is MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH


def test_subprocess_and_bridge_suts_are_refused(
    reference_bundle: ReferenceBundle,
) -> None:
    from dynamisbench.domain.spec.sut import SUTInterface, SUTInterfaceKind

    for kind in (SUTInterfaceKind.SUBPROCESS, SUTInterfaceKind.BRIDGE):
        command = ("python", "-m", "controller") if kind is SUTInterfaceKind.SUBPROCESS else None
        sut = reference_bundle.system_under_test.model_copy(
            update={"interface": SUTInterface(kind=kind, command=command)}
        )
        with pytest.raises(MaterializationError) as caught:
            materialize_inputs(
                reference_bundle.workspace,
                reference_bundle.run_spec,
                benchmark=reference_bundle.benchmark,
                scenario=reference_bundle.scenario,
                realization=reference_bundle.realization,
                system_under_test=sut,
                environment=reference_bundle.environment,
            )
        assert caught.value.code is MaterializationRefusalCode.SUT_EXECUTABLE_CLOSURE_UNSUPPORTED


def test_platform_environment_identity_is_not_forced_equal(tmp_path: Path) -> None:
    windows = build_reference_bundle(tmp_path / "windows", platform_tag="windows-x86-64")
    linux = build_reference_bundle(tmp_path / "linux", platform_tag="linux-x86-64")
    windows_result = windows.materialize()
    linux_result = linux.materialize()

    assert windows.benchmark == linux.benchmark
    assert windows.scenario == linux.scenario
    assert windows.realization == linux.realization
    assert windows.system_under_test == linux.system_under_test
    assert windows.environment != linux.environment
    assert (
        windows.run_spec.environment.semantic_digest != linux.run_spec.environment.semantic_digest
    )
    assert run_spec_fingerprint(windows.run_spec) != run_spec_fingerprint(linux.run_spec)
    assert windows_result.manifest_digest != linux_result.manifest_digest
    assert semantic_sha256(windows.benchmark) == semantic_sha256(linux.benchmark)


def test_manifest_refuses_case_only_logical_path_aliases(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    asset = result.manifest.assets[0]
    duplicate = asset.model_copy(
        update={"asset_id": "other", "logical_path": "MODELS/reference/pendulum.xml"}
    )
    with pytest.raises(ValueError):
        InputManifest(
            execution_refs=result.manifest.execution_refs,
            definitions=result.manifest.definitions,
            assets=(asset, duplicate),
            limits=ManifestLimits(),
        )


def test_manifest_refuses_path_over_the_segment_bound(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    too_deep = "/".join(["a"] * (MAX_PATH_SEGMENTS + 1))
    asset = result.manifest.assets[0].model_copy(update={"logical_path": too_deep})
    with pytest.raises(ValueError):
        InputManifest(
            execution_refs=result.manifest.execution_refs,
            definitions=result.manifest.definitions,
            assets=(asset,),
            limits=ManifestLimits(),
        )
