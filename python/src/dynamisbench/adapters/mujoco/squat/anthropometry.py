"""Declared anthropometry, joint and barbell authority of the barbell back-squat model.

Pure Python: no MuJoCo, no NumPy, no filesystem. Every number that shapes the mechanics of
the model is stated here once, with its source, and the MJCF generator
(:mod:`~dynamisbench.adapters.mujoco.squat.mjcf`) only renders what this module computes.

Subject
-------
A synthetic adult male athlete, body mass 75 kg and stature 1.75 m, carrying an empty
men's Olympic barbell (20 kg) in the high-bar back-squat position. The athlete is
synthetic: no individual was measured, and the parameters below are population-level
regressions, not a subject calibration.

Sources and how they are combined
---------------------------------
* **Segment mass fractions, centre-of-mass locations and radii of gyration**: de Leva P.
  (1996) *Adjustments to Zatsiorsky-Seluyanov's segment inertia parameters*, J. Biomech.
  29(9):1223-1230, Table 4 (males), including the three-part trunk subdivision.
* **Vertical landmark heights**: Drillis R. & Contini R. (1966) stature-proportional
  segment model as tabulated by Winter D.A. (2009) *Biomechanics and Motor Control of
  Human Movement*, 4th ed., Fig. 4.1 (ankle 0.039 H, shoulder 0.818 H, foot length
  0.152 H, foot breadth 0.055 H).
* **Segment lengths** not fixed by those heights are de Leva's male lengths scaled by
  ``stature / 1.741 m`` (de Leva's reference male stature).
* **Hip joint centres**: Bell A.L., Pedersen D.R. & Brand R.A. (1990) J. Biomech.
  23(6):617-621, 36 % of an inter-ASIS breadth of 0.245 m lateral of the pelvic midline.

Combining a length-based table with a stature-based table cannot be exactly consistent.
The reconciliation is explicit: the leg and head lengths come from de Leva, the ankle
height from Drillis & Contini, and the trunk takes the remainder so that the vertex height
in the anatomical zero posture equals the declared stature. The resulting trunk is 4.4 %
shorter than the scaled de Leva trunk; its radii of gyration are applied to the model
length, so segment mass is exact and inertia is consistent with the model geometry.

Frames and sign conventions
---------------------------
World and every body frame in the anatomical zero posture: ``x`` anterior, ``y`` left,
``z`` up (right-handed). Every body frame has its origin at the body's proximal joint
centre, except the pelvis (origin at the mid-hip point, the midpoint of the hip joint
centres) and the barbell (origin at its geometric centre, long axis ``y``).

Each hinge axis is chosen so that a **positive angle is the named anatomical direction on
both sides** (flexion, adduction, internal rotation, dorsiflexion, inversion; leftward
bending and leftward rotation for the spine and neck). Left/right mirror pairs therefore
flip the ``x`` and ``z`` components of frontal- and transverse-plane axes.

Joint ranges of motion are representative adult normative values (American Academy of
Orthopaedic Surgeons, Greene & Heckman 1994; Soucie et al. 2011 Haemophilia 17:500-507),
except weight-bearing ankle dorsiflexion (Bennell et al. 1998 lunge test), which governs
squat depth, and the spine (White & Panjabi 1990; Troke et al. 2005). Joint torque
capacities are representative peak isometric values for a resistance-trained adult male
from dynamometry literature (e.g. Anderson, Madigan & Nussbaum 2007 J. Biomech.
40:3105-3113; Harbo, Brincks & Andersen 2012 Eur. J. Appl. Physiol. 112:267-275; McGill
1997 for trunk extension). They bound the actuators; they are not calibrated to a person
and the model does not yet represent torque-angle or torque-velocity dependence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

__all__ = [
    "ANKLE_HEIGHT_FRACTION",
    "BARBELL",
    "BODY_MASS_KG",
    "DE_LEVA_MALE",
    "DE_LEVA_REFERENCE_STATURE_M",
    "GRAVITY_M_S2",
    "STATURE_M",
    "BarbellPart",
    "BarbellSpec",
    "DeLevaSegment",
    "Geometry",
    "JointSpec",
    "SegmentInertia",
    "barbell_inertia",
    "geometry",
    "joint_specs",
    "segment_inertias",
]

BODY_MASS_KG: Final = 75.0
STATURE_M: Final = 1.75
GRAVITY_M_S2: Final = 9.80665
"""Standard gravity (ISO 80000-3), along world -z."""

DE_LEVA_REFERENCE_STATURE_M: Final = 1.741
"""Mean stature of de Leva's (1996) male reference sample; the length scale denominator."""

