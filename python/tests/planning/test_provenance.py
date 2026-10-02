"""Study identity, plan provenance, and per-axis fingerprint distinctness.

A plan identifies its study by semantic digest and never by prose, and it records the
exact authority and the exact factor cases it was compiled from.
"""

from __future__ import annotations

from tests.domain import factories as domain
from tests.planning.compiler import (
    compile_plan,
    one_run,
    plan_of,
)
from tests.planning.factor_factories import (
    environment_reference,
    factor_case,
    sut_reference,
)
from tests.planning.factories import (
    World,
    default_world,
    second_environment,
    second_system_under_test,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_the_study_is_identified_by_its_semantic_identity_and_never_by_its_prose() -> None:
    from dynamisbench.identity import semantic_sha256

    study = study_definition(replicates=1, seeds=(7,))

    plan = compile_plan(study)

    assert plan.study.identifier == study.study_id
    assert plan.study.version == study.version
    assert plan.study.semantic_digest == semantic_sha256(study)


def test_study_research_prose_alone_does_not_reach_any_run_spec_or_fingerprint() -> None:
    """The research question, analysis plan, description and label identify the study and
    nothing any run executes."""
    original = study_definition(replicates=1, seeds=(7,))
    reworded = study_definition(
        replicates=1,
        seeds=(7,),
        research_question="Does contact stiffness change apex height?",
        analysis_plan="Report the median apex height per case.",
        description="A differently worded description of the same experiment.",
        label="A differently worded label",
    )
    world = default_world()
    cases = (factor_case(),)

    first = plan_of(original, world, factor_cases=cases)
    second = plan_of(reworded, world, factor_cases=cases)

    assert first.study.semantic_digest != second.study.semantic_digest
    assert [run.fingerprint for run in first.runs] == [run.fingerprint for run in second.runs]
    assert [run.spec for run in first.runs] == [run.spec for run in second.runs]


def test_changing_exact_authority_changes_the_relevant_run_spec_and_fingerprint() -> None:
    base = default_world()
    amended = World(
        benchmarks=(
            domain.benchmark_release(
                scenarios=base.benchmarks[0].scenarios,
                quantities=base.benchmarks[0].quantities,
                metrics=base.benchmarks[0].metrics,
                references=base.benchmarks[0].references,
                applicability_domain=("A differently stated applicability domain.",),
            ),
        ),
        realizations=base.realizations,
        systems_under_test=base.systems_under_test,
        environments=base.environments,
    )

    first = one_run()
    second = plan_of(
        study_definition(replicates=1, seeds=(7,)), amended, factor_cases=(factor_case(),)
    )

    assert first.runs[0].spec.benchmark != second.runs[0].spec.benchmark
    assert first.runs[0].fingerprint != second.runs[0].fingerprint


def test_the_plan_records_the_exact_authority_it_resolved() -> None:
    from dynamisbench.identity import semantic_sha256

    world = default_world()
    subject = study_definition(replicates=1, seeds=(7,))

    plan = compile_plan(subject, world)

    assert [item.semantic_digest for item in plan.benchmarks] == [
        semantic_sha256(item) for item in world.benchmarks
    ]
    assert [item.semantic_digest for item in plan.systems_under_test] == [
        semantic_sha256(item) for item in world.systems_under_test
    ]
    assert [item.semantic_digest for item in plan.environments] == [
        semantic_sha256(item) for item in world.environments
    ]
    assert [item.realization.semantic_digest for item in plan.bindings] == [
        semantic_sha256(item) for item in world.realizations
    ]


def test_the_plan_records_the_exact_factor_cases_it_was_compiled_from() -> None:
    cases = (factor_case("case-b"), factor_case("case-a"))

    plan = one_run(factor_cases=cases)

    assert list(plan.factor_cases) == sorted(cases, key=lambda case: str(case.case_id))


def test_a_study_over_two_environments_produces_a_distinct_fingerprint_per_environment() -> None:
    base = default_world()
    world = World(
        benchmarks=base.benchmarks,
        realizations=base.realizations,
        systems_under_test=base.systems_under_test,
        environments=(base.environments[0], second_environment()),
    )
    study = study_definition(
        environments=(
            environment_reference("env.mujoco.x86-64"),
            environment_reference("env.opensim.x86-64"),
        ),
        replicates=1,
        seeds=(7,),
    )

    plan = plan_of(study, world, factor_cases=(factor_case(),))

    assert len(plan.runs) == 2
    assert len({run.fingerprint.hex for run in plan.runs}) == 2


def test_a_study_over_two_systems_under_test_produces_a_distinct_fingerprint_per_system() -> None:
    base = default_world()
    world = World(
        benchmarks=base.benchmarks,
        realizations=base.realizations,
        systems_under_test=(
            base.systems_under_test[0],
            second_system_under_test(),
        ),
        environments=base.environments,
    )
    study = study_definition(
        systems_under_test=(
            sut_reference("sut.baseline-0"),
            sut_reference("sut.baseline-1"),
        ),
        replicates=1,
        seeds=(7,),
    )

    plan = plan_of(study, world, factor_cases=(factor_case(),))

    assert len(plan.runs) == 2
    assert len({run.fingerprint.hex for run in plan.runs}) == 2
