"""Deterministic MJCF rendering of the barbell back-squat model.

Pure Python. The renderer turns the declared authority in
:mod:`~dynamisbench.adapters.mujoco.squat.anthropometry` into one MJCF document, byte for byte
reproducibly: the same inputs always produce the same bytes on every platform. The packaged
asset ``assets/barbell_back_squat.xml`` is exactly ``render_model_xml(keyframe)`` for the
committed standing keyframe, and a test proves it.

Modelling decisions encoded here (each is a declared simplification, not a hidden one):

* **Inertia is explicit.** ``inertiafromgeom="false"``: every body's mass, centre of mass and
  principal inertia come from de Leva via ``<inertial>``; geoms are shape only.
* **Joints are serial hinges with hard anatomical limits** (MuJoCo soft limit constraints).
  The knee is a pure hinge (no roll-back), the subtalar axis is simplified to the foot's
  antero-posterior axis, and the wrist is rigid.
* **Actuators are joint torque generators with first-order activation dynamics.** Control is a
  normalised neural excitation in [-1, 1]; activation follows it with time constant
  :data:`ACTIVATION_TIME_CONSTANT_S`; torque is activation times the joint's peak capacity
  and is clamped to the asymmetric capacities declared per direction.
* **Contact**: only the floor collides with the body and the bar (no self-collision). Each
  foot touches the floor through five plantar spheres (two heel, first and fifth metatarsal
  head, hallux), declared as explicit contact pairs so that their friction directions have
  their own reference dynamics; the other body geoms would only meet the floor in a fall.
* **Barbell coupling**: the bar is a free rigid body. A near-rigid weld equality holds the bar
  centre on the upper-trapezius shelf and a connect equality at each hand holds the grip.
  Coupling forces are therefore real constraint forces that the solver reports, not an
  implicit mass merge; the arms can pull the bar into the shelf or hang on it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

from dynamisbench.adapters.mujoco.squat import anthropometry as anth

__all__ = [
    "ACTIVATION_TIME_CONSTANT_S",
    "ACTUATED_JOINTS",
    "CONTACT_FRICTION",
    "FLOOR_GEOM",
    "FRICTION_SOLREF",
    "GRIP_SITES",
    "INTEGRATOR",
    "KEYFRAME_NAME",
    "MODEL_NAME",
    "NOSLIP_ITERATIONS",
    "SOLE_POINTS",
    "SOLVER_ITERATIONS",
    "SOLVER_TOLERANCE",
    "TIMESTEP_S",
    "render_model_xml",
]

MODEL_NAME: Final = "dynamisbench-barbell-back-squat"
KEYFRAME_NAME: Final = "stand"
TIMESTEP_S: Final = 0.001
INTEGRATOR: Final = "implicitfast"
SOLVER_ITERATIONS: Final = 100
SOLVER_TOLERANCE: Final = 1e-10
NOSLIP_ITERATIONS: Final = 10
"""Coulomb stiction at the soles. MuJoCo's friction is a soft velocity-level constraint, so
without the no-slip post-solver a sustained shear load creeps: measured on this model, the
feet of a wide stance slide apart at ~2 mm/s. Shod feet on a lifting platform do not creep;
with 10 no-slip iterations the feet seat by ~0.5 mm and then hold."""
ACTIVATION_TIME_CONSTANT_S: Final = 0.03
"""First-order excitation-to-activation time constant. Between reported muscle activation
(~10 ms) and deactivation (~40 ms) times (Zajac 1989; Thelen 2003)."""
CONTACT_FRICTION: Final = (0.9, 0.005, 0.0001)
"""Sliding, torsional and rolling friction of the sole-floor contact: rubber-soled lifting
shoe on a wooden platform (static coefficient ~0.8-1.0)."""
CONTACT_SOLREF: Final = (0.015, 1.0)
"""Sole-floor contact time constant and damping ratio: critically damped, settling to
~0.6-0.8 mm penetration under body weight. This is numerical contact stabilization, not a
calibrated model of plantar soft tissue (which compresses several millimetres)."""
FRICTION_SOLREF: Final = (0.002, 1.0)
"""Reference dynamics of the sole-floor *friction* directions (explicit contact pairs).

