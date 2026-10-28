"""The canonical RES-550 reference case, as validated domain definitions.

The fixed-reference MuJoCo adapter is compiled for exactly one scientific experiment. That
experiment is not only the model bytes and the integrator settings in
:mod:`dynamisbench.adapters.mujoco.reference`; it is also the benchmark release, scenario,
realization, system under test and execution environment whose content the accepted
``RunSpec`` resolved. This module is the reviewed, engine-independent source of those
definitions.

Why the definitions live in production code
-------------------------------------------

The worker must compare a request against authority that is independent of the request.
Pinning only an identifier and a version is not enough, because the same identifier and
version can name a different definition. The reviewed semantic digest of each definition is
therefore pinned in :mod:`dynamisbench.adapters.mujoco.reference`, and this module is the
canonical source those pins are generated from. A test recomputes every digest from these
definitions and compares it with the pin, and a tool
(``python/tools/mujoco_reference_authority.py``) reproduces the same values outside the test
suite. Nothing here imports MuJoCo, reads the filesystem, or depends on a request.

The adapter never derives an expected digest from a request. It compares the request's
resolved references with these constants, so a definition that keeps ``benchmark_id``,
``version`` and every other visible name but changes its meaning is refused.
"""

from __future__ import annotations

from typing import Final

from dynamisbench.adapters.mujoco import reference
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
    FactorId,
    MetricId,
    QuantityId,
    RealizationId,
    ReferenceId,
    ScenarioId,
    SUTId,
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
from dynamisbench.domain.spec.studies import FactorTarget, FactorTargetKind
from dynamisbench.domain.spec.sut import (
    SUTDefinition,
    SUTInterface,
    SUTInterfaceKind,
    SUTKind,
    SUTProvenance,
)
from dynamisbench.identity import semantic_sha256
from dynamisbench.planning.authority import (
    ResolvedBenchmarkRef,
    ResolvedEnvironmentRef,
    ResolvedRealizationRef,
    ResolvedScenarioRef,
    ResolvedSUTRef,
)
from dynamisbench.planning.factors import FactorAssignment
from dynamisbench.planning.runspec import RunSpec

__all__ = [
    "GRAVITY_FACTOR_ID",
    "REFERENCE_METRIC_ID",
    "REFERENCE_REFERENCE_ID",
    "benchmark_release",
    "environment_definition",
    "realization_definition",
    "run_spec",
    "scenario_definition",
    "system_under_test",
]

GRAVITY_FACTOR_ID: Final = FactorId("f.reference.gravity")
REFERENCE_METRIC_ID: Final = MetricId("m.reference.hinge-angle.mean")
REFERENCE_REFERENCE_ID: Final = ReferenceId("r.reference.pendulum")


def _exact(version: str) -> VersionSpecifier:
    """One exact-version constraint; the only specifier the reference case declares."""
    return VersionSpecifier(clauses=(VersionClause(comparator=Comparator.EXACT, version=version),))


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


