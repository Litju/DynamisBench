"""Qualification of one controlled back-squat repetition produced by forward dynamics.

The repetition runs in the isolated worker (``--repetition``, ``--repetition-timestep``).
Each test states the physical identity or behavioural bound it enforces. The acceptance
bounds are declared once below; the negative controls at the end re-run the repetition with
the two defects found while building it and show that these same bounds reject them.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ElementTree
from typing import Any, Final

import numpy as np
import pytest

from dynamisbench.adapters.mujoco.squat import contract, movement
from tests.execution.mujoco_squat.support import (
    ATHLETE_MASS_KG,
    BALANCE_POINT_M,
    BAR_WEIGHT_N,
    GRAVITY_M_S2,
    SYSTEM_WEIGHT_N,
    run_worker_code,
)

TOTAL_MASS_KG: Final = ATHLETE_MASS_KG + 20.0

# --- acceptance bounds (declared before observation) -----------------------------------------
MAX_FOOT_SLIP_M: Final = 0.002
"""Shod feet do not visibly slide during a squat; 2 mm covers soft-contact creep."""
MAX_PENETRATION_M: Final = 0.002
MIN_HEEL_LOAD_FRACTION: Final = 0.2
"""Heels stay loaded: a heel rise during a flat-footed squat is a fault."""
MIN_FOREFOOT_LOAD_FRACTION: Final = 0.2
MIN_COP_MARGIN_M: Final = 0.03
"""The centre of pressure stays at least 3 cm inside the support polygon."""
MIN_XCOM_MARGIN_M: Final = 0.03
"""Extrapolated centre of mass (Hof 2005) stays at least 3 cm inside the support polygon."""
MAX_COM_OFFSET_M: Final = 0.01
"""The whole-system centre of mass stays within 1 cm of the mid-foot balance point."""
MIN_CONTACT_POINT_LOAD_N: Final = 10.0
"""Every plantar point keeps carrying at least 10 N (the load threshold is 5 N)."""
MAX_COUPLING_ERROR_M: Final = 5e-4
MAX_PLAN_GRF_RMS_OVER_WEIGHT: Final = 0.03
"""The internal model's planned ground reaction matches the simulated one (mass/inertia
consistency of the model with itself under contact)."""


def _rep(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["repetition"]


def _series(rep: dict[str, Any], key: str) -> np.ndarray:
    return np.asarray(rep["samples"][key], dtype=np.float64)


def _joint(rep: dict[str, Any], name: str, key: str = "joint_angle_deg") -> np.ndarray:
    return _series(rep, key)[:, rep["joint_names"].index(name)]


# ---------------------------------------------------------------------------------------------
# Phases


def test_the_repetition_passes_through_every_phase_in_order(
    squat_repetition: dict[str, Any],
) -> None:
    rep = _rep(squat_repetition)
    plan = squat_repetition["plan"]
    assert rep["completed"] and rep["failure"] == ""
    events = rep["command_events"]
    assert [event["phase"] for event in events] == [
        "standing",
        "descent",
        "bottom",
        "ascent",
        "return",
    ]
    times = {event["phase"]: event["t"] for event in events}
    assert times["descent"] == pytest.approx(plan["standing_s"], abs=1e-9)
    # The bottom and the return are entered on *measured* state, never before the intent ends.
    assert times["bottom"] >= times["descent"] + plan["descent_s"] - 1e-9
    assert times["bottom"] <= times["descent"] + plan["descent_s"] + 0.25
    assert times["ascent"] == pytest.approx(times["bottom"] + plan["bottom_pause_s"], abs=2e-3)
    assert times["return"] >= times["ascent"] + plan["ascent_s"] - 1e-9
    assert times["return"] <= times["ascent"] + plan["ascent_s"] + 0.25


def test_measured_phases_agree_with_the_commanded_ones(squat_repetition: dict[str, Any]) -> None:
    """Segmenting the hip-height trace alone recovers the same phases at human tempo."""
    rep = _rep(squat_repetition)
    measured = rep["summary"]["measured_phases"]
    assert [item["phase"] for item in measured] == [
        "standing",
        "descent",
        "bottom",
        "ascent",
        "standing",
    ]
    times = {event["phase"]: event["t"] for event in rep["command_events"]}
    descent, bottom, ascent = measured[1], measured[2], measured[3]
    assert times["descent"] <= descent["start_s"] < times["descent"] + 0.5
    assert 0.8 <= descent["end_s"] - descent["start_s"] <= 2.0
    assert 0.6 <= ascent["end_s"] - ascent["start_s"] <= 1.6
    assert bottom["start_s"] < times["ascent"] < bottom["end_s"]
    assert ascent["end_s"] <= times["return"] + 0.1


# ---------------------------------------------------------------------------------------------
# Mechanics


def test_impulse_and_momentum_balance(squat_repetition: dict[str, Any]) -> None:
    """Starting and ending at rest, the mean ground reaction is exactly body + bar weight, and
    at every step the momentum change equals the external impulse up to integration error."""
    rep = _rep(squat_repetition)
    ground = rep["summary"]["ground_reaction"]
    assert ground["mean_vertical_over_weight"] == pytest.approx(1.0, abs=1e-3)
    # Synchronized momentum and impulse: 0.1 % of the ~50 N s peak momentum. (Measured one
    # timestep apart, the same check reported ten times this.)
    assert rep["extrema"]["max_momentum_residual_n_s"] < 0.05


def test_contact_loads_account_for_the_whole_ground_reaction(
    squat_repetition: dict[str, Any],
) -> None:
    """The per-point normal loads sum to the measured vertical ground reaction, no other body
    part touches the floor, and the loaded-contact series is a real load measurement."""
    rep = _rep(squat_repetition)
    extrema = rep["extrema"]
    assert extrema["max_contact_load_sum_error_n"] < 1e-6
    assert extrema["max_other_floor_load_n"] == 0.0
    normal = _series(rep, "contact_normal_n")
    assert normal.shape[1] == 10
    vertical = _series(rep, "grf_left_n")[:, 2] + _series(rep, "grf_right_n")[:, 2]
    assert np.allclose(normal.sum(axis=1), vertical, atol=1e-6)
    assert np.all(_series(rep, "loaded_contacts") == np.sum(normal > 5.0, axis=1))
    # Heel and forefoot of each foot share its load; the heels never unload.
    left_heel = normal[:, :2].sum(axis=1) / normal[:, :5].sum(axis=1)
    right_heel = normal[:, 5:7].sum(axis=1) / normal[:, 5:].sum(axis=1)
    assert float(np.min(np.minimum(left_heel, right_heel))) > MIN_HEEL_LOAD_FRACTION


def test_samples_are_synchronized_snapshots_on_an_exact_grid(
    squat_repetition: dict[str, Any],
) -> None:
    """Each sample describes one instant: its time is its grid index times the period, the
    first sample is the keyframe state at t = 0, and the last is the final state."""
    rep = _rep(squat_repetition)
    times = _series(rep, "t")
    index = _series(rep, "sample_index")
    assert np.array_equal(index, np.arange(len(index)))
    assert np.allclose(times, index * 0.01, atol=1e-9)
    assert times[0] == 0.0 and times[-1] == pytest.approx(rep["duration_s"], abs=1e-9)
    first = _series(rep, "qpos")[0]
    key = ElementTree.fromstring(contract.model_bytes()).find("./keyframe/key")
    assert key is not None
    keyframe = np.array([float(value) for value in key.attrib["qpos"].split()])
    # MuJoCo normalises the keyframe quaternions when it compiles, so compare to 1e-9; a sample
    # taken one timestep late would differ by ~1e-3 here.
    assert np.allclose(first, keyframe, rtol=0.0, atol=1e-9)
    assert rep["samples"]["phase"][0] == "standing"


def test_work_and_energy_balance_in_every_phase(squat_repetition: dict[str, Any]) -> None:
    """Actuator work minus passive damping dissipation equals the change of mechanical
    energy; the remainder (soft contact and coupling dissipation) must be tiny."""
    rep = _rep(squat_repetition)
    energy = rep["summary"]["energy"]
    potential = TOTAL_MASS_KG * GRAVITY_M_S2 * energy["com_drop_m"]
    for name in ("descent", "ascent", "bottom", "return", "standing"):
        phase = rep["work"][name]
        actuator = phase["positive_j"] + phase["negative_j"]
        residual = actuator - phase["damping_dissipation_j"] - phase["mechanical_energy_change_j"]
        assert abs(residual) < 0.01 * abs(phase["mechanical_energy_change_j"]) + 1.0, name
    descent, ascent = rep["work"]["descent"], rep["work"]["ascent"]
    assert descent["mechanical_energy_change_j"] == pytest.approx(-potential, rel=0.02)
    assert ascent["mechanical_energy_change_j"] == pytest.approx(potential, rel=0.02)
    # Lowering is braked by the muscles (negative work), rising is driven by them.
    assert -descent["negative_j"] <= potential and descent["positive_j"] < 1.0
    assert ascent["positive_j"] >= potential and ascent["negative_j"] > -1.0
    assert 0.3 < energy["com_drop_m"] < 0.55


def test_the_internal_model_predicts_the_ground_reaction(squat_repetition: dict[str, Any]) -> None:
    rep = _rep(squat_repetition)
    ground = rep["summary"]["ground_reaction"]
    assert ground["planned_minus_measured_rms_over_weight"] < MAX_PLAN_GRF_RMS_OVER_WEIGHT
    assert rep["extrema"]["max_feedforward_residual"] < 1e-6


def test_feet_stay_planted_flat_and_unslipped(squat_repetition: dict[str, Any]) -> None:
    rep = _rep(squat_repetition)
    extrema = rep["extrema"]
    ground = rep["summary"]["ground_reaction"]
    # Load-bearing, not merely touching: every plantar point carries real load throughout.
    assert extrema["min_loaded_sole_contacts"] == 10
    assert extrema["min_contact_point_load_n"] > MIN_CONTACT_POINT_LOAD_N
    assert extrema["max_sole_point_slip_m"] < MAX_FOOT_SLIP_M
    assert extrema["max_foot_slip_m"] < MAX_FOOT_SLIP_M
    assert extrema["max_penetration_m"] < MAX_PENETRATION_M
    # Per foot, so that one heel lifting cannot hide behind the other foot.
    assert extrema["min_heel_load_fraction_per_foot"] > MIN_HEEL_LOAD_FRACTION
    assert extrema["min_forefoot_load_fraction_per_foot"] > MIN_FOREFOOT_LOAD_FRACTION
    # Each contact point stays well inside its own friction cone.
    assert extrema["max_friction_utilization"] < 0.5
    assert ground["max_shear_over_vertical"] < 0.2  # friction use well inside mu = 0.9
    assert ground["min_left_share"] > 0.48 and ground["max_left_share"] < 0.52


def test_the_bar_stays_coupled_level_and_over_the_feet(squat_repetition: dict[str, Any]) -> None:
    rep = _rep(squat_repetition)
    extrema = rep["extrema"]
    bar = rep["summary"]["barbell"]
    assert extrema["max_weld_position_error_m"] < MAX_COUPLING_ERROR_M
    assert extrema["max_grip_error_m"] < MAX_COUPLING_ERROR_M
    assert extrema["max_weld_angle_error_deg"] < 0.1
    assert bar["max_tilt_deg"] < 1.0 and bar["max_lateral_m"] < 1e-3
    assert 0.4 < bar["vertical_travel_m"] < 0.65
    low, high = bar["x_range_m"]
    assert -0.03 < low and high < 0.16  # over the foot, heel to toe
    assert bar["horizontal_range_m"] < 0.12
    # The shelf carries the bar plus the hanging arms, modulated by the movement.
    assert 0.6 * BAR_WEIGHT_N < bar["min_shelf_force_n"] < bar["max_shelf_force_n"]
    assert bar["max_shelf_force_n"] < 1.8 * BAR_WEIGHT_N


def test_joints_stay_inside_their_ranges_and_actuators_inside_capacity(
    squat_repetition: dict[str, Any],
) -> None:
    extrema = _rep(squat_repetition)["extrema"]
    assert extrema["max_range_violation_deg"] == 0
    assert extrema["min_joint_limit_margin_deg"] > 2.0
    assert extrema["saturated_fraction"] == 0
    assert extrema["max_abs_activation"] < 0.7


def test_balance_is_kept_throughout(squat_repetition: dict[str, Any]) -> None:
    balance = _rep(squat_repetition)["summary"]["balance"]
    assert balance["min_cop_margin_m"] > MIN_COP_MARGIN_M
    assert balance["min_xcom_margin_m"] > MIN_XCOM_MARGIN_M
    low, high = balance["com_x_range_m"]
    assert BALANCE_POINT_M - MAX_COM_OFFSET_M < low and high < BALANCE_POINT_M + MAX_COM_OFFSET_M


# ---------------------------------------------------------------------------------------------
# Human-likeness


def test_the_bottom_is_a_parallel_high_bar_squat_with_a_neutral_spine(
    squat_repetition: dict[str, Any],
) -> None:
    rep = _rep(squat_repetition)
    bottom = rep["summary"]["bottom"]
    ranges = rep["summary"]["ranges"]
    assert 118.0 < bottom["knee_flexion_deg"] < 122.0
    assert 110.0 < bottom["hip_flexion_deg"] < 130.0
    assert 25.0 < bottom["ankle_dorsiflexion_deg"] < 40.0
    assert 25.0 < bottom["trunk_inclination_deg"] < 45.0
    assert 0.40 < bottom["pelvis_height_m"] < 0.50
    assert ranges["max_abs_lumbar_flexion_deg"] < 5.0  # no "butt wink"
    assert ranges["max_abs_thoracic_flexion_deg"] < 5.0
    assert 10.0 < ranges["max_hip_abduction_deg"] < 35.0  # knees out with the toes


def test_the_movement_is_smooth_symmetric_and_at_human_speed(
    squat_repetition: dict[str, Any],
) -> None:
    rep = _rep(squat_repetition)
    summary = rep["summary"]
    assert summary["smoothness"]["knee_speed_reversals_in_descent"] == 0
    assert summary["smoothness"]["knee_speed_reversals_in_ascent"] == 0
    assert 80.0 < summary["ranges"]["peak_knee_speed_descent_deg_s"] < 250.0
    assert 80.0 < summary["ranges"]["peak_knee_speed_ascent_deg_s"] < 250.0
    assert summary["tracking"]["max_knee_error_deg"] < 2.0
    assert summary["symmetry"]["max_angle_difference_deg"] < 0.1
    assert summary["symmetry"]["max_torque_difference_nm"] < 1.0
    ground = summary["ground_reaction"]
    assert 0.6 < ground["min_vertical_over_weight"] and ground["max_vertical_over_weight"] < 1.5
    # No high-frequency chatter: the vertical ground reaction's second difference stays small.
    grf = (_series(rep, "grf_left_n")[:, 2] + _series(rep, "grf_right_n")[:, 2]) / SYSTEM_WEIGHT_N
    assert float(np.max(np.abs(np.diff(grf, 2)))) / 0.01**2 < 200.0


def test_joint_moments_and_power_have_human_magnitudes_and_timing(
    squat_repetition: dict[str, Any],
) -> None:
    rep = _rep(squat_repetition)
    torques = rep["summary"]["torques"]
    times = {event["phase"]: event["t"] for event in rep["command_events"]}
    knee = torques["knee_flexion_l"]
    hip = torques["hip_flexion_l"]
    assert 1.0 < knee["peak_extensor_nm_per_kg"] < 2.2
    assert 0.8 < hip["peak_extensor_nm_per_kg"] < 2.2
    assert knee["peak_extensor_nm"] < 0.6 * 300.0 and hip["peak_extensor_nm"] < 0.6 * 300.0
    # Peak extensor demand is out of the hole: around the bottom and the start of the ascent.
    for peak in (knee, hip):
        assert times["bottom"] - 0.3 <= peak["time_of_peak_s"] <= times["ascent"] + 0.5
    power = rep["summary"]["energy"]["peak_actuator_power_w"] / ATHLETE_MASS_KG
    assert 5.0 < power < 20.0


def test_the_athlete_returns_to_the_standing_rest_state(squat_repetition: dict[str, Any]) -> None:
    back = _rep(squat_repetition)["summary"]["return"]
    assert back["final_max_joint_deviation_deg"] < 0.5
    assert back["final_com_offset_m"] < 0.005
    assert back["final_max_joint_speed_deg_s"] < 1.0


def test_the_motion_is_produced_by_torques_not_written_states(
    squat_repetition: dict[str, Any],
) -> None:
    """The measured angles lag and deviate from the reference, as integrated dynamics do, and
    the actuator torques carry the load: the knee extensor torque follows the movement."""
    rep = _rep(squat_repetition)
    knee = _joint(rep, "knee_flexion_l")
    reference = _joint(rep, "knee_flexion_l", "reference_angle_deg")
    difference = np.abs(knee - reference)
    assert float(np.max(difference)) > 0.05  # not a replayed reference
    torque = -_joint(rep, "knee_flexion_l", "joint_torque_nm")
    assert float(np.max(torque)) > 5 * float(np.abs(torque[0]))


# ---------------------------------------------------------------------------------------------
# Numerics


def test_the_repetition_is_insensitive_to_halving_the_timestep(
    squat_repetition_timestep: dict[str, Any],
) -> None:
    study = squat_repetition_timestep
    nominal, refined = study["nominal"], study["half_timestep"]
    assert nominal["timestep_s"] == 0.001 and refined["timestep_s"] == 0.0005
    assert nominal["completed"] and refined["completed"]
    differences = study["differences"]
    assert differences["shared_samples"] >= 500
    assert differences["max_event_time_difference_s"] < 1e-3
    assert differences["max_knee_angle_difference_deg"] < 0.5
    assert differences["max_joint_angle_difference_deg"] < 1.0
    assert differences["max_bar_position_difference_m"] < 0.003
    assert differences["max_com_position_difference_m"] < 0.002
    assert differences["max_vertical_grf_difference_over_weight"] < 0.03
    assert differences["max_cop_difference_m"] < 0.01
    peak = [
        run["summary"]["torques"]["knee_flexion_l"]["peak_extensor_nm"]
        for run in (nominal, refined)
    ]
    assert peak[0] == pytest.approx(peak[1], rel=0.02)
    for run in (nominal, refined):
        assert run["extrema"]["max_sole_point_slip_m"] < MAX_FOOT_SLIP_M
        assert run["extrema"]["min_loaded_sole_contacts"] == 10
    # A synchronized measurement does not depend on the timestep: the tracking error of the
    # two runs agrees. (Comparing the state one step later with the reference, as before,
    # made it grow with the timestep.)
    assert nominal["extrema"]["max_knee_tracking_error_deg"] == pytest.approx(
        refined["extrema"]["max_knee_tracking_error_deg"], abs=0.02
    )
    # The impulse-momentum residual is integration error: it halves with the timestep.
    ratio = (
        nominal["extrema"]["max_momentum_residual_n_s"]
        / refined["extrema"]["max_momentum_residual_n_s"]
    )
    assert 1.7 < ratio < 2.3


def test_the_repetition_is_deterministic_across_processes(
    squat_repetition: dict[str, Any], squat_repetition_timestep: dict[str, Any]
) -> None:
    assert (
        _rep(squat_repetition)["trajectory_sha256"]
        == squat_repetition_timestep["nominal"]["trajectory_sha256"]
    )


# ---------------------------------------------------------------------------------------------
# Negative controls: the same bounds reject the defects found while building the repetition


_CONTROL = """
import json, mujoco
from dynamisbench.adapters.mujoco.squat import analysis, engine
model = engine.load_model()
{setup}
record = engine.simulate_repetition(model{arguments})
summary = analysis.summarize_repetition(record.samples, record.joint_names,
    athlete_mass_kg=75.0, total_mass_kg=95.0, gravity_m_s2=9.80665)
