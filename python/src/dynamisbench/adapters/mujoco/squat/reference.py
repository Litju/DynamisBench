"""World-frame gauge of the standing squat reference (RES-640).

The squat model has an exact symmetry: the floor is an infinite plane, gravity is vertical,
every actuator is an internal joint torque, and the only external contacts are friction
contacts on that plane. Rotating the *entire* system (athlete and barbell) about the world
vertical axis therefore maps a physical state onto the same physical state: no potential
energy, contact load, joint angle or trajectory changes. The same holds for translating it in
the plane. Formally the model is invariant under the special Euclidean group of the floor
plane, and a state's *placement* in that group (two translations and a heading) has no physical
content.

The reference generator must nevertheless write one representative of that equivalence class,
and the packaged keyframe is compared elementwise against a regenerated one. The generator's
contact settle solves a system whose Jacobian is numerically singular along exactly those rigid
placements: the min-norm least-squares step then injects an arbitrary placement. Its two
translations are reproduced across floating-point environments because they are driven by the
deterministic structure of that solve, but its heading is not: it is sampled from last-bit
rounding noise at the 1e-6 rad level, because rotating the whole body about the vertical changes
no generalised force at all. Comparing that heading against a pinned value therefore compares a
rounding sample, not the model.

This module removes the ambiguity by projection onto one declared representative: the pelvis
(the root body) heading is exactly zero, i.e. the athlete faces the declared +x direction. The
projection is a rigid rotation of the whole system about the vertical axis through the pelvis
origin, so it changes no physical quantity; it fixes only the arbitrary heading that the
generator cannot determine. The horizontal translations are deliberately left as generated:
they are the same kind of gauge, but the declared stance anchors them explicitly and the settle
reproduces them to better than 1e-8 m, so they are not an ambiguity in practice (the measured
bound is in ``evidence/RES-640``).

:func:`physical_state` is the complementary view: everything about a standing state that the
gauge does not touch. Two states with equal physical states are the same squat, wherever they
are placed on the floor.

Pure Python, no engine import: the asset checker canonicalises a packaged keyframe without
MuJoCo, and the diagnostic probe compares physical states without a simulator.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Final

from dynamisbench.adapters.mujoco.squat import mjcf

__all__ = [
    "BAR_QPOS",
    "GAUGE_QPOS_INDICES",
    "ROOT_QPOS",
    "canonical_world_frame",
    "pelvis_heading_rad",
    "physical_state",
    "rotate_world_frame",
]

ROOT_QPOS: Final = 0
"""``qpos`` address of the first coordinate of the floating pelvis: a free joint's pose."""

BAR_QPOS: Final = 7 + len(mjcf.ACTUATED_JOINTS)
"""``qpos`` address of the barbell free joint: the pelvis free joint, then every hinge."""

GAUGE_QPOS_INDICES: Final = (
    ROOT_QPOS,
    ROOT_QPOS + 1,
    ROOT_QPOS + 3,
    ROOT_QPOS + 4,
    ROOT_QPOS + 5,
    ROOT_QPOS + 6,
    BAR_QPOS,
    BAR_QPOS + 1,
    BAR_QPOS + 3,
    BAR_QPOS + 4,
    BAR_QPOS + 5,
    BAR_QPOS + 6,
)
"""``qpos`` entries a rotation about the world vertical axis changes: the two free poses.

The pelvis height (indices 2 and 38) and every hinge angle are invariant; the horizontal
positions and the four quaternion components of each free body are not.
"""


def _unit_quaternion(qpos: Sequence[float], address: int) -> tuple[float, float, float, float]:
    values = [float(value) for value in qpos[address + 3 : address + 7]]
    norm = math.sqrt(sum(value * value for value in values))
    if not (math.isfinite(norm) and norm > 0.0):
        raise ValueError(f"qpos[{address + 3}:{address + 7}] is not a finite quaternion")
    return (values[0] / norm, values[1] / norm, values[2] / norm, values[3] / norm)


def _rotation(
    quaternion: tuple[float, float, float, float],
) -> tuple[tuple[float, float, float], ...]:
    """Rotation matrix of a unit quaternion ``(w, x, y, z)``."""
    w, x, y, z = quaternion
    return (
        (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)),
        (2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - w * x)),
        (2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y)),
    )


def pelvis_heading_rad(qpos: Sequence[float]) -> float:
    """Heading of the pelvis about the world vertical axis, radians.

    The pelvis body carries the root free joint, so its world orientation is exactly
    ``qpos[3:7]``. The heading is the yaw of that rotation (``atan2(R[1, 0], R[0, 0])``): the
    angle between the athlete's declared forward axis and world +x, positive towards +y.
    """
    return _yaw(_rotation(_unit_quaternion(qpos, ROOT_QPOS)))


