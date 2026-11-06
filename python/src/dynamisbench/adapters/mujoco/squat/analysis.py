"""Summary metrics of a recorded back-squat repetition.

NumPy only; no engine import. Every number is computed from the sampled series the engine
recorded from MuJoCo state. Nothing here feeds back into the simulation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dynamisbench.adapters.mujoco.squat.movement import detect_phases

__all__ = ["phase_mask", "summarize_repetition"]

FloatArray = NDArray[np.float64]


def phase_mask(phases: Sequence[str], name: str) -> NDArray[np.bool_]:
    return np.array([phase == name for phase in phases], dtype=bool)


def _sign_reversals(values: FloatArray, threshold: float) -> int:
    """Number of sign reversals of ``values``, ignoring excursions smaller than ``threshold``."""
    signs = [int(np.sign(v)) for v in values if abs(v) > threshold]
    return sum(1 for a, b in zip(signs, signs[1:], strict=False) if a != b)


def summarize_repetition(
    samples: dict[str, list[Any]],
    joint_names: Sequence[str],
    *,
    athlete_mass_kg: float,
    total_mass_kg: float,
    gravity_m_s2: float,
) -> dict[str, Any]:
    """Reduce the sampled series of one repetition to its reported metrics."""
    t = np.asarray(samples["t"], dtype=np.float64)
    phases = list(samples["phase"])
    angle = np.asarray(samples["joint_angle_deg"], dtype=np.float64)
    speed = np.asarray(samples["joint_velocity_deg_s"], dtype=np.float64)
    torque = np.asarray(samples["joint_torque_nm"], dtype=np.float64)
    reference = np.asarray(samples["reference_angle_deg"], dtype=np.float64)
    column = {name: index for index, name in enumerate(joint_names)}
    weight = total_mass_kg * gravity_m_s2
    grf_l = np.asarray(samples["grf_left_n"], dtype=np.float64)
    grf_r = np.asarray(samples["grf_right_n"], dtype=np.float64)
    grf_z = grf_l[:, 2] + grf_r[:, 2]
    planned_z = np.asarray(samples["grf_planned_vertical_n"], dtype=np.float64)
    com = np.asarray(samples["com_position_m"], dtype=np.float64)
    bar = np.asarray(samples["bar_position_m"], dtype=np.float64)
    bar_velocity = np.asarray(samples["bar_velocity_m_s"], dtype=np.float64)
    cop = np.asarray(samples["cop_m"], dtype=np.float64)
    pelvis = np.asarray(samples["pelvis_height_m"], dtype=np.float64)
    power = np.asarray(samples["actuator_power_w"], dtype=np.float64)

    def joint(name: str) -> FloatArray:
        return angle[:, column[name]]

    bottom = int(np.argmax(0.5 * (joint("knee_flexion_l") + joint("knee_flexion_r"))))
    measured = detect_phases(t, pelvis)
    descent = phase_mask(phases, "descent")
    ascent = phase_mask(phases, "ascent")

    peak_extensor = {}
    for name in ("knee_flexion_l", "hip_flexion_l", "lumbar_flexion", "ankle_dorsiflexion_l"):
        series = torque[:, column[name]]
        peak_extensor[name] = {
            "peak_extensor_nm": float(-np.min(series)),
            "peak_extensor_nm_per_kg": float(-np.min(series) / athlete_mass_kg),
            "time_of_peak_s": float(t[int(np.argmin(series))]),
        }
    pairs = [(name, name[:-2] + "_r") for name in joint_names if name.endswith("_l")]
    angle_asymmetry = max(
        float(np.max(np.abs(angle[:, column[left]] - angle[:, column[right]])))
        for left, right in pairs
    )
    torque_asymmetry = max(
        float(np.max(np.abs(torque[:, column[left]] - torque[:, column[right]])))
        for left, right in pairs
    )
    knee_speed = 0.5 * (speed[:, column["knee_flexion_l"]] + speed[:, column["knee_flexion_r"]])
    standing_com_z = float(com[0, 2])
    bottom_com_z = float(np.min(com[:, 2]))
    return {
        "measured_phases": [
            {"phase": item.phase, "start_s": item.start_s, "end_s": item.end_s} for item in measured
        ],
        "bottom": {
            "t_s": float(t[bottom]),
            "knee_flexion_deg": float(joint("knee_flexion_l")[bottom]),
            "hip_flexion_deg": float(joint("hip_flexion_l")[bottom]),
            "ankle_dorsiflexion_deg": float(joint("ankle_dorsiflexion_l")[bottom]),
            "lumbar_flexion_deg": float(joint("lumbar_flexion")[bottom]),
            "trunk_inclination_deg": float(samples["trunk_inclination_deg"][bottom]),
            "pelvis_height_m": float(pelvis[bottom]),
            "bar_height_m": float(bar[bottom, 2]),
        },
        "ranges": {
            "max_knee_flexion_deg": float(np.max(joint("knee_flexion_l"))),
            "max_hip_flexion_deg": float(np.max(joint("hip_flexion_l"))),
            "max_ankle_dorsiflexion_deg": float(np.max(joint("ankle_dorsiflexion_l"))),
            "max_abs_lumbar_flexion_deg": float(np.max(np.abs(joint("lumbar_flexion")))),
            "max_abs_thoracic_flexion_deg": float(np.max(np.abs(joint("thoracic_flexion")))),
            "max_trunk_inclination_deg": float(np.max(samples["trunk_inclination_deg"])),
            "peak_knee_speed_descent_deg_s": float(np.max(knee_speed[descent])),
            "peak_knee_speed_ascent_deg_s": float(-np.min(knee_speed[ascent])),
            "max_hip_abduction_deg": float(-np.min(joint("hip_adduction_l"))),
        },
        "tracking": {
            "max_knee_error_deg": float(
                np.max(np.abs(joint("knee_flexion_l") - reference[:, column["knee_flexion_l"]]))
            ),
            "rms_knee_error_deg": float(
                np.sqrt(
                    np.mean((joint("knee_flexion_l") - reference[:, column["knee_flexion_l"]]) ** 2)
                )
            ),
        },
        "smoothness": {
            "knee_speed_reversals_in_descent": _sign_reversals(knee_speed[descent], 5.0),
            "knee_speed_reversals_in_ascent": _sign_reversals(knee_speed[ascent], 5.0),
        },
        "torques": peak_extensor,
        "symmetry": {
            "max_angle_difference_deg": angle_asymmetry,
            "max_torque_difference_nm": torque_asymmetry,
        },
        "ground_reaction": {
            "mean_vertical_over_weight": float(np.mean(grf_z) / weight),
            "min_vertical_over_weight": float(np.min(grf_z) / weight),
            "max_vertical_over_weight": float(np.max(grf_z) / weight),
            "planned_minus_measured_rms_over_weight": float(
                np.sqrt(np.mean((planned_z - grf_z) ** 2)) / weight
            ),
            "min_left_share": float(np.min(grf_l[:, 2] / grf_z)),
            "max_left_share": float(np.max(grf_l[:, 2] / grf_z)),
            "max_shear_over_vertical": float(
                np.max(np.hypot(grf_l[:, 0] + grf_r[:, 0], grf_l[:, 1] + grf_r[:, 1]) / grf_z)
            ),
        },
        "balance": {
            "min_cop_margin_m": float(np.min(samples["cop_margin_m"])),
            "min_xcom_margin_m": float(np.min(samples["xcom_margin_m"])),
            "cop_x_range_m": [float(np.min(cop[:, 0])), float(np.max(cop[:, 0]))],
            "com_x_range_m": [float(np.min(com[:, 0])), float(np.max(com[:, 0]))],
        },
        "barbell": {
            "vertical_travel_m": float(np.max(bar[:, 2]) - np.min(bar[:, 2])),
            "horizontal_range_m": float(np.max(bar[:, 0]) - np.min(bar[:, 0])),
            "x_range_m": [float(np.min(bar[:, 0])), float(np.max(bar[:, 0]))],
            "max_lateral_m": float(np.max(np.abs(bar[:, 1]))),
            "max_tilt_deg": float(np.max(samples["bar_tilt_deg"])),
            "peak_down_speed_m_s": float(-np.min(bar_velocity[:, 2])),
            "peak_up_speed_m_s": float(np.max(bar_velocity[:, 2])),
            "min_shelf_force_n": float(np.min(samples["shelf_force_n"])),
            "max_shelf_force_n": float(np.max(samples["shelf_force_n"])),
        },
        "energy": {
            "com_drop_m": standing_com_z - bottom_com_z,
            "potential_energy_change_j": total_mass_kg
            * gravity_m_s2
            * (standing_com_z - bottom_com_z),
            "peak_actuator_power_w": float(np.max(power)),
            "min_actuator_power_w": float(np.min(power)),
        },
        "return": {
            "final_max_joint_deviation_deg": float(np.max(np.abs(angle[-1] - angle[0]))),
            "final_com_offset_m": float(np.linalg.norm(com[-1, :2] - com[0, :2])),
            "final_max_joint_speed_deg_s": float(np.max(np.abs(speed[-1]))),
        },
    }
