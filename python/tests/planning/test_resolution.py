"""Exact reference resolution: one definition, or a refusal.

The VVUQ authority says a study's reference must resolve to *exactly one* supplied
validated definition with the same identifier and version, and that the planner records
that definition's semantic digest. These tests pin each half of that: every ref resolves,
nothing resolves implicitly, and every resolved reference carries the exact content
identity of what it resolved to rather than a name that could later move.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    BenchmarkRef,
    EnvironmentId,
    EnvironmentRef,
    RealizationId,
    RealizationRef,
    SUTId,
    SUTRef,
)
from dynamisbench.identity import semantic_sha256
from dynamisbench.planning.authority import PlanningContext
from dynamisbench.planning.errors import AuthorityResolutionError
from tests.domain import factories as domain
from tests.planning import factories as planning


def test_every_study_reference_resolves_to_exactly_one_definition() -> None:
    world = planning.default_world()
    context = world.context()
    subject = planning.study()

    benchmark = context.resolve_benchmark(subject.benchmarks[0])
    realization = context.resolve_realization(subject.realizations[0])
    system_under_test = context.resolve_system_under_test(subject.systems_under_test[0])
    environment = context.resolve_environment(subject.environments[0])

    assert benchmark.definition == world.benchmarks[0]
    assert realization.definition == world.realizations[0]
    assert system_under_test.definition == world.systems_under_test[0]
    assert environment.definition == world.environments[0]


def test_a_reference_to_an_identifier_the_context_does_not_supply_fails() -> None:
    context = PlanningContext(realizations=(domain.realization_definition(),))

    with pytest.raises(AuthorityResolutionError) as failure:
        context.resolve_benchmark(
            BenchmarkRef(identifier=BenchmarkId("db.absent"), version="1.0.0")
        )

    assert "db.absent" in str(failure.value)
    assert "supplies no benchmark release" in str(failure.value)


def test_a_wrong_version_fails_rather_than_resolving_to_the_nearest_one() -> None:
    """No ``latest``. A study naming 2.0.0 must not be planned against 1.0.0."""
    context = planning.default_world().context()

    with pytest.raises(AuthorityResolutionError) as failure:
        context.resolve_benchmark(
            BenchmarkRef(identifier=BenchmarkId("db.lcmj20"), version="2.0.0")
        )

    message = str(failure.value)
    assert "no implicit latest-version resolution" in message
    assert "['1.0.0']" in message


@pytest.mark.parametrize(
    ("concept", "resolve", "reference"),
    [
        (
            "realization",
            lambda context: context.resolve_realization,
            RealizationRef(identifier=RealizationId("rl.absent"), version="1.0.0"),
        ),
        (
            "system under test",
            lambda context: context.resolve_system_under_test,
            SUTRef(identifier=SUTId("sut.absent"), version="1.0.0"),
        ),
        (
            "execution environment",
            lambda context: context.resolve_environment,
            EnvironmentRef(identifier=EnvironmentId("env.absent"), version="1.0.0"),
        ),
    ],
)
def test_every_concept_refuses_a_missing_definition(concept, resolve, reference) -> None:
    context = planning.default_world().context()

    with pytest.raises(AuthorityResolutionError) as failure:
        resolve(context)(reference)

    assert f"supplies no {concept}" in str(failure.value)


def test_a_context_that_supplies_one_identity_twice_is_refused_at_construction() -> None:
    """Duplicate authority makes the catalog ambiguous; ambiguity is refused, not resolved."""
    realization = domain.realization_definition()

    with pytest.raises(ValueError, match="twice"):
        PlanningContext(realizations=(realization, realization))


def test_a_context_may_hold_several_versions_of_one_identifier() -> None:
    """Two versions of one concept are two artifacts, not a duplicate."""
    first = domain.benchmark_release(version="1.0.0")
    second = domain.benchmark_release(version="2.0.0", label="Second release")
    context = PlanningContext(benchmarks=(second, first))

    assert (
        context.resolve_benchmark(
            BenchmarkRef(identifier=BenchmarkId("db.lcmj20"), version="1.0.0")
        ).reference.version
        == "1.0.0"
    )
    assert (
        context.resolve_benchmark(
            BenchmarkRef(identifier=BenchmarkId("db.lcmj20"), version="2.0.0")
        ).reference.version
        == "2.0.0"
    )


def test_a_realization_identifier_cannot_be_supplied_where_a_benchmark_is_required() -> None:
    """ADR-002's concept separation holds through resolution, not only at authoring."""
    with pytest.raises(ValueError, match="expected BenchmarkId"):
        BenchmarkRef.model_validate(
            {"identifier": RealizationId("rl.mujoco.loaded-cmj"), "version": "1.0.0"}
        )


