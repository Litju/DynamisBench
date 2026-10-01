"""Canonical physical quantity semantics.

Cross-engine interoperability happens at canonical physical quantities, never at a
native state vector (Architecture section 5, ADR-001). A quantity therefore has to
state enough for two independent engines to agree on what a recorded number means:
dimension, canonical SI unit, reference frame, axis convention, sign convention,
body/system inclusion, time basis, and sampling semantics.

The engine-independent half of the interoperability boundary lives here and is
frozen into a benchmark release. The realization-specific extraction mapping and
normalization transform live on ``RealizationDefinition`` instead, because a
benchmark release must stay engine-independent while the mapping is by definition
engine-specific. No engine-native object appears anywhere in this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import AfterValidator, Field, model_validator

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    unique_items,
)
from dynamisbench.domain.spec.identifiers import Name, QuantityId, Version

BASE_DIMENSION_NAMES: Final = (
    "length",
    "mass",
    "time",
    "electric_current",
    "temperature",
    "amount_of_substance",
    "luminous_intensity",
)

_SI_BASE_UNITS: Final[tuple[tuple[str, tuple[int, ...]], ...]] = (
    ("m", (1, 0, 0, 0, 0, 0, 0)),
    ("kg", (0, 1, 0, 0, 0, 0, 0)),
    ("s", (0, 0, 1, 0, 0, 0, 0)),
    ("A", (0, 0, 0, 1, 0, 0, 0)),
    ("K", (0, 0, 0, 0, 1, 0, 0)),
    ("mol", (0, 0, 0, 0, 0, 1, 0)),
    ("cd", (0, 0, 0, 0, 0, 0, 1)),
)
"""The seven SI base units, in the fixed order used for canonical spellings.

Plane angle and solid angle are dimensionless in SI, so they have no base unit
here. An angular quantity therefore has a dimensionless dimension and a canonical
unit of ``1``; its angular meaning is carried by the frame, axis, and sign
conventions and by the realization's normalization transform, never by a private
dimension invented by the platform.
"""

_SI_BASE_VECTORS: Final[Mapping[str, tuple[int, ...]]] = dict(_SI_BASE_UNITS)
_SI_BASE_ORDER: Final[Mapping[str, int]] = {
    symbol: position for position, (symbol, _) in enumerate(_SI_BASE_UNITS)
}

_SI_DERIVED_ALIASES: Final[Mapping[str, Mapping[str, int]]] = {
    "Hz": {"s": -1},
    "N": {"kg": 1, "m": 1, "s": -2},
    "Pa": {"kg": 1, "m": -1, "s": -2},
    "J": {"kg": 1, "m": 2, "s": -2},
    "W": {"kg": 1, "m": 2, "s": -3},
    "C": {"A": 1, "s": 1},
    "V": {"kg": 1, "m": 2, "s": -3, "A": -1},
    "F": {"kg": -1, "m": -2, "s": 4, "A": -2},
    "ohm": {"kg": 1, "m": 2, "s": -3, "A": -2},
    "S": {"kg": -1, "m": -2, "s": 3, "A": -2},
    "Wb": {"kg": 1, "m": 2, "s": -2, "A": -1},
    "T": {"kg": 1, "m": -2, "s": -2, "A": -1},
    "H": {"kg": 1, "m": 2, "s": -2, "A": -2},
}
"""SI derived units with special names, expanded to their base-unit definition.

