"""The benchmark release: frozen scientific authority.

A benchmark release states what is being evaluated and why. Its meaning is immutable;
a change produces a new release (VVUQ Workflow, Benchmark Release). It therefore
embeds its own canonical quantities, scenarios, metrics, and references rather than
referring to definitions that could later move underneath it.

The release is the level at which cross-object authority is checked. A scenario may
not assign an initial condition on a quantity the release does not declare, may not
assign it in a unit that contradicts the declared quantity, a metric may not be
defined over an undeclared quantity, and a reference may not point at an undeclared
scenario. Those are dangling or contradictory authority, and they fail closed here
rather than at run time.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import Field, model_validator

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    keyed_by,
)
from dynamisbench.domain.spec.identifiers import BenchmarkId, Version
from dynamisbench.domain.spec.metrics import MetricDefinition
from dynamisbench.domain.spec.quantities import QuantityDefinition
from dynamisbench.domain.spec.references import ReferenceDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition


class CredibilityLevel(StrEnum):
    """One rung of the hierarchical credibility ladder.

    The VVUQ authority prefers hierarchical credibility and keeps the rungs
    distinct, so a release states which rungs it actually covers instead of implying
    complete-system credibility.
    """

    UNIT_PROBLEM = "unit_problem"
    BENCHMARK_REFERENCE_CASE = "benchmark_reference_case"
    SUBSYSTEM_CASE = "subsystem_case"
    COMPLETE_SYSTEM = "complete_system"


CREDIBILITY_LADDER: Final = (
    CredibilityLevel.UNIT_PROBLEM,
    CredibilityLevel.BENCHMARK_REFERENCE_CASE,
    CredibilityLevel.SUBSYSTEM_CASE,
    CredibilityLevel.COMPLETE_SYSTEM,
)
"""The ascending credibility ladder a release's hierarchy must be a subsequence of."""


class BenchmarkRelease(DomainModel):
    """An immutable, versioned statement of benchmark scientific authority."""

    benchmark_id: BenchmarkId
    version: Version
    label: ShortText
    description: NonEmptyText
    intended_use: NonEmptyText
    intended_non_use: NonEmptyText
    conceptual_model: NonEmptyText
    claim_ceiling: NonEmptyText
    quantities: Annotated[
        tuple[QuantityDefinition, ...], keyed_by("quantity_id"), Field(min_length=1)
    ]
    scenarios: Annotated[
        tuple[ScenarioDefinition, ...], keyed_by("scenario_id"), Field(min_length=1)
    ]
    metrics: Annotated[tuple[MetricDefinition, ...], keyed_by("metric_id"), Field(min_length=1)]
    references: Annotated[tuple[ReferenceDefinition, ...], keyed_by("reference_id")] = ()
    credibility_hierarchy: tuple[CredibilityLevel, ...] = Field(min_length=1)
    requirements: tuple[NonEmptyText, ...] = ()
    assumptions: tuple[NonEmptyText, ...] = ()
    applicability_domain: tuple[NonEmptyText, ...] = ()
    known_discrepancies: tuple[NonEmptyText, ...] = ()
    uncertainty_expectations: tuple[NonEmptyText, ...] = ()
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _hierarchy_follows_the_ladder(self) -> Self:
        position = 0
        for level in self.credibility_hierarchy:
            if level not in CREDIBILITY_LADDER[position:]:
                raise ValueError(
                    f"credibility hierarchy {list(self.credibility_hierarchy)} must be an "
                    f"ascending subsequence of {[item.value for item in CREDIBILITY_LADDER]}"
                )
            position = CREDIBILITY_LADDER.index(level) + 1
        return self

    @model_validator(mode="after")
    def _declared_authority_is_internally_consistent(self) -> Self:
        units = {quantity.quantity_id: quantity.unit.expression for quantity in self.quantities}
        scenarios = {scenario.scenario_id for scenario in self.scenarios}

        for scenario in self.scenarios:
            for assignment in scenario.initial_conditions:
                declared = units.get(assignment.quantity)
                if declared is None:
                    raise ValueError(
                        f"scenario {scenario.scenario_id!r} assigns initial condition "
                        f"{assignment.quantity!r}, which the release does not declare"
                    )
                if assignment.unit.expression != declared:
                    raise ValueError(
                        f"scenario {scenario.scenario_id!r} assigns {assignment.quantity!r} "
                        f"in {assignment.unit.expression!r} but the release declares it in "
                        f"{declared!r}"
                    )

        for metric in self.metrics:
            if metric.quantity not in units:
                raise ValueError(
                    f"metric {metric.metric_id!r} is defined over {metric.quantity!r}, "
                    "which the release does not declare"
                )

        for reference in self.references:
            if reference.scenario_id not in scenarios:
                raise ValueError(
                    f"reference {reference.reference_id!r} points at scenario "
                    f"{reference.scenario_id!r}, which the release does not declare"
                )
        return self
