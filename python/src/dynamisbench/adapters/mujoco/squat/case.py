"""The barbell back-squat realization as validated domain definitions.

Engine-free. This is the reviewed source of the benchmark release, scenario, realization,
system under test, execution environments and study of the squat, exactly as
:mod:`dynamisbench.adapters.mujoco.reference_case` is for the pendulum. Their semantic
digests are pinned in :mod:`.pins`; the worker compares a request with those pins, never with a
value the request supplies about itself.

What the release claims, and what it does not
--------------------------------------------

The release is a *benchmark reference case* of a synthetic model: it declares the canonical
quantities a run publishes, the metrics (with acceptance criteria where the criterion does not
depend on the configuration) and the qualified configuration space. It is code and solution
verification of one model. It has no experimental reference, is not validated against
measured human motion, and is not subject-specific; its ``claim_ceiling`` says so and the
workbench repeats it wherever a result is shown.

Canonical quantities with channels
----------------------------------

Per-joint, per-body and per-contact-point quantities are declared once per quantity and
published as *channels* (one column per joint, body or point, named in the quantity's notes).
A channel is a named member of the quantity, not a different quantity: all channels share the
dimension, unit, frame and sign convention declared here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from dynamisbench.adapters.mujoco.squat import anthropometry as anth
from dynamisbench.adapters.mujoco.squat import contract, mjcf, pins
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
    BASE_DIMENSION_NAMES,
    BodyInclusion,
    CanonicalUnit,
    CompositeAggregation,
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
    canonical_unit_dimension,
)
from dynamisbench.domain.spec.realizations import (
    AssetReference,
    ConfigurationEntry,
    NormalizationTransform,
    RealizationDefinition,
    RealizationQuantityMapping,
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
from dynamisbench.identity import semantic_sha256
from dynamisbench.planning.factors import FactorAssignment, FactorCase, FactorValue

__all__ = [
    "SAMPLE_PERIOD_S",
    "SquatConfiguration",
    "configuration_from_assignments",
    "configuration_from_values",
    "timestep_divides_sample_period",
    "BODY_NAMES",
    "CANONICAL_SAMPLE_RATE_HZ",
    "CONTACT_POINTS",
    "JOINT_NAMES",
    "METRIC_IDS",
    "QUANTITY_CHANNELS",
    "authority_digests",
    "benchmark_release",
    "environment_definition",
    "factor_case",
    "nominal_factor_case",
    "realization_definition",
    "scenario_definition",
    "study_definition",
    "system_under_test",
]

CANONICAL_SAMPLE_RATE_HZ: Final = 100.0
"""Canonical series are synchronized snapshots at exactly 100 Hz from t = 0."""

JOINT_NAMES: Final = tuple(spec.name for spec in anth.joint_specs())
"""The 29 actuated hinges, in the model's order."""

BODY_NAMES: Final = (
    "pelvis",
    "torso_middle",
    "torso_upper",
    "head",
    "upper_arm_l",
    "forearm_l",
    "hand_l",
    "upper_arm_r",
    "forearm_r",
    "hand_r",
    "thigh_l",
    "shank_l",
    "foot_l",
    "thigh_r",
    "shank_r",
    "foot_r",
    "barbell",
)
"""The 17 bodies, in the compiled model's body order."""

CONTACT_POINTS: Final = tuple(
    f"{side}_{point}" for side in ("l", "r") for point in mjcf.SOLE_POINTS
)
"""The ten plantar contact points, left foot then right."""

_DEG: Final = math.pi / 180.0

_WORLD: Final = ReferenceFrame(
    frame_id="world",
    parent="global",
    axis_labels=("x", "y", "z"),
    handedness=Handedness.RIGHT,
    description="Right-handed world frame: x anterior, y the athlete's left, z up; gravity -z.",
)
_FLOOR: Final = ReferenceFrame(
    frame_id="floor",
    parent="world",
    axis_labels=("x", "y"),
    description="The floor plane z = 0, with the world x and y axes.",
)
_HINGE: Final = ReferenceFrame(
    frame_id="joint-hinge",
    parent="world",
    axis_labels=("hinge",),
    description="Each joint's own hinge axis, fixed in its child segment.",
)
_NONE: Final = ReferenceFrame(
    frame_id="scalar",
    parent="world",
    axis_labels=("value",),
    description="A frame-independent scalar.",
)
_ANATOMICAL_SIGN: Final = SignConvention(
    positive_direction=(
        "the named anatomical direction on both sides: flexion, adduction, internal "
        "rotation, dorsiflexion, inversion; leftward spinal bending and rotation"
    )
)
_UNIFORM: Final = SamplingSemantics(kind=SamplingKind.UNIFORM, rate_hz=CANONICAL_SAMPLE_RATE_HZ)
_SINGLE: Final = SamplingSemantics(kind=SamplingKind.SINGLE_SAMPLE)
_START: Final = TimeBasis(kind=TimeBasisKind.RELATIVE_TO_START)
_NUMERICAL: Final = UncertaintyMetadata(
    characterization="numerical integration and contact-solver error only; no measurement"
)

