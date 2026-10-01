"""Study definitions and uncertainty factors.

A study asks a question using exact benchmark release(s), realization(s), system(s)
under test, factors, controlled variables, seeds and replicates, outcomes, and an
analysis plan. It consumes frozen benchmark authority; it never mutates it. Research
iteration happens by defining a new study, not by editing a released benchmark
(ADR-002, VVUQ Workflow).

The distributions modelled here are the deliberately small parametric set that
describes what a factor *is*. Nothing in this module samples anything: distribution
utilities and the deliberate UQ stack belong to the issue that implements study
execution.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    Token,
    keyed_by,
    unique_items,
)
from dynamisbench.domain.spec.capability import CapabilityRequirement
from dynamisbench.domain.spec.identifiers import (
    BenchmarkRef,
    EnvironmentRef,
    FactorId,
    Name,
    QuantityId,
    RealizationRef,
    StudyId,
    SUTRef,
    Version,
)


class FactorRole(StrEnum):
    """Whether a factor is varied across a study or deliberately held fixed."""

    FACTOR = "factor"
    CONTROLLED = "controlled"


class FactorTargetKind(StrEnum):
    """What a factor varies."""

    REALIZATION = "realization"
    SUT = "sut"
    ENVIRONMENT = "environment"
    BENCHMARK_QUANTITY = "benchmark_quantity"


class PointValue(DomainModel):
    """A single fixed value."""

    kind: Literal["point"] = "point"
    value: Annotated[float, Field(allow_inf_nan=False)]


class UniformRange(DomainModel):
    """A range with uniform weight."""

    kind: Literal["uniform"] = "uniform"
    lower: Annotated[float, Field(allow_inf_nan=False)]
    upper: Annotated[float, Field(allow_inf_nan=False)]

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError(f"uniform lower {self.lower} must precede upper {self.upper}")
        return self


class NormalSpread(DomainModel):
    """A normal spread about a mean."""

    kind: Literal["normal"] = "normal"
    mean: Annotated[float, Field(allow_inf_nan=False)]
    standard_deviation: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class LogNormalSpread(DomainModel):
    """A log-normal spread, used where a quantity is strictly positive."""

    kind: Literal["lognormal"] = "lognormal"
    mean_log: Annotated[float, Field(allow_inf_nan=False)]
    standard_deviation_log: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class TriangularRange(DomainModel):
    """A bounded range weighted towards a mode."""

    kind: Literal["triangular"] = "triangular"
    lower: Annotated[float, Field(allow_inf_nan=False)]
    upper: Annotated[float, Field(allow_inf_nan=False)]
    mode: Annotated[float, Field(allow_inf_nan=False)]

    @model_validator(mode="after")
    def _mode_lies_inside_the_range(self) -> Self:
        if self.lower >= self.upper:
            raise ValueError(f"triangular lower {self.lower} must precede upper {self.upper}")
        if not self.lower <= self.mode <= self.upper:
            raise ValueError(
                f"triangular mode {self.mode} must lie within [{self.lower}, {self.upper}]"
            )
        return self


FactorDistribution = Annotated[
    PointValue | UniformRange | NormalSpread | LogNormalSpread | TriangularRange,
    Field(discriminator="kind"),
]
"""The declared uncertainty of one factor, as a closed set of parametric shapes."""


class FactorTarget(DomainModel):
    """What a factor varies.

    A realization, SUT, or environment target always names the specific parameter
    being varied, because varying "a realization" is not a defined intervention. A
    benchmark-quantity target is a declared property of the frozen benchmark and has
    no such parameter.
    """

    kind: FactorTargetKind
    identifier: Name
    parameter: Token | None = None

    @model_validator(mode="after")
    def _parameter_matches_the_target(self) -> Self:
        targets_a_parameter = self.kind is not FactorTargetKind.BENCHMARK_QUANTITY
        if targets_a_parameter and self.parameter is None:
            raise ValueError(f"a {self.kind.value} factor must name the parameter it varies")
        if not targets_a_parameter and self.parameter is not None:
            raise ValueError(
                "a benchmark-quantity factor is a property of frozen authority and "
                "names no parameter"
            )
        return self


class UncertaintyFactorDefinition(DomainModel):
    """One thing a study varies or deliberately holds fixed.

    A controlled variable is held at one value, so a controlled entry must carry a
    point distribution. A controlled entry with a spread describes a factor, and
    accepting it would make the two roles indistinguishable downstream.
    """

    factor_id: FactorId
    label: ShortText
    description: NonEmptyText
    role: FactorRole
    quantity: QuantityId
    target: FactorTarget
    distribution: FactorDistribution
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _controlled_factors_are_fixed(self) -> Self:
        if self.role is FactorRole.CONTROLLED and self.distribution.kind != "point":
            raise ValueError(
                f"controlled factor {self.factor_id!r} must hold a point value, not a "
                f"{self.distribution.kind!r} distribution"
            )
        return self


class StudyDefinition(DomainModel):
    """A research question asked over exact, frozen, separately versioned authority.

    Every referenced benchmark, realization, system under test, and environment is a
    versioned reference, so a study names precisely what it consumed and cannot
    silently drift onto a newer release.
    """

    study_id: StudyId
    version: Version
    label: ShortText
    description: NonEmptyText
    research_question: NonEmptyText
    analysis_plan: NonEmptyText
    replicates: Annotated[int, Field(gt=0)]
    benchmarks: Annotated[tuple[BenchmarkRef, ...], keyed_by("identifier"), Field(min_length=1)]
    realizations: Annotated[tuple[RealizationRef, ...], keyed_by("identifier"), Field(min_length=1)]
    systems_under_test: Annotated[tuple[SUTRef, ...], keyed_by("identifier"), Field(min_length=1)]
    environments: Annotated[tuple[EnvironmentRef, ...], keyed_by("identifier"), Field(min_length=1)]
    required_capabilities: Annotated[
        tuple[CapabilityRequirement, ...], keyed_by("capability"), Field(min_length=1)
    ]
    factors: Annotated[
        tuple[UncertaintyFactorDefinition, ...], keyed_by("factor_id"), Field(min_length=1)
    ]
    outcomes: Annotated[tuple[Name, ...], unique_items(), Field(min_length=1)]
    seeds: Annotated[tuple[Annotated[int, Field(ge=0)], ...], unique_items(), Field(min_length=1)]
    notes: tuple[ShortText, ...] = ()
