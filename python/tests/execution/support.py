"""Shared construction for the execution qualification suite.

The suite runs a deliberately engine-free *control* realization: its engine name is
``control``, it declares no model asset for the ordinary path, and its worker prints a
fixed message saying it produced no scientific result. That is the point. The test worker
must never be mistaken for a MuJoCo execution, so the fixture never borrows a MuJoCo
realization, environment or adapter identity merely because those names already exist.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.environment import ComponentKind, EnvironmentDefinition
from dynamisbench.domain.spec.identifiers import (
    EnvironmentId,
    EnvironmentRef,
    RealizationId,
    RealizationRef,
)
from dynamisbench.domain.spec.realizations import AssetReference, RealizationDefinition
from dynamisbench.domain.spec.studies import (
    FactorTarget,
    FactorTargetKind,
    StudyDefinition,
)
from dynamisbench.domain.spec.sut import SUTDefinition
from dynamisbench.evidence import RunOutcome, create_staging_bundle, finalize_bundle
from dynamisbench.execution import (
    PreflightedRun,
    SupervisedExecution,
    WorkerAdapterIdentity,
    WorkerCommand,
    WorkerEnvironmentManifest,
    execute_preflighted,
    preflight_run,
)
from dynamisbench.execution.contracts import staging_locator_for
from dynamisbench.planning import FactorCase, PlannedRun, PlanningContext, plan_study
from dynamisbench.planning.authority import ResolvedEnvironmentRef
from dynamisbench.planning.runspec import ExecutionFingerprint
from dynamisbench.workspace import Workspace, initialize_workspace
from tests.domain import factories as domain

WORKERS = Path(__file__).resolve().parent / "workers"
CONTROL_WORKER = WORKERS / "control_worker.py"
MISBEHAVING_WORKER = WORKERS / "misbehaving_worker.py"

CONTROL_REALIZATION_ID = RealizationId("rl.control.loaded-cmj")
CONTROL_ENVIRONMENT_ID = EnvironmentId("env.control.x86-64")
CONTROL_ENGINE = "control"
CONTROL_ENGINE_VERSION = "1.0.0"
CONTROL_ADAPTER_ID = "control.worker"


@dataclass(frozen=True, slots=True)
class ExecutionFixture:
    """Everything one preflight/execution gate needs, built from validated authority."""

    workspace: Workspace
    run: PlannedRun
    realization: RealizationDefinition
    environment: EnvironmentDefinition
    benchmark: BenchmarkRelease
    system_under_test: SUTDefinition
    study: StudyDefinition

    @property
    def required_capabilities(self) -> tuple[Capability, ...]:
        return tuple(requirement.capability for requirement in self.run.capabilities.requirements)

    @property
    def fingerprint(self) -> ExecutionFingerprint:
        return self.run.fingerprint

    @property
    def run_id(self) -> str:
        return f"run-{self.run.ordinal:04d}"


def control_realization(**overrides) -> RealizationDefinition:
    """A realization whose engine is the engine-free control case, not MuJoCo."""
    values = {
        "realization_id": CONTROL_REALIZATION_ID,
        "version": "1.0.0",
        "label": "Engine-free control realization",
        "description": "Deterministic process-contract control case; no simulator executes.",
        "benchmark": domain.benchmark_ref(),
        "engine": domain.engine_binding(CONTROL_ENGINE, CONTROL_ENGINE_VERSION),
        "capabilities": (
            domain.capability_declaration(Capability.FORWARD_DYNAMICS),
            domain.capability_declaration(Capability.STATE_SNAPSHOT),
        ),
        "quantity_mappings": (domain.quantity_mapping(),),
        "engine_configuration": (),
        "assets": (),
    }
    values.update(overrides)
    return domain.realization_definition(**values)


def control_environment(**overrides) -> EnvironmentDefinition:
    """An explicitly selected control environment, never a simulator environment."""
    values = {
        "environment_id": CONTROL_ENVIRONMENT_ID,
        "version": "1.0.0",
        "label": "Engine-free control environment",
        "description": "The isolated process contract itself; no simulator is installed.",
        "requirements": (
            domain.environment_requirement(
                CONTROL_ENGINE, ComponentKind.TOOLCHAIN, CONTROL_ENGINE_VERSION
            ),
            domain.environment_requirement("python", ComponentKind.RUNTIME, "3.12"),
        ),
    }
    values.update(overrides)
    return domain.environment_definition(**values)


def _realization_ref() -> RealizationRef:
    return RealizationRef(identifier=CONTROL_REALIZATION_ID, version="1.0.0")


def _environment_ref() -> EnvironmentRef:
    return EnvironmentRef(identifier=CONTROL_ENVIRONMENT_ID, version="1.0.0")


def _control_target(parameter: str) -> FactorTarget:
    return FactorTarget(
        kind=FactorTargetKind.REALIZATION,
        identifier=str(CONTROL_REALIZATION_ID),
        parameter=parameter,
    )


def control_study(**overrides) -> StudyDefinition:
    """One-command control study: one scenario, one seed, one replicate, no varied factor."""
    values = {
        "replicates": 1,
        "seeds": (7,),
        "realizations": (_realization_ref(),),
        "environments": (_environment_ref(),),
        "factors": (domain.controlled_factor(target=_control_target("gravity")),),
    }
    values.update(overrides)
    return domain.study_definition(**values)


def build_fixture(
    root: Path,
    *,
    realization: RealizationDefinition | None = None,
    environment: EnvironmentDefinition | None = None,
    study: StudyDefinition | None = None,
    workspace: Workspace | None = None,
) -> ExecutionFixture:
    """Build one initialized workspace and one planned control run."""
    if workspace is None:
        source = root / "source"
        evidence = root / "evidence"
        source.mkdir()
        evidence.mkdir()
        workspace = initialize_workspace(source, evidence)

    chosen_realization = realization or control_realization()
    chosen_environment = environment or control_environment()
    benchmark = domain.benchmark_release()
    system_under_test = domain.sut_definition()
    world = PlanningContext(
        benchmarks=(benchmark,),
        realizations=(chosen_realization,),
        systems_under_test=(system_under_test,),
        environments=(chosen_environment,),
    )
    chosen_study = study or control_study()
    cases: tuple[FactorCase, ...] = ()
    plan = plan_study(chosen_study, world, factor_cases=cases)
    return ExecutionFixture(
        workspace=workspace,
        run=plan.runs[0],
        realization=chosen_realization,
        environment=chosen_environment,
        benchmark=benchmark,
        system_under_test=system_under_test,
        study=chosen_study,
    )


def adapter_identity(
    capabilities: tuple[Capability, ...],
    *,
    engine: str = CONTROL_ENGINE,
    engine_version: str = CONTROL_ENGINE_VERSION,
    adapter_id: str = CONTROL_ADAPTER_ID,
    adapter_version: str = "1.0.0",
) -> WorkerAdapterIdentity:
    return WorkerAdapterIdentity(
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        engine=engine,
        engine_version=engine_version,
        capabilities=capabilities,
    )


def worker_manifest(
    fixture: ExecutionFixture,
    *,
    script: Path = CONTROL_WORKER,
    arguments: tuple[str, ...] = (),
    timeout_seconds: float = 5.0,
    max_log_bytes: int = 256 * 1024,
    capabilities: tuple[Capability, ...] | None = None,
    environment: ResolvedEnvironmentRef | None = None,
    adapter: WorkerAdapterIdentity | None = None,
    program: str | None = None,
) -> WorkerEnvironmentManifest:
    chosen_capabilities = fixture.required_capabilities if capabilities is None else capabilities
    chosen_adapter = adapter or adapter_identity(chosen_capabilities)
    chosen_environment = fixture.run.spec.environment if environment is None else environment
    command = WorkerCommand(
        program=program or sys.executable,
        arguments=("-E", "-s", str(script), *arguments),
    )
    return WorkerEnvironmentManifest(
        environment=chosen_environment,
        adapter=chosen_adapter,
        command=command,
        timeout_seconds=timeout_seconds,
        max_log_bytes=max_log_bytes,
    )


def preflight(
    fixture: ExecutionFixture,
    manifest: WorkerEnvironmentManifest | None = None,
    *,
    required_capabilities: tuple[Capability, ...] | None = None,
) -> PreflightedRun:
    chosen_manifest = manifest or worker_manifest(fixture)
    return preflight_run(
        fixture.run_id,
        fixture.run.spec,
        fixture.fingerprint,
        realization=fixture.realization,
        environment=fixture.environment,
        manifest=chosen_manifest,
        workspace=fixture.workspace,
        required_capabilities=(
            fixture.required_capabilities
            if required_capabilities is None
            else required_capabilities
        ),
    )


def execute(
    fixture: ExecutionFixture,
    manifest: WorkerEnvironmentManifest | None = None,
    *,
    required_capabilities: tuple[Capability, ...] | None = None,
    cancel_event=None,
    observer=None,
) -> SupervisedExecution:
    admission = preflight(
        fixture,
        manifest,
        required_capabilities=required_capabilities,
    )
    return execute_preflighted(admission, cancel_event=cancel_event, observer=observer)


def write_source_asset(workspace: Workspace, relative_path: str, data: bytes) -> str:
    """Write one source-root asset and return its raw-byte SHA-256."""
    target = workspace.source_root.joinpath(*relative_path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def asset_realization(
    *,
    path: str,
    sha256: str | None,
    asset_id: str = "control-model",
) -> RealizationDefinition:
    """A control realization with one declared asset, otherwise identical authority."""
    return control_realization(
        assets=(
            AssetReference(
                asset_id=asset_id,
                path=path,
                description="Control-case asset whose bytes are the preflight subject.",
                sha256=sha256,
            ),
        )
    )


def seal_control_bundle(
    workspace: Workspace,
    run_id: str,
    *,
    outcome: RunOutcome = RunOutcome.SUCCEEDED,
):
    """Seal a minimal bundle through the real evidence finalizer."""
    bundle = create_staging_bundle(workspace, run_id)
    bundle.write_payload("run.json", b'{"kind":"control-case"}')
    return finalize_bundle(bundle, outcome)


__all__ = [
    "CONTROL_ADAPTER_ID",
    "CONTROL_ENGINE",
    "CONTROL_ENGINE_VERSION",
    "CONTROL_ENVIRONMENT_ID",
    "CONTROL_REALIZATION_ID",
    "CONTROL_WORKER",
    "MISBEHAVING_WORKER",
    "ExecutionFixture",
    "adapter_identity",
    "asset_realization",
    "build_fixture",
    "control_environment",
    "control_realization",
    "control_study",
    "execute",
    "preflight",
    "seal_control_bundle",
    "staging_locator_for",
    "worker_manifest",
    "write_source_asset",
]
