"""Factor values, factor cases, and the support rule that bounds them.

Two roles, from :class:`~dynamisbench.domain.spec.studies.FactorRole`, are resolved
by two different rules and it is worth being explicit about why.

A **controlled** factor already carries a point distribution, so its exact value is
already authority. Planning resolves it automatically and a caller may not repeat it:
repeating a controlled value would make two places able to state it, and the one that
lost would be invisible.

A **varied** factor has a declared distribution and no value. RES-232 does not sample
that distribution. A :class:`FactorCase` therefore carries the exact values a sampler
or a human chose, and it must cover every varied factor of the study exactly once.
Future M6 sampling (Sobol/QMC/SALib) produces :class:`FactorCase` objects of exactly
this shape and reuses this compiler unchanged: it adds sampling, not a second RunSpec
model.

Support is checked against the declared distribution and *only* against its support.
Probability density is not an acceptance rule — a value well inside the support of a
triangular distribution is a legal exact value even when the sampler would give it
almost no mass, and rejecting it would replace a declared distribution with this
package's opinion about which values are worth running.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import Field

from dynamisbench.domain.spec.base import DomainModel, keyed_by
from dynamisbench.domain.spec.identifiers import FactorId, Name, QuantityId
from dynamisbench.domain.spec.quantities import CanonicalUnit
from dynamisbench.domain.spec.studies import (
    FactorDistribution,
    FactorRole,
    FactorTarget,
    FactorTargetKind,
    LogNormalSpread,
    NormalSpread,
    PointValue,
    TriangularRange,
    UncertaintyFactorDefinition,
    UniformRange,
)
from dynamisbench.planning.errors import FactorResolutionError

FactorSet = tuple[UncertaintyFactorDefinition, ...]
"""The study's factors, in the canonical order ``keyed_by`` already gave them."""


class FactorValue(DomainModel):
    """One exact value assigned to one factor by a factor case."""

    factor_id: FactorId
    value: Annotated[float, Field(allow_inf_nan=False)]


class FactorCase(DomainModel):
    """One explicit, exact assignment of the study's varied factors.

    ``case_id`` is a stable name for the case, not a value. It orders cases in the plan
    and appears on each planned run, but it is deliberately *not* part of the
    execution fingerprint: renaming a case changes nothing about what any run
    executes. Two cases with different identities that assign the same values
    therefore produce runs with the same fingerprint, and both are kept — they are
    distinct study instances, and collapsing them would lose the fact that the study
    asked for both.

    ``values`` is keyed by factor, which refuses a case that assigns one factor twice
    before any resolution happens.
    """

    case_id: Name
    values: Annotated[tuple[FactorValue, ...], keyed_by("factor_id")] = ()


class FactorAssignment(DomainModel):
    """One factor's exact value, as it applies to a single candidate execution.

    The assignment is self-describing on purpose. It carries the factor's quantity and
    that quantity's canonical unit as declared by the *active* benchmark release, and
    the target parameter being varied, because those facts are what give the number
    its meaning. A RunSpec that carried only ``(factor_id, value)`` would give two
    different perturbations the same identity whenever they shared a number, and the
    unit a value is expressed in is exactly what a worker needs in order to apply it.
    """

    factor_id: FactorId
    quantity: QuantityId
    unit: CanonicalUnit
    target: FactorTarget
    value: Annotated[float, Field(allow_inf_nan=False)]


def varied_factors(factors: FactorSet) -> FactorSet:
    """The factors the study varies, which therefore require an exact case value."""
    return tuple(factor for factor in factors if factor.role is FactorRole.FACTOR)


def controlled_factors(factors: FactorSet) -> FactorSet:
    """The factors the study holds fixed, whose value the study already declares."""
    return tuple(factor for factor in factors if factor.role is FactorRole.CONTROLLED)


def supports_value(distribution: FactorDistribution, value: float) -> bool:
    """Whether ``value`` lies in the declared distribution's support.

    The rule per shape, and nothing beyond it:

    * ``point`` — the exact declared value, and nothing else;
    * ``uniform`` / ``triangular`` — the closed interval ``[lower, upper]``;
    * ``normal`` — every finite real value, with no artificial truncation, because the
      support of a normal variate is the whole real line and inventing a range would
      be this package truncating a distribution the study did not truncate;
    * ``lognormal`` — every finite value strictly above zero, because the underlying
      normal variate is only strictly positive after exponentiation.

    A triangular ``mode`` is deliberately not a constraint on a factor case: the mode
    shapes the sampling density, not the interval the quantity can take.
    """

    if isinstance(distribution, PointValue):
        return value == distribution.value
    if isinstance(distribution, UniformRange | TriangularRange):
        return distribution.lower <= value <= distribution.upper
    if isinstance(distribution, LogNormalSpread):
        return value > 0.0
    if isinstance(distribution, NormalSpread):
        return True
    raise FactorResolutionError(
        f"a {distribution.kind!r} distribution has no declared support rule; a new "
        "distribution kind must state one before a value can be accepted for it"
    )


def check_support(factor: UncertaintyFactorDefinition, value: float) -> float:
    """Return ``value`` when the declared support admits it, or refuse.

    The refusal names the factor, the distribution shape and the distribution itself,
    because the bound is what a caller has to change, and a message that only said
    "invalid" would put the study's own authority under suspicion instead.
    """

    if not supports_value(factor.distribution, value):
        raise FactorResolutionError(
            f"factor {factor.factor_id!r} was assigned {value!r}, which lies outside the "
            f"support of its declared {factor.distribution.kind!r} distribution "
            f"{factor.distribution!r}"
        )
    return value


def controlled_value(factor: UncertaintyFactorDefinition) -> float:
    """The exact value of a controlled factor, read from its point distribution.

    A controlled factor is required by the domain model to hold a point
    distribution, so this is total. The guard is here so that a future distribution
    kind cannot silently produce a value the study never declared.
    """

    distribution = factor.distribution
    if not isinstance(distribution, PointValue):
        raise FactorResolutionError(
            f"controlled factor {factor.factor_id!r} holds a {distribution.kind!r} "
            "distribution; a controlled factor must hold a point value"
        )
    return distribution.value


def active_factors(
    factors: FactorSet, referenced: Mapping[FactorTargetKind, frozenset[Name]]
) -> FactorSet:
    """The factors whose declared target is the candidate's active authority.

    A factor targets one specific realization, system under test, environment or
    benchmark. In a candidate whose realization is a different one, that factor is not
    a value this run is given — it is a statement about a different object — so it is
    excluded here rather than carried into the RunSpec as an assignment nothing would
    apply. Exclusion is silent for the run and loud in the plan: the factor is still
    validated, still target-checked, and still present in every candidate it does
    target.
    """

    return tuple(
        factor for factor in factors if factor.target.identifier in referenced[factor.target.kind]
    )


def assignment(
    factor: UncertaintyFactorDefinition,
    value: float,
    *,
    quantity: QuantityId,
    unit: CanonicalUnit,
) -> FactorAssignment:
    """Build one self-describing factor assignment for a RunSpec."""

    return FactorAssignment(
        factor_id=factor.factor_id,
        quantity=quantity,
        unit=unit,
        target=factor.target,
        value=check_support(factor, value),
    )


def case_values(case: FactorCase) -> Mapping[FactorId, float]:
    """The case's exact values, keyed by factor."""
    return {value.factor_id: value.value for value in case.values}
