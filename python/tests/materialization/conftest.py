"""Shared fixtures for the DB-3.3A materialization qualification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from dynamisbench.adapters.mujoco import reference_case
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition
from dynamisbench.domain.spec.sut import SUTDefinition
from dynamisbench.materialization import MaterializationStore, MaterializedInputs
from dynamisbench.planning import RunSpec
from dynamisbench.workspace import Workspace, initialize_workspace


@dataclass(frozen=True, slots=True)
class ReferenceBundle:
    """The reviewed reference definitions and their exact RunSpec."""

    workspace: Workspace
    run_spec: RunSpec
    benchmark: BenchmarkRelease
    scenario: ScenarioDefinition
    realization: RealizationDefinition
    system_under_test: SUTDefinition
    environment: EnvironmentDefinition

    def materialize(self) -> MaterializedInputs:
        from dynamisbench.materialization import materialize_inputs

        return materialize_inputs(
            self.workspace,
            self.run_spec,
            benchmark=self.benchmark,
            scenario=self.scenario,
            realization=self.realization,
            system_under_test=self.system_under_test,
            environment=self.environment,
        )


def build_reference_bundle(
    root: Path,
    *,
    platform_tag: str = "windows-x86-64",
    asset_bytes: bytes | None = None,
) -> ReferenceBundle:
    """Create a workspace with the reviewed reference asset and definitions."""
    source = root / "source"
    evidence = root / "evidence"
    workspace = initialize_workspace(source, evidence)
    asset = reference_case.realization_definition().assets[0]
    asset_path = source / asset.path
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(
        reference_case.reference.model_bytes() if asset_bytes is None else asset_bytes
    )
    return ReferenceBundle(
        workspace=workspace,
        run_spec=reference_case.run_spec(platform_tag=platform_tag),
        benchmark=reference_case.benchmark_release(),
        scenario=reference_case.scenario_definition(),
        realization=reference_case.realization_definition(),
        system_under_test=reference_case.system_under_test(),
        environment=reference_case.environment_definition(platform_tag=platform_tag),
    )


@pytest.fixture
def reference_bundle(tmp_path: Path) -> ReferenceBundle:
    return build_reference_bundle(tmp_path)


@pytest.fixture
def materialization_store(reference_bundle: ReferenceBundle) -> MaterializationStore:
    return MaterializationStore(reference_bundle.workspace)


__all__ = ["ReferenceBundle", "build_reference_bundle"]
