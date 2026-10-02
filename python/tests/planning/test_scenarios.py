"""Scenario expansion.

``StudyDefinition`` has no scenario subset, so a referenced benchmark contributes every
scenario in its frozen release. There is no selector to invent, and a scenario's authoring
order cannot reach the plan order.
"""

from __future__ import annotations

from dynamisbench.domain.spec.identifiers import ScenarioId
from tests.domain import factories as domain
from tests.planning.compiler import (
    one_run,
    plan_of,
    world_with_two_scenarios,
)
from tests.planning.factor_factories import (
    factor_case,
)
from tests.planning.factories import (
    World,
    default_world,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_every_scenario_of_the_release_is_expanded() -> None:
    """The study model has no scenario subset, so there is no filter to invent."""
    plan = one_run(world=world_with_two_scenarios())

    assert len(plan.runs) == 2
    assert {run.spec.scenario.identifier for run in plan.runs} == {
        "sc.loaded-cmj",
        "sc.unloaded-cmj",
    }


def test_every_planned_scenario_is_pinned_by_its_release_and_by_its_own_identity() -> None:
    from dynamisbench.identity import semantic_sha256

    world = world_with_two_scenarios()
    release = world.benchmarks[0]

    plan = one_run()
    plan = plan_of(
        study_definition(replicates=1, seeds=(7,)),
        world,
        factor_cases=(factor_case(),),
    )

    for run in plan.runs:
        assert run.spec.benchmark.semantic_digest == semantic_sha256(release)
        declared = {ScenarioId(item.scenario_id): item for item in release.scenarios}[
            ScenarioId(run.spec.scenario.identifier)
        ]
        assert run.spec.scenario.version == declared.version
        assert run.spec.scenario.semantic_digest == semantic_sha256(declared)


def test_the_authoring_order_of_scenarios_cannot_perturb_the_canonical_plan_order() -> None:
    forward = domain.benchmark_release(
        scenarios=(
            domain.scenario_definition("sc.a"),
            domain.scenario_definition("sc.b"),
            domain.scenario_definition("sc.c"),
        ),
        references=(),
    )
    backward = domain.benchmark_release(
        scenarios=(
            domain.scenario_definition("sc.c"),
            domain.scenario_definition("sc.b"),
            domain.scenario_definition("sc.a"),
        ),
        references=(),
    )
    base = default_world()

    def plan_for(release):
        world = World(
            benchmarks=(release,),
            realizations=base.realizations,
            systems_under_test=base.systems_under_test,
            environments=base.environments,
        )
        return plan_of(
            study_definition(replicates=1, seeds=(7,)),
            world,
            factor_cases=(factor_case(),),
        )

    assert plan_for(forward) == plan_for(backward)
    assert [run.spec.scenario.identifier for run in plan_for(forward).runs] == [
        "sc.a",
        "sc.b",
        "sc.c",
    ]


def test_changing_a_scenario_changes_the_fingerprint_of_its_own_run_only() -> None:
    plan = plan_of(
        study_definition(replicates=1, seeds=(7,)),
        world_with_two_scenarios(),
        factor_cases=(factor_case(),),
    )

    by_scenario = {str(run.spec.scenario.identifier): run.fingerprint for run in plan.runs}

    assert by_scenario["sc.loaded-cmj"] != by_scenario["sc.unloaded-cmj"]
