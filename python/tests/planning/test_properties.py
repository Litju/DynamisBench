"""Property qualification for the compiler, aimed at what must hold for *every* study.

Each property is generated rather than exemplified, because an invariant that only one
hand-written fixture satisfies proves nothing about the next study. The strategies build
studies from the domain's own validated builders, so every generated example is a study the
domain would accept; a property that held only for half-validated studies would be worthless.

What is generated:

* **Cardinality.** The plan has exactly the product of its declared axes. Varying each axis
  independently finds an off-by-one in the nested loops instead of assuming there is none.
* **Order.** The plan is sorted by its documented key, ordinals are consecutive from zero,
  and every run's fingerprint is the SHA-256 of its own RunSpec — for any input ordering the
  domain accepts.
* **Replicates.** Every replicate of one configuration at one seed shares an execution
  fingerprint and all of them survive in the plan. This is the property the later
  nondeterminism signal depends on.
* **What the fingerprint excludes.** Replicate index, plan ordinal, factor-case name and the
  study's prose never move it; the seed and an active factor value always do.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.identifiers import (
    EnvironmentId,
    EnvironmentRef,
    RealizationId,
    RealizationRef,
    SUTId,
    SUTRef,
)
from dynamisbench.domain.spec.studies import FactorTargetKind, StudyDefinition
from dynamisbench.planning import FactorCase, FactorValue, RunSpec, run_spec_fingerprint
from tests.domain import factories as domain
from tests.planning.compiler import compile_plan, plan_of, single_run_study
from tests.planning.factor_factories import (
    factor_case,
    multi_axis_study,
    realization_factor,
    realization_reference,
    wide_world,
)
from tests.planning.factories import World, default_world

SCENARIO_IDS = ("sc.a", "sc.b", "sc.c")
SUT_IDS = ("sut.baseline-0", "sut.baseline-1")
ENVIRONMENT_IDS = ("env.mujoco.x86-64", "env.opensim.x86-64")
CASE_IDS = ("case-a", "case-b", "case-c")
SEEDS = (7, 11, 13)
STIFFNESS = (0.85, 0.9, 1.0, 1.15)


def a_release(scenario_count: int):
    """A frozen release with exactly ``scenario_count`` evaluated cases."""
    return domain.benchmark_release(
        scenarios=tuple(
            domain.scenario_definition(SCENARIO_IDS[index]) for index in range(scenario_count)
        ),
        references=(),
    )


def realization_name(index: int) -> str:
    return f"rl.other-{index}"


def a_world(
    scenario_count: int, realization_count: int, sut_count: int, environment_count: int
) -> World:
    base = default_world()
    return World(
        benchmarks=(a_release(scenario_count),),
        realizations=(
            base.realizations[0],
            *(
                domain.realization_definition(
                    realization_id=RealizationId(realization_name(index)),
                    label=f"Second realization {index}",
                    engine=domain.engine_binding(f"engine-{index}", "1.0.0"),
                    engine_configuration=(),
                )
                for index in range(realization_count - 1)
            ),
        ),
        systems_under_test=tuple(
            domain.sut_definition(sut_id=SUTId(sut_id)) for sut_id in SUT_IDS[:sut_count]
        ),
        environments=tuple(
            domain.environment_definition(
                environment_id=EnvironmentId(ENVIRONMENT_IDS[index]),
                label=f"Environment {index}",
                requirements=(
                    domain.environment_requirement(
                        f"tool-{index}", domain.ComponentKind.LIBRARY, "1.0.0"
                    ),
                ),
            )
            for index in range(environment_count)
        ),
    )


def a_study(
    realization_count: int,
    sut_count: int,
    environment_count: int,
    seed_count: int,
    replicates: int,
) -> StudyDefinition:
    return domain.study_definition(
        realizations=(
            RealizationRef(identifier=RealizationId("rl.mujoco.loaded-cmj"), version="1.0.0"),
            *(
                RealizationRef(identifier=RealizationId(realization_name(index)), version="1.0.0")
                for index in range(realization_count - 1)
            ),
        ),
        systems_under_test=tuple(
            SUTRef(identifier=SUTId(sut_id), version="1.0.0") for sut_id in SUT_IDS[:sut_count]
        ),
        environments=tuple(
            EnvironmentRef(identifier=EnvironmentId(name), version="1.0.0")
            for name in ENVIRONMENT_IDS[:environment_count]
        ),
        seeds=SEEDS[:seed_count],
        replicates=replicates,
    )


def cases(count: int) -> tuple:
    return tuple(
        factor_case(CASE_IDS[index % len(CASE_IDS)], stiffness=STIFFNESS[index % len(STIFFNESS)])
        for index in range(count)
    )


axis = st.integers(min_value=1, max_value=3)


def prose() -> st.SearchStrategy[str]:
    """Free text the domain will accept: at least one character, and never blank.

    Restricted to printable non-space characters because the domain rejects whitespace-only
    text as an empty claim. Without that, a strategy that occasionally generates a blank
    string fails the *validator* rather than the property, which is a property test
    measuring the wrong thing.
    """
    return st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=120
    )


@given(
    realization_count=axis,
    scenario_count=axis,
    sut_count=st.integers(min_value=1, max_value=2),
    environment_count=st.integers(min_value=1, max_value=2),
    case_count=axis,
    seed_count=axis,
    replicates=st.integers(min_value=1, max_value=4),
)
def test_the_plan_has_exactly_the_cardinality_of_its_declared_product(
    realization_count: int,
    scenario_count: int,
    sut_count: int,
    environment_count: int,
    case_count: int,
    seed_count: int,
    replicates: int,
) -> None:
    world = a_world(scenario_count, realization_count, sut_count, environment_count)
    study = a_study(realization_count, sut_count, environment_count, seed_count, replicates)

    plan = plan_of(study, world, factor_cases=cases(case_count))

    assert len(plan.runs) == (
        realization_count
        * scenario_count
        * sut_count
        * environment_count
        * case_count
        * seed_count
        * replicates
    )


@given(realization_count=axis, replicates=st.integers(min_value=2, max_value=5), seed_count=axis)
def test_every_replicate_of_one_configuration_shares_one_execution_fingerprint(
    realization_count: int, replicates: int, seed_count: int
) -> None:
    world = a_world(1, realization_count, 1, 1)
    study = a_study(realization_count, 1, 1, seed_count, replicates)

    plan = plan_of(study, world, factor_cases=cases(1))

    by_configuration: dict[tuple[object, ...], set[str]] = {}
    for run in plan.runs:
        key = (
            run.spec.realization.identifier,
            run.spec.scenario.identifier,
            run.spec.system_under_test.identifier,
            run.spec.environment.identifier,
            run.factor_case,
            run.spec.seed,
        )
        by_configuration.setdefault(key, set()).add(run.fingerprint.hex)

    assert by_configuration
    for key, fingerprints in by_configuration.items():
        assert len(fingerprints) == 1, (key, fingerprints)


@given(realization_count=axis, replicates=st.integers(min_value=2, max_value=5), seed_count=axis)
def test_replicates_are_all_kept_as_distinct_planned_instances(
    realization_count: int, replicates: int, seed_count: int
) -> None:
    world = a_world(1, realization_count, 1, 1)
    study = a_study(realization_count, 1, 1, seed_count, replicates)

    plan = plan_of(study, world, factor_cases=cases(1))

    by_configuration: dict[tuple[object, ...], list[int]] = {}
    for run in plan.runs:
        key = (run.spec.realization.identifier, run.spec.seed, run.factor_case)
        by_configuration.setdefault(key, []).append(run.replicate_index)

    for indices in by_configuration.values():
        assert sorted(indices) == list(range(replicates)), indices
    assert len({run.ordinal for run in plan.runs}) == len(plan.runs)


@given(realization_count=axis, case_count=axis, replicates=st.integers(min_value=1, max_value=3))
def test_a_plan_is_ordered_by_its_documented_key_and_numbered_from_zero(
    realization_count: int, case_count: int, replicates: int
) -> None:
    world = a_world(2, realization_count, 1, 1)
    study = a_study(realization_count, 1, 1, 2, replicates)

    plan = plan_of(study, world, factor_cases=cases(case_count))

    assert [run.ordinal for run in plan.runs] == list(range(len(plan.runs)))
    keys = [
        (
            str(run.spec.benchmark.identifier),
            str(run.spec.benchmark.version),
            str(run.spec.realization.identifier),
            str(run.spec.scenario.identifier),
            str(run.spec.system_under_test.identifier),
            str(run.spec.environment.identifier),
            str(run.factor_case),
            run.spec.seed,
            run.replicate_index,
        )
        for run in plan.runs
    ]
    assert keys == sorted(keys)


@given(realization_count=axis, replicates=st.integers(min_value=1, max_value=3))
def test_every_planned_run_fingerprints_its_own_run_spec(
    realization_count: int, replicates: int
) -> None:
    world = a_world(2, realization_count, 1, 1)
    study = a_study(realization_count, 1, 1, 2, replicates)

    plan = plan_of(study, world, factor_cases=cases(1))

    for run in plan.runs:
        assert isinstance(run.spec, RunSpec)
        assert run.fingerprint == run_spec_fingerprint(run.spec)


@given(
    replicates=st.integers(min_value=1, max_value=4),
    seed_count=st.integers(min_value=2, max_value=3),
)
def test_changing_a_seed_changes_the_fingerprint(replicates: int, seed_count: int) -> None:
    world = default_world()

    plan = plan_of(
        single_run_study(replicates=replicates, seeds=SEEDS[:seed_count]),
        world,
        factor_cases=cases(1),
    )

    by_seed = {run.spec.seed: run.fingerprint for run in plan.runs}
    assert len(set(by_seed.values())) == len(by_seed)


@given(index=st.integers(min_value=0, max_value=len(STIFFNESS) - 2))
def test_changing_an_active_factor_value_changes_the_fingerprint(index: int) -> None:
    world = default_world()
    subject = single_run_study()

    first = plan_of(subject, world, factor_cases=(factor_case(stiffness=STIFFNESS[index]),))
    second = plan_of(subject, world, factor_cases=(factor_case(stiffness=STIFFNESS[index + 1]),))

    assert first.runs[0].fingerprint != second.runs[0].fingerprint
    assert first.runs[0].spec.factors != second.runs[0].spec.factors


@given(replicates=st.integers(min_value=1, max_value=4))
def test_a_factor_case_name_alone_never_changes_a_fingerprint(replicates: int) -> None:
    world = default_world()
    subject = single_run_study(replicates=replicates)

    original = plan_of(subject, world, factor_cases=(factor_case("case-a"),))
    renamed = plan_of(subject, world, factor_cases=(factor_case("case-z"),))

    assert original.factor_cases[0].case_id != renamed.factor_cases[0].case_id
    assert original.runs[0].fingerprint == renamed.runs[0].fingerprint
    assert original.runs[0].spec == renamed.runs[0].spec


@given(
    question=prose(),
    analysis=prose(),
    label=prose(),
)
def test_study_prose_alone_never_reaches_a_run_spec_or_a_fingerprint(
    question: str, analysis: str, label: str
) -> None:
    first = compile_plan(single_run_study(research_question="Baseline question."))
    second = compile_plan(
        single_run_study(research_question=question, analysis_plan=analysis, label=label)
    )

    assert first.study.semantic_digest != second.study.semantic_digest
    assert first.runs[0].spec == second.runs[0].spec
    assert first.runs[0].fingerprint == second.runs[0].fingerprint


@given(scenario_count=axis)
def test_every_scenario_of_the_release_appears_in_every_replicate(scenario_count: int) -> None:
    world = a_world(scenario_count, 1, 1, 1)

    plan = plan_of(single_run_study(replicates=2, seeds=SEEDS[:1]), world, factor_cases=cases(1))

    declared = {str(item.scenario_id) for item in world.benchmarks[0].scenarios}

    for replicate_index in (0, 1):
        observed = [
            str(run.spec.scenario.identifier)
            for run in plan.runs
            if run.replicate_index == replicate_index
        ]
        assert sorted(observed) == sorted(declared)


@given(case_count=st.integers(min_value=1, max_value=3))
def test_a_factor_is_never_assigned_to_a_candidate_it_does_not_target(case_count: int) -> None:
    world = wide_world()
    first = realization_factor("rl.mujoco.loaded-cmj")
    second = realization_factor("rl.opensim.loaded-cmj")
    subject = domain.study_definition(
        realizations=(
            realization_reference("rl.mujoco.loaded-cmj"),
            realization_reference("rl.opensim.loaded-cmj"),
        ),
        factors=(first, second),
        replicates=1,
        seeds=SEEDS[:1],
    )
    case_set = tuple(
        FactorCase(
            case_id=CASE_IDS[index % len(CASE_IDS)],
            values=(
                FactorValue(factor_id=first.factor_id, value=STIFFNESS[index % len(STIFFNESS)]),
                FactorValue(factor_id=second.factor_id, value=STIFFNESS[index + 1]),
            ),
        )
        for index in range(case_count)
    )

    plan = plan_of(subject, world, factor_cases=case_set)

    for run in plan.runs:
        for assignment in run.spec.factors:
            assert assignment.target.parameter is not None
            if assignment.target.kind is FactorTargetKind.REALIZATION:
                assert assignment.target.identifier == str(run.spec.realization.identifier)


@given(
    realization_count=axis,
    seed_count=axis,
    replicates=st.integers(min_value=1, max_value=3),
)
def test_a_reordered_catalog_and_reordered_cases_give_the_same_plan(
    realization_count: int, seed_count: int, replicates: int
) -> None:
    from dynamisbench.identity import canonical_semantic_bytes

    world = a_world(2, realization_count, 1, 1)
    subject = a_study(realization_count, 1, 1, seed_count, replicates)
    first = cases(2)
    second = cases(2)

    forward = plan_of(subject, world, factor_cases=first)
    backward = plan_of(
        subject,
        World(
            benchmarks=tuple(reversed(world.benchmarks)),
            realizations=tuple(reversed(world.realizations)),
            systems_under_test=tuple(reversed(world.systems_under_test)),
            environments=tuple(reversed(world.environments)),
        ),
        factor_cases=tuple(reversed(second)),
    )

    assert canonical_semantic_bytes(forward) == canonical_semantic_bytes(backward)


@given(replicates=st.integers(min_value=1, max_value=3))
def test_an_optional_capability_gap_is_recorded_and_never_blocks_the_plan(replicates: int) -> None:
    subject = domain.study_definition(
        required_capabilities=(
            domain.capability_requirement(Capability.FORWARD_DYNAMICS),
            domain.capability_requirement(Capability.INVERSE_DYNAMICS, essential=False),
        ),
        replicates=replicates,
        seeds=SEEDS[:1],
    )

    plan = plan_of(subject, default_world(), factor_cases=cases(1))

    assert plan.runs
    assert {run.capabilities.unmet_optional for run in plan.runs} == {
        (Capability.INVERSE_DYNAMICS,)
    }
    assert {run.applicability.state.value for run in plan.runs} == {"unassessed"}


@given(scenario_count=axis, replicates=st.integers(min_value=1, max_value=3))
def test_the_wide_multi_axis_study_is_ordered_and_complete(
    scenario_count: int, replicates: int
) -> None:
    """The same properties on the world whose every axis has more than one member."""
    from dynamisbench.identity import canonical_semantic_bytes

    world = wide_world()
    subject = multi_axis_study(replicates=replicates, seeds=SEEDS[:2])
    plan = plan_of(subject, world, factor_cases=cases(2))

    realizations = len(subject.realizations)
    scenarios = len(world.benchmarks[0].scenarios)
    systems = len(subject.systems_under_test)
    environments = len(subject.environments)
    assert [run.ordinal for run in plan.runs] == list(range(len(plan.runs)))
    assert len(plan.runs) == realizations * scenarios * systems * environments * 2 * 2 * replicates
    assert canonical_semantic_bytes(plan) == canonical_semantic_bytes(
        plan_of(subject, world, factor_cases=tuple(reversed(cases(2))))
    )