MuJoCo friction is a velocity servo: the tangential reference acceleration is ``-b v`` with
``b`` set by the time constant, and a slip velocity decays with that lag while the position
drift it leaves is never restored (no-slip iterations, cone type and integrator do not change
this). In quiet standing nothing drives it. In a squat the load moves continuously over the
soles, and with the normal-contact time constant (0.015 s) both feet slid 8.4 mm backwards in
one repetition while no contact used more than a quarter of its friction cone. With 0.002 s
(two timesteps, MuJoCo's stability floor) the same repetition slides 0.1 mm."""
BAR_SHELF_SOLREF: Final = (0.005, 1.0)
GRIP_SOLREF: Final = (0.005, 1.0)
LIMIT_SOLREF: Final = (0.005, 1.0)
LIMIT_SOLIMP: Final = (0.95, 0.99, 0.001)
"""Anatomical end-of-range stops. MuJoCo scales a limit's softness by the effective inertia of
its constraint row, which for the ankle and subtalar joints is the 1 kg foot while the load
that reaches the stop is the whole body. With MuJoCo's default limit softness a passive
collapse drove the subtalar joint 33 deg and the ankle 23 deg past their stops; with these
values the worst end-range excursion in the same collapse is ~2 deg (capsule/ligament give)."""
"""Bar-shelf weld and hand-grip connect: critically damped, time constant five timesteps
(MuJoCo needs at least two for stability). They make the coupling near-rigid; measured on
this model, 0.01 s let the couplings stretch up to ~0.1 m under full-strength random
excitation. The residual compliance is constraint stabilization, not a soft-tissue model."""
FLOOR_GEOM: Final = "floor"

ACTUATED_JOINTS: Final = tuple(spec.name for spec in anth.joint_specs())

GRIP_SITES: Final = (("grip_l", "bar_grip_l"), ("grip_r", "bar_grip_r"))

_BODY_CONTYPE: Final = 2
_BODY_CONAFFINITY: Final = 1
_FLOOR_CONTYPE: Final = 1
_FLOOR_CONAFFINITY: Final = 2
"""Collision filter: body-floor pairs collide ((2 & 2) != 0); body-body pairs never do
((2 & 1) == 0 both ways), so there is no self-collision and no bar-body collision."""


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("an MJCF number must be finite")
    text = format(value, ".10g")
    if text in ("-0", "-0.0"):
        return "0"
    return text


def _vec(values: Sequence[float]) -> str:
    return " ".join(_number(float(value)) for value in values)


def _sole_points(g: anth.Geometry) -> tuple[tuple[str, float, float], ...]:
    """(name, x, lateral offset) of the plantar contact spheres for a *left* foot.

    ``lateral offset`` is positive laterally; it is mirrored for the right foot.
    """
    r = anth.SOLE_CONTACT_RADIUS_M
    heel_x = -g.heel_offset + r + 0.008
    first_met_x = anth.FIRST_METATARSAL_HEAD_FRACTION * g.foot - g.heel_offset
    fifth_met_x = anth.FIFTH_METATARSAL_HEAD_FRACTION * g.foot - g.heel_offset
    hallux_x = g.foot - g.heel_offset - r - 0.005
    half_breadth = 0.5 * g.foot_breadth
    return (
        ("heel_lateral", heel_x, 0.022),
        ("heel_medial", heel_x, -0.022),
        ("met1", first_met_x, -(half_breadth - r)),
        ("met5", fifth_met_x, half_breadth - r - 0.006),
        ("hallux", hallux_x, -(half_breadth - r - 0.012)),
    )


SOLE_POINTS: Final = tuple(name for name, _x, _y in _sole_points(anth.geometry()))


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0

    def line(self, text: str) -> None:
        self.lines.append("  " * self.depth + text)

    def open(self, text: str) -> None:
        self.line(text)
        self.depth += 1

    def close(self, tag: str) -> None:
        self.depth -= 1
        self.line(f"</{tag}>")


def _inertial(w: _Writer, segment: anth.SegmentInertia) -> None:
    w.line(
        f'<inertial pos="{_vec(segment.com)}" mass="{_number(segment.mass)}" '
        f'diaginertia="{_vec(segment.inertia)}"/>'
    )


def _joints(w: _Writer, body: str) -> None:
    for spec in anth.joint_specs():
        if spec.body != body:
            continue
        w.line(
            f'<joint name="{spec.name}" type="hinge" axis="{_vec(spec.axis)}" '
            f'range="{_vec(spec.range_deg)}" damping="{_number(spec.damping)}"/>'
        )


def _capsule(w: _Writer, name: str, start: Sequence[float], end: Sequence[float], r: float) -> None:
    w.line(
        f'<geom name="{name}" class="segment" type="capsule" '
        f'fromto="{_vec((*start, *end))}" size="{_number(r)}"/>'
    )


def _arm(w: _Writer, side: str, g: anth.Geometry, inertia: dict[str, anth.SegmentInertia]) -> None:
    mirror = 1.0 if side == "l" else -1.0
    shoulder_z = g.shoulder_height - (g.hip_height + g.pelvis + g.torso_middle)
    w.open(
        f'<body name="upper_arm_{side}" '
        f'pos="{_vec((g.shoulder_anterior, mirror * g.shoulder_half_width, shoulder_z))}">'
    )
    _inertial(w, inertia[f"upper_arm_{side}"])
    _joints(w, f"upper_arm_{side}")
    _capsule(w, f"upper_arm_{side}_geom", (0, 0, -0.02), (0, 0, -g.upper_arm + 0.02), 0.045)
    w.open(f'<body name="forearm_{side}" pos="{_vec((0, 0, -g.upper_arm))}">')
    _inertial(w, inertia[f"forearm_{side}"])
    _joints(w, f"forearm_{side}")
    _capsule(w, f"forearm_{side}_geom", (0, 0, -0.02), (0, 0, -g.forearm + 0.01), 0.035)
    w.open(f'<body name="hand_{side}" pos="{_vec((0, 0, -g.forearm))}">')
    _inertial(w, inertia[f"hand_{side}"])
    w.line(
        f'<geom name="hand_{side}_geom" class="segment" type="box" '
        f'pos="{_vec((0, 0, -0.5 * g.hand))}" size="{_vec((0.015, 0.045, 0.5 * g.hand))}"/>'
    )
    # The bar lies across the palm: palm surface plus the bar radius anterior of the hand.
    w.line(f'<site name="grip_{side}" pos="{_vec((0.029, 0, -0.45 * g.hand))}" size="0.01"/>')
    w.close("body")
    w.close("body")
    w.close("body")


def _leg(w: _Writer, side: str, g: anth.Geometry, inertia: dict[str, anth.SegmentInertia]) -> None:
    mirror = 1.0 if side == "l" else -1.0
    w.open(f'<body name="thigh_{side}" pos="{_vec((0, mirror * g.hip_half_width, 0))}">')
    _inertial(w, inertia[f"thigh_{side}"])
    _joints(w, f"thigh_{side}")
    _capsule(w, f"thigh_{side}_geom", (0, 0, -0.03), (0, 0, -g.thigh + 0.03), 0.065)
    w.open(f'<body name="shank_{side}" pos="{_vec((0, 0, -g.thigh))}">')
    _inertial(w, inertia[f"shank_{side}"])
    _joints(w, f"shank_{side}")
    _capsule(w, f"shank_{side}_geom", (0, 0, -0.03), (0, 0, -g.shank + 0.05), 0.045)
    w.open(f'<body name="foot_{side}" pos="{_vec((0, 0, -g.shank))}">')
    _inertial(w, inertia[f"foot_{side}"])
    _joints(w, f"foot_{side}")
    toe_x = g.foot - g.heel_offset
    w.line(
        f'<geom name="foot_{side}_shape" class="visual" type="box" '
        f'pos="{_vec((0.5 * (toe_x - g.heel_offset), 0, -0.55 * g.ankle_height))}" '
        f'size="{_vec((0.5 * g.foot, 0.5 * g.foot_breadth, 0.4 * g.ankle_height))}"/>'
    )
    r = anth.SOLE_CONTACT_RADIUS_M
    for name, x, lateral in _sole_points(g):
        w.line(
            f'<geom name="foot_{side}_{name}" class="sole" '
            f'pos="{_vec((x, mirror * lateral, -g.ankle_height + r))}" size="{_number(r)}"/>'
        )
    w.line(f'<site name="sole_{side}" pos="{_vec((0, 0, -g.ankle_height))}" size="0.01"/>')
    w.close("body")
    w.close("body")
    w.close("body")


def _barbell(w: _Writer, g: anth.Geometry) -> None:
    bar = anth.BARBELL
    mass, inertia = anth.barbell_inertia(bar)
    shelf = _shelf_position(g)
    # In the anatomical zero posture the trunk is vertical, so the shelf's world position is
    # the hip height plus its trunk-frame offset. The keyframe overrides this pose.
    world = (shelf[0], shelf[1], g.hip_height + g.pelvis + g.torso_middle + shelf[2])
    w.open(f'<body name="barbell" pos="{_vec(world)}">')
    w.line('<freejoint name="barbell_root"/>')
    w.line(f'<inertial pos="0 0 0" mass="{_number(mass)}" diaginertia="{_vec(inertia)}"/>')
    for part in bar.parts:
        w.line(
            f'<geom name="bar_{part.name}" class="bar" type="cylinder" '
            f'pos="{_vec((0, part.center_y, 0))}" zaxis="0 1 0" '
            f'size="{_vec((part.outer_radius, 0.5 * part.length))}"/>'
        )
    w.line('<site name="bar_center" pos="0 0 0" size="0.01"/>')
    w.line(f'<site name="bar_grip_l" pos="{_vec((0, bar.grip_half_width, 0))}" size="0.01"/>')
    w.line(f'<site name="bar_grip_r" pos="{_vec((0, -bar.grip_half_width, 0))}" size="0.01"/>')
    w.close("body")


def _shelf_position(g: anth.Geometry) -> tuple[float, float, float]:
    """Bar-centre shelf in the upper-trunk frame (origin at the thoracic joint centre)."""
    dx, dy, dz = anth.BARBELL.shelf_offset
    return (dx, dy, g.torso_upper + dz)


def render_model_xml(
    keyframe_qpos: Sequence[float] | None = None,
    keyframe_act: Sequence[float] | None = None,
) -> str:
    """Render the complete MJCF document.

    :param keyframe_qpos: the standing equilibrium configuration to embed as keyframe
        ``stand``, or ``None`` for the keyframe-free document the standing solver starts from.
    :param keyframe_act: the tonic activation that holds that configuration; it is written as
        both the keyframe's activation state and its control, so resetting to the keyframe
        yields the complete equilibrium state. Required exactly when ``keyframe_qpos`` is given.
    """
    if (keyframe_qpos is None) != (keyframe_act is None):
        raise ValueError("a keyframe needs both its configuration and its tonic activation")
    g = anth.geometry()
    inertia = {segment.body: segment for segment in anth.segment_inertias()}
    friction = _vec(CONTACT_FRICTION)
    w = _Writer()
    w.line('<?xml version="1.0" encoding="utf-8"?>')
    w.line("<!--")
    w.line("  DynamisBench barbell back-squat model (generated; do not edit by hand).")
    w.line("")
    w.line("  Synthetic adult male athlete, 75 kg, 1.75 m, with an empty 20 kg men's Olympic")
    w.line("  barbell in the high-bar position. Segment inertia: de Leva (1996) males. Source")
    w.line("  of every number: dynamisbench/adapters/mujoco/squat/anthropometry.py.")
    w.line("  Regenerate or check with python/tools/mujoco_squat_model.py.")
    w.line("")
    w.line("  Units: metres, kilograms, seconds, newtons; joint ranges in degrees.")
    w.line("  Frames: x anterior, y left, z up. Positive hinge angles are the named anatomical")
    w.line("  direction on both sides (flexion, adduction, internal rotation, dorsiflexion,")
    w.line("  inversion; leftward bending and rotation for spine and neck).")
    w.line("-->")
    w.open(f'<mujoco model="{MODEL_NAME}">')
    w.line('<compiler angle="degree" inertiafromgeom="false" autolimits="true"/>')
    w.line(
        f'<option timestep="{_number(TIMESTEP_S)}" integrator="{INTEGRATOR}" solver="Newton" '
        f'iterations="{SOLVER_ITERATIONS}" tolerance="{_number(SOLVER_TOLERANCE)}" '
        f'noslip_iterations="{NOSLIP_ITERATIONS}" cone="elliptic" jacobian="dense" '
        f'gravity="0 0 {_number(-anth.GRAVITY_M_S2)}"/>'
    )
    w.open("<visual>")
    w.line('<global offwidth="1280" offheight="960"/>')
    w.close("visual")
    w.open("<default>")
    w.line(f'<joint solreflimit="{_vec(LIMIT_SOLREF)}" solimplimit="{_vec(LIMIT_SOLIMP)}"/>')
    w.open('<default class="segment">')
    w.line(
        f'<geom contype="{_BODY_CONTYPE}" conaffinity="{_BODY_CONAFFINITY}" condim="3" '
        f'friction="{friction}" solref="{_vec(CONTACT_SOLREF)}" rgba="0.85 0.68 0.58 1"/>'
    )
    w.close("default")
    w.open('<default class="sole">')
    w.line(
        f'<geom type="sphere" contype="{_BODY_CONTYPE}" conaffinity="{_BODY_CONAFFINITY}" '
        f'condim="3" friction="{friction}" solref="{_vec(CONTACT_SOLREF)}" '
        'rgba="0.2 0.2 0.2 1"/>'
    )
    w.close("default")
    w.open('<default class="bar">')
    w.line(
        f'<geom contype="{_BODY_CONTYPE}" conaffinity="{_BODY_CONAFFINITY}" condim="3" '
        f'friction="{friction}" rgba="0.55 0.57 0.6 1"/>'
    )
    w.close("default")
    w.open('<default class="visual">')
    w.line('<geom contype="0" conaffinity="0" group="2" rgba="0.25 0.25 0.3 1"/>')
    w.close("default")
    w.close("default")

    w.open("<worldbody>")
    w.line('<light name="key" pos="1.5 -1.5 3" dir="-0.5 0.5 -1" directional="true"/>')
    w.line(
        f'<geom name="{FLOOR_GEOM}" type="plane" size="3 3 0.05" contype="{_FLOOR_CONTYPE}" '
        f'conaffinity="{_FLOOR_CONAFFINITY}" condim="3" friction="{friction}" '
        f'solref="{_vec(CONTACT_SOLREF)}" rgba="0.55 0.45 0.35 1"/>'
    )
    # Pelvis (de Leva lower trunk): root of the kinematic tree, origin at mid-hip.
    w.open(f'<body name="pelvis" pos="{_vec((0, 0, g.hip_height))}">')
    w.line('<freejoint name="root"/>')
    _inertial(w, inertia["pelvis"])
    w.line(
        '<geom name="pelvis_geom" class="segment" type="ellipsoid" '
        f'pos="{_vec((0.02, 0, 0.5 * g.pelvis))}" '
        f'size="{_vec((0.1, 0.15, 0.5 * g.pelvis + 0.03))}"/>'
    )
    w.open(f'<body name="torso_middle" pos="{_vec((0, 0, g.pelvis))}">')
    _inertial(w, inertia["torso_middle"])
    _joints(w, "torso_middle")
    w.line(
        '<geom name="torso_middle_geom" class="segment" type="ellipsoid" '
        f'pos="{_vec((0.03, 0, 0.5 * g.torso_middle))}" '
        f'size="{_vec((0.1, 0.14, 0.5 * g.torso_middle + 0.01))}"/>'
    )
    w.open(f'<body name="torso_upper" pos="{_vec((0, 0, g.torso_middle))}">')
    _inertial(w, inertia["torso_upper"])
    _joints(w, "torso_upper")
    w.line(
        '<geom name="torso_upper_geom" class="segment" type="ellipsoid" '
        f'pos="{_vec((0.035, 0, 0.45 * g.torso_upper))}" '
        f'size="{_vec((0.1, 0.17, 0.5 * g.torso_upper + 0.01))}"/>'
    )
    w.line(f'<site name="bar_shelf" pos="{_vec(_shelf_position(g))}" size="0.012"/>')
    w.open(f'<body name="head" pos="{_vec((0, 0, g.torso_upper))}">')
    _inertial(w, inertia["head"])
    _joints(w, "head")
    _capsule(w, "neck_geom", (0.03, 0, 0.0), (0.03, 0, 0.08), 0.05)
    w.line(
        f'<geom name="head_geom" class="segment" type="ellipsoid" '
        f'pos="{_vec((0.045, 0, g.head - 0.11))}" size="0.095 0.08 0.11"/>'
    )
    w.close("body")
    _arm(w, "l", g, inertia)
    _arm(w, "r", g, inertia)
    w.close("body")
    w.close("body")
    _leg(w, "l", g, inertia)
    _leg(w, "r", g, inertia)
    w.close("body")
    _barbell(w, g)
    w.close("worldbody")

    # Sole-floor contacts as explicit pairs, so the friction directions get their own, faster
    # reference dynamics (FRICTION_SOLREF). MuJoCo does not also generate these pairs
    # dynamically, so the contact set is unchanged: five plantar contacts per foot.
    w.open("<contact>")
    sliding, torsional, rolling = CONTACT_FRICTION
    for side in ("l", "r"):
        for point in SOLE_POINTS:
            w.line(
                f'<pair geom1="{FLOOR_GEOM}" geom2="foot_{side}_{point}" condim="3" '
                f'friction="{_vec((sliding, sliding, torsional, rolling, rolling))}" '
                f'solref="{_vec(CONTACT_SOLREF)}" solreffriction="{_vec(FRICTION_SOLREF)}"/>'
            )
    w.close("contact")
    w.open("<equality>")
    w.line(
        f'<weld name="bar_on_back" site1="bar_center" site2="bar_shelf" '
        f'solref="{_vec(BAR_SHELF_SOLREF)}"/>'
    )
    for hand, bar in GRIP_SITES:
        w.line(
            f'<connect name="{hand}_hold" site1="{hand}" site2="{bar}" '
            f'solref="{_vec(GRIP_SOLREF)}"/>'
        )
    w.close("equality")

    w.open("<actuator>")
    for spec in anth.joint_specs():
        negative, positive = spec.torque_nm
        peak = max(negative, positive)
        w.line(
            f'<general name="{spec.name}" joint="{spec.name}" dyntype="filter" '
            f'dynprm="{_number(ACTIVATION_TIME_CONSTANT_S)}" gainprm="{_number(peak)}" '
            f'ctrlrange="-1 1" forcerange="{_vec((-negative, positive))}"/>'
        )
    w.close("actuator")

    if keyframe_qpos is not None and keyframe_act is not None:
        w.open("<keyframe>")
        w.line(
            f'<key name="{KEYFRAME_NAME}" qpos="{_vec(keyframe_qpos)}" '
            f'act="{_vec(keyframe_act)}" ctrl="{_vec(keyframe_act)}"/>'
        )
        w.close("keyframe")
    w.close("mujoco")
    return "\n".join(w.lines) + "\n"