QUANTITY_CHANNELS: Final[dict[str, tuple[str, ...]]] = {
    "q.squat.joint-angle": JOINT_NAMES,
    "q.squat.joint-angular-velocity": JOINT_NAMES,
    "q.squat.joint-reference-angle": JOINT_NAMES,
    "q.squat.joint-torque": JOINT_NAMES,
    "q.squat.segment-position": tuple(f"{b}.{a}" for b in BODY_NAMES for a in "xyz"),
    "q.squat.segment-orientation": tuple(f"{b}.{a}" for b in BODY_NAMES for a in "wxyz"),
    "q.squat.com-position": ("x", "y", "z"),
    "q.squat.com-velocity": ("x", "y", "z"),
    "q.squat.bar-position": ("x", "y", "z"),
    "q.squat.bar-velocity": ("x", "y", "z"),
    "q.squat.ground-reaction-force": tuple(f"{s}.{a}" for s in ("left", "right") for a in "xyz"),
    "q.squat.centre-of-pressure": tuple(
        f"{s}.{a}" for s in ("both", "left", "right") for a in "xy"
    ),
    "q.squat.plantar-normal-load": CONTACT_POINTS,
    "q.squat.plantar-contact-position": tuple(f"{p}.{a}" for p in CONTACT_POINTS for a in "xy"),
    "q.squat.friction-utilization": CONTACT_POINTS,
    "q.squat.heel-load-share": ("left", "right"),
}
"""The channel names of every multi-channel canonical quantity (all others are scalar)."""


def _exact(version: str) -> VersionSpecifier:
    return VersionSpecifier(clauses=(VersionClause(comparator=Comparator.EXACT, version=version),))


def _quantity(
    quantity_id: str,
    label: str,
    description: str,
    unit: str,
    *,
    frame: ReferenceFrame = _NONE,
    sign: str | SignConvention = "a larger value is more of the named quantity",
    sampling: SamplingSemantics = _UNIFORM,
    bodies: tuple[str, ...] | None = None,
    aggregation: CompositeAggregation = CompositeAggregation.SINGLE,
) -> QuantityDefinition:
    canonical = CanonicalUnit(expression=unit)
    exponents = canonical_unit_dimension(canonical.expression)
    dimension = PhysicalDimension(
        **{
            name: value
            for name, value in zip(BASE_DIMENSION_NAMES, exponents, strict=True)
            if value
        }
    )
    channels = QUANTITY_CHANNELS.get(quantity_id)
    notes: tuple[str, ...] = ()
    if channels is not None:
        notes = (f"published as {len(channels)} channels; see case.QUANTITY_CHANNELS",)
    return QuantityDefinition(
        quantity_id=QuantityId(quantity_id),
        version="1.0.0",
        label=label,
        description=description,
        dimension=dimension,
        unit=canonical,
        frame=frame,
        sign_convention=sign
        if isinstance(sign, SignConvention)
        else SignConvention(positive_direction=sign),
        time_basis=_START,
        sampling=sampling,
        body_inclusion=None
        if bodies is None
        else BodyInclusion(included=bodies, aggregation=aggregation),
        uncertainty=_NUMERICAL,
        notes=notes,
    )


