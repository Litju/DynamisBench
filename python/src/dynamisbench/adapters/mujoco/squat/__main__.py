"""Fixed-mode entry point of the barbell back-squat model (isolated worker environment only).

    python -I -m dynamisbench.adapters.mujoco.squat <mode>

Modes (exactly one; no paths, no model selection, no free parameters):

``--keyframe``   generate the standing equilibrium from the declarations (used by
                 ``tools/mujoco_squat_model.py``; does not need the packaged asset)
``--report``     compile the packaged model and report its structure, mass properties,
                 standing keyframe and minimum-effort static equilibrium
``--stand``      10 s of closed-loop quiet standing from the keyframe
``--perturb``    15 N s pushes (forward, backward, lateral) during standing, and the same
                 forward push with half the declared stiffness (stability margin)
``--passive``    3 s with zero neural excitation from the keyframe (the athlete relaxes)
``--flight``     momentum conservation in flight under random excitation, at two timesteps
``--squat``      static squat postures at the declared depths, and a 5 s closed-loop hold
                 at 90 deg knee flexion
``--repetition`` one controlled repetition (standing, descent, bottom, ascent, standing) by
                 forward dynamics, with its full measured time series and summary
``--repetition-timestep``
                 the same repetition at the model timestep and at half of it, compared
``--laboratory`` the laboratory dataset: the compiled model, and four recordings (nominal,
                 its half-timestep companion, two ablations) with frames and evaluated checks

Each mode writes one RFC 8785 canonical JSON object to stdout. These are qualification
observations of the model, not DynamisBench native, canonical or assessment evidence.
"""

from __future__ import annotations

import dataclasses
import math
import sys
from collections.abc import Callable
from typing import Any, Final

import numpy as np

from dynamisbench.adapters.mujoco.squat import (
    analysis,
    contract,
    criteria,
    engine,
    mjcf,
    movement,
    reference,
    stance,
)
from dynamisbench.adapters.mujoco.squat import anthropometry as anth
from dynamisbench.identity import canonical_semantic_bytes

__all__ = ["main"]

STANDING_DURATION_S: Final = 10.0
PERTURBATION_DURATION_S: Final = 6.0
PUSH_FORCE_N: Final = 150.0
PUSH_START_S: Final = 1.0
PUSH_DURATION_S: Final = 0.1
PASSIVE_DURATION_S: Final = 3.0
SQUAT_HOLD_DEPTH_DEG: Final = 90.0
SQUAT_HOLD_DURATION_S: Final = 5.0
MOMENTUM_SEED: Final = 7
SAMPLE_PERIOD_S: Final = 0.05


def _finite(value: Any) -> Any:
    """Convert NumPy values to JSON values, refusing any non-finite number."""
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_finite(item) for item in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise engine.EngineError("an observation value is not finite")
        return number
    if isinstance(value, str) or value is None:
        return value
    raise TypeError(f"unsupported observation value {type(value)!r}")


def _envelope(mode: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": contract.OBSERVATION_SCHEMA,
        "mode": mode,
        "engine": contract.ENGINE,
        "engine_version": engine.engine_version(),
        "python_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "claim": contract.CLAIM_LIMIT,
        **body,
    }


def _run(summary: engine.RunSummary) -> dict[str, Any]:
    return {item.name: getattr(summary, item.name) for item in dataclasses.fields(summary)}


def _keyframe() -> dict[str, Any]:
    model = engine.generator_model()
    generation = engine.standing_reference(model)
    return {
        "qpos": generation.qpos,
        "act": generation.activation,
        "relaxation_duration_s": engine.RELAXATION_DURATION_S,
        "relaxation_final_max_speed": generation.relaxation_final_max_speed,
        # Diagnostic only: the world heading the relaxation landed on before the reference was
        # projected onto the declared frame. It is the gauge that RES-640 showed is not
        # reproducible; it is reported, never used as a reference.
        "relaxation_heading_before_projection_rad": reference.pelvis_heading_rad(
            [float(value) for value in generation.unprojected_qpos]
        ),
        # The static state is reported as the settle produced it, so the diagnostic can show
        # the world heading that the relaxation received. It is not the reference either.
        "static_solution_qpos": generation.static_qpos,
        "static_solution_act": generation.static_activation,
    }


