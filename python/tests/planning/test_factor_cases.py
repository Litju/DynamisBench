"""Factor-case coverage and declared support.

Controlled factors resolve from the study and cannot be restated. Varied factors need
exact values in exact support; RES-232 samples nothing, so a value has to arrive in a
case. Probability density is never an acceptance rule.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.identifiers import FactorId
from dynamisbench.domain.spec.studies import (
    FactorRole,
    NormalSpread,
    PointValue,
    UniformRange,
)
from dynamisbench.planning import (
    BASELINE_CASE_ID,
    FactorCase,
    FactorResolutionError,
    FactorValue,
)
from tests.domain import factories as domain
from tests.planning.compiler import (
    compile_plan,
    one_run,
)
from tests.planning.factor_factories import (
    controlled_stiffness_factor,
    factor_case,
    minimal_study,
)
from tests.planning.factories import (
    study as study_definition,
)


def test_a_study_with_no_varied_factors_is_expanded_with_one_baseline_case() -> None:
    study = minimal_study(replicates=1, seeds=(7,))

    plan = compile_plan(study, factor_cases=())

    assert plan.factor_cases == (FactorCase(case_id=BASELINE_CASE_ID),)
    assert len(plan.runs) == 1


def test_a_controlled_factor_resolves_without_being_supplied() -> None:
    study = minimal_study(replicates=1, seeds=(7,))
    controlled = study.factors[0]

    plan = compile_plan(study, factor_cases=())

    resolved = plan.runs[0].spec.factors[0]
    assert resolved.factor_id == controlled.factor_id
    assert resolved.value == 9.80665


def test_a_controlled_factor_cannot_be_overridden_by_a_factor_case() -> None:
    controlled = domain.controlled_factor()
    overriding = FactorCase(
        case_id="case-a",
        values=(
            FactorValue(factor_id=controlled.factor_id, value=1.0),
            FactorValue(factor_id=FactorId("f.contact-stiffness"), value=0.9),
        ),
    )

    with pytest.raises(FactorResolutionError, match="may not override it"):
        compile_plan(study_definition(replicates=1, seeds=(7,)), factor_cases=(overriding,))


def test_a_study_with_varied_factors_and_no_factor_case_fails() -> None:
    """Planning samples nothing, so it cannot invent a value."""
    with pytest.raises(FactorResolutionError, match="no factor cases were supplied"):
        compile_plan(study_definition(), factor_cases=())


def test_a_case_that_omits_a_varied_factor_fails() -> None:
    study = study_definition(
        factors=(
            domain.uncertainty_factor(),
            domain.uncertainty_factor(
                factor_id="f.damping", distribution=UniformRange(lower=0.1, upper=0.2)
            ),
        ),
        replicates=1,
        seeds=(7,),
    )
    partial = FactorCase(
        case_id="case-a",
        values=(FactorValue(factor_id=FactorId("f.contact-stiffness"), value=0.9),),
    )

    with pytest.raises(FactorResolutionError, match="does not assign varied factor"):
        compile_plan(study, factor_cases=(partial,))


def test_a_case_naming_a_factor_the_study_does_not_declare_fails() -> None:
    extra = FactorCase(
        case_id="case-a",
        values=(
            FactorValue(factor_id=FactorId("f.contact-stiffness"), value=0.9),
            FactorValue(factor_id=FactorId("f.undeclared"), value=1.0),
        ),
    )

    with pytest.raises(FactorResolutionError, match="does not declare"):
        one_run(factor_cases=(extra,))


@pytest.mark.parametrize(
    ("distribution", "value"),
    [
        (UniformRange(lower=0.8, upper=1.2), 1.9),
        (UniformRange(lower=0.8, upper=1.2), 0.1),
    ],
    ids=["above", "below"],
)
def test_a_uniform_factor_value_outside_its_bounds_fails_planning(distribution, value) -> None:
    study = study_definition(factors=(domain.uncertainty_factor(distribution=distribution),))

    with pytest.raises(FactorResolutionError, match="outside the support"):
        compile_plan(
            study,
            factor_cases=(factor_case("case-a", stiffness=value),),
        )


@pytest.mark.parametrize("value", [-0.1, 0.0, -3.0], ids=["negative", "zero", "far-negative"])
def test_a_lognormal_factor_refuses_a_non_positive_value(value) -> None:
    from dynamisbench.domain.spec.studies import LogNormalSpread

    study = study_definition(
        factors=(
            domain.uncertainty_factor(
                distribution=LogNormalSpread(mean_log=0.0, standard_deviation_log=0.2)
            ),
        )
    )

    with pytest.raises(FactorResolutionError, match="outside the support"):
        compile_plan(study, factor_cases=(factor_case("case-a", stiffness=value),))


def test_a_triangular_factor_value_outside_its_bounds_fails_planning() -> None:
    from dynamisbench.domain.spec.studies import TriangularRange

    study = study_definition(
        factors=(
            domain.uncertainty_factor(distribution=TriangularRange(lower=0.8, upper=1.2, mode=1.0)),
        )
    )

    with pytest.raises(FactorResolutionError, match="outside the support"):
        compile_plan(study, factor_cases=(factor_case("case-a", stiffness=1.3),))


def test_a_normal_factor_accepts_a_far_outside_value_without_truncation() -> None:
    study = study_definition(
        factors=(
            domain.uncertainty_factor(distribution=NormalSpread(mean=1.0, standard_deviation=0.01)),
        ),
        replicates=1,
        seeds=(7,),
    )

    plan = compile_plan(study, factor_cases=(factor_case("case-a", stiffness=-40.0),))

    assert plan.runs[0].spec.factors[0].value == -40.0


def test_a_factor_case_for_a_study_with_no_varied_factors_fails() -> None:
    with pytest.raises(FactorResolutionError, match="varies no factor"):
        compile_plan(minimal_study(replicates=1, seeds=(7,)))


def test_a_varied_factor_holding_a_point_value_must_be_given_exactly_that_value() -> None:
    """A degenerate varied factor is still a factor: its support is its declared point."""
    study = study_definition(
        factors=(domain.uncertainty_factor(distribution=PointValue(value=1.0)),),
        replicates=1,
        seeds=(7,),
    )

    with pytest.raises(FactorResolutionError, match="outside the support"):
        compile_plan(study, factor_cases=(factor_case("case-a", stiffness=1.5),))

    accepted = compile_plan(study, factor_cases=(factor_case("case-a", stiffness=1.0),))
    assert accepted.runs[0].spec.factors[0].value == 1.0


def test_a_study_may_declare_only_controlled_factors_and_still_resolve_them() -> None:
    study = study_definition(
        factors=(domain.controlled_factor(), controlled_stiffness_factor()),
        replicates=1,
        seeds=(7,),
    )

    plan = compile_plan(study, factor_cases=())

    assert {item.factor_id for item in plan.runs[0].spec.factors} == {
        "f.gravity",
        "f.contact-damping",
    }
    assert all(item.role is FactorRole.CONTROLLED for item in study.factors)