def _quantities() -> tuple[QuantityDefinition, ...]:
    athlete = tuple(name for name in BODY_NAMES if name != "barbell")
    return (
        _quantity(
            "q.squat.joint-angle",
            "Joint angle",
            "Angle of each actuated hinge from the anatomical zero posture, in radians.",
            "1",
            frame=_HINGE,
            sign=_ANATOMICAL_SIGN,
        ),
        _quantity(
            "q.squat.joint-angular-velocity",
            "Joint angular velocity",
            "Time derivative of each hinge angle.",
            "s^-1",
            frame=_HINGE,
            sign=_ANATOMICAL_SIGN,
        ),
        _quantity(
            "q.squat.joint-reference-angle",
            "Joint reference angle",
            "The controller's reference angle of each hinge at the same instant.",
            "1",
            frame=_HINGE,
            sign=_ANATOMICAL_SIGN,
        ),
        _quantity(
            "q.squat.joint-torque",
            "Joint actuator torque",
            "Torque each joint actuator applies about its hinge; an extensor moment is its "
            "negative for a flexion axis.",
            "N*m",
            frame=_HINGE,
            sign=_ANATOMICAL_SIGN,
        ),
        _quantity(
            "q.squat.segment-position",
            "Segment origin position",
            "World position of each body's frame origin (its proximal joint centre).",
            "m",
            frame=_WORLD,
            sign="along the positive world axis",
            bodies=BODY_NAMES,
        ),
        _quantity(
            "q.squat.segment-orientation",
            "Segment orientation",
            "Unit quaternion (w, x, y, z) rotating each body frame into the world frame.",
            "1",
            frame=_WORLD,
            sign="active rotation from body to world; w >= 0 is not enforced",
            bodies=BODY_NAMES,
        ),
        _quantity(
            "q.squat.com-position",
            "System centre of mass",
            "Centre of mass of athlete and barbell together.",
            "m",
            frame=_WORLD,
            sign="along the positive world axis",
            bodies=BODY_NAMES,
            aggregation=CompositeAggregation.SUM,
        ),
        _quantity(
            "q.squat.com-velocity",
            "System centre-of-mass velocity",
            "Velocity of the athlete-and-barbell centre of mass.",
            "m*s^-1",
            frame=_WORLD,
            sign="along the positive world axis",
            bodies=BODY_NAMES,
            aggregation=CompositeAggregation.SUM,
        ),
        _quantity(
            "q.squat.bar-position",
            "Barbell centre position",
            "World position of the barbell's geometric centre.",
            "m",
            frame=_WORLD,
            sign="along the positive world axis",
            bodies=("barbell",),
        ),
        _quantity(
            "q.squat.bar-velocity",
            "Barbell centre velocity",
            "Linear velocity of the barbell centre.",
            "m*s^-1",
            frame=_WORLD,
            sign="along the positive world axis",
            bodies=("barbell",),
        ),
        _quantity(
            "q.squat.bar-tilt",
            "Barbell tilt",
            "Angle between the barbell's long axis and the horizontal plane.",
            "1",
            bodies=("barbell",),
        ),
        _quantity(
            "q.squat.ground-reaction-force",
            "Ground reaction force per foot",
            "Resultant floor force on each foot (sum over its plantar contact points).",
            "N",
            frame=_WORLD,
            sign="force on the athlete along the positive world axis",
            bodies=("foot_l", "foot_r"),
        ),
        _quantity(
            "q.squat.vertical-grf-ratio",
            "Vertical ground reaction over weight",
            "Sum of both feet's vertical ground reaction divided by the weight of athlete "
            "and barbell.",
            "1",
            bodies=("foot_l", "foot_r"),
            aggregation=CompositeAggregation.SUM,
        ),
        _quantity(
            "q.squat.planned-vertical-grf",
            "Internal-model vertical ground reaction",
            "The vertical ground reaction the controller's internal model predicts.",
            "N",
        ),
        _quantity(
            "q.squat.centre-of-pressure",
            "Centre of pressure",
            "Centre of pressure of both feet and of each foot on the floor.",
            "m",
            frame=_FLOOR,
            sign="along the positive floor axis",
        ),
        _quantity(
            "q.squat.cop-margin",
            "Centre-of-pressure margin",
            "Signed distance from the centre of pressure to the edge of the support polygon "
            "of load-bearing contact points; positive inside.",
            "m",
            frame=_FLOOR,
            sign="positive inside the loaded support polygon",
        ),
        _quantity(
            "q.squat.xcom-margin",
            "Extrapolated centre-of-mass margin",
            "Signed distance from the extrapolated centre of mass (Hof 2005) to the loaded "
            "support polygon edge; positive inside.",
            "m",
            frame=_FLOOR,
            sign="positive inside the loaded support polygon",
        ),
        _quantity(
            "q.squat.plantar-normal-load",
            "Plantar normal load",
            "Normal force at each plantar contact point.",
            "N",
            sign="compressive load on the sole",
        ),
        _quantity(
            "q.squat.plantar-contact-position",
            "Plantar contact position",
            "Floor-plane position of each plantar contact point.",
            "m",
            frame=_FLOOR,
            sign="along the positive floor axis",
        ),
        _quantity(
            "q.squat.friction-utilization",
            "Friction utilization",
            "Tangential over (friction coefficient x normal) force at each plantar point; 1 is "
            "the edge of the friction cone, 0 for an unloaded point.",
            "1",
        ),
        _quantity(
            "q.squat.plantar-load-minimum",
            "Lightest plantar point load",
            "The smallest normal load over the ten plantar points at each instant.",
            "N",
            sign="compressive load on the sole",
        ),
        _quantity(
            "q.squat.loaded-contact-count",
            "Load-bearing plantar points",
            "Number of plantar points bearing more than 5 N at each instant.",
            "1",
        ),
        _quantity(
            "q.squat.friction-utilization-peak",
            "Peak friction utilization",
            "The largest friction utilization over the ten plantar points at each instant.",
            "1",
        ),
        _quantity(
            "q.squat.heel-load-share",
            "Heel load share per foot",
            "Load on a foot's two heel points over that foot's total normal load.",
            "1",
        ),
        _quantity(
            "q.squat.heel-load-share-lesser-foot",
            "Heel load share, lesser foot",
            "The smaller of the two feet's heel load shares at each instant.",
            "1",
        ),
        _quantity(
            "q.squat.sole-point-slip",
            "Sole point slip",
            "Largest floor-plane displacement of any plantar point from its position at t = 0.",
            "m",
            frame=_FLOOR,
        ),
        _quantity(
            "q.squat.knee-flexion-left",
            "Left knee flexion",
            "Angle of the left knee hinge (the knee_flexion_l channel of the joint angle).",
            "1",
            frame=_HINGE,
            sign=_ANATOMICAL_SIGN,
        ),
        _quantity(
            "q.squat.lumbar-flexion",
            "Lumbar flexion",
            "Angle of the lumbar flexion hinge (the lumbar_flexion channel of the joint angle).",
            "1",
            frame=_HINGE,
            sign=_ANATOMICAL_SIGN,
        ),
        _quantity(
            "q.squat.knee-extensor-moment-left",
            "Left knee extensor moment",
            "Negative of the left knee actuator torque: the moment extending the knee.",
            "N*m",
            frame=_HINGE,
            sign="extension of the left knee",
        ),
        _quantity(
            "q.squat.com-anterior",
            "Centre of mass, anterior position",
            "World x of the system centre of mass (the ankle line is near x = 0).",
            "m",
            frame=_WORLD,
            sign="anterior",
        ),
        _quantity(
            "q.squat.actuator-power",
            "Actuator power",
            "Sum over all joint actuators of torque times joint angular velocity.",
            "W",
        ),
        _quantity(
            "q.squat.shelf-force",
            "Bar shelf force",
            "Magnitude of the force the upper-trunk shelf exerts on the barbell.",
            "N",
            bodies=("torso_upper", "barbell"),
        ),
        _quantity(
            "q.squat.activation-peak",
            "Peak actuator activation",
            "The largest absolute actuator activation over all joints at each instant.",
            "1",
        ),
        _quantity(
            "q.squat.trunk-inclination",
            "Trunk inclination",
            "Angle of the pelvis-to-head line from vertical.",
            "1",
            bodies=("pelvis", "head"),
        ),
        _quantity(
            "q.squat.pelvis-height",
            "Pelvis height",
            "Height of the pelvis frame origin above the floor.",
            "m",
            frame=_WORLD,
            sign="up",
            bodies=("pelvis",),
        ),
        _quantity(
            "q.squat.depth-intent",
            "Depth intent",
            "The controller's commanded knee-flexion depth at each instant.",
            "1",
        ),
        _quantity(
            "q.squat.commanded-phase",
            "Commanded phase",
            "Code of the commanded phase: 0 standing, 1 descent, 2 bottom, 3 ascent, 4 return.",
            "1",
        ),
        _quantity(
            "q.squat.barbell-mass",
            "Barbell mass",
            "Mass of the empty IWF barbell carried in the high-bar position.",
            "kg",
            sampling=_SINGLE,
            bodies=("barbell",),
        ),
        _quantity(
            "q.squat.initial-com-speed",
            "Initial centre-of-mass speed",
            "Speed of the system centre of mass at t = 0.",
            "m*s^-1",
            sampling=_SINGLE,
            bodies=athlete,
            aggregation=CompositeAggregation.SUM,
        ),
        *(
            _quantity(
                domain.quantity_id,
                domain.label,
                f"Configuration parameter '{domain.parameter}' of the squat realization.",
                domain.unit,
                sampling=_SINGLE,
            )
            for domain in pins.FACTOR_DOMAINS
        ),
    )