ANKLE_HEIGHT_FRACTION: Final = 0.039
"""Ankle joint height / stature (Drillis & Contini 1966, Winter 2009 Fig. 4.1)."""
SHOULDER_HEIGHT_FRACTION: Final = 0.818
"""Shoulder (glenohumeral) height / stature (Drillis & Contini 1966, Winter 2009 Fig. 4.1)."""
FOOT_BREADTH_FRACTION: Final = 0.055
"""Foot breadth / stature (Drillis & Contini 1966, Winter 2009 Fig. 4.1)."""

HIP_JOINT_HALF_WIDTH_M: Final = 0.36 * 0.245
"""Bell et al. (1990): hip joint centre 36 % of inter-ASIS breadth lateral of the midline."""
SHOULDER_JOINT_HALF_WIDTH_M: Final = 0.18
"""Half the distance between glenohumeral centres: a biacromial breadth of 0.40 m (adult
male population mean for this stature) less 0.02 m from acromion tip to joint centre."""
SHOULDER_JOINT_ANTERIOR_M: Final = 0.03
"""The glenohumeral centre lies anterior of the CERV-MIDH trunk axis, whose top landmark
(cervicale, the C7 spinous process) is a posterior skin point."""

HEEL_FRACTION_OF_FOOT: Final = 0.22
"""Horizontal distance ankle-joint-centre to heel as a fraction of foot length. Modelling
assumption typical of adult feet (the ankle lies over the posterior quarter of the foot)."""
FIRST_METATARSAL_HEAD_FRACTION: Final = 0.72
FIFTH_METATARSAL_HEAD_FRACTION: Final = 0.63
"""Metatarsal head positions measured from the heel as a fraction of foot length."""
SOLE_CONTACT_RADIUS_M: Final = 0.012
"""Radius of each plantar contact sphere (heel pad / metatarsal pad / hallux pulp)."""


@dataclass(frozen=True, slots=True)
class DeLevaSegment:
    """One row of de Leva (1996) Table 4, males.

    ``com_fraction`` is measured from ``origin`` towards ``insertion``; radii are fractions
    of the segment length about the sagittal (antero-posterior), transverse
    (medio-lateral) and longitudinal axes, in that order.
    """

    origin: str
    insertion: str
    length_mm: float
    mass_fraction: float
    com_fraction: float
    radius_sagittal: float
    radius_transverse: float
    radius_longitudinal: float


