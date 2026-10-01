"""Canonical quantity, metric, and reference semantics (Architecture section 5).

These are the gates that make the scientific interoperability boundary explicit
enough for two independent engines to agree on what a recorded number means.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.identifiers import QuantityId
from dynamisbench.domain.spec.metrics import (
    AggregationMethod,
    ComparisonOperator,
    MetricAggregation,
    MetricCriterion,
    MetricDefinition,
)
from dynamisbench.domain.spec.quantities import (
    BASE_DIMENSION_NAMES,
    DIMENSIONLESS,
    AxisConvention,
    BodyInclusion,
    CanonicalUnit,
    CompositeAggregation,
    Handedness,
    PhysicalDimension,
    QuantityDefinition,
    ReferenceFrame,
    RotationSense,
    SamplingKind,
    SamplingSemantics,
    SignConvention,
    TimeBasis,
    TimeBasisKind,
    UncertaintyMetadata,
    canonical_unit_dimension,
)
from dynamisbench.domain.spec.references import (
    ReferenceDefinition,
    ReferenceOrigin,
    VerificationCategory,
)

from .factories import (
    WORLD_FRAME,
    axis_convention,
    force_dimension,
    metric_definition,
    quantity_definition,
    reference_definition,
    reference_frame,
)

REQUIRED_INTEROPERABILITY_FIELDS = (
    "quantity_id",
    "dimension",
    "unit",
    "frame",
    "sign_convention",
    "time_basis",
    "sampling",
)


def test_a_quantity_carries_every_required_interoperability_field() -> None:
    quantity = quantity_definition()
    for field in REQUIRED_INTEROPERABILITY_FIELDS:
        assert field in QuantityDefinition.model_fields
        assert getattr(quantity, field) is not None
    for optional_field in ("axis_convention", "body_inclusion", "uncertainty"):
        assert optional_field in QuantityDefinition.model_fields


def test_a_quantity_exposes_its_optional_interoperability_fields_when_supplied() -> None:
    quantity = quantity_definition(
        axis_convention=axis_convention(), uncertainty=UncertaintyMetadata(characterization="x")
    )
    assert quantity.axis_convention is not None
    assert quantity.uncertainty is not None


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1", (0, 0, 0, 0, 0, 0, 0)),
        ("m", (1, 0, 0, 0, 0, 0, 0)),
        ("m/s", (1, 0, -1, 0, 0, 0, 0)),
        ("N", (1, 1, -2, 0, 0, 0, 0)),
        ("kg*m^2/s^3", (2, 1, -3, 0, 0, 0, 0)),
        ("N/m^2", (-1, 1, -2, 0, 0, 0, 0)),
        ("A", (0, 0, 0, 1, 0, 0, 0)),
        ("K", (0, 0, 0, 0, 1, 0, 0)),
        ("mol", (0, 0, 0, 0, 0, 1, 0)),
        ("cd", (0, 0, 0, 0, 0, 0, 1)),
    ],
)
def test_canonical_unit_dimensions_are_computed_from_si_algebra(
    expression: str, expected: tuple[int, ...]
) -> None:
    assert canonical_unit_dimension(expression) == expected


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("m/s", "m*s^-1"),
        ("s^-1*m", "m*s^-1"),
        ("m*s^-1", "m*s^-1"),
        ("kg*m^2/s^3", "m^2*kg*s^-3"),
        ("W", "m^2*kg*s^-3"),
        ("N*W", "m^3*kg^2*s^-5"),
        ("N/Pa", "m^2"),
        ("m*m", "m^2"),
        ("1", "1"),
    ],
)
def test_a_unit_has_exactly_one_canonical_spelling(spelling: str, canonical: str) -> None:
    assert CanonicalUnit(expression=spelling).expression == canonical


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "metre",
        "m//s",
        "m s",
        "m+kg",
        "m/(s)",
        "m/s^",
        "/m",
        "1*1",
        "m^0",
        "rad",
        "sr",
        "g",
        "N!",
    ],
)
def test_malformed_or_non_si_units_fail_closed(expression: str) -> None:
    with pytest.raises(ValidationError):
        CanonicalUnit(expression=expression)


def test_plane_angle_is_dimensionless_in_si_and_says_why() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CanonicalUnit(expression="rad")
    assert "dimensionless in SI" in str(excinfo.value)
    assert canonical_unit_dimension("1") == DIMENSIONLESS.as_tuple()


def test_a_quantity_whose_dimension_contradicts_its_unit_fails_closed() -> None:
    with pytest.raises(ValidationError) as excinfo:
        quantity_definition(dimension=PhysicalDimension(length=1))
    assert "declares dimension" in str(excinfo.value)
    assert "but unit" in str(excinfo.value)


def test_a_quantity_with_a_matching_dimension_and_unit_is_accepted() -> None:
    assert quantity_definition().dimension.as_tuple() == force_dimension().as_tuple()
    assert quantity_definition().unit.expression == "m*kg*s^-2"


def test_dimension_names_cover_the_seven_si_base_dimensions() -> None:
    assert len(BASE_DIMENSION_NAMES) == 7
    assert set(PhysicalDimension.model_fields) == set(BASE_DIMENSION_NAMES)


def test_a_reference_frame_needs_a_declared_parent() -> None:
    with pytest.raises(ValidationError):
        ReferenceFrame(
            frame_id="world",
            parent="world",
            axis_labels=("x", "y", "z"),
            handedness=Handedness.RIGHT,
            description="self parented",
        )
    assert reference_frame("lab").parent == "world"


def test_a_three_dimensional_frame_must_declare_handedness() -> None:
    with pytest.raises(ValidationError):
        ReferenceFrame(
            frame_id="lab",
            parent="world",
            axis_labels=("x", "y", "z"),
            description="no handedness",
        )
    with pytest.raises(ValidationError):
        ReferenceFrame(
            frame_id="line",
            parent="world",
            axis_labels=("along",),
            handedness=Handedness.RIGHT,
            description="handedness on a one dimensional frame",
        )


def test_a_reference_frame_rejects_repeated_axis_labels() -> None:
    with pytest.raises(ValidationError):
        ReferenceFrame(
            frame_id="lab",
            parent="world",
            axis_labels=("x", "x", "z"),
            handedness=Handedness.RIGHT,
            description="repeated axis",
        )


def test_a_one_dimensional_frame_is_accepted_without_handedness() -> None:
    frame = ReferenceFrame(
        frame_id="force-line",
        parent="world",
        axis_labels=("along",),
        description="Force plate one dimensional frame.",
    )
    assert frame.handedness is None


def test_an_axis_convention_names_three_distinct_axes() -> None:
    assert axis_convention().order == ("x", "y", "z")
    with pytest.raises(ValidationError):
        AxisConvention(order=("x", "x", "z"), sense=RotationSense.EXTRINSIC)
    with pytest.raises(ValidationError):
        AxisConvention(order=("x", "y"), sense=RotationSense.EXTRINSIC)


def test_a_sign_convention_must_state_its_positive_direction() -> None:
    with pytest.raises(ValidationError):
        SignConvention(positive_direction="  ")
    assert quantity_definition().sign_convention.positive_direction


def test_body_inclusion_and_exclusion_must_be_disjoint() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BodyInclusion(
            included=("foot", "shank"),
            excluded=("foot",),
            aggregation=CompositeAggregation.SINGLE,
        )
    assert "both included and excluded" in str(excinfo.value)


def test_body_inclusion_must_cover_at_least_one_body() -> None:
    with pytest.raises(ValidationError):
        BodyInclusion(included=(), aggregation=CompositeAggregation.SUM)


def test_body_inclusion_rejects_repeated_bodies() -> None:
    with pytest.raises(ValidationError):
        BodyInclusion(
            included=("foot", "foot"),
            aggregation=CompositeAggregation.SINGLE,
        )


def test_an_event_relative_time_basis_must_name_its_origin() -> None:
    assert TimeBasis(kind=TimeBasisKind.RELATIVE_TO_EVENT, origin="takeoff").origin == "takeoff"
    with pytest.raises(ValidationError):
        TimeBasis(kind=TimeBasisKind.RELATIVE_TO_EVENT)
    with pytest.raises(ValidationError):
        TimeBasis(kind=TimeBasisKind.ABSOLUTE, origin="takeoff")


def test_a_uniform_sample_declares_exactly_one_of_period_or_rate() -> None:
    with pytest.raises(ValidationError):
        SamplingSemantics(kind=SamplingKind.UNIFORM)
    with pytest.raises(ValidationError) as excinfo:
        SamplingSemantics(kind=SamplingKind.UNIFORM, period_s=0.001, rate_hz=1000.0)
    assert "exactly one of period_s or rate_hz" in str(excinfo.value)
    assert SamplingSemantics(kind=SamplingKind.UNIFORM, period_s=0.001).period_s == 0.001
    assert SamplingSemantics(kind=SamplingKind.UNIFORM, rate_hz=1000.0).rate_hz == 1000.0


@pytest.mark.parametrize("kind", list(SamplingKind)[1:])
def test_a_rate_free_sampling_kind_takes_no_period_or_rate(kind: SamplingKind) -> None:
    assert SamplingSemantics(kind=kind).kind is kind
    with pytest.raises(ValidationError):
        SamplingSemantics(kind=kind, rate_hz=1000.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_sampling_rates_must_be_positive_and_finite(bad: float) -> None:
    with pytest.raises(ValidationError):
        SamplingSemantics(kind=SamplingKind.UNIFORM, rate_hz=bad)


def test_a_metric_is_defined_over_a_canonical_quantity() -> None:
    metric = metric_definition()
    assert isinstance(metric.quantity, QuantityId)
    assert metric.quantity == "q.jump.height"
    assert "quantity" in MetricDefinition.model_fields


def test_a_metric_window_is_bounded_or_absent() -> None:
    with pytest.raises(ValidationError):
        MetricAggregation(method=AggregationMethod.MEAN, window_start_s=0.0)
    with pytest.raises(ValidationError) as excinfo:
        MetricAggregation(method=AggregationMethod.MEAN, window_start_s=1.0, window_end_s=1.0)
    assert "must precede end" in str(excinfo.value)
    assert MetricAggregation(method=AggregationMethod.MEAN).window_end_s is None


def test_a_metric_criterion_is_optional_and_finite() -> None:
    assert metric_definition().criterion is not None
    assert metric_definition(criterion=None).criterion is None
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            MetricCriterion(operator=ComparisonOperator.LESS, threshold=bad)


def test_a_published_reference_must_be_citable() -> None:
    with pytest.raises(ValidationError) as excinfo:
        reference_definition(origin=ReferenceOrigin.PUBLISHED)
    assert "must carry a citation" in str(excinfo.value)
    cited = reference_definition(origin=ReferenceOrigin.PUBLISHED, citation="Doe 2020")
    assert cited.citation == "Doe 2020"
    assert reference_definition(origin=ReferenceOrigin.SYNTHETIC).citation is None


def test_the_verification_categories_stay_distinct() -> None:
    assert {category.value for category in VerificationCategory} == {
        "code_verification",
        "solution_verification",
        "model_validation",
        "controller_benchmarking",
        "complete_system_qualification",
    }
    assert reference_definition().category is VerificationCategory.MODEL_VALIDATION


def test_a_reference_belongs_to_a_scenario_of_its_benchmark() -> None:
    assert reference_definition().scenario_id == "sc.loaded-cmj"
    with pytest.raises(ValidationError):
        ReferenceDefinition.model_validate(
            {
                "reference_id": "r.baseline-0",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "category": "model_validation",
                "origin": "experimental",
            }
        )


def test_no_quantity_public_field_accepts_an_engine_native_payload() -> None:
    for model in (QuantityDefinition, MetricDefinition, ReferenceDefinition, CanonicalUnit):
        assert model.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError) as excinfo:
        CanonicalUnit.model_validate({"expression": "m", "qpos": [0.0]})
    assert "qpos" in str(excinfo.value)


@given(
    length=st.integers(min_value=-3, max_value=3),
    mass=st.integers(min_value=-3, max_value=3),
    time=st.integers(min_value=-3, max_value=3),
)
def test_a_declared_dimension_must_always_agree_with_the_declared_unit(
    length: int, mass: int, time: int
) -> None:
    dimension = PhysicalDimension(length=length, mass=mass, time=time)
    factors = [
        f"{symbol}^{exponent}"
        for symbol, exponent in (("m", length), ("kg", mass), ("s", time))
        if exponent != 0
    ]
    unit = CanonicalUnit(expression="*".join(factors) if factors else "1")
    matching = quantity_definition(dimension=dimension, unit=unit)
    assert matching.dimension.as_tuple() == canonical_unit_dimension(unit.expression)

    shifted = PhysicalDimension(length=length + 1, mass=mass, time=time)
    with pytest.raises(ValidationError):
        quantity_definition(dimension=shifted, unit=unit)


class _Frame(DomainModel):
    frame: ReferenceFrame


def test_frames_serialise_without_any_engine_native_state() -> None:
    payload = _Frame(frame=WORLD_FRAME).model_dump_json()
    assert "handedness" in payload
    for forbidden in ("qpos", "qvel", "MjData", "State", "obs"):
        assert forbidden not in payload