def _equilibrium(model: Any, qpos: np.ndarray) -> dict[str, Any]:
    solution = engine.static_equilibrium(model, qpos)
    lay = engine.layout(model)
    return {
        "residual": solution.residual,
        "joints": {
            name: {
                "torque_nm": float(solution.torque[k]),
                "activation": float(solution.activation[k]),
            }
            for k, name in enumerate(lay.joint_names)
        },
        "foot_wrench": {side: wrench for side, wrench in solution.foot_wrench.items()},
        "centre_of_pressure_xy_m": solution.centre_of_pressure,
        "shelf_wrench_on_bar": solution.shelf_wrench_on_bar,
        "grip_force_on_bar_n": solution.grip_force_on_bar,
    }


def _report() -> dict[str, Any]:
    model = engine.load_model()
    lay = engine.layout(model)
    qpos, activation = engine.keyframe_state(model)
    geometry = anth.geometry()
    bar_mass, bar_inertia = anth.barbell_inertia()
    return {
        "model_sha256": contract.MODEL_SHA256,
        "counts": {
            "nq": int(model.nq),
            "nv": int(model.nv),
            "nu": int(model.nu),
            "na": int(model.na),
            "nbody": int(model.nbody),
            "njnt": int(model.njnt),
            "ngeom": int(model.ngeom),
            "neq": int(model.neq),
            "nkey": int(model.nkey),
        },
        "total_mass_kg": float(np.sum(model.body_mass)),
        "segments": [
            {
                "body": segment.body,
                "mass_kg": float(model.body_mass[lay.bodies[segment.body]]),
                "com_m": np.asarray(model.body_ipos[lay.bodies[segment.body]]),
                "principal_inertia_kg_m2": np.asarray(model.body_inertia[lay.bodies[segment.body]]),
            }
            for segment in anth.segment_inertias()
        ],
        "barbell": {
            "mass_kg": bar_mass,
            "principal_inertia_kg_m2": bar_inertia,
            "grip_half_width_m": anth.BARBELL.grip_half_width,
        },
        "geometry_m": {
            "stature": anth.STATURE_M,
            "ankle_height": geometry.ankle_height,
            "hip_height": geometry.hip_height,
            "cervicale_height": geometry.cervicale_height,
            "shoulder_height": geometry.shoulder_height,
            "thigh": geometry.thigh,
            "shank": geometry.shank,
            "trunk": geometry.trunk,
            "foot": geometry.foot,
        },
        "joints": [
            {
                "name": spec.name,
                "range_deg": spec.range_deg,
                "torque_capacity_nm": spec.torque_nm,
                "compiled_range_rad": lay.joint_range[k],
            }
            for k, spec in enumerate(anth.joint_specs())
        ],
        "stance": {
            "ankle_half_width_m": stance.STANCE.ankle_half_width_m,
            "toe_out_deg": stance.STANCE.toe_out_deg,
            "balance_point_anterior_m": stance.BALANCE_POINT_ANTERIOR_M,
        },
        "keyframe": engine.keyframe_diagnostics(model),
        "keyframe_posture": engine.posture_kinematics(model, qpos),
        "keyframe_activation_max": float(np.max(np.abs(activation))),
        "static_equilibrium": _equilibrium(model, qpos),
    }


def _stand() -> dict[str, Any]:
    model = engine.load_model()
    qpos, activation = engine.keyframe_state(model)
    summary = engine.simulate(
        model,
        qpos,
        activation,
        controller=engine.controller_for(model, qpos, activation),
        duration_s=STANDING_DURATION_S,
        sample_period_s=SAMPLE_PERIOD_S,
    )
    return {"model_sha256": contract.MODEL_SHA256, "run": _run(summary)}


def _push(model: Any, force: tuple[float, float, float], stiffness_scale: float) -> dict[str, Any]:
    qpos, activation = engine.keyframe_state(model)
    summary = engine.simulate(
        model,
        qpos,
        activation,
        controller=engine.controller_for(model, qpos, activation, stiffness_scale=stiffness_scale),
        duration_s=PERTURBATION_DURATION_S,
        disturbance=engine.Disturbance("pelvis", PUSH_START_S, PUSH_DURATION_S, force),
        sample_period_s=SAMPLE_PERIOD_S,
    )
    return {
        "force_n": force,
        "impulse_n_s": PUSH_DURATION_S * math.sqrt(sum(component**2 for component in force)),
        "stiffness_scale": stiffness_scale,
        "run": _run(summary),
    }


