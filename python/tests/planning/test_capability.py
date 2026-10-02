"""Capability compatibility as planning applies it.

An essential requirement a realization cannot satisfy stops the compile; an unmet optional
requirement is recorded on every planned run. Neither may be silently dropped.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.capability import Capability
from dynamisbench.planning import (
    IncompatibleCapabilityError,
)
from tests.domain import factories as domain
from tests.planning.compiler import (
    compile_plan,
    world_with_two_scenarios,
)
from tests.planning.factories import (
    World,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_an_essential_capability_failure_stops_the_whole_compile() -> None:
    """Not a smaller plan that still looks complete."""
    study = study_definition(
        required_capabilities=(
            domain.capability_requirement(Capability.FORWARD_DYNAMICS),
            domain.capability_requirement(Capability.INVERSE_DYNAMICS),
        ),
        replicates=1,
        seeds=(7,),
    )

    with pytest.raises(IncompatibleCapabilityError):
        compile_plan(study)


def test_an_optional_capability_gap_is_recorded_on_every_planned_run() -> None:
    study = study_definition(
        required_capabilities=(
            domain.capability_requirement(Capability.FORWARD_DYNAMICS),
            domain.capability_requirement(Capability.TRAJECTORY_OPTIMIZATION, essential=False),
        ),
        replicates=2,
        seeds=(7,),
    )

    plan = compile_plan(study)

    assert {run.capabilities.unmet_optional for run in plan.runs} == {
        (Capability.TRAJECTORY_OPTIMIZATION,)
    }


def test_a_scenario_capability_requirement_can_refuse_an_otherwise_usable_realization() -> None:
    world = world_with_two_scenarios()
    unanalysable = domain.benchmark_release(
        scenarios=(
            domain.scenario_definition(
                "sc.needs-inverse-dynamics",
                required_capabilities=(domain.capability_requirement(Capability.INVERSE_DYNAMICS),),
            ),
            domain.scenario_definition("sc.needs-inverse-dynamics-2"),
        ),
        references=(),
    )
    restricted = World(
        benchmarks=(unanalysable,),
        realizations=world.realizations,
        systems_under_test=world.systems_under_test,
        environments=world.environments,
    )

    with pytest.raises(IncompatibleCapabilityError, match="inverse_dynamics"):
        compile_plan(world=restricted)