def _metric(
    metric_id: str,
    label: str,
    description: str,
    quantity: str,
    method: AggregationMethod,
    criterion: tuple[ComparisonOperator, float] | None = None,
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=MetricId(metric_id),
        version="1.0.0",
        label=label,
        description=description,
        quantity=QuantityId(quantity),
        aggregation=MetricAggregation(method=method),
        criterion=None
        if criterion is None
        else MetricCriterion(operator=criterion[0], threshold=criterion[1]),
    )


_METRICS: Final = (
    (
        "m.squat.knee-flexion.maximum",
        "Deepest knee flexion",
        "Maximum left knee flexion over the run (reported; the depth is a configuration).",
        "q.squat.knee-flexion-left",
        AggregationMethod.MAXIMUM,
        None,
    ),
    (
        "m.squat.knee-extensor-moment.maximum",
        "Peak knee extensor moment",
        "Maximum left knee extensor moment over the run (reported).",
        "q.squat.knee-extensor-moment-left",
        AggregationMethod.MAXIMUM,
        None,
    ),
    (
        "m.squat.vertical-grf-ratio.mean.lower",
        "Mean vertical ground reaction, lower bound",
        "Starting and ending at rest, the mean vertical ground reaction is the weight.",
        "q.squat.vertical-grf-ratio",
        AggregationMethod.MEAN,
        (ComparisonOperator.GREATER, 0.999),
    ),
    (
        "m.squat.vertical-grf-ratio.mean.upper",
        "Mean vertical ground reaction, upper bound",
        "Starting and ending at rest, the mean vertical ground reaction is the weight.",
        "q.squat.vertical-grf-ratio",
        AggregationMethod.MEAN,
        (ComparisonOperator.LESS, 1.001),
    ),
    (
        "m.squat.vertical-grf-ratio.maximum",
        "Peak vertical ground reaction",
        "Maximum vertical ground reaction over weight (reported).",
        "q.squat.vertical-grf-ratio",
        AggregationMethod.MAXIMUM,
        None,
    ),
    (
        "m.squat.loaded-contacts.minimum",
        "Fewest load-bearing plantar points",
        "Every plantar point bears load throughout: the feet stay flat.",
        "q.squat.loaded-contact-count",
        AggregationMethod.MINIMUM,
        (ComparisonOperator.GREATER_OR_EQUAL, 10.0),
    ),
    (
        "m.squat.plantar-load.minimum",
        "Lightest plantar point load",
        "No plantar point unloads.",
        "q.squat.plantar-load-minimum",
        AggregationMethod.MINIMUM,
        (ComparisonOperator.GREATER, 10.0),
    ),
    (
        "m.squat.heel-load-share.minimum",
        "Heel load share, lesser foot, minimum",
        "The heels stay loaded on each foot: no heel rise.",
        "q.squat.heel-load-share-lesser-foot",
        AggregationMethod.MINIMUM,
        (ComparisonOperator.GREATER, 0.2),
    ),
    (
        "m.squat.friction-utilization.maximum",
        "Peak friction utilization",
        "Each contact stays well inside its friction cone.",
        "q.squat.friction-utilization-peak",
        AggregationMethod.MAXIMUM,
        (ComparisonOperator.LESS, 0.5),
    ),
    (
        "m.squat.sole-slip.maximum",
        "Sole point slip",
        "Shod feet do not slide during a squat.",
        "q.squat.sole-point-slip",
        AggregationMethod.MAXIMUM,
        (ComparisonOperator.LESS, 0.002),
    ),
    (
        "m.squat.cop-margin.minimum",
        "Smallest centre-of-pressure margin",
        "The centre of pressure stays well inside the loaded support polygon.",
        "q.squat.cop-margin",
        AggregationMethod.MINIMUM,
        (ComparisonOperator.GREATER, 0.03),
    ),
    (
        "m.squat.lumbar-flexion.maximum",
        "Lumbar flexion, maximum",
        "Neutral spine: no lumbar flexion beyond 5 degrees.",
        "q.squat.lumbar-flexion",
        AggregationMethod.MAXIMUM,
        (ComparisonOperator.LESS, 5.0 * _DEG),
    ),
    (
        "m.squat.lumbar-flexion.minimum",
        "Lumbar flexion, minimum",
        "Neutral spine: no lumbar extension beyond 5 degrees.",
        "q.squat.lumbar-flexion",
        AggregationMethod.MINIMUM,
        (ComparisonOperator.GREATER, -5.0 * _DEG),
    ),
    (
        "m.squat.com-anterior.maximum",
        "Centre of mass, most anterior",
        "The system centre of mass stays over the mid-foot (x = 50 mm) within 10 mm.",
        "q.squat.com-anterior",
        AggregationMethod.MAXIMUM,
        (ComparisonOperator.LESS, 0.06),
    ),
    (
        "m.squat.com-anterior.minimum",
        "Centre of mass, most posterior",
        "The system centre of mass stays over the mid-foot (x = 50 mm) within 10 mm.",
        "q.squat.com-anterior",
        AggregationMethod.MINIMUM,
        (ComparisonOperator.GREATER, 0.04),
    ),
    (
        "m.squat.bar-tilt.maximum",
        "Barbell tilt, maximum",
        "The bar stays level (within 0.1 degree) on a symmetric squat.",
        "q.squat.bar-tilt",
        AggregationMethod.MAXIMUM,
        (ComparisonOperator.LESS, 0.1 * _DEG),
    ),
    (
        "m.squat.activation.maximum",
        "Peak actuator activation",
        "No actuator saturates (activation below 1).",
        "q.squat.activation-peak",
        AggregationMethod.MAXIMUM,
        (ComparisonOperator.LESS, 1.0),
    ),
)

