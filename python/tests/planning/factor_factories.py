"""Factor cases, factor targets, and the study shapes that exercise them.

Separate from :mod:`tests.planning.factories` because a factor case is only meaningful
once factor resolution exists, and because a study that varies nothing, a study that
varies one thing, and a study that varies something per realization are three different
questions rather than three parameters of one builder.

Each target-specific builder names its factor after the authority it targets, so two
factors on the same study are two factors rather than a duplicate ``factor_id``.
"""

from __future__ import annotations

from typing import Any

from dynamisbench.domain.spec.identifiers import (
    EnvironmentId,
    EnvironmentRef,
    FactorId,
    QuantityId,
    RealizationId,
    RealizationRef,
    SUTId,
    SUTRef,
)
from dynamisbench.domain.spec.studies import (
    FactorRole,
    FactorTarget,
    FactorTargetKind,
    PointValue,
    StudyDefinition,
    UncertaintyFactorDefinition,
)
from dynamisbench.planning.factors import FactorCase, FactorValue
from tests.domain import factories as domain
from tests.planning.factories import (
    World,
    default_world,
    multi_scenario_benchmark,
    second_environment,
    second_realization,
    second_system_under_test,
)

__all__ = [
    "benchmark_quantity_factor",
    "controlled_stiffness_factor",
    "environment_factor",
    "environment_reference",
    "factor_case",
    "factor_for",
    "minimal_study",
    "multi_axis_study",
    "realization_factor",
    "realization_reference",
    "sut_factor",
    "sut_reference",
    "wide_world",
]


def factor_case(case_id: str = "case-a", *, stiffness: float = 0.9) -> FactorCase:
    """One exact factor case for the study's single varied factor ``f.contact-stiffness``."""
    return factor_for(domain.uncertainty_factor(), case_id=case_id, value=stiffness)


def factor_for(
    factor: UncertaintyFactorDefinition,
    case_id: str = "case-a",
    value: float = 0.9,
) -> FactorCase:
    """The one case that assigns exactly one factor's value."""
    return FactorCase(
        case_id=case_id,
        values=(FactorValue(factor_id=factor.factor_id, value=value),),
    )


def minimal_study(**overrides: Any) -> StudyDefinition:
    """A study with no varied factor at all, so the baseline case is exercised."""
    values: dict[str, Any] = {"factors": (domain.controlled_factor(),)}
    values.update(overrides)
    return domain.study_definition(**values)


def realization_reference(identifier: str, version: str = "1.0.0") -> RealizationRef:
    return RealizationRef(identifier=RealizationId(identifier), version=version)


def sut_reference(identifier: str, version: str = "1.0.0") -> SUTRef:
    return SUTRef(identifier=SUTId(identifier), version=version)


def environment_reference(identifier: str, version: str = "1.0.0") -> EnvironmentRef:
    return EnvironmentRef(identifier=EnvironmentId(identifier), version=version)


def _factor_for_target(target: FactorTarget, **overrides: Any) -> UncertaintyFactorDefinition:
    """A varied factor that varies exactly one declared parameter of one target."""
    return domain.uncertainty_factor(
        factor_id=FactorId(f"f.contact-stiffness.{target.identifier}"),
        target=target,
        **overrides,
    )


def realization_factor(
    realization_id: str = "rl.mujoco.loaded-cmj", **overrides: Any
) -> UncertaintyFactorDefinition:
    """A varied factor targeting one specific realization."""
    return _factor_for_target(
        FactorTarget(
            kind=FactorTargetKind.REALIZATION,
            identifier=realization_id,
            parameter="contact-stiffness",
        ),
        **overrides,
    )


def sut_factor(sut_id: str = "sut.baseline-0", **overrides: Any) -> UncertaintyFactorDefinition:
    """A varied factor targeting one specific system under test."""
    return _factor_for_target(
        FactorTarget(kind=FactorTargetKind.SUT, identifier=sut_id, parameter="contact-stiffness"),
        **overrides,
    )


def environment_factor(
    environment_id: str = "env.mujoco.x86-64", **overrides: Any
) -> UncertaintyFactorDefinition:
    """A varied factor targeting one specific execution environment."""
    return _factor_for_target(
        FactorTarget(
            kind=FactorTargetKind.ENVIRONMENT,
            identifier=environment_id,
            parameter="contact-stiffness",
        ),
        **overrides,
    )


def benchmark_quantity_factor(
    benchmark_id: str = "db.lcmj20", **overrides: Any
) -> UncertaintyFactorDefinition:
    """A varied factor that is a declared property of one frozen benchmark release."""
    return _factor_for_target(
        FactorTarget(kind=FactorTargetKind.BENCHMARK_QUANTITY, identifier=benchmark_id),
        **overrides,
    )


def controlled_stiffness_factor(**overrides: Any) -> UncertaintyFactorDefinition:
    """A controlled factor holding a realization parameter that a varied factor also moves."""
    values: dict[str, Any] = {
        "factor_id": FactorId("f.contact-damping"),
        "label": "Contact damping scale",
        "description": "Held fixed for every run so damping cannot confound stiffness.",
        "quantity": QuantityId("q.foot.vertical_force"),
        "target": FactorTarget(
            kind=FactorTargetKind.REALIZATION,
            identifier="rl.mujoco.loaded-cmj",
            parameter="contact-damping",
        ),
        "role": FactorRole.CONTROLLED,
        "distribution": PointValue(value=0.5),
    }
    values.update(overrides)
    return UncertaintyFactorDefinition(**values)


def multi_axis_study(**overrides: Any) -> StudyDefinition:
    """A study over two systems under test and two environments."""
    values: dict[str, Any] = {
        "systems_under_test": (
            sut_reference("sut.baseline-0"),
            sut_reference("sut.baseline-1"),
        ),
        "environments": (
            environment_reference("env.mujoco.x86-64"),
            environment_reference("env.opensim.x86-64"),
        ),
        "seeds": (7,),
    }
    values.update(overrides)
    return domain.study_definition(**values)


def wide_world() -> World:
    """Two scenarios, two realizations of the same release, two systems, two environments.

    The world :func:`multi_axis_study` is written against, so the expansion product is
    observable in every direction at once.
    """
    base = default_world()
    return World(
        benchmarks=(multi_scenario_benchmark(),),
        realizations=(base.realizations[0], second_realization()),
        systems_under_test=(base.systems_under_test[0], second_system_under_test()),
        environments=(base.environments[0], second_environment()),
    )
