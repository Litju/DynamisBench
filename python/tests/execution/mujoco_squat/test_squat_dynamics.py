"""Real-MuJoCo qualification of the barbell back-squat model.

Every observation comes from the fixed-mode entry point running in the isolated worker
environment. The thresholds are independent physical identities (body weight, static moment
balance, momentum balance) or stated behavioural bounds; none is copied from the adapter.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from tools.mujoco_squat_model import check

from dynamisbench.adapters.mujoco.squat import anthropometry, mjcf
from tests.execution.mujoco.support import worker_python
from tests.execution.mujoco_squat.support import (
    ATHLETE_MASS_KG,
    BALANCE_POINT_M,
    BAR_WEIGHT_N,
    DE_LEVA_MALE_MASS_FRACTION,
    GRAVITY_M_S2,
    STATURE_M,
    SYSTEM_WEIGHT_N,
    run_mode,
    run_raw,
)

ARM_WEIGHT_N = (
    sum(DE_LEVA_MALE_MASS_FRACTION[name] for name in ("upper_arm", "forearm", "hand"))
    * ATHLETE_MASS_KG
    * GRAVITY_M_S2
)


# ---------------------------------------------------------------------------------------------
# Independent geometry: each foot's support polygon from the sole geometry and the stance


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted(set(points))

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _inside(point: tuple[float, float], hull: list[tuple[float, float]], margin: float) -> bool:
    """Whether ``point`` is inside the convex ``hull`` by at least ``margin`` metres."""
    for index, start in enumerate(hull):
        end = hull[(index + 1) % len(hull)]
        edge = (end[0] - start[0], end[1] - start[1])
        length = math.hypot(*edge)
        distance = (edge[0] * (point[1] - start[1]) - edge[1] * (point[0] - start[0])) / length
        if distance < margin:
            return False
    return True


def _foot_polygon(
    side: str, ankle_half_width: float, toe_out_deg: float
) -> list[tuple[float, float]]:
    import xml.etree.ElementTree as ElementTree

    from dynamisbench.adapters.mujoco.squat import contract

    root = ElementTree.fromstring(contract.model_bytes())
    foot = next(body for body in root.iter("body") if body.attrib.get("name") == f"foot_{side}")
    sign = 1.0 if side == "l" else -1.0
    angle = math.radians(sign * toe_out_deg)
    points = []
    for geom in foot.findall("geom"):
        if geom.attrib.get("class") != "sole":
            continue
        x, y, _z = (float(v) for v in geom.attrib["pos"].split())
        points.append(
            (
                x * math.cos(angle) - y * math.sin(angle),
                sign * ankle_half_width + x * math.sin(angle) + y * math.cos(angle),
            )
        )
    assert len(points) == 5
    return _convex_hull(points)


# ---------------------------------------------------------------------------------------------
# Compilation, structure and the standing keyframe


def test_the_model_compiles_to_the_declared_structure(squat_report: dict[str, Any]) -> None:
    counts = squat_report["counts"]
    assert counts == {
        "nq": 7 + 29 + 7,
        "nv": 6 + 29 + 6,
        "nu": 29,
        "na": 29,
        "nbody": 1 + 16 + 1,
        "njnt": 29 + 2,
        "ngeom": counts["ngeom"],
        "neq": 3,
        "nkey": 1,
    }
    assert math.isclose(squat_report["total_mass_kg"], ATHLETE_MASS_KG + 20.0, abs_tol=1e-9)
    for segment in squat_report["segments"]:
        family = segment["body"][:-2] if segment["body"].endswith(("_l", "_r")) else segment["body"]
        assert math.isclose(
            segment["mass_kg"], DE_LEVA_MALE_MASS_FRACTION[family] * ATHLETE_MASS_KG, abs_tol=1e-9
        )
        assert all(value > 0 for value in segment["principal_inertia_kg_m2"])


def test_the_keyframe_is_a_true_standing_rest_state(squat_report: dict[str, Any]) -> None:
    key = squat_report["keyframe"]
    assert key["vertex_height_anatomical_zero_m"] == pytest.approx(STATURE_M, abs=1e-6)
    assert 0.97 * STATURE_M < key["vertex_height_stand_m"] < STATURE_M
    assert key["sole_contacts"] == 10
    assert 0.0 < key["sole_penetration_min_m"] <= key["sole_penetration_max_m"] < 0.002
    assert key["weld_position_error_m"] < 5e-4 and key["weld_angle_error_deg"] < 0.1
    assert key["grip_error_m"] < 5e-4
    assert key["foot_orientation_error_deg"] < 1.0
    assert key["range_violation_deg"] == 0
    # Generalised force imbalance at t=0: a rest state, against a 932 N body weight.
    assert key["initial_force_imbalance_max_unactuated"] < 0.05
    assert key["initial_force_imbalance_max_actuated"] < 0.05
    assert key["com_x_m"] == pytest.approx(BALANCE_POINT_M, abs=0.002)
    assert abs(key["com_y_m"]) < 1e-4
    assert 1.0 < key["com_z_m"] < 1.2
    assert 0.80 * STATURE_M < key["bar_z_m"] < 0.87 * STATURE_M  # high-bar: on the upper back
    posture = squat_report["keyframe_posture"]
    assert 0 < posture["knee_flexion_deg"] < 10 and 0 < posture["hip_flexion_deg"] < 10
    assert posture["trunk_inclination_deg"] < 10
    assert squat_report["keyframe_activation_max"] < 0.2


def test_the_standing_statics_balance_like_a_person(squat_report: dict[str, Any]) -> None:
    static = squat_report["static_equilibrium"]
    assert static["residual"] < 1e-6
    for side in ("l", "r"):
        assert static["foot_wrench"][side][2] == pytest.approx(SYSTEM_WEIGHT_N / 2, rel=0.01)
        # Friction needed is a small fraction of the declared 0.9 coefficient.
        shear = math.hypot(static["foot_wrench"][side][0], static["foot_wrench"][side][1])
        assert shear / static["foot_wrench"][side][2] < 0.2
        hull = _foot_polygon(side, 0.18, 20.0)
        cop = static["centre_of_pressure_xy_m"][side]
        assert _inside((cop[0], cop[1]), hull, margin=0.02), "CoP must be well inside the foot"
    # Ankle moment from statics: body weight acting at the CoM, 5 cm anterior of the ankles,
    # shared by two plantarflexor groups (dorsiflexion is positive, so the torque is negative).
    expected = SYSTEM_WEIGHT_N * squat_report["keyframe"]["com_x_m"] / 2
    for side in ("l", "r"):
        torque = static["joints"][f"ankle_dorsiflexion_{side}"]["torque_nm"]
        assert torque < 0
        assert -torque == pytest.approx(expected, rel=0.15)
    # The bar rests on the shelf: the shelf carries at least the bar, at most bar plus arms.
    shelf_vertical = static["shelf_wrench_on_bar"][2]
    assert BAR_WEIGHT_N <= shelf_vertical <= BAR_WEIGHT_N + 2 * ARM_WEIGHT_N
    for joint, values in static["joints"].items():
        assert abs(values["activation"]) < 0.2, joint


# ---------------------------------------------------------------------------------------------
# Forward dynamics


def test_closed_loop_standing_is_stable_and_carries_body_weight(
    squat_stand: dict[str, Any],
) -> None:
    run = squat_stand["run"]
    assert run["all_finite"] and run["steps"] == 10_000 and run["duration_s"] == 10.0
    assert run["vertical_grf_mean_last_s_n"] == pytest.approx(SYSTEM_WEIGHT_N, rel=0.005)
    assert run["vertical_grf_min_n"] > 0.98 * SYSTEM_WEIGHT_N
    assert run["vertical_grf_max_n"] < 1.02 * SYSTEM_WEIGHT_N
    assert run["com_max_horizontal_excursion_m"] < 1e-3
    assert run["joint_max_deviation_deg"] < 0.1
    assert run["min_loaded_sole_contacts"] == 10 and run["final_loaded_sole_contacts"] == 10
    assert run["min_geometric_sole_contacts"] == 10
    assert run["min_contact_point_load_n"] > 20.0  # every plantar point really carries load
    assert run["foot_max_slip_m"] < 1e-4
    assert run["weld_max_position_error_m"] < 5e-4 and run["grip_max_error_m"] < 5e-4
    assert run["max_abs_activation"] < 0.2 and run["saturated_fraction"] == 0
    assert run["cop_anterior_mean_last_s_m"] == pytest.approx(BALANCE_POINT_M, abs=0.005)
    assert run["joint_limit_max_violation_deg"] == 0
    assert run["max_floor_penetration_m"] < 0.002
    assert run["bar_max_tilt_deg"] < 0.5
    assert BAR_WEIGHT_N <= run["shelf_force_mean_last_s_n"] <= BAR_WEIGHT_N + 2 * ARM_WEIGHT_N
    assert len(run["samples"]) == 200
    # Synchronized samples: at the instant each describes, starting at t = 0.
    assert [sample["t"] for sample in run["samples"][:3]] == [0.0, 0.05, 0.1]


def test_standing_is_bitwise_deterministic_across_processes(squat_stand: dict[str, Any]) -> None:
    again = run_mode("--stand")
    assert again["run"]["trajectory_sha256"] == squat_stand["run"]["trajectory_sha256"]


@pytest.mark.parametrize("direction", ["forward", "backward", "lateral"])
def test_a_15_newton_second_push_is_recovered(
    squat_perturb: dict[str, Any], direction: str
) -> None:
    push = squat_perturb[direction]
    assert push["impulse_n_s"] == pytest.approx(15.0)
    assert push["stiffness_scale"] == 1.0
    run = push["run"]
    assert run["all_finite"]
    assert run["com_min_height_m"] > 1.05  # never crouches or falls
    assert 0.005 < run["com_max_horizontal_excursion_m"] < 0.1  # it really was pushed
    assert run["joint_max_deviation_deg"] < 10 and run["joint_final_deviation_deg"] < 1.0
    assert run["final_loaded_sole_contacts"] == 10 and run["min_loaded_sole_contacts"] >= 4
    assert run["foot_max_slip_m"] < 0.005
    assert run["vertical_grf_mean_last_s_n"] == pytest.approx(SYSTEM_WEIGHT_N, rel=0.01)
    assert run["saturated_fraction"] == 0 and run["max_abs_activation"] < 0.5
    assert run["joint_limit_max_violation_deg"] == 0
    # People recover from a push like this in one to two seconds; they do not keep rocking.
    axis = "com_y" if direction == "lateral" else "com_x"
    start = run["samples"][0][axis]
    late = [abs(sample[axis] - start) for sample in run["samples"] if sample["t"] >= 3.0]
    assert max(late) < 0.01


def test_half_the_declared_stiffness_cannot_recover_the_same_push(
    squat_perturb: dict[str, Any],
) -> None:
    """Stability margin, and proof that nothing but the muscles holds the athlete up."""
    run = squat_perturb["forward_half_stiffness"]["run"]
    assert squat_perturb["forward_half_stiffness"]["stiffness_scale"] == 0.5
    assert run["all_finite"]
    assert run["com_min_height_m"] < 0.5


def test_without_neural_excitation_the_athlete_collapses_within_anatomy(
    squat_passive: dict[str, Any],
) -> None:
    run = squat_passive["run"]
    assert run["all_finite"]
    assert run["com_min_height_m"] < 0.5 * run["com_initial"][2]
    assert run["joint_limit_max_violation_deg"] < 3.0  # anatomical stops hold
    assert run["max_floor_penetration_m"] < 0.05
    assert run["weld_max_position_error_m"] < 0.005 and run["grip_max_error_m"] < 0.01
    assert run["saturated_fraction"] == 0
    assert run["max_abs_activation"] < 0.2  # only the decaying tonic activation


def test_momentum_balance_holds_in_flight_and_converges_with_the_timestep(
    squat_flight: dict[str, Any],
) -> None:
    nominal, refined = squat_flight["nominal"], squat_flight["half_timestep"]
    assert squat_flight["timesteps_s"] == [0.001, 0.0005]
    for probe in (nominal, refined):
        assert probe["max_contacts"] == 0
        assert probe["peak_joint_speed_rad_s"] > 10  # the excitation is violent
        assert probe["final_momentum_z_n_s"] == pytest.approx(
            probe["expected_momentum_z_n_s"], rel=0.02
        )
    # Internal forces (actuators, limits, damping, bar couplings) cannot change the system's
    # momentum; what remains is integration error, which must halve with the timestep
    # (implicitfast is first order).
    linear_ratio = (
        nominal["max_linear_momentum_error_n_s"] / refined["max_linear_momentum_error_n_s"]
    )
    angular_ratio = (
        nominal["max_angular_momentum_about_com_n_m_s"]
        / refined["max_angular_momentum_about_com_n_m_s"]
    )
    assert 1.7 < linear_ratio < 2.3
    assert 1.7 < angular_ratio < 2.3
    assert nominal["max_linear_momentum_error_n_s"] < 0.02 * abs(nominal["expected_momentum_z_n_s"])


# ---------------------------------------------------------------------------------------------
# Squat mechanics


def test_static_squat_postures_are_balanced_human_postures(squat_statics: dict[str, Any]) -> None:
    postures = squat_statics["postures"]
    depths = [posture["knee_flexion_target_deg"] for posture in postures]
    assert depths == sorted(depths) and depths[-1] >= 120.0
    for posture in postures:
        kinematics = posture["kinematics"]
        assert posture["range_violation_deg"] == 0
        assert kinematics["knee_flexion_deg"] == pytest.approx(posture["knee_flexion_target_deg"])
        # Solved exactly, then settled into the compliant sole contacts (sub-millimetre).
        assert kinematics["com_x_m"] == pytest.approx(BALANCE_POINT_M, abs=5e-4)
        assert abs(kinematics["lumbar_flexion_deg"]) < 1.0  # neutral spine
        assert abs(kinematics["thoracic_flexion_deg"]) < 1.0
        assert kinematics["trunk_inclination_deg"] == pytest.approx(
            kinematics["shank_inclination_deg"], abs=1.0
        )
        static = posture["static_equilibrium"]
        assert static["residual"] < 1e-6
        for side in ("l", "r"):
            assert static["foot_wrench"][side][2] == pytest.approx(SYSTEM_WEIGHT_N / 2, rel=0.01)
            cop = static["centre_of_pressure_xy_m"][side]
            assert _inside((cop[0], cop[1]), _foot_polygon(side, 0.18, 20.0), margin=0.02)
        for joint, values in static["joints"].items():
            assert abs(values["activation"]) < 0.5, joint
        # The plantarflexor moment is set by the balance point, not by depth.
        ankle = -static["joints"]["ankle_dorsiflexion_l"]["torque_nm"]
        assert ankle == pytest.approx(SYSTEM_WEIGHT_N * BALANCE_POINT_M / 2, rel=0.15)

    def series(key: str) -> list[float]:
        return [posture["kinematics"][key] for posture in postures]

    def torque(joint: str) -> list[float]:
        return [-p["static_equilibrium"]["joints"][joint]["torque_nm"] for p in postures]

    assert series("hip_flexion_deg") == sorted(series("hip_flexion_deg"))
    assert series("hip_height_m") == sorted(series("hip_height_m"), reverse=True)
    for extensor in ("knee_flexion_l", "hip_flexion_l", "lumbar_flexion"):
        moments = torque(extensor)
        assert all(value > 0 for value in moments), extensor  # extensor moments
        assert moments == sorted(moments), f"{extensor} extensor moment must grow with depth"


def test_the_parallel_squat_looks_like_a_high_bar_squat(squat_statics: dict[str, Any]) -> None:
    parallel = squat_statics["postures"][-1]
    kinematics = parallel["kinematics"]
    assert abs(kinematics["thigh_angle_below_horizontal_deg"]) < 5.0  # thigh ~horizontal
    assert 100.0 < kinematics["hip_flexion_deg"] < 130.0
    assert 25.0 < kinematics["ankle_dorsiflexion_deg"] < 40.0
    assert 25.0 < kinematics["trunk_inclination_deg"] < 45.0
    assert kinematics["knee_x_m"] > kinematics["toe_x_m"] - 0.02  # knees travel to the toes
    joints = parallel["static_equilibrium"]["joints"]
    knee_per_kg = -joints["knee_flexion_l"]["torque_nm"] / ATHLETE_MASS_KG
    hip_per_kg = -joints["hip_flexion_l"]["torque_nm"] / ATHLETE_MASS_KG
    assert 0.5 < knee_per_kg < 1.5 and 0.5 < hip_per_kg < 1.5


def test_a_90_degree_squat_is_held_by_forward_dynamics(squat_statics: dict[str, Any]) -> None:
    hold = squat_statics["hold"]
    assert hold["knee_flexion_deg"] == 90.0
    run = hold["run"]
    assert run["all_finite"] and run["duration_s"] == 5.0
    assert run["vertical_grf_mean_last_s_n"] == pytest.approx(SYSTEM_WEIGHT_N, rel=0.005)
    assert run["com_max_horizontal_excursion_m"] < 0.005
    assert run["joint_max_deviation_deg"] < 1.0
    assert run["min_loaded_sole_contacts"] == 10
    assert run["min_contact_point_load_n"] > 20.0
    assert run["foot_max_slip_m"] < 0.002
    assert run["saturated_fraction"] == 0 and run["max_abs_activation"] < 0.5
    assert run["joint_limit_max_violation_deg"] == 0
    assert run["com_min_height_m"] < squat_statics["postures"][0]["kinematics"]["com_z_m"]


# ---------------------------------------------------------------------------------------------
# Entry-point and asset authority


@pytest.mark.parametrize(
    "arguments",
    [(), ("--stand", "--report"), ("--unknown",), ("model.xml",), ("--identity",)],
)
def test_the_entry_point_refuses_every_unlisted_argument_vector(arguments: tuple[str, ...]) -> None:
    completed = run_raw(arguments)
    assert completed.returncode == 2
    assert completed.stdout == ""


def test_the_packaged_asset_is_the_regenerated_one() -> None:
    worker_python()  # skip or fail exactly as the other real-MuJoCo tests do
    assert check() == []


def test_the_controller_table_covers_every_actuated_joint() -> None:
    from dynamisbench.adapters.mujoco.squat.control import STIFFNESS_NM_PER_RAD, joint_family

    assert {joint_family(name) for name in mjcf.ACTUATED_JOINTS} == set(STIFFNESS_NM_PER_RAD)
    assert len(anthropometry.joint_specs()) == len(mjcf.ACTUATED_JOINTS)
