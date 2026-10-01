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
    Comparator,
    MetricId,
    QuantityId,
    ReferenceId,
    ScenarioId,
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
from dynamisbench.domain.spec.references import (
    ReferenceDefinition,
    ReferenceOrigin,
    VerificationCategory,
)

EXACT = Comparator.EXACT
AT_LEAST = Comparator.GREATER_THAN_OR_EQUAL


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