METRIC_IDS: Final = tuple(entry[0] for entry in _METRICS)


def scenario_definition() -> ScenarioDefinition:
    """One controlled back-squat repetition from the standing keyframe with a 20 kg bar."""
    return ScenarioDefinition(
        scenario_id=ScenarioId(pins.SCENARIO_ID),
        version=pins.SCENARIO_VERSION,
        label="Controlled back-squat repetition with an empty bar",
        description=(
            "From quiet standing with a 20 kg bar on the upper trapezius: one repetition - "
            "standing, descent, bottom pause, ascent, return to standing - integrated from "
            "actuator torques. Depth, tempo, timestep, internal-model gain and sole friction "
            "are configuration factors; the horizon is the longest qualified configuration."
        ),
        duration_s=8.5,
        initial_conditions=(
            QuantityAssignment(
                quantity=QuantityId("q.squat.barbell-mass"),
                value=anth.BARBELL.mass,
                unit=CanonicalUnit(expression="kg"),
            ),
            QuantityAssignment(
                quantity=QuantityId("q.squat.initial-com-speed"),
                value=0.0,
                unit=CanonicalUnit(expression="m*s^-1"),
            ),
        ),
        events=(
            EventDefinition(event_id="descent", label="Descent commanded"),
            EventDefinition(event_id="bottom", label="Bottom reached (measured)"),
            EventDefinition(event_id="ascent", label="Ascent commanded"),
            EventDefinition(event_id="return", label="Return to standing"),
        ),
        required_capabilities=(
            CapabilityRequirement(
                capability=Capability.FORWARD_DYNAMICS,
                essential=True,
                rationale="The repetition is a closed-loop forward-dynamics rollout.",
            ),
        ),
    )


def benchmark_release() -> BenchmarkRelease:
    """The frozen back-squat reference case the realization implements."""
    return BenchmarkRelease(
        benchmark_id=BenchmarkId(pins.BENCHMARK_ID),
        version=pins.BENCHMARK_VERSION,
        label="Barbell back squat, synthetic athlete",
        description=(
            "A controlled back-squat repetition of a synthetic, population-scaled 75 kg, "
            "1.75 m athlete carrying an empty 20 kg barbell, as canonical time series of "
            "kinematics, kinetics, contact and balance."
        ),
        intended_use=(
            "Code and solution verification of a torque-driven musculoskeletal-scale rigid "
            "body model of the squat; comparison of configurations of the same model."
        ),
        intended_non_use=(
            "Not a validated model of any person or population, not a clinical or "
            "injury-risk tool, and not evidence about real squat technique."
        ),
        conceptual_model=(
            "16 rigid segments (de Leva 1996), 29 torque-actuated hinges with activation "
            "dynamics, a welded high-bar barbell held at both grips, ten compliant plantar "
            "contact points, a postural controller with a dynamic internal model."
        ),
        claim_ceiling=(
            "Mechanical consistency and numerical verification of one synthetic model within "
            "predeclared bounds on the qualified environment. No validation against measured "
            "human motion; not subject-specific."
        ),
        quantities=_quantities(),
        scenarios=(scenario_definition(),),
        metrics=tuple(_metric(*entry) for entry in _METRICS),
        credibility_hierarchy=(CredibilityLevel.BENCHMARK_REFERENCE_CASE,),
        assumptions=(
            "Rigid segments, ideal hinges, torque generators instead of muscles, no "
            "sensorimotor delay, an exact internal model at gain 1, double precision, "
            "deterministic execution.",
        ),
        applicability_domain=(
            "One repetition from quiet standing; depth 90-120 degrees of knee flexion, "
            "descent 1-2 s, ascent 0.8-1.6 s, timestep 0.25-1 ms, internal-model gain 0-1, "
            "sole friction time constant 2-15 ms; empty 20 kg bar.",
        ),
        known_discrepancies=(
            "No experimental reference: agreement with human data is not assessed.",
            "A pure-hinge knee cannot produce valgus; foot slip converges to about 1.4 mm.",
        ),
        uncertainty_expectations=(
            "No stochastic process; results depend only on configuration, timestep and the "
            "implementation identity.",
        ),
    )