print(json.dumps({{"completed": record.completed,
    "slip": record.extrema["max_sole_point_slip_m"],
    "min_heel": record.extrema["min_heel_load_fraction_per_foot"],
    "min_contacts": record.extrema["min_loaded_sole_contacts"],
    "cop_margin": summary["balance"]["min_cop_margin_m"],
    "com_x_range": summary["balance"]["com_x_range_m"],
    "plan_rms": summary["ground_reaction"]["planned_minus_measured_rms_over_weight"],
    "tracking": summary["tracking"]["max_knee_error_deg"]}}))
"""


def test_control_soft_friction_lets_the_feet_slide() -> None:
    """With the sole friction at the normal-contact time constant (the model before this
    repetition was built), the feet slide several millimetres: the slip bound rejects it."""
    setup = (
        "import numpy as np\n"
        "for pair in range(model.npair):\n"
        "    model.pair_solreffriction[pair, 0] = 0.015"
    )
    result = run_worker_code(_CONTROL.format(setup=setup, arguments=""))
    assert result["slip"] > 2.5 * MAX_FOOT_SLIP_M


def test_control_without_the_dynamic_internal_model_the_squat_is_not_acceptable() -> None:
    """With only static feedforward, feedback must absorb every inertial effect: balance
    degrades and the ground reaction departs from the plan, and the bounds reject it."""
    result = run_worker_code(_CONTROL.format(setup="", arguments=", dynamic_feedforward=False"))
    low, high = result["com_x_range"]
    rejected = (
        result["cop_margin"] < MIN_COP_MARGIN_M
        or result["min_heel"] < MIN_HEEL_LOAD_FRACTION
        or result["plan_rms"] > MAX_PLAN_GRF_RMS_OVER_WEIGHT
        or high - BALANCE_POINT_M > MAX_COM_OFFSET_M
        or BALANCE_POINT_M - low > MAX_COM_OFFSET_M
    )
    assert rejected, result


# ---------------------------------------------------------------------------------------------
# Engine-free unit tests of the movement logic


def test_minimum_jerk_starts_and_ends_at_rest_with_the_textbook_peak_speed() -> None:
    position, velocity, acceleration = movement.minimum_jerk(10.0, 120.0, 1.5, 0.0)
    assert (position, velocity, acceleration) == (10.0, 0.0, 0.0)
    position, velocity, acceleration = movement.minimum_jerk(10.0, 120.0, 1.5, 1.5)
    assert (position, velocity, acceleration) == (120.0, 0.0, 0.0)
    _, peak, _ = movement.minimum_jerk(10.0, 120.0, 1.5, 0.75)
    assert peak == pytest.approx(1.875 * 110.0 / 1.5)


def test_the_spline_interpolates_and_is_twice_continuously_differentiable() -> None:
    knots = np.array([0.0, 1.0, 2.5, 4.0, 5.0])
    values = np.column_stack([np.sin(knots), knots**2])
    spline = movement.NaturalCubicSpline(knots, values)
    for knot, value in zip(knots, values, strict=True):
        assert np.allclose(spline(float(knot))[0], value)
    for knot in knots[1:-1]:
        left, right = spline(float(knot) - 1e-9), spline(float(knot) + 1e-9)
        assert np.allclose(left[1], right[1], atol=1e-6)
        assert np.allclose(left[2], right[2], atol=1e-6)
    with pytest.raises(ValueError):
        spline(5.5)


def test_the_phase_machine_waits_for_the_measured_state() -> None:
    plan = movement.REPETITION
    machine = movement.PhaseMachine(plan=plan, standing_depth_deg=5.0)
    assert (
        machine.update(0.5, knee_flexion_deg=5.0, knee_speed_deg_s=0.0, sagittal_error_deg=0.0)
        is movement.Phase.STANDING
    )
    assert (
        machine.update(1.0, knee_flexion_deg=5.0, knee_speed_deg_s=0.0, sagittal_error_deg=0.0)
        is movement.Phase.DESCENT
    )
    end = 1.0 + plan.descent_s
    # The intent has arrived but the athlete has not: no bottom yet.
    assert (
        machine.update(end, knee_flexion_deg=100.0, knee_speed_deg_s=40.0, sagittal_error_deg=90.0)
        is movement.Phase.DESCENT
    )
    assert (
        machine.update(
            end + 0.1, knee_flexion_deg=119.5, knee_speed_deg_s=1.0, sagittal_error_deg=90.0
        )
        is movement.Phase.BOTTOM
    )
    assert (
        machine.update(
            end + 0.4, knee_flexion_deg=119.5, knee_speed_deg_s=0.0, sagittal_error_deg=90.0
        )
        is movement.Phase.ASCENT
    )
    top = end + 0.4 + plan.ascent_s
    assert (
        machine.update(top, knee_flexion_deg=20.0, knee_speed_deg_s=-50.0, sagittal_error_deg=15.0)
        is movement.Phase.ASCENT
    )
    assert (
        machine.update(
            top + 0.1, knee_flexion_deg=5.5, knee_speed_deg_s=0.0, sagittal_error_deg=1.0
        )
        is movement.Phase.RETURN
    )
    assert machine.failed is None


def test_the_phase_machine_declares_a_stuck_athlete_failed() -> None:
    machine = movement.PhaseMachine(plan=movement.REPETITION, standing_depth_deg=5.0)
    machine.update(1.0, knee_flexion_deg=5.0, knee_speed_deg_s=0.0, sagittal_error_deg=0.0)
    late = 1.0 + movement.REPETITION.descent_s + movement.TRANSITION_TIMEOUT_S + 0.01
    machine.update(late, knee_flexion_deg=60.0, knee_speed_deg_s=0.0, sagittal_error_deg=50.0)
    assert machine.failed is not None


def test_phase_detection_recovers_a_synthetic_repetition() -> None:
    t = np.arange(0.0, 6.0, 0.01)
    height = np.full_like(t, 0.92)
    for index, time_s in enumerate(t):
        if 1.0 <= time_s < 2.5:
            height[index] = movement.minimum_jerk(0.92, 0.46, 1.5, time_s - 1.0)[0]
        elif 2.5 <= time_s < 2.8:
            height[index] = 0.46
        elif 2.8 <= time_s < 4.0:
            height[index] = movement.minimum_jerk(0.46, 0.92, 1.2, time_s - 2.8)[0]
    phases = movement.detect_phases(t, height)
    assert [phase.phase for phase in phases] == [
        "standing",
        "descent",
        "bottom",
        "ascent",
        "standing",
    ]
    assert 1.0 < phases[1].start_s < 1.3 and 2.2 < phases[1].end_s < 2.5
    assert 2.8 < phases[3].start_s < 3.1 and 3.7 < phases[3].end_s < 4.0
    assert math.isclose(phases[-1].end_s, t[-1])


def test_contact_load_measurement_separates_touching_from_bearing() -> None:
    """A point that touches the floor with almost no force is in contact but not loaded: it
    neither counts as load-bearing nor spans the support polygon."""
    code = """
