"""Every way planning refuses to compile, as one closed set of named failures.

Planning is a compiler, so its most important output is a refusal: authority that
cannot be resolved exactly, a candidate whose essential capability the realization
does not provide, or a factor case that does not cover the study's varied factors
must stop the compile *before* a RunSpec exists (VVUQ Workflow, Study planning
semantics). Refusing later, at execution time, would mean a plan had already
claimed a scientific configuration nobody had verified.

The three failures are kept distinct because they are answered by three different
people. :class:`AuthorityResolutionError` means the supplied authority is not the
authority the study named. :class:`IncompatibleCapabilityError` means the authority
is right but the realization cannot answer what the study needs. :class:
`FactorResolutionError` means the study's factors were not given exact values.
Collapsing them into one exception would force a caller to re-derive which of the
three happened in order to report it.
"""

from __future__ import annotations


class PlanningError(Exception):
    """Base class for every refusal to compile a study plan."""


class AuthorityResolutionError(PlanningError):
    """A reference did not resolve to exactly one supplied definition.

    Raised for a missing referenced authority, a duplicate in the planning
    context, a reference naming a concept the context cannot supply, a version
    that does not match, a realization bound to a benchmark the study does not
    reference, and a factor target or quantity that dangles. All of them are the
    same class of problem — the plan would otherwise execute against authority
    nobody supplied — and none of them is recoverable by trying harder.
    """


class IncompatibleCapabilityError(PlanningError):
    """A realization does not provide a capability a candidate execution needs.

    Only *essential* requirements raise. A missing non-essential requirement is a
    recorded compatibility warning on the planned run, not a failure, because the
    study declared that it can proceed without it.
    """


class FactorResolutionError(PlanningError):
    """A factor case does not exactly cover the study's varied factors.

    Raised for a varied factor with no case, a case that omits a varied factor,
    a case that names a factor the study does not declare, a case that tries to
    override a controlled factor, a non-finite value, and a value outside the
    declared distribution's support.
    """
