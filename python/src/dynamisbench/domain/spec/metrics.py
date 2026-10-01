"""Metric definitions.

A metric compares evidence against a reference, so it is expressed over a canonical
quantity rather than over any engine's output. A pass/fail threshold is modelled only
as an explicit optional criterion: a metric without a criterion is legitimate and
simply does not decide pass/fail (VVUQ Workflow, Assessment Evidence).

The statistics vocabulary is deliberately the small set the VVUQ authority names
directly. A study that needs a statistic outside this set declares its own metric
definition rather than bending an existing one.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from dynamisbench.domain.spec.base import DomainModel, NonEmptyText, ShortText
from dynamisbench.domain.spec.identifiers import MetricId, QuantityId, Version


class AggregationMethod(StrEnum):
    """How a metric combines the samples inside its evaluation window."""

    MEAN = "mean"
    MEDIAN = "median"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    STANDARD_DEVIATION = "standard_deviation"


class ComparisonOperator(StrEnum):
    """Direction of a metric criterion comparison."""

    LESS = "less"
    LESS_OR_EQUAL = "less_or_equal"
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    GREATER_OR_EQUAL = "greater_or_equal"
    GREATER = "greater"


class MetricAggregation(DomainModel):
    """The statistic a metric reports over its evaluation window.

    A window is bounded or absent, never half-declared: stating a start without an
    end does not identify a window.
    """

    method: AggregationMethod
    window_start_s: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    window_end_s: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def _window_is_bounded(self) -> Self:
        start, end = self.window_start_s, self.window_end_s
        if (start is None) != (end is None):
            raise ValueError("a metric window must declare both a start and an end, or neither")
        if start is not None and end is not None and start >= end:
            raise ValueError(f"metric window start {start} must precede end {end}")
        return self


class MetricCriterion(DomainModel):
    """A threshold that turns a metric result into a pass/fail decision.

    The threshold is expressed in the canonical unit of the metric's quantity, which
    is why no unit is repeated here and could drift out of step with the quantity.
    """

    operator: ComparisonOperator
    threshold: Annotated[float, Field(allow_inf_nan=False)]


class MetricDefinition(DomainModel):
    """One named quantity-level comparison used to assess a system under test."""

    metric_id: MetricId
    version: Version
    label: ShortText
    description: NonEmptyText
    quantity: QuantityId
    aggregation: MetricAggregation | None = None
    criterion: MetricCriterion | None = None
    notes: tuple[ShortText, ...] = ()
