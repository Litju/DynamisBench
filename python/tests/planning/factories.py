"""The planning world: validated definitions a study's references resolve against.

Every object a study references exists here with the exact identifier and version the
study names, so a planning test can vary one axis at a time without restating the whole
authority each time. The builders come from :mod:`tests.domain.factories`, which is the
DB-1.2 qualification's own vocabulary: planning tests are about the compiler, not about
re-authoring the domain.

Study shapes and factor builders live in :mod:`tests.planning.factor_factories`, because
they are only meaningful once factor cases exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    BenchmarkRef,
    EnvironmentId,
    RealizationId,
    ScenarioId,
    SUTId,
)
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.studies import StudyDefinition
from dynamisbench.domain.spec.sut import SUTDefinition
from dynamisbench.planning.authority import PlanningContext
from tests.domain import factories as domain

__all__ = [
    "World",
    "benchmark_ref",
    "default_world",
    "forward_dynamics_only",
    "multi_scenario_benchmark",
    "second_benchmark",
    "second_environment",
    "second_realization",
    "second_system_under_test",
    "study",
    "study_referencing",
]


@dataclass(frozen=True)
class World:
    """The validated definitions a study's references resolve against."""

    benchmarks: tuple[BenchmarkRelease, ...]
    realizations: tuple[RealizationDefinition, ...]
    systems_under_test: tuple[SUTDefinition, ...]
    environments: tuple[EnvironmentDefinition, ...]

    def context(self) -> PlanningContext:
        return PlanningContext(
            benchmarks=self.benchmarks,
            realizations=self.realizations,
            systems_under_test=self.systems_under_test,
            environments=self.environments,
        )


def benchmark_ref(benchmark_id: str = "db.sprint20", version: str = "1.0.0") -> BenchmarkRef:
    """A reference to a benchmark by nominal identifier and version."""
    return BenchmarkRef(identifier=BenchmarkId(benchmark_id), version=version)


def multi_scenario_benchmark() -> BenchmarkRelease:
    """A release with two scenarios, so 'expands every scenario' is observable."""
    return domain.benchmark_release(
        scenarios=(
            domain.scenario_definition("sc.unloaded-cmj"),
            domain.scenario_definition("sc.loaded-cmj"),
        )
    )


def second_benchmark() -> BenchmarkRelease:
    """A second, unrelated frozen release, so pairing can be observed."""
    return domain.benchmark_release(
        benchmark_id=BenchmarkId("db.sprint20"),
        version="1.0.0",
        label="Benchmark Family 002 — countermovement sprint start",
        scenarios=(domain.scenario_definition("sc.sprint-start"),),
        references=(
            domain.reference_definition(
                "r.sprint-baseline",
                scenario_id=ScenarioId("sc.sprint-start"),
            ),
        ),
    )


def second_realization(benchmark: BenchmarkRef | None = None) -> RealizationDefinition:
    """A second realization of the same release, in another engine."""
    return domain.realization_definition(
        realization_id=RealizationId("rl.opensim.loaded-cmj"),
        version="1.0.0",
        label="OpenSim realization of the loaded countermovement jump",
        benchmark=benchmark or domain.benchmark_ref(),
        engine=domain.engine_binding("opensim", "4.5"),
        engine_configuration=(),
    )


def second_system_under_test() -> SUTDefinition:
    """A second object under test, so the expansion product has a second axis."""
    return domain.sut_definition(
        sut_id=SUTId("sut.baseline-1"),
        provenance=domain.sut_provenance(resolved_commit="a1b2c3d4e5f6"),
    )


def second_environment() -> EnvironmentDefinition:
    """A second execution environment, so a different environment is a different run."""
    return domain.environment_definition(
        environment_id=EnvironmentId("env.opensim.x86-64"),
        label="OpenSim 4.5 on CPython 3.12",
        requirements=(
            domain.environment_requirement("opensim", domain.ComponentKind.ENGINE, "4.5"),
            domain.environment_requirement("python", domain.ComponentKind.RUNTIME, "3.12"),
        ),
    )


def default_world() -> World:
    """One benchmark, one realization, one system under test, one environment."""
    return World(
        benchmarks=(domain.benchmark_release(),),
        realizations=(domain.realization_definition(),),
        systems_under_test=(domain.sut_definition(),),
        environments=(domain.environment_definition(),),
    )


def forward_dynamics_only() -> tuple[Any, ...]:
    """A capability advertisement covering only forward dynamics."""
    return (domain.capability_declaration(Capability.FORWARD_DYNAMICS),)


def study(**overrides: Any) -> StudyDefinition:
    """The DB-1.2 minimal study, with its varied factor's value left to a factor case."""
    return domain.study_definition(**overrides)


def study_referencing(*, benchmark: str = "db.lcmj20", version: str = "1.0.0") -> StudyDefinition:
    """A study whose single benchmark reference the caller controls."""
    return domain.study_definition(benchmarks=(benchmark_ref(benchmark, version),))
