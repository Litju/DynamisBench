"""Declared stance and posture targets of the barbell back-squat model.

Pure Python. These are the *task* declarations the posture solver satisfies: where the feet
are, where the whole-system centre of mass must be, and which joint angles are preferred when
the task leaves freedom. They are not joint-angle trajectories and nothing here is a function
of time. Every posture the engine produces is a static solution of these declarations and is
then checked by real forward dynamics.

Hard constraints (satisfied to solver precision): both feet flat on the floor at the declared
position and toe-out; both hands on the bar's grip points; the bar on the upper-trapezius
shelf; the horizontal projection of the whole-system (athlete + barbell) centre of mass at the
declared balance point; and, for squat postures, the declared knee flexion. Everything else is
a weighted preference toward a neutral posture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "ARM_HOLD_DEG",
    "BALANCE_POINT_ANTERIOR_M",
    "SQUAT_DEPTHS_DEG",
    "STANCE",
    "STANDING_PREFERENCE_DEG",
    "TRUNK_SHANK_PARALLEL_WEIGHT",
    "PosturePreference",
    "Stance",
    "preference_for",
]


@dataclass(frozen=True, slots=True)
class Stance:
    """Foot placement in the world frame. The ankle joint centres define the origin line."""

    ankle_half_width_m: float
    """Half the distance between the ankle joint centres."""
    toe_out_deg: float
    """Rotation of each foot's long axis away from straight ahead (about +z, outward)."""


STANCE: Final = Stance(ankle_half_width_m=0.18, toe_out_deg=20.0)
"""Ankle centres 0.36 m apart (equal to the glenohumeral separation: a shoulder-width squat
stance) with 20 deg toe-out, the middle of the 15-30 deg range lifters self-select (e.g.
Escamilla et al. 2001 Med. Sci. Sports Exerc. 33:1552-1566)."""

BALANCE_POINT_ANTERIOR_M: Final = 0.05
"""Horizontal position of the whole-system centre of mass anterior of the ankle joint line.
0.05 m is ~41 % of foot length from the heel: the quiet-standing centre-of-pressure location
(Winter 1995 Gait Posture 3:193-214), and over the mid-foot where lifters keep the bar."""


@dataclass(frozen=True, slots=True)
class PosturePreference:
    """A soft preference for one joint family: target angle (deg) and weight (1/rad)."""

    target_deg: float
    weight: float


STANDING_PREFERENCE_DEG: Final[dict[str, PosturePreference]] = {
    "knee_flexion": PosturePreference(5.0, 1.0),
    "hip_flexion": PosturePreference(5.0, 0.3),
    "ankle_dorsiflexion": PosturePreference(5.0, 0.1),
    "hip_adduction": PosturePreference(0.0, 0.1),
    "hip_rotation": PosturePreference(0.0, 0.1),
    "subtalar_inversion": PosturePreference(0.0, 0.3),
}
"""Unbraced ready stance with the bar on the back: slightly soft knees and hips. Families not
listed (spine, neck) prefer 0 deg with weight 1; the arms use :data:`ARM_HOLD_DEG`."""

ARM_HOLD_DEG: Final[dict[str, PosturePreference]] = {
    "shoulder_flexion": PosturePreference(-20.0, 0.3),
    "shoulder_abduction": PosturePreference(35.0, 0.3),
    "shoulder_rotation": PosturePreference(-100.0, 0.3),
    "elbow_flexion": PosturePreference(110.0, 0.3),
}
"""The high-bar hold: elbows down and behind the bar, forearms near vertical. The hands are
hard-constrained to the grip, so these only choose among arm configurations that reach it;
they are also the initial guess, because a hanging-arm start converges to an elbows-forward
posture no lifter uses."""

SQUAT_DEPTHS_DEG: Final = (30.0, 60.0, 90.0, 120.0)
"""Knee flexion of the static squat postures the engine analyses: quarter, half, 90 deg and
parallel depth (in this model the thigh reaches horizontal at ~120 deg knee flexion)."""

_SQUAT_PREFERENCE_DEG: Final[dict[str, PosturePreference]] = {
    "hip_flexion": PosturePreference(0.0, 0.01),
    "ankle_dorsiflexion": PosturePreference(0.0, 0.01),
    "hip_adduction": PosturePreference(0.0, 0.1),
    "hip_rotation": PosturePreference(0.0, 0.1),
    "subtalar_inversion": PosturePreference(0.0, 0.3),
}
"""In a squat the knee flexion is the declared depth and the balance constraint couples hip and
ankle. The remaining freedom is resolved by :data:`TRUNK_SHANK_PARALLEL_WEIGHT`, not by these
near-zero regularisers, while the spine stays neutral (weight 1). Equal preferences toward
zero on hip and ankle instead put almost all flexion in the ankles (knees far forward, trunk
upright), which is not how the lift is performed."""

TRUNK_SHANK_PARALLEL_WEIGHT: Final = 1.0
"""Soft preference that the trunk (mid-hip to cervicale) stays parallel to the shank, the
coordination of a well-executed high-bar back squat (e.g. Schoenfeld 2010 J. Strength Cond.
Res. 24:3497-3506; Fry, Smith & Schilling 2003 J. Strength Cond. Res. 17:629-633 on how
trunk lean and forward knee travel trade off)."""


def preference_for(joint_family: str, *, squat: bool) -> PosturePreference:
    """The soft posture preference of one joint family (the joint name without side)."""
    if joint_family in ARM_HOLD_DEG:
        return ARM_HOLD_DEG[joint_family]
    table = _SQUAT_PREFERENCE_DEG if squat else STANDING_PREFERENCE_DEG
    return table.get(joint_family, PosturePreference(0.0, 1.0))
