"""Study, uncertainty factor, and cross-object invariants (ADR-002, ADR-003)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    EnvironmentId,
    RealizationId,
    StudyId,
    SUTId,
)
from dynamisbench.domain.spec.studies import (
    FactorDistribution,
    FactorRole,
    FactorTarget,
    FactorTargetKind,
    LogNormalSpread,
    NormalSpread,
    PointValue,
    StudyDefinition,
    TriangularRange,
    UncertaintyFactorDefinition,
    UniformRange,
)

from .factories import (
    ENGINE_NATIVE_TOKENS,
    controlled_factor,
    factor_target,
    study_definition,
    uncertainty_factor,
)

_DISTRIBUTION_ADAPTER = TypeAdapter(FactorDistribution)


def test_a_study_references_four_separately_versioned_concepts() -> None:
    study = study_definition()
    assert isinstance(study.study_id, StudyId)
    assert isinstance(study.benchmarks[0].identifier, BenchmarkId)
    assert isinstance(study.realizations[0].identifier, RealizationId)
    assert isinstance(study.systems_under_test[0].identifier, SUTId)
    assert isinstance(study.environments[0].identifier, EnvironmentId)
    assert study.benchmarks[0].version == "1.0.0"
    assert study.research_question
    assert study.analysis_plan


def test_a_study_may_not_reference_the_same_concept_twice() -> None:
    base = study_definition().model_dump(mode="json")
    for field in ("benchmarks", "realizations", "systems_under_test", "environments"):
        payload = {**base, field: [base[field][0], base[field][0]]}
        with pytest.raises(ValidationError) as excinfo:
            StudyDefinition.model_validate(payload)
        assert "duplicate identifier" in str(excinfo.value)


def test_a_study_may_not_pin_two_versions_of_the_same_benchmark() -> None:
    base = study_definition().model_dump(mode="json")
    payload = {
        **base,
        "benchmarks": [base["benchmarks"][0], {**base["benchmarks"][0], "version": "2.0.0"}],
    }
    with pytest.raises(ValidationError) as excinfo:
        StudyDefinition.model_validate(payload)
    assert "duplicate identifier" in str(excinfo.value)


@pytest.mark.parametrize(
    "field",
    [
        "benchmarks",
        "realizations",
        "systems_under_test",
        "environments",
        "required_capabilities",
        "factors",
        "outcomes",
        "seeds",
    ],
)
def test_a_study_must_declare_every_repeatable_part_of_itself(field: str) -> None:
    base = study_definition().model_dump(mode="json")
    with pytest.raises(ValidationError):
        StudyDefinition.model_validate({**base, field: []})


def test_a_study_state_is_reference_by_typed_identity_only() -> None:
    base = study_definition().model_dump(mode="json")
    for field, foreign in (
        ("benchmarks", SUTId("sut.baseline-0")),
        ("realizations", BenchmarkId("db.lcmj20")),
        ("systems_under_test", StudyId("study.other")),
        ("environments", RealizationId("rl.other")),
    ):
        payload = {**base, field: [{**base[field][0], "identifier": foreign}]}
        with pytest.raises(ValidationError) as excinfo:
            StudyDefinition.model_validate(payload)
        assert "expected" in str(excinfo.value)


def test_a_study_declares_at_least_one_required_capability() -> None:
    study = study_definition()
    assert Capability.FORWARD_DYNAMICS in {
        requirement.capability for requirement in study.required_capabilities
    }
    with pytest.raises(ValidationError) as excinfo:
        StudyDefinition.model_validate(
            {
                **study_definition().model_dump(mode="json"),
                "required_capabilities": [
                    study_definition().required_capabilities[0].model_dump(mode="json"),
                    study_definition().required_capabilities[0].model_dump(mode="json"),
                ],
            }
        )
    assert "duplicate capability" in str(excinfo.value)


def test_a_study_is_reproducible_only_with_seeds_and_replicates() -> None:
    study = study_definition()
    assert study.seeds and study.replicates >= 1
    for bad_replicates in (0, -1):
        with pytest.raises(ValidationError):
            StudyDefinition.model_validate(
                {**study.model_dump(mode="json"), "replicates": bad_replicates}
            )
    with pytest.raises(ValidationError):
        StudyDefinition.model_validate({**study.model_dump(mode="json"), "seeds": [-1]})
    with pytest.raises(ValidationError):
        StudyDefinition.model_validate({**study.model_dump(mode="json"), "seeds": [11, 11]})


def test_a_study_may_not_repeat_an_outcome() -> None:
    with pytest.raises(ValidationError) as excinfo:
        StudyDefinition.model_validate(
            {
                **study_definition().model_dump(mode="json"),
                "outcomes": ["q.jump.height", "q.jump.height"],
            }
        )
    assert "duplicate entry" in str(excinfo.value)


@pytest.mark.parametrize(
    "distribution",
    [
        PointValue(value=1.0),
        UniformRange(lower=0.0, upper=1.0),
        NormalSpread(mean=0.0, standard_deviation=0.1),
        LogNormalSpread(mean_log=0.0, standard_deviation_log=0.1),
        TriangularRange(lower=0.0, upper=1.0, mode=0.5),
    ],
)
def test_the_declared_uncertainty_vocabulary_is_a_closed_parametric_set(
    distribution: FactorDistribution,
) -> None:
    assert (
        _DISTRIBUTION_ADAPTER.validate_python(distribution.model_dump(mode="json")) == distribution
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "uniform", "lower": 1.0, "upper": 0.0},
        {"kind": "uniform", "lower": 0.0, "upper": 0.0},
        {"kind": "normal", "mean": 0.0, "standard_deviation": 0.0},
        {"kind": "normal", "mean": 0.0, "standard_deviation": -1.0},
        {"kind": "lognormal", "mean_log": 0.0, "standard_deviation_log": 0.0},
        {"kind": "triangular", "lower": 0.0, "upper": 1.0, "mode": 2.0},
        {"kind": "triangular", "lower": 0.0, "upper": 0.0, "mode": 0.0},
        {"kind": "weibull"},
        {"value": 1.0},
    ],
)
def test_a_malformed_uncertainty_fails_closed(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _DISTRIBUTION_ADAPTER.validate_python(payload)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_uncertainty_parameters_must_be_finite(value: float) -> None:
    with pytest.raises(ValidationError):
        PointValue(value=value)
    with pytest.raises(ValidationError):
        UniformRange(lower=value, upper=1.0)


def test_a_factor_target_states_what_it_varies() -> None:
    assert factor_target().kind is FactorTargetKind.REALIZATION
    assert factor_target().parameter == "contact-stiffness"
    with pytest.raises(ValidationError) as excinfo:
        FactorTarget(kind=FactorTargetKind.REALIZATION, identifier="rl.mujoco.loaded-cmj")
    assert "must name the parameter it varies" in str(excinfo.value)
    with pytest.raises(ValidationError) as excinfo:
        FactorTarget(
            kind=FactorTargetKind.BENCHMARK_QUANTITY,
            identifier="q.jump.height",
            parameter="not-allowed",
        )
    assert "names no parameter" in str(excinfo.value)
    assert (
        FactorTarget(kind=FactorTargetKind.BENCHMARK_QUANTITY, identifier="q.jump.height").parameter
        is None
    )


def test_a_controlled_factor_must_hold_a_single_value() -> None:
    assert controlled_factor().distribution.kind == "point"
    with pytest.raises(ValidationError) as excinfo:
        controlled_factor(distribution=UniformRange(lower=0.8, upper=1.2))
    assert "must hold a point value" in str(excinfo.value)
    assert uncertainty_factor().role is FactorRole.FACTOR


def test_a_study_may_not_repeat_a_factor_identity() -> None:
    with pytest.raises(ValidationError) as excinfo:
        StudyDefinition.model_validate(
            {
                **study_definition().model_dump(mode="json"),
                "factors": [
                    uncertainty_factor().model_dump(mode="json"),
                    uncertainty_factor().model_dump(mode="json"),
                ],
            }
        )
    assert "duplicate factor_id" in str(excinfo.value)


def test_a_factor_names_the_canonical_quantity_it_varies() -> None:
    factor = uncertainty_factor()
    assert isinstance(factor, UncertaintyFactorDefinition)
    assert factor.quantity == "q.jump.height" or factor.quantity == "q.foot.vertical_force"
    assert "quantity" in UncertaintyFactorDefinition.model_fields


def test_a_factor_never_carries_a_sampler_or_a_realization_object() -> None:
    payload = uncertainty_factor().model_dump_json().lower()
    for token in ("sample(", "rng", "np.", "numpy", "qpos", "mjdata", "state"):
        assert token not in payload


@given(
    value=st.floats(allow_nan=False, allow_infinity=False, width=32),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
    replicates=st.integers(min_value=1, max_value=64),
)
def test_any_finite_point_factor_and_seed_pair_is_a_valid_study(
    value: float, seed: int, replicates: int
) -> None:
    study = StudyDefinition.model_validate(
        {
            **study_definition().model_dump(mode="json"),
            "factors": [
                controlled_factor(distribution=PointValue(value=value)).model_dump(mode="json")
            ],
            "seeds": [seed],
            "replicates": replicates,
        }
    )
    assert study.seeds == (seed,)
    assert study.replicates == replicates


def test_a_study_never_serialises_an_engine_native_type() -> None:
    payload = study_definition().model_dump_json().lower()
    for token in ENGINE_NATIVE_TOKENS:
        assert token not in payload
