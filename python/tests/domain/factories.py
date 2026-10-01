"""Valid-object builders shared by the DB-1.2 domain qualification.

The corpus under ``fixtures/domain`` is the authority-facing view: JSON documents
that must validate or must fail closed. These builders produce the valid Python
objects the corpus is compared against, so a fixture and its builder cannot drift
apart in field coverage without the corpus failing.

YAML is only an authoring representation (RES-228). The validated domain object is
the semantic representation these builders construct.
"""

from __future__ import annotations

from typing import Any

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
    ComparisonOperator,
    MetricAggregation,
    MetricCriterion,
    MetricDefinition,
)
from dynamisbench.domain.spec.quantities import (
    AxisConvention,
    BodyInclusion,
    CanonicalUnit,
    CompositeAggregation,
    Handedness,
    PhysicalDimension,
    QuantityDefinition,
    ReferenceFrame,
    RotationSense,
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
    NormalizationTransform,
    RealizationDefinition,
    RealizationQuantityMapping,
)
from dynamisbench.domain.spec.references import (
    ReferenceDefinition,
    ReferenceOrigin,
    VerificationCategory,
)
from dynamisbench.domain.spec.scenarios import (
    EventDefinition,
    QuantityAssignment,
    ScenarioDefinition,
)
from dynamisbench.domain.spec.studies import (
    FactorRole,
    FactorTarget,
    FactorTargetKind,
    PointValue,
    StudyDefinition,
    UncertaintyFactorDefinition,
    UniformRange,
)
from dynamisbench.domain.spec.sut import (
    SUTDefinition,
    SUTInterface,
    SUTInterfaceKind,
    SUTKind,
    SUTProvenance,
)

EXACT = Comparator.EXACT
AT_LEAST = Comparator.GREATER_THAN_OR_EQUAL

ENGINE_NATIVE_TOKENS = (
    "mjmodel",
    "mjdata",
    "qpos",
    "qvel",
    "qacc",
    "simtk",
    "opensim",
    "statevector",
    "statespace",
    "observation_space",
    "actuator",
    "geom_rgba",
    "multibody",
)
"""Engine-native type and field names that must never appear in a domain payload.

An engine's *name* is legitimate authority: a realization may be called
``rl.mujoco.loaded-cmj`` and an environment ``env.mujoco.x86-64``. An engine's
*types* are not, and none of these tokens may reach a public domain interface.
"""


def specifier(*clauses: tuple[Comparator, str]) -> VersionSpecifier:
    """Build a conjunctive version specifier from comparator/version pairs."""
    return VersionSpecifier(
        clauses=tuple(
            VersionClause(comparator=comparator, version=version) for comparator, version in clauses
        )
    )


def capability_requirement(
    capability: Capability, *, essential: bool = True
) -> CapabilityRequirement:
    return CapabilityRequirement(
        capability=capability,
        essential=essential,
        rationale=f"{capability.value} is required by this definition",
    )


def capability_declaration(capability: Capability) -> CapabilityDeclaration:
    return CapabilityDeclaration(
        capability=capability,
        summary=f"realization provides {capability.value}",
    )


def engine_binding(engine: str = "mujoco", version: str = "3.3.0") -> EngineBinding:
    return EngineBinding(engine=engine, specifier=specifier((EXACT, version)))


def environment_requirement(
    component: str,
    kind: ComponentKind,
    version: str,
) -> EnvironmentRequirement:
    return EnvironmentRequirement(
        component=component,
        kind=kind,
        specifier=specifier((AT_LEAST, version)),
    )


def environment_definition(**overrides: Any) -> EnvironmentDefinition:
    """A minimal valid execution environment."""
    values: dict[str, Any] = {
        "environment_id": "env.mujoco.x86-64",
        "version": "1.0.0",
        "label": "MuJoCo 3.3.0 on CPython 3.12",
        "description": "Exact scientific execution environment for the MuJoCo realization.",
        "requirements": (
            environment_requirement("mujoco", ComponentKind.ENGINE, "3.3.0"),
            environment_requirement("python", ComponentKind.RUNTIME, "3.12"),
            environment_requirement("windows", ComponentKind.PLATFORM, "11"),
        ),
    }
    values.update(overrides)
    return EnvironmentDefinition(**values)


