"""Fixtures and process helpers for the real MuJoCo qualification suite.

The suite deliberately keeps the *authority* of the reference case in the test: the
physical constants, the expected model structure and the independent numerical reference
are written here rather than imported from the adapter's declarations. The adapter's own
constants are then checked against them. A test that merely echoed the adapter back to
itself would not qualify anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dynamisbench.adapters.mujoco import reference
from dynamisbench.adapters.mujoco.diagnostics import ReferenceDiagnostic
from dynamisbench.domain.spec.benchmark import BenchmarkRelease, CredibilityLevel
from dynamisbench.domain.spec.capability import (
    Capability,
    CapabilityDeclaration,
    CapabilityRequirement,
    EngineBinding,
)
from dynamisbench.domain.spec.environment import (
    ComponentKind,
    EnvironmentDefinition,
    EnvironmentRequirement,
)
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    BenchmarkRef,
    Comparator,
    EnvironmentId,
    EnvironmentRef,
    FactorId,
    MetricId,
    QuantityId,
    RealizationId,
    RealizationRef,
    ReferenceId,
    ScenarioId,
    StudyId,
    SUTId,
    SUTRef,
    VersionClause,
    VersionSpecifier,
)
from dynamisbench.domain.spec.metrics import (
    AggregationMethod,
    MetricAggregation,
    MetricDefinition,
)
from dynamisbench.domain.spec.quantities import (
    CanonicalUnit,
    Handedness,
    PhysicalDimension,
    QuantityDefinition,
    ReferenceFrame,
    SamplingKind,
    SamplingSemantics,
    SignConvention,
    TimeBasis,
    TimeBasisKind,
    UncertaintyMetadata,
)
from dynamisbench.domain.spec.realizations import (
    AssetReference,
    ConfigurationEntry,
    RealizationDefinition,
    RealizationQuantityMapping,
)
from dynamisbench.domain.spec.references import (
    ReferenceDefinition,
    ReferenceOrigin,
    VerificationCategory,
)
from dynamisbench.domain.spec.scenarios import QuantityAssignment, ScenarioDefinition
from dynamisbench.domain.spec.studies import (
    FactorRole,
    FactorTarget,
    FactorTargetKind,
    PointValue,
    StudyDefinition,
    UncertaintyFactorDefinition,
)
from dynamisbench.domain.spec.sut import (
    SUTDefinition,
    SUTInterface,
    SUTInterfaceKind,
    SUTKind,
    SUTProvenance,
)
from dynamisbench.execution import (
    PreflightedRun,
    SupervisedExecution,
    WorkerAdapterIdentity,
    WorkerCommand,
    WorkerEnvironmentManifest,
    execute_preflighted,
    preflight_run,
)
from dynamisbench.planning import PlannedRun, PlanningContext, plan_study
from dynamisbench.workspace import PersistenceClass, Workspace, initialize_workspace
from tests.execution.support import ExecutionFixture

WORKER_PROJECT = Path(__file__).resolve().parents[3] / "worker-mujoco"
PINNED_MUJOCO_VERSION = "3.17.0"
"""The version pinned by ``worker-mujoco/pyproject.toml``; checked independently here."""

MODEL_SOURCE_PATH = "models/reference/pendulum.xml"
"""The workspace-relative realization asset path used by the reference fixture."""

STUDY_ID = "study.reference.pendulum"
STUDY_VERSION = "1.0.0"
SUT_ID = "sut.reference.pendulum"
SUT_VERSION = "1.0.0"

# Independent physical specification of the reference case. These are asserted against both
# the packaged XML and the adapter's model-derived diagnostic.
MASS_KG = 1.0
COM_DISTANCE_M = 1.0
COM_INERTIA_KG_M2 = 0.001
GRAVITY_M_S2 = 9.80665
INITIAL_ANGLE_RAD = 0.5235987755982988  # 30 degrees
INITIAL_ANGULAR_VELOCITY_RAD_S = 0.0
TIMESTEP_S = 0.001
DURATION_S = 2.0
HINGE_INERTIA_KG_M2 = COM_INERTIA_KG_M2 + MASS_KG * COM_DISTANCE_M**2


def worker_python() -> Path:
    """Resolve the explicitly provisioned worker interpreter, or explain the absence."""
    configured = os.environ.get("DYNAMISBENCH_MUJOCO_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else WORKER_PROJECT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not candidate.is_file():
        message = (
            f"the isolated MuJoCo worker environment is not provisioned at {candidate}; "
            "run `uv sync --frozen --project worker-mujoco` in python/"
        )
        if os.environ.get("DYNAMISBENCH_REQUIRE_MUJOCO") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return candidate


def _qualification_environment(scratch: Path) -> dict[str, str]:
    """The minimal environment the identity command needs, with no inherited PATH.

    The production supervisor rebuilds the environment in
    :mod:`dynamisbench.execution.environment`; this helper exists only for the qualification
    interface that runs before a request exists. It follows the same rules: no PATH, no
    PYTHONPATH, no loader variables, and a private temporary directory.
    """
    values = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "TZ": "UTC",
    }
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR"):
            if name in os.environ:
                values[name] = os.environ[name]
        values["TEMP"] = str(scratch)
        values["TMP"] = str(scratch)
    else:
        values["HOME"] = str(scratch)
        values["LANG"] = "C.UTF-8"
        values["LC_ALL"] = "C.UTF-8"
        values["TMPDIR"] = str(scratch)
    return values


def run_worker_identity(scratch: Path) -> dict[str, Any]:
    """Run the worker's qualification-only identity mode in the isolated interpreter."""
    completed = subprocess.run(
        [
            str(worker_python()),
            "-I",
            "-m",
            "dynamisbench.adapters.mujoco",
            "--identity",
        ],
        cwd=scratch,
        env=_qualification_environment(scratch),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"the worker identity command failed with exit {completed.returncode}: "
            f"{completed.stderr[-2000:]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        pytest.fail(f"the worker identity command did not emit one JSON object: {error}")
    assert isinstance(payload, dict)
    return payload


def run_worker_process(
    arguments: tuple[str, ...],
    stdin: bytes,
    scratch: Path,
) -> subprocess.CompletedProcess[bytes]:
    """Run the fixed worker executable with an explicit argument vector and stdin."""
    return subprocess.run(
        [
            str(worker_python()),
            "-I",
            "-m",
            "dynamisbench.adapters.mujoco",
            *arguments,
        ],
        input=stdin,
        cwd=scratch,
        env=_qualification_environment(scratch),
        capture_output=True,
        timeout=180,
        check=False,
    )


def _run_worker_module(module: str, arguments: tuple[str, ...], scratch: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(worker_python()), "-I", "-m", module, *arguments],
        cwd=scratch,
        env=_qualification_environment(scratch),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"{module} exited {completed.returncode}: {completed.stderr[-4000:]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        pytest.fail(f"{module} did not emit one JSON object: {error}")
    assert isinstance(payload, dict)
    return payload


def run_qualification(scratch: Path) -> dict[str, Any]:
    """Run the fixed qualification observation in the isolated worker environment."""
    return _run_worker_module(
        "dynamisbench.adapters.mujoco.qualification",
        (),
        scratch,
    )


def run_nonfinite_probe(scratch: Path) -> dict[str, Any]:
    """Run the real-MuJoCo non-finite state guard probe."""
    return _run_worker_module(
        "dynamisbench.adapters.mujoco.qualification",
        ("--nonfinite-check",),
        scratch,
    )


def adapter_identity(identity: dict[str, Any]) -> WorkerAdapterIdentity:
    """Build the protocol adapter identity from the installed worker's own report."""
    return WorkerAdapterIdentity(
        adapter_id=identity["adapter_id"],
        adapter_version=identity["adapter_version"],
        engine=identity["engine"],
        engine_version=identity["engine_version"],
        capabilities=tuple(Capability(value) for value in identity["capabilities"]),
        implementation_digest=identity["implementation_digest"],
    )


def _exact(version: str) -> VersionSpecifier:
    return VersionSpecifier(clauses=(VersionClause(comparator=Comparator.EXACT, version=version),))


def environment_definition(identity: dict[str, Any]) -> EnvironmentDefinition:
    """The platform-specific environment identity that the worker must match."""
    tag = reference.platform_tag()
    return EnvironmentDefinition(
        environment_id=EnvironmentId(f"env.mujoco.reference.{tag}"),
        version=reference.ENVIRONMENT_VERSION,
        label=f"MuJoCo {identity['engine_version']} reference environment on {tag}",
        description=(
            "Isolated Python/MuJoCo execution environment for the RES-550 fixed "
            f"reference pendulum on {tag}."
        ),
        requirements=(
            EnvironmentRequirement(
                component="mujoco",
                kind=ComponentKind.ENGINE,
                specifier=_exact(identity["engine_version"]),
                purpose="The native engine version the adapter actual execution checks.",
            ),
            EnvironmentRequirement(
                component="python",
                kind=ComponentKind.RUNTIME,
                specifier=_exact(identity["python_version"]),
                purpose="The exact CPython patch release of the isolated worker venv.",
            ),
        ),
    )


def _world_frame() -> ReferenceFrame:
    return ReferenceFrame(
        frame_id="world",
        parent="global",
        axis_labels=("x", "y", "z"),
        handedness=Handedness.RIGHT,
        description="Right-handed world frame with gravity along -z.",
    )


def _hinge_frame() -> ReferenceFrame:
    return ReferenceFrame(
        frame_id="hinge",
        parent="world",
        axis_labels=("y",),
        description="The single hinge axis, positive by the right-hand rule about +y.",
    )


def _quantity(
    quantity_id: str,
    *,
    label: str,
    description: str,
    dimension: PhysicalDimension,
    unit: str,
    sampling: SamplingSemantics,
    uncertainty: str,
    frame: ReferenceFrame,
) -> QuantityDefinition:
    return QuantityDefinition(
        quantity_id=QuantityId(quantity_id),
        version="1.0.0",
        label=label,
        description=description,
        dimension=dimension,
        unit=CanonicalUnit(expression=unit),
        frame=frame,
        sign_convention=SignConvention(
            positive_direction="positive rotation about +y by the right-hand rule"
        ),
        time_basis=TimeBasis(kind=TimeBasisKind.RELATIVE_TO_START),
        sampling=sampling,
        uncertainty=UncertaintyMetadata(characterization=uncertainty),
    )


def benchmark_release() -> BenchmarkRelease:
    """The frozen, synthetic reference release used only to qualify the adapter."""
    angle = _quantity(
        "q.pendulum.hinge-angle",
        label="Hinge angle",
        description="Planar pendulum hinge angle measured from the downward vertical.",
        dimension=PhysicalDimension(),
        unit="1",
        sampling=SamplingSemantics(kind=SamplingKind.UNIFORM, rate_hz=1000.0),
        uncertainty="numerical integration error only; no measurement uncertainty",
        frame=_hinge_frame(),
    )
    angular_velocity = _quantity(
        "q.pendulum.hinge-angular-velocity",
        label="Hinge angular velocity",
        description="Time derivative of the planar pendulum hinge angle.",
        dimension=PhysicalDimension(time=-1),
        unit="s^-1",
        sampling=SamplingSemantics(kind=SamplingKind.UNIFORM, rate_hz=1000.0),
        uncertainty="numerical integration error only; no measurement uncertainty",
        frame=_hinge_frame(),
    )
    gravity = _quantity(
        "q.pendulum.gravity",
        label="Gravitational acceleration",
        description="Uniform downward gravitational acceleration in the reference case.",
        dimension=PhysicalDimension(length=1, time=-2),
        unit="m/s^2",
        sampling=SamplingSemantics(kind=SamplingKind.SINGLE_SAMPLE),
        uncertainty="declared standard gravity; not an empirical estimate",
        frame=_world_frame(),
    )
    metric = MetricDefinition(
        metric_id=MetricId("m.reference.hinge-angle.mean"),
        version="1.0.0",
        label="Mean hinge angle",
        description=(
            "A placeholder benchmark statistic over the synthetic reference run. No "
            "assessment is computed in RES-550."
        ),
        quantity=QuantityId("q.pendulum.hinge-angle"),
        aggregation=MetricAggregation(
            method=AggregationMethod.MEAN, window_start_s=0.0, window_end_s=DURATION_S
        ),
    )
    scenario = ScenarioDefinition(
        scenario_id=ScenarioId(reference.SCENARIO_ID),
        version=reference.SCENARIO_VERSION,
        label="Reference pendulum, 30 degrees, zero velocity",
        description=(
            "One unactuated planar pendulum released from 30 degrees with zero angular "
            "velocity for two seconds."
        ),
        duration_s=DURATION_S,
        initial_conditions=(
            QuantityAssignment(
                quantity=QuantityId("q.pendulum.hinge-angle"),
                value=INITIAL_ANGLE_RAD,
                unit=CanonicalUnit(expression="1"),
            ),
            QuantityAssignment(
                quantity=QuantityId("q.pendulum.hinge-angular-velocity"),
                value=INITIAL_ANGULAR_VELOCITY_RAD_S,
                unit=CanonicalUnit(expression="s^-1"),
            ),
        ),
        required_capabilities=(
            CapabilityRequirement(
                capability=Capability.FORWARD_DYNAMICS,
                essential=True,
                rationale="The reference case is an unactuated forward-dynamics rollout.",
            ),
        ),
    )
    reference_case = ReferenceDefinition(
        reference_id=ReferenceId("r.reference.pendulum"),
        version="1.0.0",
        label="Independent nonlinear pendulum reference",
        description=(
            "Synthetic solution-verification reference for the planar pendulum equation, "
            "not an experimental or human-movement validation case."
        ),
        scenario_id=ScenarioId(reference.SCENARIO_ID),
        category=VerificationCategory.SOLUTION_VERIFICATION,
        origin=ReferenceOrigin.SYNTHETIC,
        license="CC0-1.0",
    )
    return BenchmarkRelease(
        benchmark_id=BenchmarkId(reference.BENCHMARK_ID),
        version=reference.BENCHMARK_VERSION,
        label="Synthetic planar pendulum adapter reference",
        description=(
            "A minimal, legally distributable physical reference case for qualifying a real "
            "MuJoCo forward-dynamics adapter."
        ),
        intended_use=(
            "Numerical and process-contract verification of the first real DynamisBench "
            "MuJoCo adapter on a low-dimensional rigid-body system."
        ),
        intended_non_use=(
            "Not a human-movement benchmark, not a DB-LCMJ20 realization, and not evidence "
            "of biomechanical validity."
        ),
        conceptual_model=(
            "One rigid body on a frictionless hinge with a point mass at 1 m, uniform "
            "standard gravity, no contacts and no actuation."
        ),
        claim_ceiling=(
            "Agreement with an independent nonlinear pendulum solution within predeclared "
            "numerical tolerances on the qualified environment; no scientific validation."
        ),
        quantities=(angle, angular_velocity, gravity),
        scenarios=(scenario,),
        metrics=(metric,),
        references=(reference_case,),
        credibility_hierarchy=(CredibilityLevel.UNIT_PROBLEM,),
        assumptions=(
            "Rigid body, ideal hinge, uniform gravity, no damping, no contacts, no "
            "actuation, double precision, deterministic execution.",
        ),
        applicability_domain=(
            "Single planar pendulum, zero control, 30 degree initial angle, 2 s horizon.",
        ),
        known_discrepancies=(
            "The reference is synthetic; it is not a physical experiment or a human model.",
        ),
        uncertainty_expectations=(
            "No stochastic process; only numerical integration error is expected.",
        ),
    )


def realization_definition(
    *,
    asset_sha256: str,
    engine_version: str,
    asset_path: str = MODEL_SOURCE_PATH,
) -> RealizationDefinition:
    """The narrow forward-dynamics realization that maps to the fixed adapter."""
    return RealizationDefinition(
        realization_id=RealizationId(reference.REALIZATION_ID),
        version=reference.REALIZATION_VERSION,
        label="MuJoCo fixed reference-pendulum adapter",
        description=(
            "The first real MuJoCo realization: one self-contained pendulum model and one "
            "zero-control forward-dynamics rollout."
        ),
        benchmark=BenchmarkRef(
            identifier=BenchmarkId(reference.BENCHMARK_ID),
            version=reference.BENCHMARK_VERSION,
        ),
        engine=EngineBinding(engine="mujoco", specifier=_exact(engine_version)),
        capabilities=(
            CapabilityDeclaration(
                capability=Capability.FORWARD_DYNAMICS,
                summary="real MuJoCo forward dynamics for the fixed planar pendulum",
                limitations=(
                    "One fixed model; no arbitrary model loading, controllers, contacts, "
                    "interactive stepping, inverse dynamics or optimization.",
                ),
            ),
        ),
        quantity_mappings=(
            RealizationQuantityMapping(
                quantity=QuantityId("q.pendulum.hinge-angle"),
                source="hinge-angle",
                notes=("The adapter's native diagnostic reports the hinge angle in radians.",),
            ),
            RealizationQuantityMapping(
                quantity=QuantityId("q.pendulum.hinge-angular-velocity"),
                source="hinge-angular-velocity",
                notes=("The adapter's native diagnostic reports angular velocity in rad/s.",),
            ),
        ),
        engine_configuration=(
            ConfigurationEntry(name="timestep", value=str(TIMESTEP_S)),
            ConfigurationEntry(name="integrator", value=reference.INTEGRATOR),
            ConfigurationEntry(name="solver", value=reference.SOLVER),
            ConfigurationEntry(name="iterations", value=str(reference.ITERATIONS)),
            ConfigurationEntry(name="tolerance", value="1e-12"),
            ConfigurationEntry(name="duration", value=str(DURATION_S)),
            ConfigurationEntry(name="initial-angle", value=str(INITIAL_ANGLE_RAD)),
            ConfigurationEntry(
                name="initial-angular-velocity", value=str(INITIAL_ANGULAR_VELOCITY_RAD_S)
            ),
            ConfigurationEntry(name="gravity", value=str(GRAVITY_M_S2)),
            ConfigurationEntry(name="model", value="reference-pendulum"),
            ConfigurationEntry(name="precision", value="float64"),
            ConfigurationEntry(name="seed-policy", value="no-stochastic-process"),
        ),
        assets=(
            AssetReference(
                asset_id="reference-model",
                path=asset_path,
                description="Self-contained MJCF XML of the reviewed reference pendulum.",
                sha256=asset_sha256,
            ),
        ),
        known_discrepancies=(
            "Synthetic unit-problem reference; it does not establish human-movement validity.",
        ),
    )


def system_under_test(*, asset_sha256: str) -> SUTDefinition:
    """The model itself is the object under test; there is no controller SUT."""
    return SUTDefinition(
        sut_id=SUTId(SUT_ID),
        version=SUT_VERSION,
        label="Fixed planar pendulum model",
        description="The unactuated reference model, with no controller or external SUT.",
        kind=SUTKind.MODEL,
        interface=SUTInterface(kind=SUTInterfaceKind.IN_PROCESS),
        provenance=SUTProvenance(build_digest=asset_sha256),
        required_capabilities=(
            CapabilityRequirement(
                capability=Capability.FORWARD_DYNAMICS,
                essential=True,
                rationale="The model is exercised by forward integration only.",
            ),
        ),
    )


def study_definition(environment_id: EnvironmentId) -> StudyDefinition:
    """One replicate, one seed, one controlled gravity factor, one outcome."""
    gravity = UncertaintyFactorDefinition(
        factor_id=FactorId("f.reference.gravity"),
        label="Gravitational acceleration",
        description="Standard gravity held fixed for the synthetic reference case.",
        role=FactorRole.CONTROLLED,
        quantity=QuantityId("q.pendulum.gravity"),
        target=FactorTarget(
            kind=FactorTargetKind.REALIZATION,
            identifier=reference.REALIZATION_ID,
            parameter="gravity",
        ),
        distribution=PointValue(value=GRAVITY_M_S2),
    )
    return StudyDefinition(
        study_id=StudyId(STUDY_ID),
        version=STUDY_VERSION,
        label="RES-550 MuJoCo reference qualification",
        description="A one-run numerical qualification of the fixed MuJoCo reference adapter.",
        research_question=(
            "Does the fixed MuJoCo run reproduce an independent nonlinear pendulum solution "
            "within declared numerical tolerances?"
        ),
        analysis_plan=(
            "Compare the native trajectory and energy with an independent solve_ivp "
            "reference and a finite-amplitude period; do not compute a scientific assessment."
        ),
        replicates=1,
        benchmarks=(
            BenchmarkRef(
                identifier=BenchmarkId(reference.BENCHMARK_ID),
                version=reference.BENCHMARK_VERSION,
            ),
        ),
        realizations=(
            RealizationRef(
                identifier=RealizationId(reference.REALIZATION_ID),
                version=reference.REALIZATION_VERSION,
            ),
        ),
        systems_under_test=(SUTRef(identifier=SUTId(SUT_ID), version=SUT_VERSION),),
        environments=(
            EnvironmentRef(
                identifier=environment_id,
                version=reference.ENVIRONMENT_VERSION,
            ),
        ),
        required_capabilities=(
            CapabilityRequirement(
                capability=Capability.FORWARD_DYNAMICS,
                essential=True,
                rationale="The study evaluates a forward-dynamics rollout.",
            ),
        ),
        factors=(gravity,),
        outcomes=(reference.OUTCOME,),
        seeds=(0,),
    )


def build_mujoco_fixture(
    root: Path,
    *,
    identity: dict[str, Any],
) -> ExecutionFixture:
    """Build one initialized workspace and one planned real-MuJoCo reference run."""
    source = root / "source"
    evidence = root / "evidence"
    source.mkdir()
    evidence.mkdir()
    workspace = initialize_workspace(source, evidence)

    model_bytes = reference.model_bytes()
    model_path = workspace.source_root.joinpath(*MODEL_SOURCE_PATH.split("/"))
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(model_bytes)
    asset_sha256 = hashlib.sha256(model_bytes).hexdigest()
    assert asset_sha256 == reference.MODEL_SHA256

    benchmark = benchmark_release()
    environment = environment_definition(identity)
    realization = realization_definition(
        asset_sha256=asset_sha256,
        engine_version=identity["engine_version"],
    )
    sut = system_under_test(asset_sha256=asset_sha256)
    study = study_definition(environment.environment_id)
    context = PlanningContext(
        benchmarks=(benchmark,),
        realizations=(realization,),
        systems_under_test=(sut,),
        environments=(environment,),
    )
    plan = plan_study(study, context)
    planned: PlannedRun = plan.runs[0]
    return ExecutionFixture(
        workspace=workspace,
        run=planned,
        realization=realization,
        environment=environment,
        benchmark=benchmark,
        system_under_test=sut,
        study=study,
    )


def worker_manifest(
    fixture: ExecutionFixture,
    identity: dict[str, Any],
    *,
    adapter: WorkerAdapterIdentity | None = None,
    timeout_seconds: float = 120.0,
) -> WorkerEnvironmentManifest:
    """The fixed worker launch vector for the selected environment."""
    return WorkerEnvironmentManifest(
        environment=fixture.run.spec.environment,
        adapter=adapter or adapter_identity(identity),
        command=WorkerCommand(
            program=str(worker_python()),
            arguments=("-I", "-m", "dynamisbench.adapters.mujoco"),
        ),
        timeout_seconds=timeout_seconds,
    )


def preflight_fixture(
    fixture: ExecutionFixture,
    identity: dict[str, Any],
    *,
    run_id: str | None = None,
    adapter: WorkerAdapterIdentity | None = None,
    realization: RealizationDefinition | None = None,
    environment: EnvironmentDefinition | None = None,
) -> PreflightedRun:
    """Preflight one reference run, optionally with a substituted identity."""
    return preflight_run(
        run_id or fixture.run_id,
        fixture.run,
        realization=realization or fixture.realization,
        environment=environment or fixture.environment,
        manifest=worker_manifest(fixture, identity, adapter=adapter),
        workspace=fixture.workspace,
    )


def execute_fixture(
    fixture: ExecutionFixture,
    identity: dict[str, Any],
    *,
    run_id: str | None = None,
    adapter: WorkerAdapterIdentity | None = None,
    realization: RealizationDefinition | None = None,
) -> SupervisedExecution:
    """Preflight and execute one reference run through the real supervisor."""
    admission = preflight_fixture(
        fixture,
        identity,
        run_id=run_id,
        adapter=adapter,
        realization=realization,
    )
    return execute_preflighted(admission)


def staging_root(fixture: ExecutionFixture, run_id: str) -> Path:
    return fixture.workspace.location(PersistenceClass.STAGING).path / run_id


def sealed_root(fixture: ExecutionFixture, run_id: str) -> Path:
    return fixture.workspace.location(PersistenceClass.SEALED_EVIDENCE).path / run_id


def native_diagnostic(workspace: Workspace, run_id: str) -> ReferenceDiagnostic:
    """Read and validate the adapter's bounded stderr diagnostic from staging.

    This is the adapter diagnostic, not sealed native evidence. The test reads it through
    the workspace resolver and the same diagnostic model the adapter wrote.
    """
    path = workspace.resolve(PersistenceClass.STAGING, f"{run_id}/logs/worker.stderr.txt")
    text = path.read_text(encoding="utf-8", errors="replace")
    prefix = "DYNAMISBENCH_MUJOCO_DIAGNOSTIC "
    lines = [line for line in text.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        pytest.fail(
            f"expected exactly one adapter diagnostic line in {path.name}, found {len(lines)}; "
            f"stderr was:\n{text[-4000:]}"
        )
    payload = lines[0][len(prefix) :]
    return ReferenceDiagnostic.model_validate_json(payload)


def expected_platform_tag() -> str:
    """The platform tag this host must report, or a skip on an unqualified host."""
    try:
        return reference.platform_tag()
    except reference.ReferencePlatformError as error:
        pytest.skip(str(error))


def host_python_version() -> str:
    """The worker environment's declared CPython patch from the repository pin."""
    return (Path(__file__).resolve().parents[3] / ".python-version").read_text().strip()


def assert_identity_is_the_reviewed_environment(identity: dict[str, Any]) -> None:
    """Independent checks on the installed worker's reported provenance."""
    expected_platform_tag()
    assert identity["engine"] == "mujoco"
    assert identity["engine_version"] == PINNED_MUJOCO_VERSION
    assert identity["python_version"] == host_python_version()
    assert identity["platform"] == expected_platform_tag()
    assert identity["model_sha256"] == reference.MODEL_SHA256
    assert tuple(identity["capabilities"]) == ("forward_dynamics",)
    assert identity["adapter_id"] == "dynamisbench.mujoco.reference"
    assert identity["adapter_version"] == "0.1.0"
    assert len(identity["implementation_digest"]) == 64
    assert all(len(entry["sha256"]) == 64 for entry in identity["source_manifest"])


def platform_name() -> str:
    """A human-readable platform label for diagnostics."""
    return f"{platform.system()} {platform.machine()}"