def _yaw(rotation: tuple[tuple[float, float, float], ...]) -> float:
    return math.atan2(rotation[1][0], rotation[0][0])


def rotate_world_frame(qpos: Sequence[float], angle: float) -> list[float]:
    """Return ``qpos`` rotated rigidly about the world vertical axis through the pelvis.

    Both free bodies are rotated; every hinge angle, the pelvis height and its roll and pitch
    are unchanged. ``angle`` is positive towards +y, radians.
    """
    values = [float(value) for value in qpos]
    if len(values) != BAR_QPOS + 7:
        raise ValueError(f"a standing qpos has {BAR_QPOS + 7} entries, not {len(values)}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("a standing qpos must be finite")
    for address in (ROOT_QPOS, BAR_QPOS):
        norm = math.hypot(*values[address + 3 : address + 7])
        # Packaged quaternions are serialized to ten significant digits.
        # Four component errors of at most 5e-11 give a norm error <= 1e-10.
        if abs(norm - 1.0) > 1e-10:
            raise ValueError(
                "a free-body quaternion must have unit norm within serialization error 1e-10"
            )
    if not math.isfinite(angle):
        raise ValueError("a world-frame rotation must be finite")
    if angle == 0.0:
        return values
    cosine, sine = math.cos(angle), math.sin(angle)
    half_cosine, half_sine = math.cos(0.5 * angle), math.sin(0.5 * angle)
    pivot_x, pivot_y = values[ROOT_QPOS], values[ROOT_QPOS + 1]
    for address in (ROOT_QPOS, BAR_QPOS):
        x = values[address] - pivot_x
        y = values[address + 1] - pivot_y
        values[address] = pivot_x + cosine * x - sine * y
        values[address + 1] = pivot_y + sine * x + cosine * y
        w, qx, qy, qz = values[address + 3 : address + 7]
        values[address + 3] = half_cosine * w - half_sine * qz
        values[address + 4] = half_cosine * qx - half_sine * qy
        values[address + 5] = half_cosine * qy + half_sine * qx
        values[address + 6] = half_cosine * qz + half_sine * w
    return values


def canonical_world_frame(qpos: Sequence[float]) -> list[float]:
    """Return ``qpos`` rotated to zero pelvis heading: the declared representative.

    The whole system is rotated rigidly, so no physical quantity changes; the result's
    :func:`pelvis_heading_rad` is zero to rounding error, which is the declared representative
    of the reference state.
    """
    values = rotate_world_frame(qpos, 0.0)
    return rotate_world_frame(values, -pelvis_heading_rad(values))


def physical_state(qpos: Sequence[float]) -> dict[str, Any]:
    """Every quantity of a standing state that the world-frame gauge does not change.

    The kinematic tree plus these numbers determines the configuration up to a rotation and a
    translation in the floor plane: the 29 hinge angles, the pelvis height and tilt, and the
    barbell's pose in the pelvis frame. The pelvis tilt is the ZYX roll/pitch pair, which a
    change of heading leaves unchanged; the barbell pose is expressed in the pelvis frame for
    the same reason. Angles are radians and lengths metres.
    """
    values = [float(value) for value in qpos]
    if len(values) != BAR_QPOS + 7:
        raise ValueError(f"a standing qpos has {BAR_QPOS + 7} entries, not {len(values)}")
    pelvis = _rotation(_unit_quaternion(values, ROOT_QPOS))
    barbell = _rotation(_unit_quaternion(values, BAR_QPOS))
    pitch = math.asin(max(-1.0, min(1.0, -pelvis[2][0])))
    roll = math.atan2(pelvis[2][1], pelvis[2][2])
    offset = [values[BAR_QPOS + axis] - values[ROOT_QPOS + axis] for axis in range(3)]
    bar_position = [sum(pelvis[axis][row] * offset[axis] for axis in range(3)) for row in range(3)]
    bar_rotation = [
        sum(pelvis[k][row] * barbell[k][column] for k in range(3))
        for row in range(3)
        for column in range(3)
    ]
    return {
        "joint_angles_rad": values[BAR_QPOS - len(mjcf.ACTUATED_JOINTS) : BAR_QPOS],
        "pelvis_height_m": [values[ROOT_QPOS + 2]],
        "pelvis_roll_pitch_rad": [roll, pitch],
        "barbell_position_in_pelvis_m": bar_position,
        "barbell_rotation_in_pelvis": bar_rotation,
    }
