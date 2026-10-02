"""Factor activity and assignment: what a RunSpec is told, and what it is not.

A factor targets one specific authority. In a candidate that is a different one, the
factor is not a value that run is given, so it is excluded from the RunSpec rather than
recorded as an assignment with no effect. Exclusion is silent for the run and loud in the
plan: the factor is still validated, still target-checked, and still present in every
candidate it does target.
"""

from __future__ import annotations

from dynamisbench.domain.spec.studies import FactorTargetKind
from dynamisbench.planning.factors import active_factors, assignment
from tests.domain import factories as domain
from tests.planning.factor_factories import realization_factor


def test_only_the_factors_that_target_a_candidate_authority_are_active() -> None:
    """A factor targeting another realization is a statement about a different object."""
    factor = realization_factor("rl.opensim.loaded-cmj")

    active = active_factors(
        (factor,), {FactorTargetKind.REALIZATION: frozenset({"rl.mujoco.loaded-cmj"})}
    )

    assert active == ()


def test_an_assignment_names_the_factor_it_comes_from_and_its_target() -> None:
    """Two factors that share a number are still two different interventions."""
    factor = domain.uncertainty_factor()
    unit = domain.quantity_definition().unit

    resolved = assignment(factor, 0.9, quantity=factor.quantity, unit=unit)

    assert resolved.unit == unit
    assert resolved.value == 0.9
    assert resolved.target == factor.target
    assert resolved.quantity == factor.quantity
    assert resolved.factor_id == factor.factor_id
