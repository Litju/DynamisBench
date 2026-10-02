"""Invariants a plan must not be able to violate.

A plan may not assert an ordinal that is not its position or a fingerprint it did not
compute, may not carry run identity, and may not expose any way to run anything.
"""

from __future__ import annotations

import pytest

from dynamisbench.planning import (
    AuthorityResolutionError,
    ExecutionFingerprint,
    PlannedRun,
    PlanningContext,
    StudyPlan,
    run_spec_fingerprint,
)
from tests.planning.compiler import (
    compile_plan,
    one_run,
    world_with_two_realizations,
)
from tests.planning.factories import (
    World,
    default_world,
    second_benchmark,
    study_referencing,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_a_plan_cannot_assert_an_ordinal_that_is_not_its_position() -> None:
    plan = compile_plan(study_definition(replicates=2, seeds=(7,)))
    tampered = plan.runs[1].model_copy(update={"ordinal": 7})

    with pytest.raises(ValueError, match="ordinal is the position in canonical order"):
        StudyPlan.model_validate(
            {**plan.model_dump(), "runs": [plan.runs[0].model_dump(), tampered.model_dump()]}
        )


def test_a_plan_cannot_assert_a_fingerprint_it_did_not_compute() -> None:
    plan = one_run()
    forged = plan.runs[0].model_copy(update={"fingerprint": ExecutionFingerprint(hex="0" * 64)})

    with pytest.raises(ValueError, match="may not assert an execution identity"):
        StudyPlan.model_validate({**plan.model_dump(), "runs": [forged.model_dump()]})


def test_a_planned_run_carries_exactly_the_plan_metadata_around_one_spec() -> None:
    run = one_run().runs[0]

    assert set(PlannedRun.model_fields) == {
        "ordinal",
        "factor_case",
        "replicate_index",
        "spec",
        "fingerprint",
        "capabilities",
        "applicability",
    }
    assert run.fingerprint == run_spec_fingerprint(run.spec)


def test_the_plan_carries_no_run_identity_of_any_kind() -> None:
    """Run identity belongs to the execution lifecycle, not to deterministic plan identity."""
    forbidden = {"run_id", "staging", "bundle", "created_at", "timestamp", "host", "path"}
    run = one_run().runs[0]

    assert not set(StudyPlan.model_fields) & forbidden
    assert not set(PlannedRun.model_fields) & forbidden
    assert not set(type(run.spec).model_fields) & forbidden


def test_a_plan_is_a_frozen_value_that_exposes_no_way_to_run_anything() -> None:
    forbidden = ("execute", "run", "submit", "enqueue", "spawn", "launch", "start", "seal")

    for name in dir(StudyPlan):
        if name.startswith("_"):
            continue
        assert not any(word in name.lower() for word in forbidden), name


def test_the_context_may_hold_authority_the_study_does_not_consume() -> None:
    """Unreferenced definitions are simply not expanded; they are not an error."""
    base = default_world()
    world = World(
        benchmarks=(*base.benchmarks, second_benchmark()),
        realizations=base.realizations,
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )

    plan = compile_plan(study_definition(replicates=1, seeds=(7,)), world=world)

    assert len(plan.runs) == 1
    assert [item.identifier for item in plan.benchmarks] == ["db.lcmj20"]


def test_an_empty_context_fails_closed_rather_than_planning_nothing() -> None:
    with pytest.raises(AuthorityResolutionError):
        compile_plan(world=World((), (), (), ()))


def test_a_context_is_not_required_to_be_reused_between_plans() -> None:
    """There is no hidden registry: two plans from the same context are equal."""
    world = default_world()
    study = study_definition(replicates=1, seeds=(7,))

    first = compile_plan(study, world)
    second = compile_plan(study, world)

    assert first == second
    assert (
        PlanningContext(
            benchmarks=world.benchmarks,
            realizations=world.realizations,
            systems_under_test=world.systems_under_test,
            environments=world.environments,
        )
        == world.context()
    )


def test_a_study_naming_a_version_the_context_does_not_hold_fails_before_expansion() -> None:
    study = study_referencing(benchmark="db.lcmj20", version="3.1.4")

    with pytest.raises(AuthorityResolutionError):
        compile_plan(study)


def test_the_context_canonicalises_its_own_ordering() -> None:
    base = default_world()
    world = world_with_two_realizations()

    assert (
        PlanningContext(
            benchmarks=base.benchmarks,
            realizations=tuple(reversed(world.realizations)),
            systems_under_test=base.systems_under_test,
            environments=base.environments,
        )
        == world.context()
    )