WORLD_FRAME = ReferenceFrame(
    frame_id="world",
    parent="global",
    axis_labels=("x", "y", "z"),
    handedness=Handedness.RIGHT,
    description="Right-handed world frame with the vertical along +z.",
)


def reference_frame(frame_id: str = "lab") -> ReferenceFrame:
    return ReferenceFrame(
        frame_id=frame_id,
        parent="world",
        axis_labels=("ant", "lat", "ver"),
        handedness=Handedness.RIGHT,
        description="Laboratory frame aligned with the world frame.",
    )


def force_dimension() -> PhysicalDimension:
    return PhysicalDimension(length=1, mass=1, time=-2)


def quantity_definition(
    quantity_id: str = "q.foot.vertical_force", **overrides: Any
) -> QuantityDefinition:
    """A minimal valid canonical quantity: a vertical ground reaction force."""
    values: dict[str, Any] = {
        "quantity_id": QuantityId(quantity_id),
        "version": "1.0.0",
        "label": "Vertical ground reaction force",
        "description": "Vertical component of the ground reaction force on the foot.",
        "dimension": force_dimension(),
        "unit": CanonicalUnit(expression="N"),
        "frame": WORLD_FRAME,
        "sign_convention": SignConvention(
            positive_direction="upward, away from the supporting surface"
        ),
        "body_inclusion": BodyInclusion(
            included=("foot",), aggregation=CompositeAggregation.SINGLE
        ),
        "time_basis": TimeBasis(kind=TimeBasisKind.RELATIVE_TO_START),
        "sampling": SamplingSemantics(kind=SamplingKind.UNIFORM, rate_hz=1000.0),
        "uncertainty": UncertaintyMetadata(
            characterization="expected to be limited by force-plate acquisition noise"
        ),
    }
    values.update(overrides)
    return QuantityDefinition(**values)


def metric_definition(metric_id: str = "m.jump_height.rmse", **overrides: Any) -> MetricDefinition:
    """A minimal valid metric: RMSE of a canonical quantity against a threshold."""
    values: dict[str, Any] = {
        "metric_id": MetricId(metric_id),
        "version": "1.0.0",
        "label": "Jump height RMSE",
        "description": "Root mean square error of canonical jump height.",
        "quantity": QuantityId("q.jump.height"),
        "aggregation": MetricAggregation(
            method=AggregationMethod.MEAN, window_start_s=0.0, window_end_s=1.0
        ),
        "criterion": MetricCriterion(operator=ComparisonOperator.LESS, threshold=0.01),
    }
    values.update(overrides)
    return MetricDefinition(**values)


def reference_definition(
    reference_id: str = "r.baseline-0", **overrides: Any
) -> ReferenceDefinition:
    """A minimal valid reference case for a scenario."""
    values: dict[str, Any] = {
        "reference_id": ReferenceId(reference_id),
        "version": "1.0.0",
        "label": "Baseline 0 reference",
        "description": "Reference trajectory for the loaded countermovement jump scenario.",
        "scenario_id": ScenarioId("sc.loaded-cmj"),
        "category": VerificationCategory.MODEL_VALIDATION,
        "origin": ReferenceOrigin.EXPERIMENTAL,
        "license": "internal research use",
    }
    values.update(overrides)
    return ReferenceDefinition(**values)


def axis_convention() -> AxisConvention:
    return AxisConvention(order=("x", "y", "z"), sense=RotationSense.INTRINSIC)


def quantity_assignment(
    quantity: str = "q.foot.vertical_force",
    value: float = 0.0,
    unit: str = "N",
) -> QuantityAssignment:
    return QuantityAssignment(
        quantity=QuantityId(quantity), value=value, unit=CanonicalUnit(expression=unit)
    )


def event(event_id: str = "takeoff", **overrides: Any) -> EventDefinition:
    values: dict[str, Any] = {
        "event_id": event_id,
        "label": event_id.replace("-", " ").title(),
        "expected_time_s": 0.3,
        "tolerance_s": 0.005,
    }
    values.update(overrides)
    return EventDefinition(**values)