def _perturb() -> dict[str, Any]:
    model = engine.load_model()
    return {
        "model_sha256": contract.MODEL_SHA256,
        "forward": _push(model, (PUSH_FORCE_N, 0.0, 0.0), 1.0),
        "backward": _push(model, (-PUSH_FORCE_N, 0.0, 0.0), 1.0),
        "lateral": _push(model, (0.0, PUSH_FORCE_N, 0.0), 1.0),
        "forward_half_stiffness": _push(model, (PUSH_FORCE_N, 0.0, 0.0), 0.5),
    }


def _passive() -> dict[str, Any]:
    model = engine.load_model()
    qpos, activation = engine.keyframe_state(model)
    summary = engine.simulate(
        model,
        qpos,
        activation,
        controller=None,
        duration_s=PASSIVE_DURATION_S,
        sample_period_s=SAMPLE_PERIOD_S,
    )
    return {"model_sha256": contract.MODEL_SHA256, "run": _run(summary)}


def _flight() -> dict[str, Any]:
    nominal = engine.load_model()
    refined = engine.load_model()
    refined.opt.timestep = 0.5 * float(nominal.opt.timestep)
    return {
        "model_sha256": contract.MODEL_SHA256,
        "nominal": engine.momentum_probe(nominal, seed=MOMENTUM_SEED),
        "half_timestep": engine.momentum_probe(refined, seed=MOMENTUM_SEED),
        "timesteps_s": [float(nominal.opt.timestep), float(refined.opt.timestep)],
    }


def _squat() -> dict[str, Any]:
    model = engine.load_model()
    postures = []
    for depth in stance.SQUAT_DEPTHS_DEG:
        qpos = engine.settle(model, engine.solve_posture(model, knee_flexion_deg=depth))
        postures.append(
            {
                "knee_flexion_target_deg": depth,
                "kinematics": engine.posture_kinematics(model, qpos),
                "static_equilibrium": _equilibrium(model, qpos),
                "range_violation_deg": engine.range_violation_deg(model, qpos),
            }
        )
    hold_qpos = engine.settle(
        model, engine.solve_posture(model, knee_flexion_deg=SQUAT_HOLD_DEPTH_DEG)
    )
    hold_activation = engine.static_equilibrium(model, hold_qpos).activation
    summary = engine.simulate(
        model,
        hold_qpos,
        hold_activation,
        controller=engine.controller_for(model, hold_qpos, hold_activation),
        duration_s=SQUAT_HOLD_DURATION_S,
        sample_period_s=SAMPLE_PERIOD_S,
    )
    return {
        "model_sha256": contract.MODEL_SHA256,
        "postures": postures,
        "hold": {
            "knee_flexion_deg": SQUAT_HOLD_DEPTH_DEG,
            "kinematics": engine.posture_kinematics(model, hold_qpos),
            "run": _run(summary),
        },
    }


def _plan() -> dict[str, Any]:
    return {
        item.name: getattr(movement.REPETITION, item.name)
        for item in dataclasses.fields(movement.REPETITION)
    }


def _repetition_body(record: engine.RepetitionRecord, *, include_samples: bool) -> dict[str, Any]:
    summary = analysis.summarize_repetition(
        record.samples,
        record.joint_names,
        athlete_mass_kg=anth.BODY_MASS_KG,
        total_mass_kg=anth.BODY_MASS_KG + anth.BARBELL.mass,
        gravity_m_s2=anth.GRAVITY_M_S2,
    )
    body: dict[str, Any] = {
        "timestep_s": record.timestep_s,
        "duration_s": record.duration_s,
        "steps": record.steps,
        "completed": record.completed,
        "failure": record.failure if record.failure is not None else "",
        "trajectory_sha256": record.trajectory_sha256,
        "command_events": record.command_events,
        "extrema": record.extrema,
        "work": record.work,
        "summary": summary,
        "synergy_knots": record.synergy_knots,
        "synergy_off_axis_rotation_rad": record.synergy_off_axis_rotation_rad,
    }
    if include_samples:
        body["joint_names"] = list(record.joint_names)
        body["samples"] = record.samples
    return body