import json, numpy as np
from dynamisbench.adapters.mujoco.squat import engine
normal = np.array([100.0, 100.0, 100.0, 100.0, 1.0, 100.0, 100.0, 100.0, 100.0, 0.0])
position = np.array([[0, 0.2], [0, 0.16], [0.15, 0.14], [0.12, 0.22], [0.2, 0.17],
                     [0, -0.2], [0, -0.16], [0.15, -0.14], [0.12, -0.22], [0.2, -0.17]], float)
loads = engine.ContactLoads(normal_n=normal, tangential_n=np.zeros(10),
    friction_utilization=np.zeros(10), penetration_m=np.zeros(10), position_xy=position,
    in_contact=np.array([True] * 9 + [False]), total_force_n=np.array([0, 0, normal.sum()]),
    other_floor_vertical_n=0.0)
hull = loads.support_polygon()
print(json.dumps({"in_contact": int(loads.in_contact.sum()), "loaded": int(loads.loaded.sum()),
    "hull_max_x": max(x for x, _ in hull), "heel_l": loads.heel_share("l"),
    "forefoot_r": loads.forefoot_share("r")}))
"""
    result = run_worker_code(code)
    assert result["in_contact"] == 9 and result["loaded"] == 8
    assert result["hull_max_x"] == pytest.approx(0.15)  # the unloaded hallux points are excluded
    assert result["heel_l"] == pytest.approx(200.0 / 401.0)
    assert result["forefoot_r"] == pytest.approx(200.0 / 400.0)