def scenario_definition(scenario_id: str = "sc.loaded-cmj", **overrides: Any) -> ScenarioDefinition:
    """A minimal valid scenario: a bounded case with declared initial conditions."""
    values: dict[str, Any] = {
        "scenario_id": ScenarioId(scenario_id),
        "version": "1.0.0",
        "label": "Loaded countermovement jump",
        "description": "Countermovement jump executed from a loaded standing posture.",
        "duration_s": 2.0,
        "initial_conditions": (quantity_assignment(),),
        "events": (event("takeoff"),),
        "required_capabilities": (capability_requirement(Capability.FORWARD_DYNAMICS),),
    }
    values.update(overrides)
    return ScenarioDefinition(**values)


def sut_provenance(**overrides: Any) -> SUTProvenance:
    values: dict[str, Any] = {
        "repository": "org/zero-sot-sqp",
        "ref": "refs/tags/v1.2.0",
        "resolved_commit": "1f2e3d4c5b6a",
    }
    values.update(overrides)
    return SUTProvenance(**values)


def sut_definition(sut_id: str = "sut.baseline-0", **overrides: Any) -> SUTDefinition:
    """A minimal valid system under test."""
    values: dict[str, Any] = {
        "sut_id": SUTId(sut_id),
        "version": "1.0.0",
        "label": "Baseline 0 controller",
        "description": "Baseline controller used to qualify the realization.",
        "kind": SUTKind.CONTROLLER,
        "interface": SUTInterface(
            kind=SUTInterfaceKind.SUBPROCESS,
            command=("python", "-m", "baseline_controller"),
        ),
        "provenance": sut_provenance(),
    }
    values.update(overrides)
    return SUTDefinition(**values)


def quantity_mapping(quantity: str = "q.foot.vertical_force") -> RealizationQuantityMapping:
    return RealizationQuantityMapping(
        quantity=QuantityId(quantity),
        source="force_sensor_foot",
        transform=NormalizationTransform(name="sensor-nearest", version="1.0.0"),
    )


def benchmark_ref(benchmark_id: str = "db.lcmj20", version: str = "1.0.0") -> BenchmarkRef:
    return BenchmarkRef(identifier=BenchmarkId(benchmark_id), version=version)


def realization_definition(
    realization_id: str = "rl.mujoco.loaded-cmj", **overrides: Any
) -> RealizationDefinition:
    """A minimal valid realization with no engine-native object in sight."""
    values: dict[str, Any] = {
        "realization_id": RealizationId(realization_id),
        "version": "1.0.0",
        "label": "MuJoCo realization of the loaded countermovement jump",
        "description": "Executable implementation of the benchmark in MuJoCo.",
        "benchmark": benchmark_ref(),
        "engine": engine_binding(),
        "capabilities": (
            capability_declaration(Capability.FORWARD_DYNAMICS),
            capability_declaration(Capability.STATE_SNAPSHOT),
        ),
        "quantity_mappings": (quantity_mapping(),),
        "engine_configuration": (ConfigurationEntry(name="integrator", value="implicitfast"),),
        "assets": (
            AssetReference(
                asset_id="subject-model",
                path="models/realization/subject.xml",
                description="Segment geometry and inertia of the modelled subject.",
                sha256="0" * 64,
            ),
        ),
        "known_discrepancies": (
            "Contact stiffness is not calibrated against the reference plate.",
        ),
    }
    values.update(overrides)
    return RealizationDefinition(**values)


def jump_height_quantity() -> QuantityDefinition:
    return quantity_definition(
        quantity_id="q.jump.height",
        label="Jump height",
        description="Apex height of the centre of mass above its standing value.",
        dimension=PhysicalDimension(length=1),
        unit=CanonicalUnit(expression="m"),
        sign_convention=SignConvention(positive_direction="upward from the standing value"),
        body_inclusion=BodyInclusion(included=("com",), aggregation=CompositeAggregation.SINGLE),
        sampling=SamplingSemantics(kind=SamplingKind.IRREGULAR),
        time_basis=TimeBasis(kind=TimeBasisKind.RELATIVE_TO_START),
        uncertainty=UncertaintyMetadata(
            characterization="expected to be dominated by marker placement variability"
        ),
    )