DE_LEVA_MALE: Final[dict[str, DeLevaSegment]] = {
    "head": DeLevaSegment("VERT", "CERV", 242.9, 0.0694, 0.5976, 0.362, 0.376, 0.312),
    "torso_upper": DeLevaSegment("CERV", "XYPH", 242.1, 0.1596, 0.2999, 0.716, 0.454, 0.659),
    "torso_middle": DeLevaSegment("XYPH", "OMPH", 215.5, 0.1633, 0.4502, 0.482, 0.383, 0.468),
    "pelvis": DeLevaSegment("OMPH", "MIDH", 145.7, 0.1117, 0.6115, 0.615, 0.551, 0.587),
    "upper_arm": DeLevaSegment("SJC", "EJC", 281.7, 0.0271, 0.5772, 0.285, 0.269, 0.158),
    "forearm": DeLevaSegment("EJC", "WJC", 268.9, 0.0162, 0.4574, 0.276, 0.265, 0.121),
    "hand": DeLevaSegment("WJC", "MET3", 86.2, 0.0061, 0.7900, 0.628, 0.513, 0.401),
    "thigh": DeLevaSegment("HJC", "KJC", 422.2, 0.1416, 0.4095, 0.329, 0.329, 0.149),
    "shank": DeLevaSegment("KJC", "LMAL", 434.0, 0.0433, 0.4459, 0.255, 0.249, 0.103),
    "foot": DeLevaSegment("HEEL", "TTIP", 258.1, 0.0137, 0.4415, 0.257, 0.245, 0.124),
}
"""de Leva (1996) Table 4, males. ``pelvis`` is de Leva's lower trunk (LPT)."""

_TRUNK_PARTS: Final = ("pelvis", "torso_middle", "torso_upper")


@dataclass(frozen=True, slots=True)
class Geometry:
    """Every length of the model, in metres, derived once from stature."""

    length_scale: float
    ankle_height: float
    shank: float
    thigh: float
    hip_height: float
    head: float
    trunk: float
    pelvis: float
    torso_middle: float
    torso_upper: float
    cervicale_height: float
    shoulder_height: float
    upper_arm: float
    forearm: float
    hand: float
    foot: float
    foot_breadth: float
    heel_offset: float
    hip_half_width: float
    shoulder_half_width: float
    shoulder_anterior: float


def geometry(stature_m: float = STATURE_M) -> Geometry:
    """Compute every model length from stature (see the module docstring for sources)."""
    if not math.isfinite(stature_m) or stature_m <= 0.0:
        raise ValueError("stature must be a finite positive length")
    scale = stature_m / DE_LEVA_REFERENCE_STATURE_M

    def scaled(name: str) -> float:
        return DE_LEVA_MALE[name].length_mm / 1000.0 * scale

    ankle_height = ANKLE_HEIGHT_FRACTION * stature_m
    shank = scaled("shank")
    thigh = scaled("thigh")
    head = scaled("head")
    hip_height = ankle_height + shank + thigh
    trunk = stature_m - hip_height - head
    de_leva_trunk_mm = sum(DE_LEVA_MALE[name].length_mm for name in _TRUNK_PARTS)
    parts = {name: trunk * DE_LEVA_MALE[name].length_mm / de_leva_trunk_mm for name in _TRUNK_PARTS}
    foot = scaled("foot")
    return Geometry(
        length_scale=scale,
        ankle_height=ankle_height,
        shank=shank,
        thigh=thigh,
        hip_height=hip_height,
        head=head,
        trunk=trunk,
        pelvis=parts["pelvis"],
        torso_middle=parts["torso_middle"],
        torso_upper=parts["torso_upper"],
        cervicale_height=hip_height + trunk,
        shoulder_height=SHOULDER_HEIGHT_FRACTION * stature_m,
        upper_arm=scaled("upper_arm"),
        forearm=scaled("forearm"),
        hand=scaled("hand"),
        foot=foot,
        foot_breadth=FOOT_BREADTH_FRACTION * stature_m,
        heel_offset=HEEL_FRACTION_OF_FOOT * foot,
        hip_half_width=HIP_JOINT_HALF_WIDTH_M,
        shoulder_half_width=SHOULDER_JOINT_HALF_WIDTH_M,
        shoulder_anterior=SHOULDER_JOINT_ANTERIOR_M,
    )


@dataclass(frozen=True, slots=True)
class SegmentInertia:
    """Mass, centre of mass and principal inertia of one body, in its body frame.

    Principal axes coincide with the body frame axes in the anatomical zero posture.
    """

    body: str
    segment: str
    mass: float
    com: tuple[float, float, float]
    inertia: tuple[float, float, float]