def scenario_definition() -> ScenarioDefinition:
    """The one scenario of the reference release: 30 degrees, zero velocity, 2 s."""
    return ScenarioDefinition(
        scenario_id=ScenarioId(reference.SCENARIO_ID),
        version=reference.SCENARIO_VERSION,
        label="Reference pendulum, 30 degrees, zero velocity",
        description=(
            "One unactuated planar pendulum released from 30 degrees with zero angular "
            "velocity for two seconds."
        ),
        duration_s=reference.DURATION_S,
        initial_conditions=(
            QuantityAssignment(
                quantity=QuantityId("q.pendulum.hinge-angle"),
                value=reference.INITIAL_ANGLE_RAD,
                unit=CanonicalUnit(expression="1"),
            ),
            QuantityAssignment(
                quantity=QuantityId("q.pendulum.hinge-angular-velocity"),
                value=reference.INITIAL_ANGULAR_VELOCITY_RAD_S,
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


def benchmark_release() -> BenchmarkRelease:
    """The frozen synthetic unit-problem release the adapter is compiled against."""
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
        metric_id=REFERENCE_METRIC_ID,
        version="1.0.0",
        label="Mean hinge angle",
        description=(
            "A placeholder benchmark statistic over the synthetic reference run. No "
            "assessment is computed in RES-550."
        ),
        quantity=QuantityId("q.pendulum.hinge-angle"),
        aggregation=MetricAggregation(
            method=AggregationMethod.MEAN,
            window_start_s=0.0,
            window_end_s=reference.DURATION_S,
        ),
    )
    reference_case = ReferenceDefinition(
        reference_id=REFERENCE_REFERENCE_ID,
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
        scenarios=(scenario_definition(),),
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


def environment_definition(
    *,
    platform_tag: str,
    engine_version: str = reference.ENGINE_VERSION,
    python_version: str = reference.PYTHON_VERSION,
) -> EnvironmentDefinition:
    """The platform-specific scientific environment the reference adapter is compiled for.

    The environment identifier names the platform because Windows and Linux are distinct
    qualification targets and are never one environment (ADR-023). Its semantic digest is
    therefore platform-specific and is pinned per platform.
    """
    return EnvironmentDefinition(
        environment_id=EnvironmentId(f"env.mujoco.reference.{platform_tag}"),
        version=reference.ENVIRONMENT_VERSION,
        label=f"MuJoCo {engine_version} reference environment on {platform_tag}",
        description=(
            "Isolated Python/MuJoCo execution environment for the RES-550 fixed "
            f"reference pendulum on {platform_tag}."
        ),
        requirements=(
            EnvironmentRequirement(
                component="mujoco",
                kind=ComponentKind.ENGINE,
                specifier=_exact(engine_version),
                purpose="The native engine version the adapter actual execution checks.",
            ),
            EnvironmentRequirement(
                component="python",
                kind=ComponentKind.RUNTIME,
                specifier=_exact(python_version),
                purpose="The exact CPython patch release of the isolated worker venv.",
            ),
        ),
    )


def realization_definition(
    *,
    asset_sha256: str = reference.MODEL_SHA256,
    asset_path: str = reference.MODEL_SOURCE_PATH,
    engine_version: str = reference.ENGINE_VERSION,
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
            ConfigurationEntry(name="timestep", value=str(reference.TIMESTEP_S)),
            ConfigurationEntry(name="integrator", value=reference.INTEGRATOR),
            ConfigurationEntry(name="solver", value=reference.SOLVER),
            ConfigurationEntry(name="iterations", value=str(reference.ITERATIONS)),
            ConfigurationEntry(name="tolerance", value="1e-12"),
            ConfigurationEntry(name="duration", value=str(reference.DURATION_S)),
            ConfigurationEntry(name="initial-angle", value=str(reference.INITIAL_ANGLE_RAD)),
            ConfigurationEntry(
                name="initial-angular-velocity",
                value=str(reference.INITIAL_ANGULAR_VELOCITY_RAD_S),
            ),
            ConfigurationEntry(name="gravity", value=str(reference.GRAVITY_M_S2)),
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


def system_under_test(*, asset_sha256: str = reference.MODEL_SHA256) -> SUTDefinition:
    """The model itself is the object under test; there is no controller SUT."""
    return SUTDefinition(
        sut_id=SUTId(reference.SUT_ID),
        version=reference.SUT_VERSION,
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


def run_spec(*, platform_tag: str) -> RunSpec:
    """The exact canonical ``RunSpec`` of the reference experiment on one platform.

    Every reference is stated as the pinned identity from
    :mod:`dynamisbench.adapters.mujoco.reference`, never as a digest derived from these
    definitions. That keeps the execution fingerprint independently recomputable while
    leaving the worker's admission comparison authoritative over the pins rather than over a
    request. ``reference_authority_matches_definitions`` in the qualification suite proves
    that the pins and these definitions agree.
    """
    return RunSpec(
        benchmark=ResolvedBenchmarkRef(
            identifier=BenchmarkId(reference.BENCHMARK_ID),
            version=reference.BENCHMARK_VERSION,
            semantic_digest=reference.BENCHMARK_SEMANTIC_DIGEST,
        ),
        scenario=ResolvedScenarioRef(
            identifier=ScenarioId(reference.SCENARIO_ID),
            version=reference.SCENARIO_VERSION,
            semantic_digest=reference.SCENARIO_SEMANTIC_DIGEST,
        ),
        realization=ResolvedRealizationRef(
            identifier=RealizationId(reference.REALIZATION_ID),
            version=reference.REALIZATION_VERSION,
            semantic_digest=reference.REALIZATION_SEMANTIC_DIGEST,
        ),
        system_under_test=ResolvedSUTRef(
            identifier=SUTId(reference.SUT_ID),
            version=reference.SUT_VERSION,
            semantic_digest=reference.SUT_SEMANTIC_DIGEST,
        ),
        environment=ResolvedEnvironmentRef(
            identifier=EnvironmentId(reference.expected_environment_id_for(platform_tag)),
            version=reference.ENVIRONMENT_VERSION,
            semantic_digest=reference.environment_semantic_digest_for(platform_tag),
        ),
        factors=(
            FactorAssignment(
                factor_id=GRAVITY_FACTOR_ID,
                quantity=QuantityId("q.pendulum.gravity"),
                unit=CanonicalUnit(expression=reference.GRAVITY_UNIT),
                target=FactorTarget(
                    kind=FactorTargetKind.REALIZATION,
                    identifier=reference.REALIZATION_ID,
                    parameter="gravity",
                ),
                value=reference.GRAVITY_M_S2,
            ),
        ),
        seed=reference.SEED,
        outcomes=(reference.OUTCOME,),
    )


def reference_authority_matches_definitions() -> dict[str, str]:
    """Recompute every pinned digest from these definitions, for tests and tools.

    Returns a mapping from the pinned constant name to the observed digest. A caller must
    compare it with :mod:`dynamisbench.adapters.mujoco.reference`; this module deliberately
    does not decide whether the pins are current, because that would make the same file the
    authority and its own verifier.
    """
    benchmark = benchmark_release()
    return {
        "benchmark": semantic_sha256(benchmark).hex,
        "scenario": semantic_sha256(scenario_definition()).hex,
        "realization": semantic_sha256(realization_definition()).hex,
        "system_under_test": semantic_sha256(system_under_test()).hex,
        "environment_windows_x86_64": semantic_sha256(
            environment_definition(platform_tag="windows-x86-64")
        ).hex,
        "environment_linux_x86_64": semantic_sha256(
            environment_definition(platform_tag="linux-x86-64")
        ).hex,
    }