def _mapping(quantity: str, source: str, transform: str = "identity") -> RealizationQuantityMapping:
    return RealizationQuantityMapping(
        quantity=QuantityId(quantity),
        source=source,
        transform=NormalizationTransform(name=transform, version="1.0.0"),
    )


QUANTITY_MAPPINGS: Final = (
    ("q.squat.joint-angle", "joint.*.angle", "identity"),
    ("q.squat.joint-angular-velocity", "joint.*.velocity", "identity"),
    ("q.squat.joint-reference-angle", "joint.*.reference", "identity"),
    ("q.squat.joint-torque", "joint.*.torque", "identity"),
    ("q.squat.segment-position", "body.*.position", "identity"),
    ("q.squat.segment-orientation", "body.*.quaternion", "identity"),
    ("q.squat.com-position", "com.position", "identity"),
    ("q.squat.com-velocity", "com.velocity", "identity"),
    ("q.squat.bar-position", "bar.position", "identity"),
    ("q.squat.bar-velocity", "bar.velocity", "identity"),
    ("q.squat.bar-tilt", "bar.tilt", "identity"),
    ("q.squat.ground-reaction-force", "grf", "identity"),
    ("q.squat.vertical-grf-ratio", "grf", "vertical-over-weight"),
    ("q.squat.planned-vertical-grf", "plan.vertical_grf", "identity"),
    ("q.squat.centre-of-pressure", "cop", "identity"),
    ("q.squat.cop-margin", "margin.cop", "identity"),
    ("q.squat.xcom-margin", "margin.xcom", "identity"),
    ("q.squat.plantar-normal-load", "contact.*.normal", "identity"),
    ("q.squat.plantar-contact-position", "contact.*.position", "identity"),
    ("q.squat.friction-utilization", "contact.*", "friction-utilization"),
    ("q.squat.plantar-load-minimum", "contact.*.normal", "minimum-over-channels"),
    ("q.squat.loaded-contact-count", "contact.*.normal", "count-above-5n"),
    ("q.squat.friction-utilization-peak", "contact.*", "friction-utilization-peak"),
    ("q.squat.heel-load-share", "contact.*.normal", "heel-share-per-foot"),
    ("q.squat.heel-load-share-lesser-foot", "contact.*.normal", "heel-share-lesser-foot"),
    ("q.squat.sole-point-slip", "contact.*.position", "displacement-from-start-maximum"),
    ("q.squat.knee-flexion-left", "joint.knee_flexion_l.angle", "identity"),
    ("q.squat.lumbar-flexion", "joint.lumbar_flexion.angle", "identity"),
    ("q.squat.knee-extensor-moment-left", "joint.knee_flexion_l.torque", "negate"),
    ("q.squat.com-anterior", "com.position.x", "identity"),
    ("q.squat.actuator-power", "actuator.power", "identity"),
    ("q.squat.shelf-force", "shelf.force", "identity"),
    ("q.squat.activation-peak", "actuator.activation_peak", "identity"),
    ("q.squat.trunk-inclination", "trunk.inclination", "identity"),
    ("q.squat.pelvis-height", "pelvis.height", "identity"),
    ("q.squat.depth-intent", "intent.depth", "identity"),
    ("q.squat.commanded-phase", "phase.commanded", "identity"),
)
"""(canonical quantity, native source, normalization transform) for every published series."""


def realization_definition(
    *,
    asset_sha256: str = contract.MODEL_SHA256,
    asset_path: str = pins.MODEL_SOURCE_PATH,
) -> RealizationDefinition:
    """The compiled squat realization: the packaged model and its controller, in MuJoCo."""
    return RealizationDefinition(
        realization_id=RealizationId(pins.REALIZATION_ID),
        version=pins.REALIZATION_VERSION,
        label="MuJoCo torque-driven barbell back squat",
        description=(
            "The generated MJCF athlete-barbell model, its postural controller with a dynamic "
            "internal model, and the synchronized measurement layer, executed in the isolated "
            "MuJoCo worker."
        ),
        benchmark=BenchmarkRef(
            identifier=BenchmarkId(pins.BENCHMARK_ID), version=pins.BENCHMARK_VERSION
        ),
        engine=EngineBinding(engine="mujoco", specifier=_exact(contract.ENGINE_VERSION)),
        capabilities=(
            CapabilityDeclaration(
                capability=Capability.FORWARD_DYNAMICS,
                summary="closed-loop MuJoCo forward dynamics of one squat repetition",
                limitations=(
                    "One compiled model; configuration only within the declared factor "
                    "supports; no arbitrary model loading or interactive stepping.",
                ),
            ),
        ),
        quantity_mappings=tuple(_mapping(*entry) for entry in QUANTITY_MAPPINGS),
        engine_configuration=(
            ConfigurationEntry(name="integrator", value="implicitfast"),
            ConfigurationEntry(name="solver", value="Newton"),
            ConfigurationEntry(name="cone", value="elliptic"),
            ConfigurationEntry(name="sample-rate-hz", value="100"),
            ConfigurationEntry(name="model", value="barbell-back-squat"),
            ConfigurationEntry(name="precision", value="float64"),
            ConfigurationEntry(name="seed-policy", value="no-stochastic-process"),
        ),
        assets=(
            AssetReference(
                asset_id="squat-model",
                path=asset_path,
                description="Generated MJCF of the athlete and barbell (see mjcf.py).",
                sha256=asset_sha256,
            ),
        ),
        known_discrepancies=(
            "Synthetic, population-scaled model; not validated against measured motion.",
        ),
    )