def _principal(mass: float, length: float, row: DeLevaSegment) -> tuple[float, float, float]:
    """(Ixx, Iyy, Izz) of a vertical segment: x antero-posterior, y medio-lateral, z long."""
    return (
        mass * (row.radius_sagittal * length) ** 2,
        mass * (row.radius_transverse * length) ** 2,
        mass * (row.radius_longitudinal * length) ** 2,
    )


def segment_inertias(
    body_mass_kg: float = BODY_MASS_KG,
    stature_m: float = STATURE_M,
) -> tuple[SegmentInertia, ...]:
    """Inertial properties of every body of the athlete, left and right limbs explicit.

    Centre-of-mass positions are on the segment's longitudinal axis at de Leva's fraction,
    expressed in the body frame (origin at the proximal joint centre). The foot is the one
    horizontal segment: its longitudinal axis is ``x`` and its centre of mass is placed
    midway between the ankle joint centre and the sole.
    """
    if not math.isfinite(body_mass_kg) or body_mass_kg <= 0.0:
        raise ValueError("body mass must be a finite positive mass")
    g = geometry(stature_m)
    rows = DE_LEVA_MALE

    def mass(name: str) -> float:
        return rows[name].mass_fraction * body_mass_kg

    result: list[SegmentInertia] = []
    # Trunk and head: the pelvis frame is at the mid-hip point; each part above it has its
    # frame at its lower joint centre. de Leva measures these CoM fractions from the
    # *upper* landmark, so the height above the lower end is (1 - fraction) * length.
    for body, length in (
        ("pelvis", g.pelvis),
        ("torso_middle", g.torso_middle),
        ("torso_upper", g.torso_upper),
        ("head", g.head),
    ):
        row = rows[body]
        m = mass(body)
        result.append(
            SegmentInertia(
                body=body,
                segment=body,
                mass=m,
                com=(0.0, 0.0, (1.0 - row.com_fraction) * length),
                inertia=_principal(m, length, row),
            )
        )
    for side in ("l", "r"):
        for segment, length in (
            ("upper_arm", g.upper_arm),
            ("forearm", g.forearm),
            ("hand", g.hand),
            ("thigh", g.thigh),
            ("shank", g.shank),
        ):
            row = rows[segment]
            m = mass(segment)
            result.append(
                SegmentInertia(
                    body=f"{segment}_{side}",
                    segment=segment,
                    mass=m,
                    com=(0.0, 0.0, -row.com_fraction * length),
                    inertia=_principal(m, length, row),
                )
            )
        row = rows["foot"]
        m = mass("foot")
        # Horizontal segment: longitudinal axis x; medio-lateral y; vertical z.
        result.append(
            SegmentInertia(
                body=f"foot_{side}",
                segment="foot",
                mass=m,
                com=(
                    row.com_fraction * g.foot - g.heel_offset,
                    0.0,
                    -0.5 * g.ankle_height,
                ),
                inertia=(
                    m * (row.radius_longitudinal * g.foot) ** 2,
                    m * (row.radius_transverse * g.foot) ** 2,
                    m * (row.radius_sagittal * g.foot) ** 2,
                ),
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class JointSpec:
    """One actuated anatomical hinge.

    ``range_deg`` is (lower, upper) in the positive anatomical direction convention.
    ``torque_nm`` is (capacity in the negative direction, capacity in the positive
    direction), both positive magnitudes. ``damping`` is passive joint viscosity.
    """

    name: str
    body: str
    axis: tuple[float, float, float]
    range_deg: tuple[float, float]
    torque_nm: tuple[float, float]
    damping: float


HUMEROTHORACIC_EXTERNAL_ROTATION_DEG: Final = 110.0
"""External-rotation limit of the lumped shoulder. The model has no scapula, so its shoulder
is a humerothoracic joint: its rotation range is glenohumeral rotation (90 deg, AAOS) plus
the scapular posterior tilt and retraction that accompany it. The back-squat grip needs about
100 deg of it; a 90 deg limit forces the elbows in front of the shoulders, which is not how
the bar is held."""

SAGITTAL_INTRINSIC_DAMPING: Final = 5.0
"""Intrinsic viscosity of the large sagittal-plane joints (ankle, knee, hip flexion, lumbar
and thoracic flexion), N m s/rad: the instantaneous, delay-free viscous response of tonically
active muscle (order of intrinsic ankle viscosity in stance, e.g. Kearney & Hunter 1990;
Loram & Lakie 2002). Closed-loop eigen-analysis and forward simulation of this model show the
standing posture needs at least 3 N m s/rad here: the light pelvis segment between the hip
and lumbar actuators otherwise oscillates through the activation lag."""
LARGE_JOINT_DAMPING: Final = 1.0
"""Passive viscosity of the other hip, spine and subtalar axes, N m s/rad (order of measured
passive joint damping, e.g. Riener & Edrich 1999 J. Biomech. 32:539-544)."""
SMALL_JOINT_DAMPING: Final = 0.3
"""Passive viscosity of the neck, shoulder and elbow, N m s/rad."""


def joint_specs() -> tuple[JointSpec, ...]:
    """Every actuated hinge of the model, in kinematic-tree order.

    Multi-axis anatomical joints are serial hinges applied in the listed order (for the
    hip: flexion, then adduction, then internal rotation, the ISB/OpenSim convention).
    """
    sagittal = SAGITTAL_INTRINSIC_DAMPING
    large = LARGE_JOINT_DAMPING
    small = SMALL_JOINT_DAMPING
    specs: list[JointSpec] = [
        JointSpec("lumbar_flexion", "torso_middle", (0, 1, 0), (-25, 50), (300, 200), sagittal),
        JointSpec("lumbar_bending", "torso_middle", (-1, 0, 0), (-25, 25), (200, 200), large),
        JointSpec("lumbar_rotation", "torso_middle", (0, 0, 1), (-10, 10), (100, 100), large),
        JointSpec("thoracic_flexion", "torso_upper", (0, 1, 0), (-20, 35), (250, 150), sagittal),
        JointSpec("thoracic_bending", "torso_upper", (-1, 0, 0), (-20, 20), (150, 150), large),
        JointSpec("thoracic_rotation", "torso_upper", (0, 0, 1), (-30, 30), (80, 80), large),
        JointSpec("neck_flexion", "head", (0, 1, 0), (-60, 45), (50, 30), small),
        JointSpec("neck_bending", "head", (-1, 0, 0), (-40, 40), (30, 30), small),
        JointSpec("neck_rotation", "head", (0, 0, 1), (-70, 70), (25, 25), small),
    ]
    for side, mirror in (("l", 1.0), ("r", -1.0)):
        specs += [
            JointSpec(
                f"shoulder_flexion_{side}",
                f"upper_arm_{side}",
                (0, -1, 0),
                (-60, 180),
                (110, 100),
                small,
            ),
            JointSpec(
                f"shoulder_abduction_{side}",
                f"upper_arm_{side}",
                (mirror, 0, 0),
                (-30, 180),
                (110, 90),
                small,
            ),
            JointSpec(
                f"shoulder_rotation_{side}",
                f"upper_arm_{side}",
                (0, 0, -mirror),
                (-HUMEROTHORACIC_EXTERNAL_ROTATION_DEG, 70),
                (50, 50),
                small,
            ),
            JointSpec(
                f"elbow_flexion_{side}", f"forearm_{side}", (0, -1, 0), (0, 150), (65, 80), small
            ),
        ]
    for side, mirror in (("l", 1.0), ("r", -1.0)):
        specs += [
            JointSpec(
                f"hip_flexion_{side}", f"thigh_{side}", (0, -1, 0), (-30, 125), (300, 200), sagittal
            ),
            JointSpec(
                f"hip_adduction_{side}",
                f"thigh_{side}",
                (-mirror, 0, 0),
                (-45, 30),
                (170, 170),
                large,
            ),
            JointSpec(
                f"hip_rotation_{side}",
                f"thigh_{side}",
                (0, 0, -mirror),
                (-45, 45),
                (90, 80),
                large,
            ),
            JointSpec(
                f"knee_flexion_{side}", f"shank_{side}", (0, 1, 0), (-5, 150), (300, 150), sagittal
            ),
            JointSpec(
                f"ankle_dorsiflexion_{side}",
                f"foot_{side}",
                (0, -1, 0),
                (-50, 40),
                (200, 60),
                sagittal,
            ),
            JointSpec(
                f"subtalar_inversion_{side}",
                f"foot_{side}",
                (-mirror, 0, 0),
                (-20, 30),
                (50, 50),
                large,
            ),
        ]
    return tuple(specs)


@dataclass(frozen=True, slots=True)
class BarbellPart:
    """One coaxial cylindrical part of the barbell, centred at ``y`` on the bar axis."""

    name: str
    outer_radius: float
    inner_radius: float
    length: float
    center_y: float


@dataclass(frozen=True, slots=True)
class BarbellSpec:
    """An empty men's Olympic barbell (IWF Technical and Competition Rules, Section 2.2).

    Total length 2.20 m, grip-section shaft diameter 28 mm over 1.31 m between the inner
    collars, 30 mm collars, 0.415 m sleeves of 50 mm diameter, mass 20 kg. The mass is
    distributed over the parts in proportion to their solid volume and the uniform density
    is then scaled so the total is exactly the declared mass.
    """

    mass: float
    parts: tuple[BarbellPart, ...]
    grip_half_width: float
    """Distance of each hand's grip centre from the bar centre. 0.48 m (hands 0.96 m apart)
    places the index fingers just outside the 0.91 m IWF knurl rings, a common grip for the
    high-bar squat that lets the forearms stay near vertical under the bar."""
    shelf_offset: tuple[float, float, float]
    """Bar-centre position in the upper-trunk frame relative to cervicale: resting on the
    upper trapezius (high-bar position), posterior to and just below C7."""
    collar_radius: float


BARBELL: Final = BarbellSpec(
    mass=20.0,
    parts=(
        BarbellPart("shaft", 0.014, 0.0, 2.20, 0.0),
        BarbellPart("collar_l", 0.035, 0.014, 0.030, 0.670),
        BarbellPart("collar_r", 0.035, 0.014, 0.030, -0.670),
        BarbellPart("sleeve_l", 0.025, 0.014, 0.415, 0.8925),
        BarbellPart("sleeve_r", 0.025, 0.014, 0.415, -0.8925),
    ),
    grip_half_width=0.48,
    shelf_offset=(-0.035, 0.0, -0.03),
    collar_radius=0.035,
)


def barbell_inertia(spec: BarbellSpec = BARBELL) -> tuple[float, tuple[float, float, float]]:
    """Return ``(mass, (Ixx, Iyy, Izz))`` of the barbell about its centre; ``y`` is the axis.

    Each part is a thick-walled coaxial cylinder; transverse moments use the parallel-axis
    theorem along the bar. The result is exactly symmetric, so the centre of mass is the
    geometric centre.
    """
    volumes = [
        math.pi * (part.outer_radius**2 - part.inner_radius**2) * part.length for part in spec.parts
    ]
    density = spec.mass / sum(volumes)
    axial = 0.0
    transverse = 0.0
    for part, volume in zip(spec.parts, volumes, strict=True):
        m = density * volume
        r2 = part.outer_radius**2 + part.inner_radius**2
        axial += 0.5 * m * r2
        transverse += m * (3.0 * r2 + part.length**2) / 12.0 + m * part.center_y**2
    return spec.mass, (transverse, axial, transverse)
