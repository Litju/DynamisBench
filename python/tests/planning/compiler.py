"""The compile helpers every planning gate shares.

The prelude that would otherwise be duplicated at the top of each gate file lives here,
so a change to how a plan is compiled in a test is one change rather than ten, and the
words describing what the helpers do are written once.
"""

from __future__ import annotations

from dynamisbench.domain.spec.studies import StudyDefinition
from dynamisbench.planning import FactorCase, StudyPlan, plan_study
from tests.planning.factor_factories import factor_case
from tests.planning.factories import (
    World,
    default_world,
    multi_scenario_benchmark,
    second_realization,
    study,
)

__all__ = [
    "World",
    "compile_plan",
    "default_world",
    "factor_case",
    "one_run",
    "plan_of",
    "single_run_study",
    "world_with_two_realizations",
    "world_with_two_scenarios",
]


def plan_of(study: StudyDefinition, world: World, **kwargs) -> StudyPlan:
    """Compile one study against one world."""
    return plan_study(study, world.context(), **kwargs)


def compile_plan(
    study_definition: StudyDefinition | None = None,
    world: World | None = None,
    *,
    factor_cases: tuple[FactorCase, ...] | None = None,
    **kwargs,
) -> StudyPlan:
    """Compile a study against a world, with one default factor case unless told otherwise."""
    chosen_world = default_world() if world is None else world
    cases = (factor_case(),) if factor_cases is None else factor_cases
    return plan_of(
        study_definition or single_run_study(), chosen_world, factor_cases=cases, **kwargs
    )


def single_run_study(**overrides) -> StudyDefinition:
    """The minimal study reduced to one run: one seed, one replicate."""
    values: dict = {"replicates": 1, "seeds": (7,)}
    values.update(overrides)
    return study(**values)


def one_run(**kwargs) -> StudyPlan:
    """One planned run, with the planner keyword arguments the caller supplies."""
    return compile_plan(single_run_study(), **kwargs)


def world_with_two_realizations() -> World:
    """One release, two realizations of it."""
    base = default_world()
    return World(
        benchmarks=base.benchmarks,
        realizations=(base.realizations[0], second_realization()),
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )


def world_with_two_scenarios() -> World:
    """One release, two scenarios in it."""
    base = default_world()
    return World(
        benchmarks=(multi_scenario_benchmark(),),
        realizations=base.realizations,
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )
