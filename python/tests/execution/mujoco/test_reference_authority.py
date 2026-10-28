"""Independent verification of the pinned RES-550 reference authority.

The adapter refuses a request whose resolved semantic digests are not the reviewed
definitions it was compiled for. These tests prove that the pins are current and that the
accepted test fixture independently re-authors the same meaning. They do not run MuJoCo;
the real-process refusal tests live in ``test_adversarial_authority.py``.
"""

from __future__ import annotations

from dynamisbench.adapters.mujoco import reference, reference_case
from dynamisbench.identity import semantic_sha256
from dynamisbench.planning.runspec import run_spec_fingerprint
from tests.execution.mujoco.support import (
    ExecutionFixture,
    benchmark_release,
    environment_definition,
    realization_definition,
    system_under_test,
)


def _pinned() -> dict[str, str]:
    return {
        "benchmark": reference.BENCHMARK_SEMANTIC_DIGEST.hex,
        "scenario": reference.SCENARIO_SEMANTIC_DIGEST.hex,
        "realization": reference.REALIZATION_SEMANTIC_DIGEST.hex,
        "system_under_test": reference.SUT_SEMANTIC_DIGEST.hex,
        "environment_windows_x86_64": reference.ENVIRONMENT_SEMANTIC_DIGESTS["windows-x86-64"].hex,
        "environment_linux_x86_64": reference.ENVIRONMENT_SEMANTIC_DIGESTS["linux-x86-64"].hex,
    }


def test_the_pins_are_the_digests_of_the_canonical_definitions() -> None:
    observed = reference_case.reference_authority_matches_definitions()

    assert observed == _pinned()


def test_the_accepted_fixture_reauthors_the_pinned_reference_meaning(
    mujoco_identity: dict,
) -> None:
    """The qualification fixture is an independent re-authoring, not an import of the pins.

    ``tests.execution.mujoco.support`` constructs the definitions itself from the physical
    constants and the installed identity. If either the fixture or the production canonical
    definitions change meaning, this comparison fails and the pin must be reviewed.
    """
    benchmark = benchmark_release()
    realization = realization_definition(
        asset_sha256=reference.MODEL_SHA256,
        engine_version=mujoco_identity["engine_version"],
    )
    sut = system_under_test(asset_sha256=reference.MODEL_SHA256)
    environment = environment_definition(mujoco_identity)

    assert semantic_sha256(benchmark) == reference.BENCHMARK_SEMANTIC_DIGEST
    assert semantic_sha256(benchmark.scenarios[0]) == reference.SCENARIO_SEMANTIC_DIGEST
    assert semantic_sha256(realization) == reference.REALIZATION_SEMANTIC_DIGEST
    assert semantic_sha256(sut) == reference.SUT_SEMANTIC_DIGEST
    assert semantic_sha256(environment) == reference.environment_semantic_digest_for(
        reference.platform_tag()
    )


def test_the_planned_reference_execution_is_the_canonical_run_spec(
    mujoco_fixture: ExecutionFixture,
) -> None:
    """Planning the accepted fixture must produce the canonical reference execution."""
    canonical = reference_case.run_spec(platform_tag=reference.platform_tag())

    assert mujoco_fixture.run.spec == canonical
    assert mujoco_fixture.run.fingerprint == run_spec_fingerprint(canonical)
    assert canonical.seed == reference.SEED
    assert canonical.outcomes == (reference.OUTCOME,)
    assert canonical.factors[0].value == reference.GRAVITY_M_S2


def test_the_reference_model_is_the_declared_realization_asset() -> None:
    realization = reference_case.realization_definition()

    assert realization.assets[0].path == reference.MODEL_SOURCE_PATH
    assert realization.assets[0].sha256 == reference.MODEL_SHA256
    assert semantic_sha256(reference_case.benchmark_release()) == (
        reference.BENCHMARK_SEMANTIC_DIGEST
    )


def test_the_two_qualified_platforms_have_independent_environment_authority() -> None:
    windows = reference_case.environment_definition(platform_tag="windows-x86-64")
    linux = reference_case.environment_definition(platform_tag="linux-x86-64")

    assert windows.environment_id != linux.environment_id
    assert semantic_sha256(windows) != semantic_sha256(linux)
    assert reference.expected_environment_id_for("windows-x86-64") == str(windows.environment_id)