They are accepted as authoring aliases and never stored, so a derived name and its
base-unit product cannot become two spellings of one unit.
"""

_REJECTED_SYMBOLS: Final[Mapping[str, str]] = {
    "rad": (
        "plane angle is dimensionless in SI; use unit '1' and state the angular "
        "convention in the axis and sign conventions"
    ),
    "sr": (
        "solid angle is dimensionless in SI; use unit '1' and state the angular "
        "convention in the axis and sign conventions"
    ),
    "g": "gram is a scaled unit; use the SI base unit 'kg'",
}

_UNIT_EXPRESSION: Final = re.compile(
    r"^(?:1|[A-Za-z]+(?:\^-?\d{1,2})?(?:[*/][A-Za-z]+(?:\^-?\d{1,2})?)*)$"
)


def _base_exponents(expression: str) -> dict[str, int]:
    """Expand a unit expression into SI base-unit exponents.

    Derived-unit aliases are expanded, so equal units always produce equal base-unit
    exponents. Raises ``ValueError`` for an unknown symbol, a rejected symbol, a zero
    exponent, or any shape that is not a single unambiguous unit.
    """
    if not _UNIT_EXPRESSION.match(expression):
        raise ValueError(
            f"unit {expression!r} is not a SI unit expression; use '1', or SI unit "
            "symbols joined by '*' or '/' with an optional ^exponent"
        )
    exponents: dict[str, int] = {}
    if expression == "1":
        return exponents

    def add(symbol: str, magnitude: int) -> None:
        exponents[symbol] = exponents.get(symbol, 0) + magnitude

    sign = 1
    for term in re.split(r"([*/])", expression):
        if term == "*":
            sign = 1
            continue
        if term == "/":
            sign = -1
            continue
        symbol, separator, exponent_text = term.partition("^")
        if separator and int(exponent_text) == 0:
            raise ValueError(f"unit {expression!r} uses a zero exponent, which changes nothing")
        if symbol in _REJECTED_SYMBOLS:
            raise ValueError(f"unit symbol {symbol!r} is not accepted: {_REJECTED_SYMBOLS[symbol]}")
        if symbol in _SI_DERIVED_ALIASES:
            for base_symbol, magnitude in _SI_DERIVED_ALIASES[symbol].items():
                add(base_symbol, sign * magnitude * (int(exponent_text) if separator else 1))
            continue
        if symbol not in _SI_BASE_VECTORS:
            raise ValueError(f"unknown SI unit symbol {symbol!r} in {expression!r}")
        add(symbol, sign * (int(exponent_text) if separator else 1))
    return exponents


def canonical_unit_dimension(expression: str) -> tuple[int, ...]:
    """Return the SI base-dimension exponents of a SI unit expression."""
    exponents = _base_exponents(expression)
    return tuple(
        sum(exponents.get(symbol, 0) * vector[index] for symbol, vector in _SI_BASE_VECTORS.items())
        for index in range(len(BASE_DIMENSION_NAMES))
    )


def _canonical_unit_expression(expression: str) -> str:
    """Validate a unit expression and return its single canonical spelling.

    A unit is part of a quantity's scientific identity, so it must not have several
    spellings. The expression is reduced to SI base units and re-rendered in the fixed
    base-unit order, so ``kg*m^2/s^3`` and ``W`` produce the same stored unit.
    """
    exponents = _base_exponents(expression)
    symbols = sorted(
        (symbol for symbol, exponent in exponents.items() if exponent != 0),
        key=_SI_BASE_ORDER.__getitem__,
    )
    if not symbols:
        return "1"
    return "*".join(
        symbol if exponents[symbol] == 1 else f"{symbol}^{exponents[symbol]}" for symbol in symbols
    )


CanonicalUnitExpression = Annotated[
    str,
    Field(min_length=1, max_length=128),
    AfterValidator(_canonical_unit_expression),
]
"""A SI unit expression stored in its single canonical spelling."""


class CanonicalUnit(DomainModel):
    """The canonical SI unit of a quantity, in exactly one spelling."""

    expression: CanonicalUnitExpression


class Handedness(StrEnum):
    """Orientation convention of a three-dimensional reference frame."""

    RIGHT = "right"
    LEFT = "left"


class RotationSense(StrEnum):
    """Whether a rotation sequence is applied about moving or fixed axes."""

    INTRINSIC = "intrinsic"
    EXTRINSIC = "extrinsic"


class CompositeAggregation(StrEnum):
    """How a quantity that spans several bodies relates to those bodies.

    A weighted or averaged composite is deliberately not modelled here: it is a
    normalization transform of a canonical quantity, not a property of one.
    """

    SINGLE = "single"
    SUM = "sum"


class SamplingKind(StrEnum):
    """How a canonical signal is sampled over its time basis."""

    UNIFORM = "uniform"
    IRREGULAR = "irregular"
    EVENT_SAMPLED = "event_sampled"
    SINGLE_SAMPLE = "single_sample"


class TimeBasisKind(StrEnum):
    """What a quantity's time stamp is measured from."""

    ABSOLUTE = "absolute"
    RELATIVE_TO_START = "relative_to_start"
    RELATIVE_TO_EVENT = "relative_to_event"
    PHASE_RELATIVE = "phase_relative"


class PhysicalDimension(DomainModel):
    """The physical dimension of a quantity as SI base-dimension exponents."""

    length: int = 0
    mass: int = 0
    time: int = 0
    electric_current: int = 0
    temperature: int = 0
    amount_of_substance: int = 0
    luminous_intensity: int = 0

    def as_tuple(self) -> tuple[int, ...]:
        """Return the exponents in :data:`BASE_DIMENSION_NAMES` order."""
        return tuple(int(getattr(self, name)) for name in BASE_DIMENSION_NAMES)


DIMENSIONLESS: Final = PhysicalDimension()
"""The dimensionless physical dimension."""


class ReferenceFrame(DomainModel):
    """The frame a vector or scalar quantity is expressed in.

    A frame is always part of a declared chain: ``parent`` names the frame this one
    is defined against, so a quantity can never reference a frame that exists only
    in the author's head.
    """

    frame_id: Name
    parent: Name
    axis_labels: tuple[Name, ...] = Field(min_length=1, max_length=3)
    handedness: Handedness | None = None
    description: ShortText

    @model_validator(mode="after")
    def _frame_is_well_formed(self) -> Self:
        if self.frame_id == self.parent:
            raise ValueError(f"frame {self.frame_id!r} cannot be its own parent")
        if len(set(self.axis_labels)) != len(self.axis_labels):
            raise ValueError(f"axis labels must be distinct: {self.axis_labels}")
        is_three_dimensional = len(self.axis_labels) == 3
        if is_three_dimensional and self.handedness is None:
            raise ValueError("a three-dimensional frame must declare its handedness")
        if not is_three_dimensional and self.handedness is not None:
            raise ValueError("handedness applies only to a three-dimensional frame")
        return self