def test_every_resolved_reference_carries_the_semantic_identity_of_what_it_resolved_to() -> None:
    world = planning.default_world()
    subject = planning.study()
    context = world.context()

    assert context.resolve_benchmark(
        subject.benchmarks[0]
    ).reference.semantic_digest == semantic_sha256(world.benchmarks[0])
    assert context.resolve_realization(
        subject.realizations[0]
    ).reference.semantic_digest == semantic_sha256(world.realizations[0])
    assert context.resolve_system_under_test(
        subject.systems_under_test[0]
    ).reference.semantic_digest == semantic_sha256(world.systems_under_test[0])
    assert context.resolve_environment(
        subject.environments[0]
    ).reference.semantic_digest == semantic_sha256(world.environments[0])


def test_a_resolved_reference_keeps_both_its_name_and_its_digest() -> None:
    """The digest supplements the human identity and never replaces it."""
    world = planning.default_world()
    resolved = world.context().resolve_benchmark(domain.benchmark_ref())

    assert resolved.reference.identifier == BenchmarkId("db.lcmj20")
    assert resolved.reference.version == "1.0.0"
    assert len(resolved.reference.semantic_digest.hex) == 64


def test_changing_exact_authority_changes_the_resolved_digest() -> None:
    original = (
        planning.default_world()
        .context()
        .resolve_benchmark(BenchmarkRef(identifier=BenchmarkId("db.lcmj20"), version="1.0.0"))
    )
    amended = PlanningContext(
        benchmarks=(domain.benchmark_release(description="A different description."),)
    ).resolve_benchmark(BenchmarkRef(identifier=BenchmarkId("db.lcmj20"), version="1.0.0"))

    assert original.reference.semantic_digest != amended.reference.semantic_digest, (
        "a different artifact is a different scientific execution context"
    )


def test_the_context_canonicalises_its_ordering_and_ignores_the_callers_order() -> None:
    first = domain.benchmark_release()
    second = planning.second_benchmark()

    assert PlanningContext(benchmarks=(first, second)) == PlanningContext(
        benchmarks=(second, first)
    )


def test_a_scenario_resolves_only_inside_the_release_being_compiled() -> None:
    world = planning.default_world()
    context = world.context()
    release = world.benchmarks[0]

    resolved = context.scenario_of(release, release.scenarios[0].scenario_id)

    assert resolved.definition == release.scenarios[0]
    assert resolved.reference.semantic_digest == semantic_sha256(release.scenarios[0])


def test_a_scenario_the_release_does_not_declare_fails() -> None:
    from dynamisbench.domain.spec.identifiers import ScenarioId

    world = planning.default_world()

    with pytest.raises(AuthorityResolutionError, match="not declared by the benchmark release"):
        world.context().scenario_of(world.benchmarks[0], ScenarioId("sc.absent"))


def test_a_quantity_resolves_with_its_declared_canonical_unit() -> None:
    world = planning.default_world()
    release = world.benchmarks[0]

    resolved = world.context().quantity_of(release, release.quantities[0].quantity_id)

    assert resolved.definition.unit == release.quantities[0].unit
