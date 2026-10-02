"""Factor targets and quantity resolution.

A factor target is study authority and must resolve against what the study references. A
factor is active in a candidate only when its target is one of that candidate's
authorities, and every active factor's quantity must be declared by the active benchmark,
which is also where its canonical unit comes from.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.identifiers import QuantityId
from dynamisbench.planning import (
    AuthorityResolutionError,
    FactorCase,
    FactorValue,
)
from tests.domain import factories as domain
from tests.planning.compiler import (
    compile_plan,
    one_run,
    single_run_study,
    world_with_two_realizations,
)
from tests.planning.factor_factories import (
    benchmark_quantity_factor,
    environment_factor,
    factor_case,
    factor_for,
    realization_factor,
    realization_reference,
    sut_factor,
)
from tests.planning.factories import (
    default_world,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_a_target_that_does_not_resolve_against_the_study_is_refused() -> None:
    study = study_definition(
        factors=(realization_factor("rl.not-referenced"),),
        replicates=1,
        seeds=(7,),
    )

    with pytest.raises(AuthorityResolutionError, match="does not reference"):
        compile_plan(study, factor_cases=(factor_case("case-a"),))


@pytest.mark.parametrize(
    "factory",
    [sut_factor, environment_factor, benchmark_quantity_factor],
    ids=["sut", "environment", "benchmark_quantity"],
)
def test_every_target_kind_resolves_its_identifier_against_the_study(factory) -> None:
    factor = factory()
    study = study_definition(factors=(factor,), replicates=1, seeds=(7,))

    plan = compile_plan(study, factor_cases=(factor_for(factor),))

    assert [item.factor_id for item in plan.runs[0].spec.factors] == [factor.factor_id]
    assert plan.runs[0].spec.factors[0].target.kind == factor.target.kind


def test_a_target_whose_identifier_names_another_concept_does_not_resolve() -> None:
    """A SUT target naming a realization is a different object, and resolves to nothing."""
    from dynamisbench.domain.spec.studies import FactorTarget, FactorTargetKind

    study = study_definition(
        factors=(
            domain.uncertainty_factor(
                factor_id="f.gain",
                target=FactorTarget(
                    kind=FactorTargetKind.SUT,
                    identifier="rl.mujoco.loaded-cmj",
                    parameter="gain",
                ),
            ),
        ),
        replicates=1,
        seeds=(7,),
    )

    with pytest.raises(AuthorityResolutionError, match="does not reference"):
        compile_plan(study, factor_cases=(factor_case("case-a"),))


def test_a_factor_targeting_another_realization_does_not_contaminate_this_run_spec() -> None:
    """Inactive target-specific factors are absent, not present with no effect."""
    study = study_definition(
        realizations=(
            realization_reference("rl.mujoco.loaded-cmj"),
            realization_reference("rl.opensim.loaded-cmj"),
        ),
        factors=(
            domain.controlled_factor(target=realization_factor("rl.mujoco.loaded-cmj").target),
        ),
        replicates=1,
        seeds=(7,),
    )

    plan = compile_plan(study, world=world_with_two_realizations(), factor_cases=())

    mujoco = next(
        run for run in plan.runs if run.spec.realization.identifier == "rl.mujoco.loaded-cmj"
    )
    opensim = next(
        run for run in plan.runs if run.spec.realization.identifier == "rl.opensim.loaded-cmj"
    )
    assert [item.factor_id for item in mujoco.spec.factors] == ["f.gravity"]
    assert opensim.spec.factors == ()
    assert mujoco.fingerprint != opensim.fingerprint


def test_two_factor_cases_that_differ_only_in_another_candidate_factor_share_a_run_spec() -> None:
    """The two cases are distinct study instances; the candidate they both apply to asks for
    the same execution, so one fingerprint is correct and both runs are kept."""
    mujoco_factor = realization_factor("rl.mujoco.loaded-cmj")
    opensim_factor = realization_factor("rl.opensim.loaded-cmj")
    study = single_run_study(
        realizations=(
            realization_reference("rl.mujoco.loaded-cmj"),
            realization_reference("rl.opensim.loaded-cmj"),
        ),
        factors=(mujoco_factor, opensim_factor),
    )
    cases = (
        FactorCase(
            case_id="case-a",
            values=(
                FactorValue(factor_id=mujoco_factor.factor_id, value=0.9),
                FactorValue(factor_id=opensim_factor.factor_id, value=0.85),
            ),
        ),
        FactorCase(
            case_id="case-b",
            values=(
                FactorValue(factor_id=mujoco_factor.factor_id, value=0.9),
                FactorValue(factor_id=opensim_factor.factor_id, value=1.15),
            ),
        ),
    )

    plan = compile_plan(study, world=world_with_two_realizations(), factor_cases=cases)

    mujoco = [run for run in plan.runs if run.spec.realization.identifier == "rl.mujoco.loaded-cmj"]
    assert [run.factor_case for run in mujoco] == ["case-a", "case-b"]
    assert mujoco[0].spec == mujoco[1].spec
    assert mujoco[0].fingerprint == mujoco[1].fingerprint
    opensim = [
        run for run in plan.runs if run.spec.realization.identifier == "rl.opensim.loaded-cmj"
    ]
    assert opensim[0].fingerprint != opensim[1].fingerprint


def test_every_active_factor_quantity_must_exist_in_the_active_benchmark() -> None:
    study = study_definition(
        factors=(
            domain.uncertainty_factor(quantity=QuantityId("q.not-declared")),
            domain.controlled_factor(),
        ),
        replicates=1,
        seeds=(7,),
    )

    with pytest.raises(AuthorityResolutionError, match="not declared by the benchmark release"):
        compile_plan(study, factor_cases=(factor_case(),))


def test_an_active_factor_takes_its_canonical_unit_from_the_active_benchmark() -> None:
    world = default_world()
    declared = {item.quantity_id: item.unit for item in world.benchmarks[0].quantities}

    plan = one_run()

    for item in plan.runs[0].spec.factors:
        assert item.unit == declared[item.quantity]
    assert len(plan.runs[0].spec.factors) == 2
