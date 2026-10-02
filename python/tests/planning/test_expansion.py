"""StudyPlan expansion cardinality, seeds, replicates, and canonical order.

The expansion semantics are authoritative (VVUQ Workflow, Seeds and replicates): every
compatible benchmark/realization pair, times every scenario of that release, times every
referenced system under test, times every referenced environment, times every factor case,
times every declared seed, times every replicate index.

Plan order is canonical and derived only from authoritative logical values, so the
caller's input order cannot reach it. Replicates multiply the plan and intentionally share
one execution fingerprint, because they request the same execution.
"""

from __future__ import annotations

from dynamisbench.planning import (
    run_spec_fingerprint,
)
from tests.planning.compiler import (
    compile_plan,
    one_run,
    plan_of,
    single_run_study,
)
from tests.planning.factor_factories import (
    factor_case,
    multi_axis_study,
    wide_world,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_a_study_is_expanded_into_its_full_cartesian_product() -> None:
    study = multi_axis_study(replicates=2, seeds=(7, 8))
    cases = (factor_case("case-a"), factor_case("case-b", stiffness=1.1))

    plan = plan_of(study, wide_world(), factor_cases=cases)

    # 2 realizations x 2 scenarios x 2 systems under test x 2 environments
    #   x 2 cases x 2 seeds x 2 replicates
    assert len(plan.runs) == 2**6


def test_the_cardinality_is_exactly_the_product_of_its_declared_axes() -> None:
    plan = one_run()

    assert len(plan.runs) == 1


def test_replicates_multiply_the_plan_and_intentionally_share_one_fingerprint() -> None:
    """Two replicates request the same execution, so they are comparable by fingerprint.

    This is required for the nondeterminism evidence the architecture asks for: later,
    differing evidence digests under one fingerprint are the signal. Folding the replicate
    index into the fingerprint would have destroyed it.
    """
    plan = compile_plan(study_definition(replicates=3, seeds=(7,)))

    assert [run.replicate_index for run in plan.runs] == [0, 1, 2]
    assert len({run.fingerprint.hex for run in plan.runs}) == 1
    assert len({run.ordinal for run in plan.runs}) == 3


def test_two_factor_cases_that_differ_only_in_name_still_produce_two_planned_runs() -> None:
    """They are distinct study instances; collapsing them would lose that the study asked
    for both, even though the executions they request are identical."""
    plan = one_run(factor_cases=(factor_case("case-a"), factor_case("case-b")))

    assert [run.factor_case for run in plan.runs] == ["case-a", "case-b"]
    assert plan.runs[0].fingerprint == plan.runs[1].fingerprint


def test_a_replicate_index_alone_does_not_change_the_fingerprint() -> None:
    study = study_definition(replicates=3, seeds=(7,))

    plan = compile_plan(study)

    assert [run.replicate_index for run in plan.runs] == [0, 1, 2]
    assert len({run_spec_fingerprint(run.spec).hex for run in plan.runs}) == 1
    assert all(run.fingerprint == run_spec_fingerprint(run.spec) for run in plan.runs)


def test_a_factor_case_label_alone_does_not_change_the_fingerprint() -> None:
    first = one_run(factor_cases=(factor_case("case-a"),))
    second = one_run(factor_cases=(factor_case("case-z"),))

    assert first.factor_cases[0].case_id != second.factor_cases[0].case_id
    assert first.runs[0].fingerprint == second.runs[0].fingerprint


def test_every_seed_of_the_study_appears_in_every_planned_run() -> None:
    plan = compile_plan(study_definition(replicates=1, seeds=(7, 11, 13)))

    assert sorted({run.spec.seed for run in plan.runs}) == [7, 11, 13]
    assert len(plan.runs) == 3


def test_changing_a_seed_changes_the_fingerprint() -> None:
    first = compile_plan(single_run_study(seeds=(7,)))
    second = compile_plan(single_run_study(seeds=(11,)))

    assert first.runs[0].fingerprint != second.runs[0].fingerprint


def test_the_plan_is_ordered_by_the_documented_key_and_numbered_from_zero() -> None:
    plan = plan_of(
        multi_axis_study(replicates=2, seeds=(7, 11)),
        wide_world(),
        factor_cases=(factor_case("case-a"), factor_case("case-b")),
    )

    assert [run.ordinal for run in plan.runs] == list(range(len(plan.runs)))
    keys = [
        (
            str(run.spec.benchmark.identifier),
            str(run.spec.benchmark.version),
            str(run.spec.realization.identifier),
            str(run.spec.realization.version),
            str(run.spec.scenario.identifier),
            str(run.spec.scenario.version),
            str(run.spec.system_under_test.identifier),
            str(run.spec.system_under_test.version),
            str(run.spec.environment.identifier),
            str(run.spec.environment.version),
            str(run.factor_case),
            run.spec.seed,
            run.replicate_index,
        )
        for run in plan.runs
    ]
    assert keys == sorted(keys)