def _repetition() -> dict[str, Any]:
    model = engine.load_model()
    record = engine.simulate_repetition(model)
    return {
        "model_sha256": contract.MODEL_SHA256,
        "plan": _plan(),
        "repetition": _repetition_body(record, include_samples=True),
    }


def _on_common_times(
    nominal: engine.RepetitionRecord, refined: engine.RepetitionRecord
) -> dict[str, float]:
    """Largest differences between two runs on the sample times they share."""
    # Samples sit on an exact grid (sample_index * sample period, each an integer number of
    # timesteps), so the two runs are compared at identical instants, matched by index.
    shared, index_a, index_b = np.intersect1d(
        np.asarray(nominal.samples["sample_index"]),
        np.asarray(refined.samples["sample_index"]),
        return_indices=True,
    )
    times_a = np.asarray(nominal.samples["t"])[index_a]
    times_b = np.asarray(refined.samples["t"])[index_b]
    if float(np.max(np.abs(times_a - times_b))) > 1e-9:
        raise engine.EngineError("the two timestep runs are not sampled at the same instants")
    if len(shared) < 100:
        raise engine.EngineError("the two timestep runs share too few sample times")
    knee = list(nominal.joint_names).index("knee_flexion_l")
    weight = (anth.BODY_MASS_KG + anth.BARBELL.mass) * anth.GRAVITY_M_S2

    def series(record: engine.RepetitionRecord, key: str) -> np.ndarray:
        return np.asarray(record.samples[key], dtype=np.float64)

    def vertical(record: engine.RepetitionRecord) -> np.ndarray:
        return series(record, "grf_left_n")[:, 2] + series(record, "grf_right_n")[:, 2]

    torque_a = series(nominal, "joint_torque_nm")[index_a]
    torque_b = series(refined, "joint_torque_nm")[index_b]
    return {
        "shared_samples": float(len(shared)),
        "max_knee_angle_difference_deg": float(
            np.max(
                np.abs(
                    series(nominal, "joint_angle_deg")[index_a, knee]
                    - series(refined, "joint_angle_deg")[index_b, knee]
                )
            )
        ),
        "max_joint_angle_difference_deg": float(
            np.max(
                np.abs(
                    series(nominal, "joint_angle_deg")[index_a]
                    - series(refined, "joint_angle_deg")[index_b]
                )
            )
        ),
        "max_knee_torque_difference_nm": float(
            np.max(np.abs(torque_a[:, knee] - torque_b[:, knee]))
        ),
        "max_bar_position_difference_m": float(
            np.max(
                np.linalg.norm(
                    series(nominal, "bar_position_m")[index_a]
                    - series(refined, "bar_position_m")[index_b],
                    axis=1,
                )
            )
        ),
        "max_com_position_difference_m": float(
            np.max(
                np.linalg.norm(
                    series(nominal, "com_position_m")[index_a]
                    - series(refined, "com_position_m")[index_b],
                    axis=1,
                )
            )
        ),
        "max_vertical_grf_difference_over_weight": float(
            np.max(np.abs(vertical(nominal)[index_a] - vertical(refined)[index_b])) / weight
        ),
        "max_cop_difference_m": float(
            np.max(
                np.linalg.norm(
                    series(nominal, "cop_m")[index_a] - series(refined, "cop_m")[index_b], axis=1
                )
            )
        ),
        "max_event_time_difference_s": float(
            max(
                abs(a["t"] - b["t"])
                for a, b in zip(nominal.command_events, refined.command_events, strict=True)
            )
        ),
    }


def _repetition_timestep() -> dict[str, Any]:
    nominal_model = engine.load_model()
    refined_model = engine.load_model()
    refined_model.opt.timestep = 0.5 * float(nominal_model.opt.timestep)
    nominal = engine.simulate_repetition(nominal_model)
    refined = engine.simulate_repetition(refined_model)
    if len(nominal.command_events) != len(refined.command_events):
        raise engine.EngineError("the two timestep runs did not pass through the same phases")
    return {
        "model_sha256": contract.MODEL_SHA256,
        "plan": _plan(),
        "nominal": _repetition_body(nominal, include_samples=False),
        "half_timestep": _repetition_body(refined, include_samples=False),
        "differences": _on_common_times(nominal, refined),
    }


