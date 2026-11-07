"""The postural controller of the barbell back-squat model.

NumPy only; no engine import. The controller maps the *measured* joint state to neural
excitations, which MuJoCo turns into activation (first-order dynamics) and then torque. It
never writes a joint position, velocity or acceleration: every motion in a run is the forward
dynamics response to these excitations, gravity, contact and the bar.

Control law (per actuated joint ``i``)::

    u_i = clip((tau0_i + K_i (q_ref_i - q_i) - D_i qdot_i) / T_i, -1, 1)

* ``tau0`` is the **tonic torque**: the minimum-effort static-equilibrium torques of the
  reference posture, computed by the engine from the model (not tuned by hand).
* ``K`` and ``D`` are the **reflexive postural stiffness and damping** (the decentralised
  joint-impedance model of posture, e.g. Winter et al. 1998 J. Neurophysiol. 80:1211-1221);
  ``D`` is a per-family multiple of ``K`` (:data:`DAMPING_TIME_S`).
* ``T`` is the actuator's peak torque, so ``u`` is a normalised excitation.

Gains were selected by closed-loop eigen-analysis and forward simulation of this model, not
fitted to human sway data. Measured at the standing keyframe with a 15 N s forward push: the
declared stiffness recovers with a 26 mm centre-of-mass excursion and settles in ~2 s; 0.75x and
0.625x still recover (36 and 52 mm); 0.5x falls. Total ankle stiffness is ~3x the gravitational
stiffness ``m g h`` of athlete plus bar, higher than single-link estimates of human quiet stance
(~1.2-1.5 m g h, Peterka 2002), because independent joint servos on a multi-segment chain are
less efficient than coordinated control.

Known limitation: sensorimotor transmission delay is not represented. With a 20 ms delay
these gains destabilise the light segments (head, forearms). Humans tolerate 50-150 ms loop
delays because muscle provides instantaneous, operating-point-dependent short-range
stiffness; representing that needs a muscle-level actuator model, not a retuned servo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "DAMPING_TIME_S",
    "DEFAULT_DAMPING_TIME_S",
    "STIFFNESS_NM_PER_RAD",
    "PosturalController",
    "joint_family",
]

STIFFNESS_NM_PER_RAD: Final[dict[str, float]] = {
    "ankle_dorsiflexion": 1600.0,
    "subtalar_inversion": 300.0,
    "knee_flexion": 1600.0,
    "hip_flexion": 1600.0,
    "hip_adduction": 800.0,
    "hip_rotation": 400.0,
    "lumbar_flexion": 1600.0,
    "lumbar_bending": 1000.0,
    "lumbar_rotation": 400.0,
    "thoracic_flexion": 1200.0,
    "thoracic_bending": 800.0,
    "thoracic_rotation": 300.0,
    "neck_flexion": 80.0,
    "neck_bending": 60.0,
    "neck_rotation": 40.0,
    "shoulder_flexion": 120.0,
    "shoulder_abduction": 120.0,
    "shoulder_rotation": 120.0,
    "elbow_flexion": 80.0,
}
"""Reflexive postural stiffness per joint family, N m/rad."""

DAMPING_TIME_S: Final[dict[str, float]] = {"ankle_dorsiflexion": 0.35}
"""Reflexive damping as a multiple of stiffness, ``D = t * K``, for families that differ from
:data:`DEFAULT_DAMPING_TIME_S`. The ankle carries the whole-body sagittal sway mode (~0.7 Hz):
at 0.05 s a 15 N s push left the athlete rocking for more than 5 s, which people do not do;
0.35 s, within the ~0.25-0.35 s derivative-to-stiffness ratios of human postural-control fits
(Peterka 2002 J. Neurophysiol. 88:1097-1118), settles it in ~2 s."""
DEFAULT_DAMPING_TIME_S: Final = 0.05
"""Reflexive damping time of every other family. It is low on purpose: the light pelvis segment
between the hip and lumbar actuators oscillates through the 30 ms activation lag when hip or
knee reflex damping is raised (0.15 s makes this model fall after a push)."""


def joint_family(joint_name: str) -> str:
    """The joint family of an actuated joint name: the name without its ``_l``/``_r`` side."""
    if joint_name.endswith(("_l", "_r")):
        return joint_name[:-2]
    return joint_name


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class PosturalController:
    """Tonic torque plus joint-impedance feedback about one reference posture.

    Arrays are in actuator order (the order of
    :data:`~dynamisbench.adapters.mujoco.squat.mjcf.ACTUATED_JOINTS`).
    """

    reference_angles: FloatArray
    tonic_torque: FloatArray
    stiffness: FloatArray
    damping: FloatArray
    peak_torque: FloatArray

    @classmethod
    def for_posture(
        cls,
        joint_names: Sequence[str],
        reference_angles: FloatArray,
        tonic_torque: FloatArray,
        peak_torque: FloatArray,
        *,
        stiffness_scale: float = 1.0,
    ) -> PosturalController:
        """Build the controller for one reference posture with the declared gains.

        ``stiffness_scale`` exists only so the qualification can demonstrate the stability
        margin of the declared gains; production runs use 1.0.
        """
        if not np.isfinite(stiffness_scale) or stiffness_scale <= 0.0:
            raise ValueError("the stiffness scale must be a finite positive number")
        stiffness = stiffness_scale * np.array(
            [STIFFNESS_NM_PER_RAD[joint_family(name)] for name in joint_names],
            dtype=np.float64,
        )
        arrays = (reference_angles, tonic_torque, peak_torque)
        if any(array.shape != stiffness.shape for array in arrays):
            raise ValueError("every controller array must have one entry per actuated joint")
        if not all(bool(np.all(np.isfinite(array))) for array in arrays):
            raise ValueError("the controller reference, tonic torque and capacity must be finite")
        if bool(np.any(peak_torque <= 0.0)):
            raise ValueError("every peak torque must be positive")
        damping_time = np.array(
            [
                DAMPING_TIME_S.get(joint_family(name), DEFAULT_DAMPING_TIME_S)
                for name in joint_names
            ],
            dtype=np.float64,
        )
        return cls(
            reference_angles=reference_angles.copy(),
            tonic_torque=tonic_torque.copy(),
            stiffness=stiffness,
            damping=damping_time * stiffness,
            peak_torque=peak_torque.copy(),
        )

    def excitation(self, angles: FloatArray, velocities: FloatArray) -> FloatArray:
        """Normalised neural excitation for the measured joint angles and velocities."""
        torque = (
            self.tonic_torque
            + self.stiffness * (self.reference_angles - angles)
            - self.damping * velocities
        )
        return np.clip(torque / self.peak_torque, -1.0, 1.0)

    def tracking_excitation(
        self,
        angles: FloatArray,
        velocities: FloatArray,
        *,
        reference_angles: FloatArray,
        reference_velocities: FloatArray,
        feedforward_torque: FloatArray,
    ) -> FloatArray:
        """Excitation while moving: feedforward torque plus the same joint-impedance feedback.

        ``feedforward_torque`` replaces the tonic torque (it is the internal model's prediction
        of the torque the planned movement needs), and the feedback acts on the deviation from
        the moving reference. The stiffness and damping are the declared postural ones; the
        movement does not retune them.
        """
        torque = (
            feedforward_torque
            + self.stiffness * (reference_angles - angles)
            + self.damping * (reference_velocities - velocities)
        )
        return np.clip(torque / self.peak_torque, -1.0, 1.0)
