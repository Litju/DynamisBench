"""Scenario definitions.

A scenario is one evaluated case of a benchmark: a bounded situation with a declared
duration, declared initial conditions expressed in canonical quantities, and any
events the situation is recognised by. Detection of an event inside an engine is a
realization concern, so a scenario declares an expected time and tolerance rather
than an engine-side detector.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, model_validator

from dynamisbench.domain.spec.base import DomainModel, NonEmptyText, ShortText, keyed_by
from dynamisbench.domain.spec.capability import CapabilityRequirement
from dynamisbench.domain.spec.identifiers import Name, QuantityId, ScenarioId, Version
from dynamisbench.domain.spec.quantities import CanonicalUnit


class EventDefinition(DomainModel):
    """A named event a scenario is recognised by.

    An expected time and its tolerance are both present or both absent: an expected
    time with no tolerance states a position that no comparison could ever satisfy.
    """

    event_id: Name
    label: ShortText
    expected_time_s: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    tolerance_s: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _tolerance_matches_expectation(self) -> Self:
        given = (self.expected_time_s is not None, self.tolerance_s is not None)
        if given != (True, True) and given != (False, False):
            raise ValueError(
                f"event {self.event_id!r} must declare an expected time and tolerance together"
            )
        return self


class QuantityAssignment(DomainModel):
    """One initial condition, stated on a canonical quantity and its canonical unit.

    The unit is repeated here on purpose. The owning release checks that it agrees
    with the unit of the referenced quantity, so a scenario cannot quietly assign a
    value in one unit to a quantity declared in another.
    """

    quantity: QuantityId
    value: Annotated[float, Field(allow_inf_nan=False)]
    unit: CanonicalUnit


class ScenarioDefinition(DomainModel):
    """One evaluated case of the owning benchmark release."""

    scenario_id: ScenarioId
    version: Version
    label: ShortText
    description: NonEmptyText
    duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    initial_conditions: Annotated[
        tuple[QuantityAssignment, ...], keyed_by("quantity"), Field(min_length=1)
    ]
    events: Annotated[tuple[EventDefinition, ...], keyed_by("event_id")] = ()
    required_capabilities: Annotated[tuple[CapabilityRequirement, ...], keyed_by("capability")] = ()
    notes: tuple[ShortText, ...] = ()