def _round(value: float) -> float:
    """Seven significant digits: frame columns are for display, not for re-analysis."""
    return float(f"{value:.7g}")


def _frames(record: engine.RepetitionRecord) -> dict[str, Any]:
    """Column-oriented frame data of one recording, in three transport groups."""
    samples = record.samples
    joints = list(record.joint_names)
    count = len(samples["t"])
    pose: dict[str, list[float]] = {}
    positions = np.asarray(samples["body_position_m"])
    quaternions = np.asarray(samples["body_quaternion"])
    for b, body in enumerate(record.body_names):
        for a, axis in enumerate(("px", "py", "pz")):
            pose[f"{body}.{axis}"] = [_round(v) for v in positions[:, b, a]]
        for a, axis in enumerate(("qw", "qx", "qy", "qz")):
            pose[f"{body}.{axis}"] = [_round(v) for v in quaternions[:, b, a]]
    kinematics: dict[str, list[float]] = {
        "depth_intent_deg": [_round(v) for v in samples["depth_intent_deg"]],
        "phase_code": [
            float(list(movement.Phase).index(movement.Phase(p))) for p in samples["phase"]
        ],
    }
    for key, suffix in (
        ("joint_angle_deg", "angle_deg"),
        ("joint_velocity_deg_s", "velocity_deg_s"),
        ("reference_angle_deg", "reference_deg"),
    ):
        values = np.asarray(samples[key])
        for j, joint in enumerate(joints):
            kinematics[f"{joint}.{suffix}"] = [_round(v) for v in values[:, j]]
    for key, prefix in (
        ("com_position_m", "com"),
        ("com_velocity_m_s", "com_v"),
        ("bar_position_m", "bar"),
        ("bar_velocity_m_s", "bar_v"),
    ):
        values = np.asarray(samples[key])
        for a, axis in enumerate("xyz"):
            kinematics[f"{prefix}.{axis}"] = [_round(v) for v in values[:, a]]
    for key in ("bar_tilt_deg", "trunk_inclination_deg", "pelvis_height_m"):
        kinematics[key] = [_round(v) for v in samples[key]]
    kinetics: dict[str, list[float]] = {}
    torques = np.asarray(samples["joint_torque_nm"])
    for j, joint in enumerate(joints):
        kinetics[f"{joint}.torque_nm"] = [_round(v) for v in torques[:, j]]
    for key, prefix in (("grf_left_n", "grf_left"), ("grf_right_n", "grf_right")):
        values = np.asarray(samples[key])
        for a, axis in enumerate("xyz"):
            kinetics[f"{prefix}.{axis}"] = [_round(v) for v in values[:, a]]
    for key, prefix in (("cop_m", "cop"), ("cop_left_m", "cop_left"), ("cop_right_m", "cop_right")):
        cop = np.asarray(samples[key])
        kinetics[f"{prefix}.x"] = [_round(v) for v in cop[:, 0]]
        kinetics[f"{prefix}.y"] = [_round(v) for v in cop[:, 1]]
    for key in (
        "grf_planned_vertical_n",
        "cop_margin_m",
        "xcom_margin_m",
        "actuator_power_w",
        "shelf_force_n",
        "activation_max",
        "heel_load_fraction",
    ):
        kinetics[key] = [_round(v) for v in samples[key]]
    kinetics["loaded_contacts"] = [float(v) for v in samples["loaded_contacts"]]
    normal = np.asarray(samples["contact_normal_n"])
    points = [f"{side}_{point}" for side in ("l", "r") for point in mjcf.SOLE_POINTS]
    for p_index, point in enumerate(points):
        kinetics[f"contact.{point}.normal_n"] = [_round(v) for v in normal[:, p_index]]
    position = np.asarray(samples["contact_position_m"])
    for p_index, point in enumerate(points):
        kinetics[f"contact.{point}.x"] = [_round(v) for v in position[:, p_index, 0]]
        kinetics[f"contact.{point}.y"] = [_round(v) for v in position[:, p_index, 1]]
    return {
        "count": count,
        "t": [float(v) for v in samples["t"]],
        "sample_index": [int(v) for v in samples["sample_index"]],
        "phase": list(samples["phase"]),
        "body_names": list(record.body_names),
        "groups": {"pose": pose, "kinematics": kinematics, "kinetics": kinetics},
    }