class AxisConvention(DomainModel):
    """The rotation sequence a three-component orientation quantity uses."""

    order: tuple[Name, ...] = Field(min_length=3, max_length=3)
    sense: RotationSense

    @model_validator(mode="after")
    def _order_is_well_formed(self) -> Self:
        if len(set(self.order)) != 3:
            raise ValueError(f"rotation order must name three distinct axes: {self.order}")
        return self


class SignConvention(DomainModel):
    """What a positive value of a quantity means.

    The direction is stated rather than enumerated, because no finite list of sign
    conventions covers biomechanical quantities honestly.
    """

    positive_direction: ShortText
    notes: tuple[ShortText, ...] = ()


class BodyInclusion(DomainModel):
    """Which bodies a quantity is computed over."""

    included: Annotated[tuple[Name, ...], unique_items(), Field(min_length=1)]
    excluded: Annotated[tuple[Name, ...], unique_items()] = ()
    aggregation: CompositeAggregation
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _inclusion_and_exclusion_are_disjoint(self) -> Self:
        overlap = set(self.included) & set(self.excluded)
        if overlap:
            raise ValueError(f"bodies cannot be both included and excluded: {sorted(overlap)}")
        return self


class TimeBasis(DomainModel):
    """What a quantity's time stamp is measured from.

    A time origin is only meaningful relative to a declared event, so naming one is
    mandatory for an event-relative basis and forbidden otherwise. Resolving an
    origin name to the event of a particular scenario is a study and planning
    concern, not a property of the quantity.
    """

    kind: TimeBasisKind
    origin: Name | None = None

    @model_validator(mode="after")
    def _origin_matches_the_basis(self) -> Self:
        needs_origin = self.kind is TimeBasisKind.RELATIVE_TO_EVENT
        if needs_origin and self.origin is None:
            raise ValueError("an event-relative time basis must name its origin event")
        if not needs_origin and self.origin is not None:
            raise ValueError(f"time basis {self.kind.value!r} does not use an origin event")
        return self


class SamplingSemantics(DomainModel):
    """How a canonical signal is sampled, and at what rate where that is meaningful.

    A uniform sample must declare its period or its rate, and never both: stating
    both is contradictory, because the two must agree. Any other sampling kind has
    no single rate, so neither is accepted.
    """

    kind: SamplingKind
    period_s: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    rate_hz: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _sampling_rate_is_coherent(self) -> Self:
        declared = (self.period_s is not None) + (self.rate_hz is not None)
        if self.kind is SamplingKind.UNIFORM and declared != 1:
            raise ValueError("a uniform sample must declare exactly one of period_s or rate_hz")
        if self.kind is not SamplingKind.UNIFORM and declared:
            raise ValueError(
                f"sampling kind {self.kind.value!r} has no single rate; "
                "period_s and rate_hz must be omitted"
            )
        return self


class UncertaintyMetadata(DomainModel):
    """What uncertainty is expected of a quantity.

    A statement is required rather than a numeric estimate: DB-1.2 models
    expectations frozen into benchmark authority, not quantified results.
    """

    characterization: ShortText
    notes: tuple[ShortText, ...] = ()


class QuantityDefinition(DomainModel):
    """One canonical physical quantity and the semantics needed to interpret it.

    The declared ``dimension`` must agree with the declared canonical unit. Stating
    both is deliberate: the dimension is the scientific claim and the unit is its
    representation, and a definition whose two halves disagree is contradictory
    authority rather than a formatting problem.
    """

    quantity_id: QuantityId
    version: Version
    label: ShortText
    description: NonEmptyText
    dimension: PhysicalDimension
    unit: CanonicalUnit
    frame: ReferenceFrame
    sign_convention: SignConvention
    time_basis: TimeBasis
    sampling: SamplingSemantics
    axis_convention: AxisConvention | None = None
    body_inclusion: BodyInclusion | None = None
    uncertainty: UncertaintyMetadata | None = None
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _dimension_agrees_with_unit(self) -> Self:
        declared = self.dimension.as_tuple()
        derived = canonical_unit_dimension(self.unit.expression)
        if declared != derived:
            raise ValueError(
                f"quantity {self.quantity_id!r} declares dimension "
                f"{dict(zip(BASE_DIMENSION_NAMES, declared, strict=True))} but unit "
                f"{self.unit.expression!r} has dimension "
                f"{dict(zip(BASE_DIMENSION_NAMES, derived, strict=True))}"
            )
        return self
