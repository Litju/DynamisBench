"""Realization quantity coverage.

A mapping must name a quantity its benchmark declares. Coverage of every declared quantity
is not required by the current authority, so a gap is reported rather than turned into an
invented requirement, and the transformation authority stays pinned by the realization's
own identity.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.identifiers import QuantityId
from dynamisbench.planning import (
    AuthorityResolutionError,
)
from tests.domain import factories as domain
from tests.planning.compiler import (
    compile_plan,
    one_run,
)
from tests.planning.factories import (
    World,
    default_world,
)


def test_a_realization_may_not_map_a_quantity_its_benchmark_does_not_declare() -> None:
    world = default_world()
    broken = World(
        benchmarks=world.benchmarks,
        realizations=(
            domain.realization_definition(
                quantity_mappings=(domain.quantity_mapping("q.never-declared"),)
            ),
        ),
        systems_under_test=world.systems_under_test,
        environments=world.environments,
    )

    with pytest.raises(AuthorityResolutionError, match="does not declare as a canonical quantity"):
        compile_plan(world=broken)


def test_unmapped_benchmark_quantities_are_reported_rather_than_invented_as_requirements() -> None:
    """The authority does not demand full coverage, so a gap is reported, not failed."""
    world = default_world()
    declared = {item.quantity_id for item in world.benchmarks[0].quantities}

    plan = one_run()

    coverage = plan.bindings[0].quantity_coverage
    assert set(coverage.mapped) | set(coverage.unmapped) == declared
    assert not set(coverage.mapped) & set(coverage.unmapped)
    assert QuantityId("q.jump.height") in coverage.unmapped


def test_a_realization_transform_is_pinned_by_the_realization_identity_not_copied() -> None:
    """The transform's exact name and version stay inside the realization, whose digest
    already pins it; a RunSpec does not restate it."""
    plan = one_run()

    assert "quantity_mappings" not in type(plan.runs[0].spec).model_fields
    assert plan.bindings[0].realization.semantic_digest is not None
