"""Factor support, controlled values, and the exact assignments a RunSpec carries.

Three separate claims are checked here.

**Controlled factors resolve themselves.** A controlled factor's value is already
authority, so planning reads it and a case may not restate it.

**Varied factors need exact values in exact support.** RES-232 samples nothing, so a
case must cover every varied factor exactly once and each value must lie inside the
declared distribution's *support* — never inside a density threshold this package would
have invented.

**An assignment is self-describing.** It carries the quantity and the canonical unit
that give the number its meaning, and the target that says which object is being
perturbed. A RunSpec carrying only a number would give two different perturbations one
identity whenever they happened to share a value.
"""

from __future__ import annotations

import math

import pytest

from dynamisbench.domain.spec.identifiers import FactorId
from dynamisbench.domain.spec.studies import (
    LogNormalSpread,
    NormalSpread,
    PointValue,
    TriangularRange,
    UncertaintyFactorDefinition,
    UniformRange,
)
from dynamisbench.planning import FactorCase, FactorResolutionError, FactorValue


def varied(**overrides) -> UncertaintyFactorDefinition:
    from tests.domain import factories as domain

    return domain.uncertainty_factor(**overrides)


def with_distribution(distribution, **overrides) -> UncertaintyFactorDefinition:
    from tests.domain import factories as domain

    return domain.uncertainty_factor(distribution=distribution, **overrides)


@pytest.mark.parametrize(
    ("distribution", "accepted", "refused"),
    [
        (PointValue(value=1.25), [1.25], [1.25 - 1e-9, 1.25 + 1e-9, 0.0]),
        (
            UniformRange(lower=0.8, upper=1.2),
            [0.8, 1.0, 1.2],
            [0.7999999, 1.2000001, -1.0, 2.0],
        ),
        (
            TriangularRange(lower=0.8, upper=1.2, mode=1.0),
            [0.8, 0.9, 1.2],
            [0.79, 1.21],
        ),
        (
            NormalSpread(mean=1.0, standard_deviation=0.1),
            [1.0, -1e6, 1e6, 0.0],
            [],
        ),
        (
            LogNormalSpread(mean_log=0.0, standard_deviation_log=0.2),
            [1e-12, 0.5, 1.0, 1e12],
            [0.0, -1.0, -1e-12],
        ),
    ],
    ids=["point", "uniform", "triangular", "normal", "lognormal"],
)
def test_support_is_the_declared_support_and_nothing_else(
    distribution, accepted: list[float], refused: list[float]
) -> None:
    from dynamisbench.planning.factors import supports_value

    for value in accepted:
        assert supports_value(distribution, value), f"{value!r} must be accepted"
    for value in refused:
        assert not supports_value(distribution, value), f"{value!r} must be refused"


def test_a_normal_factor_accepts_values_far_outside_its_mean_without_truncation() -> None:
    """The support of a normal variate is the whole real line; truncating it would be a
    decision the study never made."""
    from dynamisbench.planning.factors import supports_value

    distribution = NormalSpread(mean=1.0, standard_deviation=1e-3)

    assert supports_value(distribution, -1e9)
    assert supports_value(distribution, 1e9)


def test_a_triangular_mode_is_not_treated_as_a_constraint_on_a_value() -> None:
    """The mode shapes the sampling density, not the interval the quantity may take."""
    from dynamisbench.planning.factors import supports_value

    distribution = TriangularRange(lower=0.0, upper=1.0, mode=0.9)

    assert supports_value(distribution, 0.001)
    assert not supports_value(distribution, -0.001)


def test_a_value_outside_support_names_the_factor_and_its_distribution() -> None:
    from dynamisbench.planning.factors import check_support

    factor = with_distribution(UniformRange(lower=0.8, upper=1.2))

    with pytest.raises(FactorResolutionError) as failure:
        check_support(factor, 4.0)

    message = str(failure.value)
    assert factor.factor_id in message
    assert "uniform" in message


def test_a_controlled_factor_resolves_to_exactly_its_declared_point() -> None:
    from dynamisbench.planning.factors import controlled_value
    from tests.domain import factories as domain

    factor = domain.controlled_factor()

    assert controlled_value(factor) == 9.80665


def test_controlled_factors_are_separated_from_varied_ones() -> None:
    from dynamisbench.planning.factors import controlled_factors, varied_factors
    from tests.domain import factories as domain

    factors = (domain.uncertainty_factor(), domain.controlled_factor())

    assert [item.factor_id for item in varied_factors(factors)] == [FactorId("f.contact-stiffness")]
    assert [item.factor_id for item in controlled_factors(factors)] == [FactorId("f.gravity")]


def test_a_factor_case_refuses_to_assign_one_factor_twice() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        FactorCase(
            case_id="case-a",
            values=(
                FactorValue(factor_id=FactorId("f.contact-stiffness"), value=0.9),
                FactorValue(factor_id=FactorId("f.contact-stiffness"), value=1.1),
            ),
        )


def test_a_factor_case_refuses_a_non_finite_value() -> None:
    for value in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            FactorValue(factor_id=FactorId("f.contact-stiffness"), value=value)


def test_a_case_identity_is_a_name_not_a_value() -> None:
    """Renaming a case cannot change what any run executes, so identity is only a label."""
    first = FactorCase(
        case_id="case-a",
        values=(FactorValue(factor_id=FactorId("f.contact-stiffness"), value=0.9),),
    )
    second = first.model_copy(update={"case_id": "case-b"})

    assert first.values == second.values
    assert first.case_id != second.case_id
