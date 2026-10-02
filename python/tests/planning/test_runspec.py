"""``RunSpec`` content and the ``ExecutionFingerprint`` boundary.

The fingerprint answers "what was this run asked to do", which is not the same question
as "what did this definition mean", "what were these bytes" or "what was produced". This
file pins that separation, and pins the one property the whole design turns on:

    same RunSpec, same seed, different replicate index
        -> the same ExecutionFingerprint

That is required, not incidental. Two replicates of one configuration request the same
execution, so they must be comparable; later, differing evidence digests under one
fingerprint are the nondeterminism signal. A planner that folded the replicate index into
the fingerprint would have destroyed it.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.identifiers import Sha256Hex
from dynamisbench.evidence.manifest import EvidenceDigest
from dynamisbench.identity import AssetDigest, DigestAlgorithm, SemanticDigest
from dynamisbench.planning import (
    ExecutionFingerprint,
    PlanningContext,
    RunSpec,
    canonical_run_spec_bytes,
    execution_fingerprint_of_canonical_bytes,
    run_spec_fingerprint,
)
from tests.planning import factories as planning


def a_spec(**overrides) -> RunSpec:
    world = planning.default_world()
    subject = planning.study()
    context = world.context()
    benchmark = context.resolve_benchmark(subject.benchmarks[0])
    realization = context.resolve_realization(subject.realizations[0])
    system_under_test = context.resolve_system_under_test(subject.systems_under_test[0])
    environment = context.resolve_environment(subject.environments[0])
    scenario = context.scenario_of(
        benchmark.definition, benchmark.definition.scenarios[0].scenario_id
    )
    values: dict = {
        "benchmark": benchmark.reference,
        "scenario": scenario.reference,
        "realization": realization.reference,
        "system_under_test": system_under_test.reference,
        "environment": environment.reference,
        "seed": 11,
        "outcomes": subject.outcomes,
    }
    values.update(overrides)
    return RunSpec(**values)


def test_the_execution_fingerprint_is_a_distinct_type_from_the_other_three_digests() -> None:
    """It answers a fourth question and must never be mistaken for another identity."""
    for other in (SemanticDigest, AssetDigest, EvidenceDigest):
        assert not issubclass(ExecutionFingerprint, other)
        assert not issubclass(other, ExecutionFingerprint)


def test_a_semantic_digest_cannot_be_supplied_where_a_fingerprint_is_expected() -> None:
    """Swapping identities is a mistake that must fail, not coerce."""
    with pytest.raises(ValueError):
        ExecutionFingerprint.model_validate(SemanticDigest(hex="0" * 64))


def test_a_fingerprint_cannot_be_supplied_where_a_semantic_digest_is_expected() -> None:
    with pytest.raises(ValueError):
        SemanticDigest.model_validate(ExecutionFingerprint(hex="0" * 64))


def test_the_fingerprint_is_the_sha256_of_the_canonical_run_spec_bytes() -> None:
    import hashlib

    spec = a_spec()
    canonical = canonical_run_spec_bytes(spec)

    assert run_spec_fingerprint(spec) == execution_fingerprint_of_canonical_bytes(canonical)
    assert run_spec_fingerprint(spec).hex == hashlib.sha256(canonical).hexdigest()


def test_the_fingerprint_uses_the_existing_sha256_algorithm_vocabulary() -> None:
    from pydantic import TypeAdapter

    fingerprint = run_spec_fingerprint(a_spec())

    assert fingerprint.algorithm == DigestAlgorithm.SHA256
    assert len(fingerprint.hex) == 64
    assert TypeAdapter(Sha256Hex).validate_python(fingerprint.hex) == fingerprint.hex


def test_the_canonical_bytes_are_produced_by_the_existing_semantic_boundary() -> None:
    """No bespoke RunSpec serializer: RFC 8785 over the validated object, as everywhere."""
    from dynamisbench.identity import canonical_semantic_bytes

    spec = a_spec()

    assert canonical_run_spec_bytes(spec) == canonical_semantic_bytes(spec)
    assert canonical_run_spec_bytes(spec).startswith(b'{"benchmark":')


@pytest.mark.parametrize(
    "authority",
    ["benchmark", "scenario", "realization", "system_under_test", "environment"],
)
def test_every_authority_in_the_spec_is_content_bound(authority: str) -> None:
    """A different authority artifact is a different scientific execution context."""
    original = a_spec()
    altered = getattr(original, authority).model_copy(
        update={"semantic_digest": SemanticDigest(hex="1" * 64)}
    )
    changed = original.model_copy(update={authority: altered})

    assert getattr(original, authority).semantic_digest != altered.semantic_digest
    assert run_spec_fingerprint(changed) != run_spec_fingerprint(original)


def test_changing_the_seed_changes_the_fingerprint() -> None:
    assert run_spec_fingerprint(a_spec(seed=11)) != run_spec_fingerprint(a_spec(seed=12))


def test_changing_an_active_factor_value_changes_the_fingerprint() -> None:
    world = planning.default_world()
    subject = planning.study()
    context = world.context()
    benchmark = context.resolve_benchmark(subject.benchmarks[0])

    def spec_with(stiffness: float) -> RunSpec:
        from dynamisbench.planning.factors import assignment

        factor = domain_factor()
        return a_spec(
            factors=(
                assignment(
                    factor,
                    stiffness,
                    quantity=factor.quantity,
                    unit=context.quantity_of(benchmark.definition, factor.quantity).definition.unit,
                ),
            )
        )

    assert run_spec_fingerprint(spec_with(0.9)) != run_spec_fingerprint(spec_with(1.1))


def test_changing_the_requested_outcomes_changes_the_fingerprint() -> None:
    """The requested output set decides what a run extracts, so it is execution-defining."""
    assert run_spec_fingerprint(a_spec(outcomes=("q.jump.height",))) != run_spec_fingerprint(
        a_spec(outcomes=("q.jump.height", "q.foot.vertical_force"))
    )


def test_the_spec_carries_no_study_prose_and_no_plan_metadata() -> None:
    """The RunSpec's field set is the whole claim that study prose cannot reach a run."""
    fields = set(RunSpec.model_fields)

    assert fields == {
        "schema_version",
        "benchmark",
        "scenario",
        "realization",
        "system_under_test",
        "environment",
        "factors",
        "seed",
        "outcomes",
    }
    assert not fields & {
        "replicate_index",
        "ordinal",
        "factor_case",
        "research_question",
        "analysis_plan",
    }
    assert "run_id" not in fields


def test_a_fingerprint_is_a_pure_function_of_the_spec() -> None:
    spec = a_spec()

    assert run_spec_fingerprint(spec) == run_spec_fingerprint(spec)
    assert run_spec_fingerprint(spec) == run_spec_fingerprint(spec.model_copy(deep=True))


def domain_factor():
    from tests.domain import factories as domain

    return domain.uncertainty_factor()


def test_a_context_digest_never_reaches_a_spec_as_a_whole_context() -> None:
    """A RunSpec names resolved authority, never the catalog it was resolved from."""
    context = PlanningContext()

    assert context.benchmarks == ()
    assert set(RunSpec.model_fields) & set(PlanningContext.model_fields) == set()