def benchmark_release(**overrides: Any) -> BenchmarkRelease:
    """A minimal valid benchmark release with internally consistent authority."""
    values: dict[str, Any] = {
        "benchmark_id": BenchmarkId("db.lcmj20"),
        "version": "1.0.0",
        "label": "Benchmark Family 001 — loaded countermovement jump",
        "description": "A loaded countermovement jump benchmark for human-movement models.",
        "intended_use": "Comparative assessment of human-movement models on a jump task.",
        "intended_non_use": "Not a clinical assessment and not a fatigue or injury model.",
        "conceptual_model": "A planar sagittal multi-segment subject on a rigid force plate.",
        "claim_ceiling": "Relative model comparison within the stated applicability domain.",
        "quantities": (quantity_definition(), jump_height_quantity()),
        "scenarios": (scenario_definition(),),
        "metrics": (metric_definition(),),
        "references": (reference_definition(),),
        "credibility_hierarchy": (
            CredibilityLevel.BENCHMARK_REFERENCE_CASE,
            CredibilityLevel.COMPLETE_SYSTEM,
        ),
    }
    values.update(overrides)
    return BenchmarkRelease(**values)


def factor_target(
    kind: FactorTargetKind = FactorTargetKind.REALIZATION, parameter: str = "contact-stiffness"
) -> FactorTarget:
    return FactorTarget(kind=kind, identifier="rl.mujoco.loaded-cmj", parameter=parameter)


def uncertainty_factor(**overrides: Any) -> UncertaintyFactorDefinition:
    """A minimal valid varied factor."""
    values: dict[str, Any] = {
        "factor_id": FactorId("f.contact-stiffness"),
        "label": "Contact stiffness scale",
        "description": "Multiplier applied to the realization's contact stiffness.",
        "role": FactorRole.FACTOR,
        "quantity": QuantityId("q.foot.vertical_force"),
        "target": factor_target(),
        "distribution": UniformRange(lower=0.8, upper=1.2),
    }
    values.update(overrides)
    return UncertaintyFactorDefinition(**values)


def controlled_factor(**overrides: Any) -> UncertaintyFactorDefinition:
    """A minimal valid controlled variable: a factor held at one value."""
    values: dict[str, Any] = {
        "factor_id": FactorId("f.gravity"),
        "label": "Gravitational acceleration",
        "description": "Held at standard gravity for every run in the study.",
        "role": FactorRole.CONTROLLED,
        "quantity": QuantityId("q.jump.height"),
        "target": factor_target(parameter="gravity"),
        "distribution": PointValue(value=9.80665),
    }
    values.update(overrides)
    return UncertaintyFactorDefinition(**values)


def study_definition(**overrides: Any) -> StudyDefinition:
    """A minimal valid study over frozen, separately versioned authority."""
    values: dict[str, Any] = {
        "study_id": StudyId("study.contact-stiffness-sensitivity"),
        "version": "1.0.0",
        "label": "Contact stiffness sensitivity",
        "description": "How sensitive canonical jump height is to contact stiffness.",
        "research_question": "How much does jump height depend on contact stiffness?",
        "analysis_plan": (
            "Aggregate per-replicate canonical jump height, then report the mean and "
            "half-range across seeds."
        ),
        "replicates": 3,
        "benchmarks": (benchmark_ref(),),
        "realizations": (
            RealizationRef(identifier=RealizationId("rl.mujoco.loaded-cmj"), version="1.0.0"),
        ),
        "systems_under_test": (SUTRef(identifier=SUTId("sut.baseline-0"), version="1.0.0"),),
        "environments": (
            EnvironmentRef(identifier=EnvironmentId("env.mujoco.x86-64"), version="1.0.0"),
        ),
        "required_capabilities": (
            capability_requirement(Capability.FORWARD_DYNAMICS),
            capability_requirement(Capability.STATE_SNAPSHOT),
        ),
        "factors": (uncertainty_factor(), controlled_factor()),
        "outcomes": ("q.jump.height",),
        "seeds": (11, 12, 13),
    }
    values.update(overrides)
    return StudyDefinition(**values)