def system_under_test(*, asset_sha256: str = contract.MODEL_SHA256) -> SUTDefinition:
    """The athlete-barbell model with its controller is the object under test."""
    return SUTDefinition(
        sut_id=SUTId(pins.SUT_ID),
        version=pins.SUT_VERSION,
        label="Synthetic athlete and barbell with postural controller",
        description=(
            "The packaged model and its controller. The controller code is bound by the adapter "
            "implementation digest; the model bytes by this build digest."
        ),
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


def environment_definition(*, platform_tag: str) -> EnvironmentDefinition:
    """The isolated MuJoCo worker environment of one qualified platform."""
    lower, upper = pins.PYTHON_SERIES
    return EnvironmentDefinition(
        environment_id=EnvironmentId(pins.environment_id_for(platform_tag)),
        version=pins.ENVIRONMENT_VERSION,
        label=f"MuJoCo {contract.ENGINE_VERSION} squat environment on {platform_tag}",
        description=(
            "The locked worker-mujoco environment: MuJoCo, NumPy and PyArrow pinned by its "
            f"uv.lock, CPython 3.12, on {platform_tag}. The exact CPython patch and dependency "
            "closure are bound into the adapter implementation digest of every run."
        ),
        requirements=(
            EnvironmentRequirement(
                component="mujoco",
                kind=ComponentKind.ENGINE,
                specifier=_exact(contract.ENGINE_VERSION),
                purpose="The native engine release the worker verifies before a step.",
            ),
            EnvironmentRequirement(
                component="python",
                kind=ComponentKind.RUNTIME,
                specifier=VersionSpecifier(
                    clauses=(
                        VersionClause(comparator=Comparator.GREATER_THAN_OR_EQUAL, version=lower),
                        VersionClause(comparator=Comparator.LESS_THAN, version=upper),
                    )
                ),
                purpose="CPython 3.12; the exact patch is recorded in the implementation digest.",
            ),
        ),
    )


def study_definition() -> StudyDefinition:
    """The configuration study: the qualified factor space of the squat realization."""
    factors = tuple(
        UncertaintyFactorDefinition(
            factor_id=FactorId(domain.factor_id),
            label=domain.label,
            description=(
                f"{domain.label}: a configuration parameter of the squat realization, "
                f"qualified over [{domain.lower:g}, {domain.upper:g}] {domain.unit}."
            ),
            role=FactorRole.FACTOR,
            quantity=QuantityId(domain.quantity_id),
            target=FactorTarget(
                kind=FactorTargetKind.REALIZATION,
                identifier=pins.REALIZATION_ID,
                parameter=domain.parameter,
            ),
            distribution=UniformRange(lower=domain.lower, upper=domain.upper),
        )
        for domain in pins.FACTOR_DOMAINS
    )
    return StudyDefinition(
        study_id=StudyId(pins.STUDY_ID),
        version=pins.STUDY_VERSION,
        label="Back-squat configuration study",
        description=(
            "Runs of the squat realization at researcher-chosen configurations within the "
            "qualified factor space."
        ),
        research_question=(
            "How do depth, tempo, integration timestep, internal-model gain and sole friction "
            "change the kinematics, kinetics, contact and balance of one repetition, and do "
            "the predeclared mechanical criteria hold?"
        ),
        analysis_plan=(
            "Each run is normalized to the release's canonical quantities, numerically "
            "verified from those quantities alone, and assessed against the release metrics; "
            "runs are compared channel by channel on the common 10 ms grid."
        ),
        replicates=1,
        benchmarks=(
            BenchmarkRef(identifier=BenchmarkId(pins.BENCHMARK_ID), version=pins.BENCHMARK_VERSION),
        ),
        realizations=(
            RealizationRef(
                identifier=RealizationId(pins.REALIZATION_ID), version=pins.REALIZATION_VERSION
            ),
        ),
        systems_under_test=(SUTRef(identifier=SUTId(pins.SUT_ID), version=pins.SUT_VERSION),),
        environments=tuple(
            EnvironmentRef(
                identifier=EnvironmentId(pins.environment_id_for(tag)),
                version=pins.ENVIRONMENT_VERSION,
            )
            for tag in sorted(pins.ENVIRONMENT_SEMANTIC_DIGESTS)
        ),
        required_capabilities=(
            CapabilityRequirement(
                capability=Capability.FORWARD_DYNAMICS,
                essential=True,
                rationale="Every run is a forward-dynamics rollout.",
            ),
        ),
        factors=factors,
        outcomes=(pins.OUTCOME,),
        seeds=(pins.SEED,),
    )


def factor_case(case_id: str, values: dict[str, float]) -> FactorCase:
    """A factor case assigning every configuration factor (missing ones take the nominal)."""
    nominal = {domain.factor_id: domain.nominal for domain in pins.FACTOR_DOMAINS}
    unknown = sorted(set(values) - set(nominal))
    if unknown:
        raise pins.SquatAuthorityError(f"unknown squat configuration factors: {unknown}")
    merged = {**nominal, **values}
    return FactorCase(
        case_id=case_id,
        values=tuple(
            FactorValue(factor_id=FactorId(factor_id), value=value)
            for factor_id, value in sorted(merged.items())
        ),
    )


def nominal_factor_case() -> FactorCase:
    """The nominal configuration: the qualified parallel-depth repetition."""
    return factor_case("nominal", {})


def authority_digests() -> dict[str, str]:
    """Recompute every pinned digest from these definitions, for the tool and the tests."""
    return {
        "benchmark": semantic_sha256(benchmark_release()).hex,
        "scenario": semantic_sha256(scenario_definition()).hex,
        "realization": semantic_sha256(realization_definition()).hex,
        "system_under_test": semantic_sha256(system_under_test()).hex,
        **{
            f"environment_{tag.replace('-', '_')}": semantic_sha256(
                environment_definition(platform_tag=tag)
            ).hex
            for tag in sorted(pins.ENVIRONMENT_SEMANTIC_DIGESTS)
        },
    }


SAMPLE_PERIOD_S: Final = 0.01
"""The canonical sample period; a configured timestep must divide it exactly."""


@dataclass(frozen=True, slots=True)
class SquatConfiguration:
    """One admissible configuration of the squat realization, in canonical SI units."""

    bottom_knee_flexion_rad: float
    descent_s: float
    ascent_s: float
    timestep_s: float
    internal_model_gain: float
    sole_friction_time_constant_s: float

    def as_json_object(self) -> dict[str, float]:
        return {
            "bottom_knee_flexion_rad": self.bottom_knee_flexion_rad,
            "descent_s": self.descent_s,
            "ascent_s": self.ascent_s,
            "timestep_s": self.timestep_s,
            "internal_model_gain": self.internal_model_gain,
            "sole_friction_time_constant_s": self.sole_friction_time_constant_s,
        }


_PARAMETER_FIELDS: Final = {
    "bottom-knee-flexion": "bottom_knee_flexion_rad",
    "descent-duration": "descent_s",
    "ascent-duration": "ascent_s",
    "timestep": "timestep_s",
    "internal-model-gain": "internal_model_gain",
    "sole-friction-time-constant": "sole_friction_time_constant_s",
}


def timestep_divides_sample_period(timestep_s: float) -> bool:
    """Whether ``timestep_s`` divides the 10 ms canonical sample period exactly."""
    if not (timestep_s > 0.0 and math.isfinite(timestep_s)):
        return False
    steps = round(SAMPLE_PERIOD_S / timestep_s)
    return steps >= 1 and abs(steps * timestep_s - SAMPLE_PERIOD_S) <= 1e-12


def configuration_from_values(values: dict[str, float]) -> SquatConfiguration:
    """Validate one factor-id -> value mapping against the qualified domain, or refuse.

    Every configuration factor must be present exactly once and lie inside its qualified
    range; the timestep must also divide the 10 ms sample period, because a snapshot is never
    interpolated between steps. Nothing is clipped or snapped.
    """
    domains = {domain.factor_id: domain for domain in pins.FACTOR_DOMAINS}
    missing = sorted(set(domains) - set(values))
    extra = sorted(set(values) - set(domains))
    if missing or extra:
        raise pins.SquatAuthorityError(
            f"the configuration must assign exactly the squat factors (missing {missing}, "
            f"unknown {extra})"
        )
    fields: dict[str, float] = {}
    for factor_id, domain in domains.items():
        value = float(values[factor_id])
        if not (math.isfinite(value) and domain.lower <= value <= domain.upper):
            raise pins.SquatAuthorityError(
                f"{domain.label} {value!r} lies outside the qualified range "
                f"[{domain.lower:g}, {domain.upper:g}] {domain.unit}"
            )
        fields[_PARAMETER_FIELDS[domain.parameter]] = value
    configuration = SquatConfiguration(**fields)
    if not timestep_divides_sample_period(configuration.timestep_s):
        raise pins.SquatAuthorityError(
            f"the integration timestep {configuration.timestep_s!r} s does not divide the 10 ms "
            "sample period exactly; snapshots are never interpolated between steps"
        )
    return configuration


def configuration_from_assignments(assignments: Sequence[FactorAssignment]) -> SquatConfiguration:
    """Read a RunSpec's factor assignments as a squat configuration, refusing any deviation.

    Each assignment must name a declared squat factor with its declared quantity, canonical
    unit and realization target parameter; only then is its value admitted.
    """
    domains = {domain.factor_id: domain for domain in pins.FACTOR_DOMAINS}
    values: dict[str, float] = {}
    for assignment in assignments:
        factor_id = str(assignment.factor_id)
        domain = domains.get(factor_id)
        if domain is None:
            raise pins.SquatAuthorityError(f"factor {factor_id!r} is not a squat factor")
        if factor_id in values:
            raise pins.SquatAuthorityError(f"factor {factor_id!r} is assigned twice")
        target = assignment.target
        if (
            str(assignment.quantity) != domain.quantity_id
            or assignment.unit.expression != CanonicalUnit(expression=domain.unit).expression
            or target.kind is not FactorTargetKind.REALIZATION
            or str(target.identifier) != pins.REALIZATION_ID
            or target.parameter != domain.parameter
        ):
            raise pins.SquatAuthorityError(
                f"factor {factor_id!r} does not carry the declared quantity, unit and "
                "realization parameter"
            )
        values[factor_id] = assignment.value
    return configuration_from_values(values)