def _laboratory_recording(
    recording_id: str,
    label: str,
    kind: str,
    description: str,
    record: engine.RepetitionRecord,
    numerics: dict[str, float] | None,
) -> dict[str, Any]:
    body = _repetition_body(record, include_samples=False)
    evaluated = {
        "extrema": body["extrema"],
        "summary": body["summary"],
        "work": body["work"],
        "numerics": numerics,
    }
    checks = criteria.evaluate(evaluated)
    return {
        "recording_id": recording_id,
        "label": label,
        "kind": kind,
        "description": description,
        **body,
        "numerics": numerics if numerics is not None else {},
        "checks": checks,
        "frames": _frames(record),
    }


def _laboratory() -> dict[str, Any]:
    model = engine.load_model()
    nominal = engine.simulate_repetition(model)
    fine_model = engine.load_model()
    fine_model.opt.timestep = 0.5 * float(model.opt.timestep)
    fine = engine.simulate_repetition(fine_model)
    no_internal_model = engine.simulate_repetition(engine.load_model(), dynamic_feedforward=False)
    soft = engine.load_model()
    for pair in range(soft.npair):
        soft.pair_solreffriction[pair, 0] = 0.015
    soft_friction = engine.simulate_repetition(soft)
    differences = _on_common_times(nominal, fine)
    numerics = {
        **differences,
        "momentum_residual_ratio": nominal.extrema["max_momentum_residual_n_s"]
        / fine.extrema["max_momentum_residual_n_s"],
        "tracking_error_difference_deg": abs(
            nominal.extrema["max_knee_tracking_error_deg"]
            - fine.extrema["max_knee_tracking_error_deg"]
        ),
    }
    recordings = [
        _laboratory_recording(
            "repetition",
            "Back squat — nominal",
            "nominal",
            "One controlled repetition at parallel depth, dt 1 ms: standing, descent, bottom, "
            "ascent, standing. Motion integrated from actuator torques.",
            nominal,
            numerics,
        ),
        _laboratory_recording(
            "repetition-half-timestep",
            "Timestep study — dt 0.5 ms",
            "timestep-companion",
            "The same repetition at half the timestep: the convergence companion of the nominal.",
            fine,
            None,
        ),
        _laboratory_recording(
            "ablation-no-internal-model",
            "Ablation — no internal model",
            "ablation",
            "The controller predicts only static torques: every inertial effect must be caught "
            "by feedback. Shown to demonstrate what the checks reject.",
            no_internal_model,
            None,
        ),
        _laboratory_recording(
            "ablation-soft-friction",
            "Ablation — soft friction",
            "ablation",
            "Sole friction at the 15 ms normal-contact time constant (the model before the "
            "repetition was built). Shown to demonstrate what the checks reject.",
            soft_friction,
            None,
        ),
    ]
    return {
        "model_sha256": contract.MODEL_SHA256,
        "criteria_schema": criteria.CRITERIA_SCHEMA,
        "plan": _plan(),
        "model": engine.describe_model(model),
        "recordings": recordings,
    }


_MODES: Final[dict[str, Callable[[], dict[str, Any]]]] = {
    "--keyframe": _keyframe,
    "--report": _report,
    "--stand": _stand,
    "--perturb": _perturb,
    "--passive": _passive,
    "--flight": _flight,
    "--squat": _squat,
    "--repetition": _repetition,
    "--repetition-timestep": _repetition_timestep,
    "--laboratory": _laboratory,
}


def main(argv: list[str] | None = None) -> int:
    """Run exactly one fixed mode, or refuse the argument vector."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1 or arguments[0] not in _MODES:
        sys.stderr.write(
            "dynamisbench squat model: exactly one of " + ", ".join(sorted(_MODES)) + "\n"
        )
        return 2
    mode = arguments[0]
    try:
        payload = _envelope(mode[2:], _MODES[mode]())
        encoded = canonical_semantic_bytes(_finite(payload))
    except contract.SquatModelError as error:
        sys.stderr.write(f"dynamisbench squat model: {error}\n")
        return 1
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
