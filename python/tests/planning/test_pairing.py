"""Benchmark / realization pairing.

A realization is a candidate only for the release ``RealizationDefinition.benchmark``
names. Two benchmarks and two realizations therefore yield two pairs and not four, and an
unrelated pair is a fact to record rather than a planning error. What is refused is a
realization bound to a benchmark the study never consumed.
"""

from __future__ import annotations

import pytest

from dynamisbench.planning import (
    AuthorityResolutionError,
)
from tests.domain import factories as domain
from tests.planning.compiler import (
    compile_plan,
    plan_of,
    single_run_study,
    world_with_two_realizations,
)
from tests.planning.factor_factories import (
    factor_case,
    factor_for,
    realization_factor,
    realization_reference,
)
from tests.planning.factories import (
    World,
    benchmark_ref,
    default_world,
    second_benchmark,
    second_realization,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_a_realization_is_a_candidate_only_for_the_benchmark_it_declares() -> None:
    base = default_world()
    world = World(
        benchmarks=(*base.benchmarks, second_benchmark()),
        realizations=(
            base.realizations[0],
            second_realization(benchmark_ref("db.sprint20")),
        ),
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )
    study = study_definition(
        benchmarks=(domain.benchmark_ref(), benchmark_ref("db.sprint20")),
        realizations=(
            realization_reference("rl.mujoco.loaded-cmj"),
            realization_reference("rl.opensim.loaded-cmj"),
        ),
        replicates=1,
        seeds=(7,),
    )

    plan = plan_of(study, world, factor_cases=(factor_case(),))

    assert len(plan.bindings) == 2, "one pair per realization, not one per combination"
    assert {
        (str(item.realization.identifier), str(item.benchmark.identifier)) for item in plan.bindings
    } == {
        ("rl.mujoco.loaded-cmj", "db.lcmj20"),
        ("rl.opensim.loaded-cmj", "db.sprint20"),
    }
    # Each release declares one scenario, so two candidate runs — not four.
    assert len(plan.runs) == 2


def test_two_realizations_of_one_benchmark_produce_candidates_for_both() -> None:
    plan = compile_plan(
        single_run_study(
            realizations=(
                realization_reference("rl.mujoco.loaded-cmj"),
                realization_reference("rl.opensim.loaded-cmj"),
            )
        ),
        world=world_with_two_realizations(),
    )

    assert {run.spec.realization.identifier for run in plan.runs} == {
        "rl.mujoco.loaded-cmj",
        "rl.opensim.loaded-cmj",
    }


def test_a_study_may_reference_unrelated_benchmarks_and_realizations_together() -> None:
    """Two benchmarks and two realizations are two pairs. The mismatched combinations are
    not candidates, and that is a fact to record rather than a planning error."""
    base = default_world()
    world = World(
        benchmarks=(*base.benchmarks, second_benchmark()),
        realizations=(
            base.realizations[0],
            second_realization(benchmark_ref("db.sprint20")),
        ),
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )

    plan = compile_plan(
        study_definition(
            benchmarks=(domain.benchmark_ref(), benchmark_ref("db.sprint20")),
            realizations=(
                realization_reference("rl.mujoco.loaded-cmj"),
                realization_reference("rl.opensim.loaded-cmj"),
            ),
            replicates=1,
            seeds=(7,),
        ),
        world=world,
    )

    assert {item.benchmark.identifier for item in plan.bindings} == {"db.lcmj20", "db.sprint20"}


def test_a_realization_bound_to_a_benchmark_the_study_does_not_reference_fails() -> None:
    """The realization is real and resolvable; what it binds is a release this study never
    consumed, so it is not a candidate."""
    base = default_world()
    world = World(
        benchmarks=(*base.benchmarks, second_benchmark()),
        realizations=(second_realization(domain.benchmark_ref()),),
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )
    factor = realization_factor("rl.opensim.loaded-cmj")
    study = single_run_study(
        benchmarks=(benchmark_ref("db.sprint20"),),
        realizations=(realization_reference("rl.opensim.loaded-cmj"),),
        factors=(factor,),
    )

    with pytest.raises(AuthorityResolutionError, match="a realization is a candidate only"):
        compile_plan(study, world=world, factor_cases=(factor_for(factor),))


def test_a_realization_bound_to_an_absent_benchmark_is_refused_even_when_another_resolves() -> None:
    base = default_world()
    world = World(
        benchmarks=base.benchmarks,
        realizations=(
            base.realizations[0],
            second_realization(benchmark_ref("db.absent")),
        ),
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )
    study = study_definition(
        realizations=(
            realization_reference("rl.mujoco.loaded-cmj"),
            realization_reference("rl.opensim.loaded-cmj"),
        ),
        replicates=1,
        seeds=(7,),
    )

    with pytest.raises(AuthorityResolutionError, match="db.absent"):
        compile_plan(study, world=world)
