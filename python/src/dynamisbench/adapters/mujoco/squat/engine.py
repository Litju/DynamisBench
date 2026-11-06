"""MuJoCo execution of the barbell back-squat model.

This is the only module of the squat package that imports MuJoCo (the second reviewed engine
import of the adapter boundary, next to the reference adapter's ``physics.py``). It is loaded
only in the isolated worker environment, by the fixed-mode entry point
:mod:`dynamisbench.adapters.mujoco.squat.__main__` and the model-generation tool.

What it does, and what it never does
------------------------------------
* It **solves** postures: a constrained Gauss-Newton solve puts the feet flat at the declared
  stance, the hands on the bar and the whole-system centre of mass over the declared balance
  point (:mod:`~dynamisbench.adapters.mujoco.squat.stance`).
* It **settles** a posture into MuJoCo's own contact and coupling mechanics with inverse
  dynamics: the floating-base and barbell coordinates are adjusted until the soft contacts and
  the bar constraints carry the load with zero generalized residual.
* It **solves the tonic torques** of a posture as a minimum-effort static equilibrium.
* It **integrates forward dynamics** with ``mj_step``: the controller only chooses neural
  excitations from the measured state. No joint position, velocity or acceleration is ever
  written during a run, and no trajectory is prescribed.

Every number a run reports is measured from the MuJoCo state.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Final

import mujoco
import numpy as np
from numpy.typing import NDArray

from dynamisbench.adapters.mujoco.squat import anthropometry as anth
from dynamisbench.adapters.mujoco.squat import contract, mjcf, movement, stance
from dynamisbench.adapters.mujoco.squat.control import PosturalController, joint_family

__all__ = [
    "RELAXATION_DURATION_S",
    "Disturbance",
    "RepetitionRecord",
    "SquatSynergy",
    "EngineError",
    "Layout",
    "RunSummary",
    "StaticEquilibrium",
    "controller_for",
    "describe_model",
    "engine_version",
    "build_synergy",
    "generator_model",
    "inverse_dynamics_feedforward",
    "keyframe_diagnostics",
    "keyframe_state",
    "layout",
    "load_model",
    "momentum_probe",
    "posture_kinematics",
    "range_violation_deg",
    "relax_to_rest",
    "settle",
    "simulate",
    "simulate_repetition",
    "solve_posture",
    "standing_state",
    "static_equilibrium",
    "verify_model",
    "vertex_height",
]

FloatArray = NDArray[np.float64]

_MASS_TOLERANCE_KG: Final = 1e-9
_GEOMETRY_TOLERANCE: Final = 1e-9
_POSTURE_TOLERANCE: Final = 1e-10
_SETTLE_TOLERANCE_N: Final = 1e-7
_STATIC_RESIDUAL_TOLERANCE: Final = 1e-6


class EngineError(contract.SquatModelError):
    """A squat-model engine computation failed its own consistency checks."""


def engine_version() -> str:
    """The actual MuJoCo version of the running worker environment."""
    return str(mujoco.__version__)


# --------------------------------------------------------------------------------------------
# Model loading and structural verification


def _compile(xml: str) -> mujoco.MjModel:
    try:
        return mujoco.MjModel.from_xml_string(xml)
    except ValueError as error:
        raise EngineError(f"the squat model does not compile: {error}") from error


def load_model() -> mujoco.MjModel:
    """Compile the reviewed, digest-verified packaged asset and verify its structure."""
    if engine_version() != contract.ENGINE_VERSION:
        raise EngineError(
            f"the running MuJoCo {engine_version()} is not the qualified {contract.ENGINE_VERSION}"
        )
    model = _compile(contract.model_bytes().decode("utf-8"))
    verify_model(model, require_keyframe=True)
    return model


def generator_model() -> mujoco.MjModel:
    """Compile the keyframe-free rendering the standing keyframe is generated from."""
    model = _compile(mjcf.render_model_xml())
    verify_model(model, require_keyframe=False)
    return model


def _name(model: mujoco.MjModel, kind: int, index: int) -> str:
    value = mujoco.mj_id2name(model, kind, index)
    return "" if value is None else str(value)


def _id(model: mujoco.MjModel, kind: int, name: str) -> int:
    index = int(mujoco.mj_name2id(model, kind, name))
    if index < 0:
        raise EngineError(f"the squat model has no {name!r}")
    return index


def verify_model(model: mujoco.MjModel, *, require_keyframe: bool) -> None:
    """Refuse a compiled model that is not the declared athlete-barbell structure.

    Every inertial, joint, actuator and solver property is compared with the authority in
    :mod:`~dynamisbench.adapters.mujoco.squat.anthropometry` and
    :mod:`~dynamisbench.adapters.mujoco.squat.mjcf`, after MuJoCo has compiled it.
    """
    specs = anth.joint_specs()
    counts = (
        ("nq", int(model.nq), 7 + len(specs) + 7),
        ("nv", int(model.nv), 6 + len(specs) + 6),
        ("nu", int(model.nu), len(specs)),
        ("na", int(model.na), len(specs)),
        ("njnt", int(model.njnt), len(specs) + 2),
        ("nbody", int(model.nbody), 1 + len(anth.segment_inertias()) + 1),
        ("neq", int(model.neq), 3),
        ("nkey", int(model.nkey), 1 if require_keyframe else 0),
    )
    for label, actual, expected in counts:
        if actual != expected:
            raise EngineError(f"the squat model has {label}={actual}, not {expected}")
    option = model.opt
    if int(option.integrator) != int(mujoco.mjtIntegrator.mjINT_IMPLICITFAST):
        raise EngineError("the squat model integrator is not implicitfast")
    if int(option.solver) != int(mujoco.mjtSolver.mjSOL_NEWTON):
        raise EngineError("the squat model solver is not Newton")
    if int(option.cone) != int(mujoco.mjtCone.mjCONE_ELLIPTIC):
        raise EngineError("the squat model friction cone is not elliptic")
    if int(option.noslip_iterations) != mjcf.NOSLIP_ITERATIONS:
        raise EngineError("the squat model no-slip iteration count changed")
    if not math.isclose(float(option.timestep), mjcf.TIMESTEP_S, rel_tol=0, abs_tol=1e-15):
        raise EngineError("the squat model timestep changed")
    gravity = np.asarray(option.gravity, dtype=np.float64)
    if not np.allclose(gravity, [0.0, 0.0, -anth.GRAVITY_M_S2], rtol=0, atol=1e-12):
        raise EngineError("the squat model gravity is not standard gravity along -z")

    for segment in anth.segment_inertias():
        body = _id(model, mujoco.mjtObj.mjOBJ_BODY, segment.body)
        if abs(float(model.body_mass[body]) - segment.mass) > _MASS_TOLERANCE_KG:
            raise EngineError(f"the {segment.body} mass is not the de Leva mass")
        if not np.allclose(model.body_ipos[body], segment.com, rtol=0, atol=_GEOMETRY_TOLERANCE):
            raise EngineError(f"the {segment.body} centre of mass moved")
        if not np.allclose(
            np.sort(model.body_inertia[body]), np.sort(segment.inertia), rtol=1e-9, atol=1e-12
        ):
            raise EngineError(f"the {segment.body} principal inertia changed")
    bar = _id(model, mujoco.mjtObj.mjOBJ_BODY, "barbell")
    bar_mass, bar_inertia = anth.barbell_inertia()
    if abs(float(model.body_mass[bar]) - bar_mass) > _MASS_TOLERANCE_KG:
        raise EngineError("the barbell mass is not the declared 20 kg")
    if not np.allclose(
        np.sort(model.body_inertia[bar]), np.sort(bar_inertia), rtol=1e-9, atol=1e-12
    ):
        raise EngineError("the barbell inertia changed")
    total = float(np.sum(model.body_mass))
    if abs(total - (anth.BODY_MASS_KG + bar_mass)) > 1e-8:
        raise EngineError(f"the model mass {total} is not athlete plus barbell")
    if bool(np.any(model.dof_armature != 0.0)):
        raise EngineError("the squat model must not add armature (non-physical rotor inertia)")

    for index, spec in enumerate(specs):
        joint = _id(model, mujoco.mjtObj.mjOBJ_JOINT, spec.name)
        if int(model.jnt_type[joint]) != int(mujoco.mjtJoint.mjJNT_HINGE):
            raise EngineError(f"{spec.name} is not a hinge")
        if _name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.jnt_bodyid[joint])) != spec.body:
            raise EngineError(f"{spec.name} is not on {spec.body}")
        if not np.allclose(model.jnt_axis[joint], spec.axis, rtol=0, atol=1e-12):
            raise EngineError(f"{spec.name} axis changed")
        expected_range = np.radians(np.asarray(spec.range_deg, dtype=np.float64))
        if int(model.jnt_limited[joint]) != 1 or not np.allclose(
            model.jnt_range[joint], expected_range, rtol=0, atol=1e-12
        ):
            raise EngineError(f"{spec.name} range of motion changed")
        if _name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, index) != spec.name:
            raise EngineError(f"actuator {index} is not {spec.name}")
        if int(model.actuator_trnid[index, 0]) != joint:
            raise EngineError(f"actuator {spec.name} does not drive its joint")
        negative, positive = spec.torque_nm
        if not np.allclose(
            model.actuator_forcerange[index], [-negative, positive], rtol=0, atol=1e-12
        ):
            raise EngineError(f"actuator {spec.name} torque capacity changed")
        if not math.isclose(
            float(model.actuator_dynprm[index, 0]),
            mjcf.ACTIVATION_TIME_CONSTANT_S,
            rel_tol=0,
            abs_tol=1e-15,
        ):
            raise EngineError(f"actuator {spec.name} activation dynamics changed")
    expected_equality = (
        int(mujoco.mjtEq.mjEQ_WELD),
        int(mujoco.mjtEq.mjEQ_CONNECT),
        int(mujoco.mjtEq.mjEQ_CONNECT),
    )
    if tuple(int(value) for value in model.eq_type) != expected_equality:
        raise EngineError("the barbell coupling is not one weld and two grip connects")


# --------------------------------------------------------------------------------------------
# Index layout


@dataclass(frozen=True, slots=True)
class Layout:
    """Addresses of every quantity the engine reads, resolved once from names."""

    joint_names: tuple[str, ...]
    joint_qpos: NDArray[np.int64]
    joint_dof: NDArray[np.int64]
    joint_range: FloatArray
    peak_torque: FloatArray
    root_qpos: int
    bar_qpos: int
    bar_dof: int
    unactuated_dof: NDArray[np.int64]
    body_dof: NDArray[np.int64]
    bodies: dict[str, int]
    sites: dict[str, int]
    floor_geom: int
    sole_geoms: dict[str, tuple[int, ...]]
    total_mass: float
    bar_mass: float


def layout(model: mujoco.MjModel) -> Layout:
    """Resolve the name-based layout of a verified squat model."""
    names = mjcf.ACTUATED_JOINTS
    joints = [_id(model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in names]
    joint_qpos = np.array([int(model.jnt_qposadr[j]) for j in joints], dtype=np.int64)
    joint_dof = np.array([int(model.jnt_dofadr[j]) for j in joints], dtype=np.int64)
    root = _id(model, mujoco.mjtObj.mjOBJ_JOINT, "root")
    bar_joint = _id(model, mujoco.mjtObj.mjOBJ_JOINT, "barbell_root")
    bar_dof = int(model.jnt_dofadr[bar_joint])
    actuated = set(int(value) for value in joint_dof)
    unactuated = np.array([i for i in range(model.nv) if i not in actuated], dtype=np.int64)
    body_dof = np.array(
        [i for i in range(model.nv) if not bar_dof <= i < bar_dof + 6], dtype=np.int64
    )
    body_names = [_name(model, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, model.nbody)]
    site_names = [_name(model, mujoco.mjtObj.mjOBJ_SITE, i) for i in range(model.nsite)]
    sole_geoms: dict[str, tuple[int, ...]] = {}
    for side in ("l", "r"):
        sole_geoms[side] = tuple(
            _id(model, mujoco.mjtObj.mjOBJ_GEOM, f"foot_{side}_{point}")
            for point in mjcf.SOLE_POINTS
        )
    peak = np.array(
        [
            max(float(-model.actuator_forcerange[i, 0]), float(model.actuator_forcerange[i, 1]))
            for i in range(model.nu)
        ],
        dtype=np.float64,
    )
    return Layout(
        joint_names=names,
        joint_qpos=joint_qpos,
        joint_dof=joint_dof,
        joint_range=np.array([model.jnt_range[j] for j in joints], dtype=np.float64),
        peak_torque=peak,
        root_qpos=int(model.jnt_qposadr[root]),
        bar_qpos=int(model.jnt_qposadr[bar_joint]),
        bar_dof=bar_dof,
        unactuated_dof=unactuated,
        body_dof=body_dof,
        bodies={name: i + 1 for i, name in enumerate(body_names)},
        sites={name: i for i, name in enumerate(site_names)},
        floor_geom=_id(model, mujoco.mjtObj.mjOBJ_GEOM, mjcf.FLOOR_GEOM),
        sole_geoms=sole_geoms,
        total_mass=float(np.sum(model.body_mass)),
        bar_mass=float(model.body_mass[_id(model, mujoco.mjtObj.mjOBJ_BODY, "barbell")]),
    )


# --------------------------------------------------------------------------------------------
# Geometry helpers


def _rotvec(matrix: FloatArray) -> FloatArray:
    """Rotation vector (axis * angle, world frame) of a 3x3 rotation matrix."""
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.ascontiguousarray(matrix, dtype=np.float64).reshape(9))
    if quat[0] < 0.0:
        quat = -quat
    result = np.zeros(3)
    mujoco.mju_quat2Vel(result, quat, 1.0)
    return result


def _rot_z(angle: float) -> FloatArray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _site_jacobian(
    model: mujoco.MjModel, data: mujoco.MjData, site: int
) -> tuple[FloatArray, FloatArray]:
    jacp = np.zeros((3, model.nv))
    jacr = np.zeros((3, model.nv))
    mujoco.mj_jacSite(model, data, jacp, jacr, site)
    return jacp, jacr


def _point_jacobian(
    model: mujoco.MjModel, data: mujoco.MjData, point: FloatArray, body: int
) -> FloatArray:
    jacp = np.zeros((3, model.nv))
    mujoco.mj_jac(model, data, jacp, None, np.ascontiguousarray(point), body)
    return jacp


def _slave_bar(model: mujoco.MjModel, data: mujoco.MjData, lay: Layout) -> None:
    """Place the bar exactly on the shelf site (zero weld violation) for posture solving."""
    shelf = lay.sites["bar_shelf"]
    data.qpos[lay.bar_qpos : lay.bar_qpos + 3] = data.site_xpos[shelf]
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.ascontiguousarray(data.site_xmat[shelf]))
    data.qpos[lay.bar_qpos + 3 : lay.bar_qpos + 7] = quat


def _kinematics(model: mujoco.MjModel, data: mujoco.MjData, lay: Layout) -> None:
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    _slave_bar(model, data, lay)
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)


# --------------------------------------------------------------------------------------------
# Posture solving


def _inclination_and_gradient(vector: FloatArray, dvector: FloatArray) -> tuple[float, FloatArray]:
    """Angle of ``vector`` from world vertical and its gradient, given ``d vector / d q``."""
    length = float(np.linalg.norm(vector))
    unit_z = float(vector[2]) / length
    angle = math.acos(max(-1.0, min(1.0, unit_z)))
    sine = max(math.sin(angle), 1e-9)
    d_unit_z = dvector[2] / length - float(vector[2]) * (vector @ dvector) / length**3
    return angle, -d_unit_z / sine


def _parallel_trunk_shank(
    model: mujoco.MjModel, data: mujoco.MjData, lay: Layout, side: str
) -> tuple[FloatArray, float]:
    """Residual row (trunk inclination - shank inclination) and its value, radians.

    The trunk is the mid-hip to cervicale line (pelvis origin to head origin); the shank is the
    knee-to-ankle line. Both inclinations are from world vertical.
    """
    pelvis, head = lay.bodies["pelvis"], lay.bodies["head"]
    knee, ankle = lay.bodies[f"shank_{side}"], lay.bodies[f"foot_{side}"]
    trunk = np.asarray(data.xpos[head] - data.xpos[pelvis], dtype=np.float64)
    shank = np.asarray(data.xpos[knee] - data.xpos[ankle], dtype=np.float64)

    def body_jacobian(body: int) -> FloatArray:
        jacp = np.zeros((3, model.nv))
        mujoco.mj_jacBody(model, data, jacp, None, body)
        return jacp

    trunk_angle, trunk_grad = _inclination_and_gradient(
        trunk, body_jacobian(head) - body_jacobian(pelvis)
    )
    shank_angle, shank_grad = _inclination_and_gradient(
        shank, body_jacobian(knee) - body_jacobian(ankle)
    )
    return trunk_grad - shank_grad, trunk_angle - shank_angle


def solve_posture(
    model: mujoco.MjModel,
    *,
    knee_flexion_deg: float | None = None,
    max_iterations: int = 400,
) -> FloatArray:
    """Solve the standing (``knee_flexion_deg=None``) or a static squat posture.

    Hard constraints: feet flat at :data:`~stance.STANCE`, hands on the bar grips, bar on the
    shelf, whole-system centre of mass over :data:`~stance.BALANCE_POINT_ANTERIOR_M`, and for
    a squat both knees at ``knee_flexion_deg``. Soft: the declared posture preferences. Every
    hinge stays inside its range of motion. Returns ``qpos`` with the bar on the shelf.
    """
    lay = layout(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    squat = knee_flexion_deg is not None
    geometry = anth.geometry()
    targets: dict[str, tuple[FloatArray, FloatArray]] = {}
    for side, sign in (("l", 1.0), ("r", -1.0)):
        targets[f"foot_{side}"] = (
            np.array([0.0, sign * stance.STANCE.ankle_half_width_m, geometry.ankle_height]),
            _rot_z(sign * math.radians(stance.STANCE.toe_out_deg)),
        )
    preferences = [
        stance.preference_for(joint_family(name), squat=squat) for name in lay.joint_names
    ]
    for k, preference in enumerate(preferences):
        data.qpos[lay.joint_qpos[k]] = math.radians(preference.target_deg)
    if squat:
        assert knee_flexion_deg is not None
        for k, name in enumerate(lay.joint_names):
            if joint_family(name) == "knee_flexion":
                data.qpos[lay.joint_qpos[k]] = math.radians(knee_flexion_deg)
    shelf = lay.sites["bar_shelf"]
    upper = lay.bodies["torso_upper"]
    pelvis = lay.bodies["pelvis"]
    columns = lay.body_dof
    n = len(columns)
    target_com = np.array([stance.BALANCE_POINT_ANTERIOR_M, 0.0])
    pelvis_weights = (1.0, 0.0 if squat else 0.3, 1.0)
    hard_norm = math.inf
    step_norm = math.inf
    for _iteration in range(max_iterations):
        _kinematics(model, data, lay)
        hard_rows: list[FloatArray] = []
        hard_res: list[FloatArray] = []
        for body_name, (position, rotation) in targets.items():
            body = lay.bodies[body_name]
            jacp = np.zeros((3, model.nv))
            jacr = np.zeros((3, model.nv))
            mujoco.mj_jacBody(model, data, jacp, jacr, body)
            hard_rows += [jacp, jacr]
            hard_res += [
                data.xpos[body] - position,
                _rotvec(data.xmat[body].reshape(3, 3) @ rotation.T),
            ]
        shelf_rotation = data.site_xmat[shelf].reshape(3, 3)
        for (hand, _bar_site), sign in zip(mjcf.GRIP_SITES, (1.0, -1.0), strict=True):
            grip_point = data.site_xpos[shelf] + shelf_rotation @ np.array(
                [0.0, sign * anth.BARBELL.grip_half_width, 0.0]
            )
            jacp, _ = _site_jacobian(model, data, lay.sites[hand])
            hard_rows.append(jacp - _point_jacobian(model, data, grip_point, upper))
            hard_res.append(data.site_xpos[lay.sites[hand]] - grip_point)
        com_jac = np.zeros((3, model.nv))
        mujoco.mj_jacSubtreeCom(model, data, com_jac, 0)
        shelf_jac, _ = _site_jacobian(model, data, shelf)
        com_jac = com_jac + (lay.bar_mass / lay.total_mass) * shelf_jac
        hard_rows.append(com_jac[:2])
        hard_res.append(data.subtree_com[0][:2] - target_com)
        if squat:
            assert knee_flexion_deg is not None
            for k, name in enumerate(lay.joint_names):
                if joint_family(name) == "knee_flexion":
                    row = np.zeros((1, model.nv))
                    row[0, lay.joint_dof[k]] = 1.0
                    hard_rows.append(row)
                    hard_res.append(
                        np.array([data.qpos[lay.joint_qpos[k]] - math.radians(knee_flexion_deg)])
                    )
        jh = np.vstack(hard_rows)[:, columns]
        rh = np.concatenate(hard_res)
        hard_norm = float(np.abs(rh).max())

        soft_rows: list[FloatArray] = []
        soft_res: list[float] = []
        for k, preference in enumerate(preferences):
            row = np.zeros(model.nv)
            row[lay.joint_dof[k]] = preference.weight
            soft_rows.append(row)
            soft_res.append(
                preference.weight
                * (data.qpos[lay.joint_qpos[k]] - math.radians(preference.target_deg))
            )
        if squat:
            for side in ("l", "r"):
                row, value = _parallel_trunk_shank(model, data, lay, side)
                soft_rows.append(stance.TRUNK_SHANK_PARALLEL_WEIGHT * row)
                soft_res.append(stance.TRUNK_SHANK_PARALLEL_WEIGHT * value)
        pelvis_rotation = _rotvec(data.xmat[pelvis].reshape(3, 3))
        for axis, weight in enumerate(pelvis_weights):
            row = np.zeros(model.nv)
            row[3 + axis] = weight
            soft_rows.append(row)
            soft_res.append(weight * float(pelvis_rotation[axis]))
        js = np.array(soft_rows)[:, columns]
        rs = np.array(soft_res)

        kkt = np.block(
            [
                [js.T @ js + 1e-6 * np.eye(n), jh.T],
                [jh, np.zeros((jh.shape[0], jh.shape[0]))],
            ]
        )
        rhs = np.concatenate([-js.T @ rs, -rh])
        try:
            solution = np.linalg.solve(kkt, rhs)
        except np.linalg.LinAlgError:
            solution = np.linalg.lstsq(kkt, rhs, rcond=None)[0]
        dq = np.zeros(model.nv)
        dq[columns] = solution[:n]
        step_norm = float(np.linalg.norm(dq))
        if step_norm > 0.1:
            dq *= 0.1 / step_norm
        mujoco.mj_integratePos(model, data.qpos, dq, 1.0)
        for k in range(len(lay.joint_names)):
            low, high = lay.joint_range[k]
            address = lay.joint_qpos[k]
            data.qpos[address] = min(max(float(data.qpos[address]), low), high)
        if step_norm < 1e-12 and hard_norm < _POSTURE_TOLERANCE:
            break
    _kinematics(model, data, lay)
    if not hard_norm < _POSTURE_TOLERANCE:
        raise EngineError(
            f"the posture solve did not satisfy its hard constraints (residual {hard_norm:.3e})"
        )
    return np.array(data.qpos, dtype=np.float64)


# --------------------------------------------------------------------------------------------
# Settling into MuJoCo's contact and coupling mechanics


def _inverse_residual(
    model: mujoco.MjModel, data: mujoco.MjData, qpos: FloatArray, dofs: NDArray[np.int64]
) -> FloatArray:
    data.qpos[:] = qpos
    data.qvel[:] = 0.0
    data.qacc[:] = 0.0
    mujoco.mj_inverse(model, data)
    return np.array(data.qfrc_inverse[dofs], dtype=np.float64)


def settle(model: mujoco.MjModel, qpos: FloatArray, *, max_iterations: int = 80) -> FloatArray:
    """Adjust only the floating-base and barbell coordinates until MuJoCo carries the load.

    Joint angles are held. The pelvis pose (plantar soft-tissue compression and rocking) and
    the bar pose (shelf and grip compliance) are solved so that MuJoCo's inverse dynamics,
    with zero velocity and acceleration, needs no force on any unactuated coordinate: the soft
    contacts and the bar constraints alone carry gravity there.
    """
    lay = layout(model)
    data = mujoco.MjData(model)
    q = np.array(qpos, dtype=np.float64)
    # Start with every sole sphere slightly inside the floor so the contact set is stable.
    q[lay.root_qpos + 2] -= 5e-4
    q[lay.bar_qpos + 2] -= 5e-4
    dofs = lay.unactuated_dof
    residual = _inverse_residual(model, data, q, dofs)
    for _iteration in range(max_iterations):
        if float(np.abs(residual).max()) < _SETTLE_TOLERANCE_N:
            break
        jacobian = np.zeros((len(dofs), len(dofs)))
        step = 1e-8
        for column, dof in enumerate(dofs):
            perturbation = np.zeros(model.nv)
            perturbation[dof] = step
            probe = q.copy()
            mujoco.mj_integratePos(model, probe, perturbation, 1.0)
            jacobian[:, column] = (_inverse_residual(model, data, probe, dofs) - residual) / step
        delta = np.linalg.lstsq(jacobian, -residual, rcond=1e-12)[0]
        largest = float(np.abs(delta).max())
        if largest > 1e-3:
            delta *= 1e-3 / largest
        update = np.zeros(model.nv)
        update[dofs] = delta
        mujoco.mj_integratePos(model, q, update, 1.0)
        residual = _inverse_residual(model, data, q, dofs)
    final = float(np.abs(residual).max())
    if not final < _SETTLE_TOLERANCE_N:
        raise EngineError(f"the contact settle did not converge (residual {final:.3e} N)")
    return q


# --------------------------------------------------------------------------------------------
# Minimum-effort static equilibrium


@dataclass(frozen=True, slots=True)
class StaticEquilibrium:
    """The minimum-effort static equilibrium of one posture.

    Unknowns are the 29 joint torques, one 6-D ground wrench per foot (at its sole site) and
    the bar coupling forces (6-D shelf wrench on the bar, 3-D force per hand). Among all exact
    solutions of ``qfrc_bias = S' tau + J_feet' w + J_bar' lambda`` it minimises the sum of
    squared normalised activations, with contact and coupling forces nearly free.
    """

    activation: FloatArray
    torque: FloatArray
    foot_wrench: dict[str, FloatArray]
    shelf_wrench_on_bar: FloatArray
    grip_force_on_bar: dict[str, FloatArray]
    centre_of_pressure: dict[str, FloatArray]
    residual: float


def _minimum_effort(
    model: mujoco.MjModel, data: mujoco.MjData, lay: Layout, load: FloatArray
) -> tuple[FloatArray, FloatArray, float]:
    """Solve ``load = S' tau + J_feet' w + J_bar' lambda`` for minimum normalised effort.

    ``data`` must hold kinematics (and CoM positions) of the configuration. Returns the
    activations, the 24 contact and coupling unknowns, and the residual. Contact and coupling
    forces are scaled to be ~free relative to neural effort, so the solution minimises the sum
    of squared activations. Shared by the static equilibrium and the movement feedforward.
    """
    selection = np.zeros((model.nv, model.nu))
    selection[lay.joint_dof, np.arange(model.nu)] = lay.peak_torque
    blocks = [selection]
    for side in ("l", "r"):
        jacp, jacr = _site_jacobian(model, data, lay.sites[f"sole_{side}"])
        blocks.append(np.hstack([jacp.T, jacr.T]))
    bar_p, bar_r = _site_jacobian(model, data, lay.sites["bar_center"])
    shelf_p, shelf_r = _site_jacobian(model, data, lay.sites["bar_shelf"])
    blocks.append(np.hstack([(bar_p - shelf_p).T, (bar_r - shelf_r).T]))
    for hand, bar_site in mjcf.GRIP_SITES:
        hand_p, _ = _site_jacobian(model, data, lay.sites[hand])
        grip_p, _ = _site_jacobian(model, data, lay.sites[bar_site])
        blocks.append((hand_p - grip_p).T)
    matrix = np.hstack(blocks)
    body_weight = lay.total_mass * anth.GRAVITY_M_S2
    bar_weight = lay.bar_mass * anth.GRAVITY_M_S2
    free = 30.0  # contact and coupling forces are ~free relative to neural effort
    foot_scale = [body_weight] * 3 + [0.1 * body_weight] * 3
    scale = np.concatenate(
        [
            np.ones(model.nu),
            free * np.array(foot_scale * 2),
            free * np.array([bar_weight] * 3 + [0.1 * bar_weight] * 3 + [bar_weight] * 6),
        ]
    )
    scaled = matrix * scale
    # Minimum-norm solution of the full-row-rank system: x = A' (A A')^-1 b. It is the same
    # solution an SVD least-squares solve returns, at a fraction of the cost; the residual is
    # verified and the SVD path is the fallback.
    try:
        solution = scaled.T @ np.linalg.solve(scaled @ scaled.T, load) * scale
    except np.linalg.LinAlgError:
        solution = np.linalg.lstsq(scaled, load, rcond=None)[0] * scale
    residual = float(np.abs(matrix @ solution - load).max())
    if residual > _STATIC_RESIDUAL_TOLERANCE:
        solution = np.linalg.lstsq(scaled, load, rcond=None)[0] * scale
        residual = float(np.abs(matrix @ solution - load).max())
    return solution[: model.nu], solution[model.nu :], residual


def static_equilibrium(model: mujoco.MjModel, qpos: FloatArray) -> StaticEquilibrium:
    """Solve the minimum-effort tonic torques that hold ``qpos`` at rest."""
    lay = layout(model)
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    load = np.array(data.qfrc_bias - data.qfrc_passive, dtype=np.float64)
    activation, forces, residual = _minimum_effort(model, data, lay, load)
    if not residual < _STATIC_RESIDUAL_TOLERANCE:
        raise EngineError(f"the static equilibrium has no exact solution ({residual:.3e})")
    wrenches = {"l": forces[0:6], "r": forces[6:12]}
    # The coupling unknowns multiply (J_site1 - J_site2)': lambda acts on the bar (site1 of
    # the weld) and on the hand (site1 of each connect), so the hand force on the bar is -mu.
    shelf = forces[12:18]
    grips = {"l": -forces[18:21], "r": -forces[21:24]}
    pressure: dict[str, FloatArray] = {}
    for side, wrench in wrenches.items():
        force, moment = wrench[:3], wrench[3:]
        origin = data.site_xpos[lay.sites[f"sole_{side}"]]
        if force[2] <= 0.0:
            raise EngineError(f"the {side} foot would have to pull on the floor")
        pressure[side] = np.array(
            [origin[0] - moment[1] / force[2], origin[1] + moment[0] / force[2]]
        )
    return StaticEquilibrium(
        activation=activation,
        torque=activation * lay.peak_torque,
        foot_wrench=wrenches,
        shelf_wrench_on_bar=shelf,
        grip_force_on_bar=grips,
        centre_of_pressure=pressure,
        residual=residual,
    )


RELAXATION_DURATION_S: Final = 30.0
"""Forward-dynamics relaxation before the keyframe is taken. The slowest closed-loop mode of
the standing posture is a 0.5 Hz whole-body sagittal sway with a ~7 s decay time constant;
30 s reduces it by ~70x."""


def relax_to_rest(
    model: mujoco.MjModel,
    qpos: FloatArray,
    activation: FloatArray,
    *,
    duration_s: float = RELAXATION_DURATION_S,
) -> tuple[FloatArray, FloatArray, float]:
    """Let the closed-loop model come to rest by forward dynamics.

    The static solution is computed with ideal foot wrenches; MuJoCo's friction only carries
    the inter-foot shear once the feet have seated (no-slip stiction). Integrating the
    controller about ``(qpos, activation)`` until the motion has died out yields a state that
    *is* a rest state of the forward dynamics. Returns ``(qpos, activation, max |qvel|)``.
    """
    lay = layout(model)
    controller = controller_for(model, qpos, activation)
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[:] = qpos
    data.act[:] = activation
    data.ctrl[:] = activation
    mujoco.mj_forward(model, data)
    steps = int(round(duration_s / float(model.opt.timestep)))
    for _step in range(steps):
        data.ctrl[:] = controller.excitation(
            np.asarray(data.qpos[lay.joint_qpos], dtype=np.float64),
            np.asarray(data.qvel[lay.joint_dof], dtype=np.float64),
        )
        mujoco.mj_step(model, data)
        if not np.all(np.isfinite(data.qpos)):
            raise EngineError("the relaxation to rest became non-finite")
    speed = float(np.max(np.abs(np.asarray(data.qvel, dtype=np.float64))))
    return (
        np.array(data.qpos, dtype=np.float64),
        np.array(data.act, dtype=np.float64),
        speed,
    )


def standing_state(model: mujoco.MjModel) -> tuple[FloatArray, FloatArray]:
    """Generate the standing equilibrium ``(qpos, activation)`` from the declarations.

    Posture solve, inverse-dynamics contact settle, minimum-effort tonic torques, then
    forward-dynamics relaxation to rest. The returned state is the packaged keyframe.
    """
    qpos = settle(model, solve_posture(model))
    activation = static_equilibrium(model, qpos).activation
    relaxed_qpos, relaxed_activation, _speed = relax_to_rest(model, qpos, activation)
    return relaxed_qpos, relaxed_activation


def keyframe_state(model: mujoco.MjModel) -> tuple[FloatArray, FloatArray]:
    """The packaged standing keyframe ``(qpos, activation)``."""
    key = _id(model, mujoco.mjtObj.mjOBJ_KEY, mjcf.KEYFRAME_NAME)
    return (
        np.array(model.key_qpos[key], dtype=np.float64),
        np.array(model.key_act[key], dtype=np.float64),
    )


# --------------------------------------------------------------------------------------------
# Forward simulation


@dataclass(frozen=True, slots=True)
class Disturbance:
    """An external force on one body's centre of mass, world frame, for a time window."""

    body: str
    start_s: float
    duration_s: float
    force_n: tuple[float, float, float]


@dataclass(slots=True)
class RunSummary:
    """Measured outcome of one forward-dynamics run. Every field comes from MuJoCo state."""

    duration_s: float
    steps: int
    all_finite: bool
    trajectory_sha256: str
    com_initial: FloatArray
    com_final: FloatArray
    com_max_horizontal_excursion_m: float
    com_min_height_m: float
    joint_max_deviation_deg: float
    joint_final_deviation_deg: float
    joint_limit_max_violation_deg: float
    vertical_grf_mean_last_s_n: float
    vertical_grf_min_n: float
    vertical_grf_max_n: float
    min_loaded_sole_contacts: int
    final_loaded_sole_contacts: int
    min_geometric_sole_contacts: int
    min_contact_point_load_n: float
    foot_max_slip_m: float
    weld_max_position_error_m: float
    weld_max_angle_error_deg: float
    grip_max_error_m: float
    shelf_force_mean_last_s_n: float
    max_abs_activation: float
    saturated_fraction: float
    cop_anterior_mean_last_s_m: float
    bar_max_tilt_deg: float
    max_floor_penetration_m: float
    samples: list[dict[str, float]] = field(default_factory=list)


LOADED_CONTACT_THRESHOLD_N: Final = 5.0
"""A plantar contact point is load-bearing when its normal force exceeds this (~0.5 % of the
athlete-plus-bar weight). A point that touches the floor geometrically but carries less does
not support the body and is excluded from the support polygon."""


@dataclass(frozen=True, slots=True)
class ContactLoads:
    """Measured load at every plantar contact point, at one instant.

    Points are ordered left foot then right foot, each as
    :data:`~dynamisbench.adapters.mujoco.squat.mjcf.SOLE_POINTS`. A point that is not in
    geometric contact has zero force and its position is the projection of its sphere centre.
    """

    normal_n: FloatArray
    tangential_n: FloatArray
    friction_utilization: FloatArray
    penetration_m: FloatArray
    position_xy: FloatArray
    in_contact: NDArray[np.bool_]
    total_force_n: FloatArray
    other_floor_vertical_n: float

    @property
    def loaded(self) -> NDArray[np.bool_]:
        return self.normal_n > LOADED_CONTACT_THRESHOLD_N

    def foot(self, side: str) -> slice:
        count = len(mjcf.SOLE_POINTS)
        return slice(0, count) if side == "l" else slice(count, 2 * count)

    def heel_share(self, side: str) -> float:
        """Heel (two heel points) share of that foot's own vertical load."""
        loads = self.normal_n[self.foot(side)]
        return float(np.sum(loads[:2]) / max(float(np.sum(loads)), 1e-9))

    def forefoot_share(self, side: str) -> float:
        """Forefoot (metatarsal heads and hallux) share of that foot's own vertical load."""
        loads = self.normal_n[self.foot(side)]
        return float(np.sum(loads[2:]) / max(float(np.sum(loads)), 1e-9))

    def centre_of_pressure(self, side: str | None = None) -> FloatArray:
        """Centre of pressure of both feet, or of one foot (``"l"`` or ``"r"``); NaN unloaded."""
        part = slice(None) if side is None else self.foot(side)
        normal = self.normal_n[part]
        total = float(np.sum(normal))
        if total <= 1e-9:
            return np.full(2, math.nan)
        return (normal @ self.position_xy[part]) / total

    def support_polygon(self) -> list[tuple[float, float]]:
        """Convex hull of the load-bearing contact points only."""
        return _convex_hull([(float(x), float(y)) for x, y in self.position_xy[self.loaded]])


def contact_loads(model: mujoco.MjModel, data: mujoco.MjData, lay: Layout) -> ContactLoads:
    """Measure the plantar contact loads from the contact forces MuJoCo applied at ``data``'s
    instant (after ``mj_forward`` or ``mj_step``, the forces of that instant)."""
    points = [g for side in ("l", "r") for g in lay.sole_geoms[side]]
    index_of = {geom: i for i, geom in enumerate(points)}
    count = len(points)
    normal = np.zeros(count)
    tangential = np.zeros(count)
    utilization = np.zeros(count)
    penetration = np.zeros(count)
    in_contact = np.zeros(count, dtype=bool)
    position = np.array([np.array(data.geom_xpos[g][:2]) for g in points], dtype=np.float64)
    total = np.zeros(3)
    other = 0.0
    local = np.zeros(6)
    for contact_index in range(data.ncon):
        contact = data.contact[contact_index]
        geoms = (int(contact.geom1), int(contact.geom2))
        if lay.floor_geom not in geoms:
            continue
        mujoco.mj_contactForce(model, data, contact_index, local)
        frame = np.asarray(contact.frame, dtype=np.float64).reshape(3, 3)
        world = frame.T @ local[:3]
        if geoms[0] != lay.floor_geom:
            world = -world
        total += world
        body = geoms[1] if geoms[0] == lay.floor_geom else geoms[0]
        if body not in index_of:
            other += float(world[2])
            continue
        i = index_of[body]
        normal[i] += float(local[0])
        tangential[i] = float(np.hypot(local[1], local[2]))
        mu = float(contact.friction[0])
        utilization[i] = tangential[i] / (mu * local[0]) if local[0] > 1e-9 else 0.0
        penetration[i] = max(0.0, -float(contact.dist))
        position[i] = np.asarray(contact.pos[:2], dtype=np.float64)
        in_contact[i] = True
    return ContactLoads(
        normal_n=normal,
        tangential_n=tangential,
        friction_utilization=utilization,
        penetration_m=penetration,
        position_xy=position,
        in_contact=in_contact,
        total_force_n=total,
        other_floor_vertical_n=other,
    )


def _shelf_force(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    """Magnitude of the translational force the shelf weld transmits to the bar."""
    rows = [
        i
        for i in range(data.nefc)
        if int(data.efc_type[i]) == int(mujoco.mjtConstraint.mjCNSTR_EQUALITY)
        and int(data.efc_id[i]) == 0
    ]
    if len(rows) != 6:
        raise EngineError("the shelf weld is not active as six constraint rows")
    return float(np.linalg.norm(np.asarray(data.efc_force[rows[:3]], dtype=np.float64)))


def _equality_errors(data: mujoco.MjData, lay: Layout) -> tuple[float, float, float]:
    shelf = lay.sites["bar_shelf"]
    center = lay.sites["bar_center"]
    position = float(np.linalg.norm(data.site_xpos[center] - data.site_xpos[shelf]))
    relative = data.site_xmat[center].reshape(3, 3) @ data.site_xmat[shelf].reshape(3, 3).T
    angle = math.degrees(float(np.linalg.norm(_rotvec(relative))))
    grip = max(
        float(np.linalg.norm(data.site_xpos[lay.sites[hand]] - data.site_xpos[lay.sites[bar]]))
        for hand, bar in mjcf.GRIP_SITES
    )
    return position, angle, grip


def range_violation_deg(model: mujoco.MjModel, qpos: FloatArray) -> float:
    """Largest excursion of any actuated joint beyond its range of motion, degrees."""
    lay = layout(model)
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    return _range_violation_deg(data, lay)


def _range_violation_deg(data: mujoco.MjData, lay: Layout) -> float:
    angles = np.asarray(data.qpos[lay.joint_qpos], dtype=np.float64)
    below = lay.joint_range[:, 0] - angles
    above = angles - lay.joint_range[:, 1]
    return math.degrees(max(0.0, float(np.max(below)), float(np.max(above))))


def simulate(
    model: mujoco.MjModel,
    qpos: FloatArray,
    activation: FloatArray,
    *,
    controller: PosturalController | None,
    duration_s: float,
    disturbance: Disturbance | None = None,
    sample_period_s: float = 0.01,
) -> RunSummary:
    """Integrate forward dynamics from ``(qpos, activation)`` at rest.

    Neural excitation comes from the postural ``controller`` (feedback from the measured
    state), or is zero when ``controller`` is ``None`` (a passive, relaxing athlete). An
    optional ``disturbance`` pushes one body. Nothing else acts on the model.
    """
    lay = layout(model)
    steps = int(round(duration_s / float(model.opt.timestep)))
    if steps <= 0 or not math.isclose(
        steps * float(model.opt.timestep), duration_s, rel_tol=0, abs_tol=1e-9
    ):
        raise EngineError("the run duration must be a positive whole number of timesteps")
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[:] = qpos
    data.qvel[:] = 0.0
    data.act[:] = activation
    data.ctrl[:] = activation
    mujoco.mj_forward(model, data)
    reference = np.asarray(qpos[lay.joint_qpos], dtype=np.float64)
    feet = {side: np.array(data.xpos[lay.bodies[f"foot_{side}"]]) for side in ("l", "r")}
    com_initial = np.array(data.subtree_com[0])
    hasher = hashlib.sha256()
    sample_every = max(1, int(round(sample_period_s / float(model.opt.timestep))))
    last_second = max(1, int(round(1.0 / float(model.opt.timestep))))
    pelvis_body = lay.bodies[disturbance.body] if disturbance is not None else -1
    bar_body = lay.bodies["barbell"]

    state = {
        "com_max_h": 0.0,
        "com_min_z": math.inf,
        "dq_max": 0.0,
        "range": 0.0,
        "grf_min": math.inf,
        "grf_max": -math.inf,
        "contacts_min": 10**6,
        "slip": 0.0,
        "weld_p": 0.0,
        "weld_a": 0.0,
        "grip": 0.0,
        "act": 0.0,
        "saturated": 0.0,
        "tilt": 0.0,
        "penetration": 0.0,
        "geometric_min": 10**6,
        "point_load_min": math.inf,
    }
    grf_tail: list[float] = []
    shelf_tail: list[float] = []
    cop_tail: list[float] = []
    samples: list[dict[str, float]] = []
    contacts = 0
    previous_time = float(data.time)
    for step in range(steps):
        # The snapshot of this step is taken at the state *before* integration: MuJoCo derives
        # kinematics, contacts and forces at that state, so everything recorded is synchronized.
        state_time = float(data.time)
        state_qpos = np.array(data.qpos, dtype=np.float64)
        state_act = np.array(data.act, dtype=np.float64)
        if controller is not None:
            data.ctrl[:] = controller.excitation(
                np.asarray(data.qpos[lay.joint_qpos], dtype=np.float64),
                np.asarray(data.qvel[lay.joint_dof], dtype=np.float64),
            )
        else:
            data.ctrl[:] = 0.0
        data.xfrc_applied[:] = 0.0
        if disturbance is not None and (
            disturbance.start_s <= float(data.time) < disturbance.start_s + disturbance.duration_s
        ):
            data.xfrc_applied[pelvis_body, :3] = disturbance.force_n
        mujoco.mj_step(model, data)
        if not (
            np.all(np.isfinite(data.qpos))
            and np.all(np.isfinite(data.qvel))
            and np.all(np.isfinite(data.act))
        ):
            raise EngineError(f"the state became non-finite at t={float(data.time):.4f} s")
        current = float(data.time)
        if not math.isclose(
            current, previous_time + float(model.opt.timestep), rel_tol=0, abs_tol=1e-9
        ):
            raise EngineError("simulation time did not advance by exactly one timestep")
        previous_time = current
        hasher.update(np.ascontiguousarray(data.qpos, dtype="<f8").tobytes())
        hasher.update(np.ascontiguousarray(data.qvel, dtype="<f8").tobytes())

        com = np.array(data.subtree_com[0], dtype=np.float64)
        state["com_max_h"] = max(
            state["com_max_h"], float(np.linalg.norm(com[:2] - com_initial[:2]))
        )
        state["com_min_z"] = min(state["com_min_z"], float(com[2]))
        angles = np.asarray(state_qpos[lay.joint_qpos], dtype=np.float64)
        deviation = math.degrees(float(np.max(np.abs(angles - reference))))
        state["dq_max"] = max(state["dq_max"], deviation)
        state["range"] = max(
            state["range"],
            math.degrees(
                max(
                    0.0,
                    float(np.max(lay.joint_range[:, 0] - angles)),
                    float(np.max(angles - lay.joint_range[:, 1])),
                )
            ),
        )
        loads = contact_loads(model, data, lay)
        force = loads.total_force_n
        cop = loads.centre_of_pressure()
        contacts = int(np.sum(loads.loaded))
        state["grf_min"] = min(state["grf_min"], float(force[2]))
        state["grf_max"] = max(state["grf_max"], float(force[2]))
        state["contacts_min"] = min(state["contacts_min"], contacts)
        state["geometric_min"] = min(state["geometric_min"], int(np.sum(loads.in_contact)))
        state["point_load_min"] = min(state["point_load_min"], float(np.min(loads.normal_n)))
        for side, start in feet.items():
            moved = np.asarray(data.xpos[lay.bodies[f"foot_{side}"]])[:2] - start[:2]
            state["slip"] = max(state["slip"], float(np.linalg.norm(moved)))
        weld_p, weld_a, grip = _equality_errors(data, lay)
        state["weld_p"] = max(state["weld_p"], weld_p)
        state["weld_a"] = max(state["weld_a"], weld_a)
        state["grip"] = max(state["grip"], grip)
        state["act"] = max(state["act"], float(np.max(np.abs(state_act))))
        state["saturated"] += float(np.mean(np.abs(np.asarray(data.ctrl)) >= 1.0))
        bar_axis = np.asarray(data.xmat[bar_body], dtype=np.float64).reshape(3, 3)[:, 1]
        state["tilt"] = max(state["tilt"], math.degrees(math.asin(min(1.0, abs(bar_axis[2])))))
        for index in range(data.ncon):
            contact = data.contact[index]
            if lay.floor_geom in (int(contact.geom1), int(contact.geom2)):
                state["penetration"] = max(state["penetration"], -float(contact.dist))
        if step >= steps - last_second:
            grf_tail.append(float(force[2]))
            if not math.isnan(float(cop[0])):
                cop_tail.append(float(cop[0]))
            shelf_tail.append(_shelf_force(model, data))
        if step % sample_every == 0:
            samples.append(
                {
                    "t": round(state_time, 9),
                    "com_x": float(com[0]),
                    "com_y": float(com[1]),
                    "com_z": float(com[2]),
                    "grf_z": float(force[2]),
                    "cop_x": float(cop[0]) if not math.isnan(float(cop[0])) else 0.0,
                    "joint_dev_deg": deviation,
                    "loaded_contacts": float(contacts),
                }
            )
    # Evaluate the final state at its own instant before reading derived quantities.
    mujoco.mj_forward(model, data)
    com_final = np.array(data.subtree_com[0])
    final_loads = contact_loads(model, data, lay)
    contacts = int(np.sum(final_loads.loaded))
    final_dev = math.degrees(
        float(np.max(np.abs(np.asarray(data.qpos[lay.joint_qpos]) - reference)))
    )
    return RunSummary(
        duration_s=duration_s,
        steps=steps,
        all_finite=True,
        trajectory_sha256=hasher.hexdigest(),
        com_initial=com_initial,
        com_final=com_final,
        com_max_horizontal_excursion_m=state["com_max_h"],
        com_min_height_m=state["com_min_z"],
        joint_max_deviation_deg=state["dq_max"],
        joint_final_deviation_deg=final_dev,
        joint_limit_max_violation_deg=state["range"],
        vertical_grf_mean_last_s_n=float(np.mean(grf_tail)),
        vertical_grf_min_n=state["grf_min"],
        vertical_grf_max_n=state["grf_max"],
        min_loaded_sole_contacts=int(state["contacts_min"]),
        final_loaded_sole_contacts=contacts,
        min_geometric_sole_contacts=int(state["geometric_min"]),
        min_contact_point_load_n=state["point_load_min"],
        foot_max_slip_m=state["slip"],
        weld_max_position_error_m=state["weld_p"],
        weld_max_angle_error_deg=state["weld_a"],
        grip_max_error_m=state["grip"],
        shelf_force_mean_last_s_n=float(np.mean(shelf_tail)),
        max_abs_activation=state["act"],
        saturated_fraction=state["saturated"] / steps,
        cop_anterior_mean_last_s_m=float(np.mean(cop_tail)) if cop_tail else math.nan,
        bar_max_tilt_deg=state["tilt"],
        max_floor_penetration_m=state["penetration"],
        samples=samples,
    )


def controller_for(
    model: mujoco.MjModel,
    qpos: FloatArray,
    activation: FloatArray,
    *,
    stiffness_scale: float = 1.0,
) -> PosturalController:
    """The postural controller about ``qpos`` with tonic torque from ``activation``."""
    lay = layout(model)
    return PosturalController.for_posture(
        lay.joint_names,
        np.asarray(qpos[lay.joint_qpos], dtype=np.float64),
        activation * lay.peak_torque,
        lay.peak_torque,
        stiffness_scale=stiffness_scale,
    )


# --------------------------------------------------------------------------------------------
# Measurements of a configuration


def vertex_height(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    """World height of the head vertex (top of the head segment's long axis)."""
    lay = layout(model)
    head = lay.bodies["head"]
    rotation = np.asarray(data.xmat[head], dtype=np.float64).reshape(3, 3)
    return float((data.xpos[head] + rotation @ np.array([0.0, 0.0, anth.geometry().head]))[2])


def keyframe_diagnostics(model: mujoco.MjModel) -> dict[str, float]:
    """Measure the packaged standing keyframe against its declared mechanics."""
    lay = layout(model)
    data = mujoco.MjData(model)
    key = _id(model, mujoco.mjtObj.mjOBJ_KEY, mjcf.KEYFRAME_NAME)
    mujoco.mj_resetDataKeyframe(model, data, key)
    mujoco.mj_forward(model, data)
    sole = set(lay.sole_geoms["l"]) | set(lay.sole_geoms["r"])
    depths = [
        -float(data.contact[i].dist)
        for i in range(data.ncon)
        if int(data.contact[i].geom1) in sole or int(data.contact[i].geom2) in sole
    ]
    weld_p, weld_a, grip = _equality_errors(data, lay)
    flatness = 0.0
    for side, sign in (("l", 1.0), ("r", -1.0)):
        rotation = np.asarray(data.xmat[lay.bodies[f"foot_{side}"]]).reshape(3, 3)
        target = _rot_z(sign * math.radians(stance.STANCE.toe_out_deg))
        flatness = max(flatness, math.degrees(float(np.linalg.norm(_rotvec(rotation @ target.T)))))
    # The anatomical zero posture (all joint angles zero) must stand exactly at the stature.
    zero = mujoco.MjData(model)
    mujoco.mj_resetData(model, zero)
    mujoco.mj_forward(model, zero)
    # Generalised force imbalance M qacc (N or N m): the physically meaningful measure of how
    # far the keyframe is from rest. Raw qacc is dominated by the lightest segment (the foot
    # about its long axis has 0.001 kg m^2).
    imbalance = np.zeros(model.nv)
    mujoco.mj_mulM(model, data, imbalance, np.ascontiguousarray(data.qacc, dtype=np.float64))
    imbalance = np.abs(imbalance)
    return {
        "sole_contacts": float(len(depths)),
        "sole_penetration_min_m": min(depths) if depths else math.nan,
        "sole_penetration_max_m": max(depths) if depths else math.nan,
        "weld_position_error_m": weld_p,
        "weld_angle_error_deg": weld_a,
        "grip_error_m": grip,
        "foot_orientation_error_deg": flatness,
        "initial_force_imbalance_max_unactuated": float(imbalance[lay.unactuated_dof].max()),
        "initial_force_imbalance_max_actuated": float(imbalance[lay.joint_dof].max()),
        "com_x_m": float(data.subtree_com[0][0]),
        "com_y_m": float(data.subtree_com[0][1]),
        "com_z_m": float(data.subtree_com[0][2]),
        "bar_x_m": float(data.qpos[lay.bar_qpos]),
        "bar_z_m": float(data.qpos[lay.bar_qpos + 2]),
        "vertex_height_stand_m": vertex_height(model, data),
        "vertex_height_anatomical_zero_m": vertex_height(model, zero),
        "range_violation_deg": _range_violation_deg(data, lay),
    }


def posture_kinematics(model: mujoco.MjModel, qpos: FloatArray) -> dict[str, float]:
    """Segment and joint angles of a posture in the terms squat studies report."""
    lay = layout(model)
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    mujoco.mj_forward(model, data)

    def inclination(body: str, axis: int = 2) -> float:
        vector = np.asarray(data.xmat[lay.bodies[body]]).reshape(3, 3)[:, axis]
        return math.degrees(math.acos(max(-1.0, min(1.0, float(vector[2])))))

    # Trunk: pelvis (mid-hip) to the upper-trunk top, from vertical.
    pelvis = np.asarray(data.xpos[lay.bodies["pelvis"]])
    head = np.asarray(data.xpos[lay.bodies["head"]])
    trunk = head - pelvis
    angles = {
        name: math.degrees(float(qpos[lay.joint_qpos[k]])) for k, name in enumerate(lay.joint_names)
    }
    thigh = np.asarray(data.xmat[lay.bodies["thigh_l"]]).reshape(3, 3)[:, 2]
    return {
        "knee_flexion_deg": angles["knee_flexion_l"],
        "hip_flexion_deg": angles["hip_flexion_l"],
        "ankle_dorsiflexion_deg": angles["ankle_dorsiflexion_l"],
        "lumbar_flexion_deg": angles["lumbar_flexion"],
        "thoracic_flexion_deg": angles["thoracic_flexion"],
        "trunk_inclination_deg": math.degrees(
            math.acos(float(trunk[2]) / float(np.linalg.norm(trunk)))
        ),
        "shank_inclination_deg": inclination("shank_l"),
        "thigh_angle_below_horizontal_deg": math.degrees(math.asin(float(-thigh[2]))),
        "hip_height_m": float(pelvis[2]),
        "bar_height_m": float(data.site_xpos[lay.sites["bar_center"]][2]),
        "bar_x_m": float(data.site_xpos[lay.sites["bar_center"]][0]),
        "knee_x_m": float(data.xpos[lay.bodies["shank_l"]][0]),
        "toe_x_m": float(max(float(data.geom_xpos[g][0]) for g in lay.sole_geoms["l"])),
        "com_x_m": float(data.subtree_com[0][0]),
        "com_z_m": float(data.subtree_com[0][2]),
    }


def momentum_probe(
    model: mujoco.MjModel, *, seed: int, duration_s: float = 0.3
) -> dict[str, float]:
    """Mechanical-consistency probe: the athlete and bar in flight under random excitation.

    The model is lifted 1 m (no contact) from rest. Actuators, joint limits, passive damping
    and the bar couplings are all internal to the athlete-bar system, so Newton-Euler requires
    ``dP/dt = M g`` exactly and the angular momentum about the system centre of mass to stay
    at its initial value of zero, whatever the excitation. Excitations are drawn from a seeded
    generator and held for 50 ms each.
    """
    lay = layout(model)
    qpos, activation = keyframe_state(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[:] = qpos
    data.qpos[lay.root_qpos + 2] += 1.0
    data.qpos[lay.bar_qpos + 2] += 1.0
    data.act[:] = activation
    rng = np.random.default_rng(seed)
    steps = int(round(duration_s / float(model.opt.timestep)))
    hold = int(round(0.05 / float(model.opt.timestep)))
    mass = lay.total_mass
    gravity = np.asarray(model.opt.gravity, dtype=np.float64)
    mujoco.mj_forward(model, data)
    mujoco.mj_subtreeVel(model, data)
    momentum0 = mass * np.asarray(data.subtree_linvel[0], dtype=np.float64)
    worst_linear = 0.0
    worst_angular = 0.0
    peak_segment_speed = 0.0
    contacts = 0
    excitation = np.zeros(model.nu)
    for step in range(steps):
        if step % hold == 0:
            excitation = rng.uniform(-1.0, 1.0, size=model.nu)
        data.ctrl[:] = excitation
        mujoco.mj_step(model, data)
        mujoco.mj_subtreeVel(model, data)
        expected = momentum0 + mass * gravity * float(data.time)
        momentum = mass * np.asarray(data.subtree_linvel[0], dtype=np.float64)
        worst_linear = max(worst_linear, float(np.max(np.abs(momentum - expected))))
        worst_angular = max(
            worst_angular, float(np.max(np.abs(np.asarray(data.subtree_angmom[0]))))
        )
        peak_segment_speed = max(
            peak_segment_speed, float(np.max(np.abs(np.asarray(data.qvel[lay.joint_dof]))))
        )
        contacts = max(contacts, int(data.ncon))
    return {
        "duration_s": duration_s,
        "seed": float(seed),
        "max_linear_momentum_error_n_s": worst_linear,
        "max_angular_momentum_about_com_n_m_s": worst_angular,
        "peak_joint_speed_rad_s": peak_segment_speed,
        "max_contacts": float(contacts),
        "final_momentum_z_n_s": float(mass * data.subtree_linvel[0][2]),
        "expected_momentum_z_n_s": float(momentum0[2] + mass * gravity[2] * float(data.time)),
    }


# --------------------------------------------------------------------------------------------
# One controlled repetition


SYNERGY_KNOT_SPACING_DEG: Final = 2.0
"""Spacing of the statically solved postures the synergy spline passes through."""
SYNERGY_OVERSHOOT_DEG: Final = 4.0
"""The synergy extends this far past the bottom depth so that the spline is not evaluated at
its free end."""
_SAGITTAL_FAMILIES: Final = (
    "ankle_dorsiflexion",
    "knee_flexion",
    "hip_flexion",
    "lumbar_flexion",
    "thoracic_flexion",
)


def _right_jacobian_so3(rotation_vector: FloatArray) -> FloatArray:
    """Right Jacobian of SO(3): body angular velocity = J_r(r) * d r / d t."""
    theta = float(np.linalg.norm(rotation_vector))
    skew = np.array(
        [
            [0.0, -rotation_vector[2], rotation_vector[1]],
            [rotation_vector[2], 0.0, -rotation_vector[0]],
            [-rotation_vector[1], rotation_vector[0], 0.0],
        ]
    )
    if theta < 1e-9:
        return np.eye(3) - 0.5 * skew
    return (
        np.eye(3)
        - (1.0 - math.cos(theta)) / theta**2 * skew
        + (theta - math.sin(theta)) / theta**3 * skew @ skew
    )


@dataclass(frozen=True, slots=True)
class SquatSynergy:
    """The balanced whole-body posture as a smooth function of knee-flexion depth.

    Every knot is a posture from :func:`solve_posture` (feet fixed, hands on the bar, CoM over
    the mid-foot, trunk parallel to the shank, neutral spine) settled into the contacts. The
    spline runs through the knots in tangent coordinates relative to the standing keyframe.
    Between standing and ``blend_width_deg`` of depth the reference blends from the keyframe
    into the synergy with a quintic step, so the reference and its derivatives are continuous.
    """

    keyframe_qpos: FloatArray
    standing_depth_deg: float
    blend_width_deg: float
    spline: Any
    offset: FloatArray
    rotational_dofs: tuple[tuple[int, int], ...]
    max_off_axis_rotation_rad: float
    knot_count: int

    def tangent(self, depth_deg: float) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Tangent coordinates of the reference and their first two depth derivatives."""
        low, _high = self.spline.domain
        if depth_deg <= low:
            zero = np.zeros_like(self.offset)
            return zero, zero.copy(), zero.copy()
        value, first, second = self.spline(depth_deg)
        blend, blend_rate, blend_curvature = movement.smoothstep(
            (depth_deg - self.standing_depth_deg) / self.blend_width_deg
        )
        width = self.blend_width_deg
        return (
            value - (1.0 - blend) * self.offset,
            first + blend_rate / width * self.offset,
            second + blend_curvature / width**2 * self.offset,
        )

    def reference(
        self,
        model: mujoco.MjModel,
        depth_deg: float,
        depth_rate_deg_s: float,
        depth_acceleration_deg_s2: float,
    ) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Reference ``(qpos, qvel, qacc)`` for a depth intent and its time derivatives."""
        x, dx, ddx = self.tangent(depth_deg)
        qpos = self.keyframe_qpos.copy()
        mujoco.mj_integratePos(model, qpos, x, 1.0)
        qvel = dx * depth_rate_deg_s
        qacc = ddx * depth_rate_deg_s**2 + dx * depth_acceleration_deg_s2
        # Free-joint rotations: tangent rates are rotation-vector rates; MuJoCo wants body
        # angular velocity. (The synergy is symmetric, so these rotations are about one axis
        # and the Jacobian-rate term of the acceleration vanishes; the build checks that.)
        for start, _end in self.rotational_dofs:
            jacobian = _right_jacobian_so3(x[start : start + 3])
            qvel[start : start + 3] = jacobian @ qvel[start : start + 3]
            qacc[start : start + 3] = jacobian @ qacc[start : start + 3]
        return qpos, qvel, qacc


def build_synergy(model: mujoco.MjModel, plan: movement.RepetitionPlan) -> SquatSynergy:
    """Solve the posture knots from standing to past the bottom and spline them."""
    lay = layout(model)
    keyframe_qpos, _activation = keyframe_state(model)
    knee = [k for k, name in enumerate(lay.joint_names) if joint_family(name) == "knee_flexion"]
    standing = math.degrees(float(np.mean(keyframe_qpos[lay.joint_qpos[knee]])))
    end = plan.bottom_knee_flexion_deg + SYNERGY_OVERSHOOT_DEG
    first = math.ceil((standing + 0.5 * SYNERGY_KNOT_SPACING_DEG) / SYNERGY_KNOT_SPACING_DEG)
    knots = [standing] + list(
        np.arange(first * SYNERGY_KNOT_SPACING_DEG, end + 1e-9, SYNERGY_KNOT_SPACING_DEG)
    )
    tangents = []
    for depth in knots:
        qpos = settle(model, solve_posture(model, knee_flexion_deg=float(depth)))
        tangent = np.zeros(model.nv)
        mujoco.mj_differentiatePos(model, tangent, 1.0, keyframe_qpos, qpos)
        tangents.append(tangent)
    values = np.array(tangents)
    rotational = []
    for joint in range(model.njnt):
        if int(model.jnt_type[joint]) == int(mujoco.mjtJoint.mjJNT_FREE):
            start = int(model.jnt_dofadr[joint]) + 3
            rotational.append((start, start + 3))
    off_axis = max(
        float(np.max(np.abs(values[:, [start, start + 2]]))) for start, _end in rotational
    )
    spline = movement.NaturalCubicSpline(np.array(knots, dtype=np.float64), values)
    return SquatSynergy(
        keyframe_qpos=keyframe_qpos,
        standing_depth_deg=standing,
        blend_width_deg=plan.blend_width_deg,
        spline=spline,
        offset=values[0],
        rotational_dofs=tuple(rotational),
        max_off_axis_rotation_rad=off_axis,
        knot_count=len(knots),
    )


def inverse_dynamics_feedforward(
    model: mujoco.MjModel,
    scratch: mujoco.MjData,
    lay: Layout,
    qpos: FloatArray,
    qvel: FloatArray,
    qacc: FloatArray,
) -> tuple[FloatArray, FloatArray, float]:
    """Internal-model feedforward: minimum-effort torques that produce ``(qvel, qacc)`` at
    ``qpos`` with the feet on the floor and the bar coupled.

    Returns the joint torques, the planned ground wrenches (12) and the solve residual. The
    load is MuJoCo's own rigid-body dynamics ``M qacc + c(q, qvel)`` minus passive damping.
    """
    scratch.qpos[:] = qpos
    scratch.qvel[:] = qvel
    scratch.qacc[:] = qacc
    mujoco.mj_kinematics(model, scratch)
    mujoco.mj_comPos(model, scratch)
    mujoco.mj_comVel(model, scratch)
    load = np.zeros(model.nv)
    mujoco.mj_rne(model, scratch, 1, load)
    load += np.asarray(model.dof_damping, dtype=np.float64) * qvel
    activation, forces, residual = _minimum_effort(model, scratch, lay, load)
    return activation * lay.peak_torque, forces[:12], residual


def _support_polygon(data: mujoco.MjData, lay: Layout) -> list[tuple[float, float]]:
    """Convex hull of the loaded sole contact points (floor projection)."""
    points = []
    for index in range(data.ncon):
        contact = data.contact[index]
        geoms = (int(contact.geom1), int(contact.geom2))
        if lay.floor_geom in geoms and any(
            g in lay.sole_geoms["l"] or g in lay.sole_geoms["r"] for g in geoms
        ):
            points.append((float(contact.pos[0]), float(contact.pos[1])))
    return _convex_hull(points)


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted(set(points))
    if len(ordered) < 3:
        return ordered

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


def _signed_margin(point: FloatArray, hull: list[tuple[float, float]]) -> float:
    """Signed distance of ``point`` to the hull boundary: positive inside, negative outside."""
    if len(hull) < 3:
        return -math.inf
    margin = math.inf
    for index, start in enumerate(hull):
        end = hull[(index + 1) % len(hull)]
        edge = (end[0] - start[0], end[1] - start[1])
        length = math.hypot(*edge)
        distance = (edge[0] * (point[1] - start[1]) - edge[1] * (point[0] - start[0])) / length
        margin = min(margin, distance)
    return margin


@dataclass(slots=True)
class RepetitionRecord:
    """Everything measured during one repetition: per-step extrema and sampled series."""

    timestep_s: float
    duration_s: float
    steps: int
    completed: bool
    failure: str | None
    trajectory_sha256: str
    command_events: list[dict[str, Any]]
    joint_names: tuple[str, ...]
    samples: dict[str, list[Any]]
    extrema: dict[str, float]
    work: dict[str, dict[str, float]]
    synergy_knots: int
    synergy_off_axis_rotation_rad: float
    feedforward_max_residual: float
    body_names: tuple[str, ...] = ()


def simulate_repetition(
    model: mujoco.MjModel,
    plan: movement.RepetitionPlan = movement.REPETITION,
    *,
    sample_period_s: float = 0.01,
    dynamic_feedforward: bool = True,
    feedforward_dynamics_gain: float | None = None,
) -> RepetitionRecord:
    """Integrate one back-squat repetition with forward dynamics and measure it.

    Each step: the phase machine advances the depth intent from the *measured* state; the
    synergy turns the intent into a reference posture, velocity and acceleration; the internal
    model turns those into feedforward torques; the postural controller adds joint-impedance
    feedback and emits excitations; MuJoCo integrates. No joint state is ever written.

    ``dynamic_feedforward=False`` is an ablation: the internal model then predicts only the
    static torques of the reference posture (no velocity or acceleration terms), so every
    inertial effect of the movement must be caught by feedback.

    ``feedforward_dynamics_gain`` generalises that switch: the planned velocity and
    acceleration reach the internal model scaled by the gain, so 1 is the full dynamic
    internal model and 0 the static-only ablation (both bit-identical to the boolean form).
    ``None`` means the boolean decides.
    """
    gain = (
        (1.0 if dynamic_feedforward else 0.0)
        if feedforward_dynamics_gain is None
        else float(feedforward_dynamics_gain)
    )
    if not (math.isfinite(gain) and 0.0 <= gain <= 1.0):
        raise EngineError("the internal-model dynamics gain must lie in [0, 1]")
    lay = layout(model)
    timestep = float(model.opt.timestep)
    synergy = build_synergy(model, plan)
    keyframe_qpos, keyframe_activation = keyframe_state(model)
    controller = controller_for(model, keyframe_qpos, keyframe_activation)
    scratch = mujoco.MjData(model)
    zero = np.zeros(model.nv)
    standing_torque, _, _ = inverse_dynamics_feedforward(
        model, scratch, lay, keyframe_qpos, zero, zero
    )
    keyframe_torque = keyframe_activation * lay.peak_torque
    knee = np.array(
        [k for k, name in enumerate(lay.joint_names) if joint_family(name) == "knee_flexion"]
    )
    sagittal = np.array(
        [k for k, name in enumerate(lay.joint_names) if joint_family(name) in _SAGITTAL_FAMILIES]
    )
    machine = movement.PhaseMachine(plan=plan, standing_depth_deg=synergy.standing_depth_deg)
    total = (
        plan.standing_s
        + plan.descent_s
        + plan.bottom_pause_s
        + plan.ascent_s
        + plan.return_s
        + 2 * movement.TRANSITION_TIMEOUT_S
    )
    max_steps = int(round(total / timestep))

    sample_every = int(round(sample_period_s / timestep))
    if sample_every < 1 or not math.isclose(
        sample_every * timestep, sample_period_s, rel_tol=0.0, abs_tol=1e-12
    ):
        raise EngineError("the sample period must be a whole number of timesteps")

    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[:] = keyframe_qpos
    data.act[:] = keyframe_activation
    data.ctrl[:] = keyframe_activation
    mujoco.mj_forward(model, data)
    mass = lay.total_mass
    gravity = np.asarray(model.opt.gravity, dtype=np.float64)
    sole_geoms = [g for side in ("l", "r") for g in lay.sole_geoms[side]]
    sole_start = np.array([np.array(data.geom_xpos[g][:2]) for g in sole_geoms])
    feet_start = {side: np.array(data.xpos[lay.bodies[f"foot_{side}"]][:2]) for side in ("l", "r")}
    bar_body = lay.bodies["barbell"]
    pelvis = lay.bodies["pelvis"]
    damping = np.asarray(model.dof_damping, dtype=np.float64)
    hasher = hashlib.sha256()

    extrema = {
        "max_foot_slip_m": 0.0,
        "max_sole_point_slip_m": 0.0,
        "max_penetration_m": 0.0,
        "min_geometric_sole_contacts": float(len(sole_geoms)),
        "min_loaded_sole_contacts": float(len(sole_geoms)),
        "min_contact_point_load_n": math.inf,
        "min_heel_load_fraction_per_foot": math.inf,
        "min_forefoot_load_fraction_per_foot": math.inf,
        "max_friction_utilization": 0.0,
        "max_contact_load_sum_error_n": 0.0,
        "max_other_floor_load_n": 0.0,
        "max_weld_position_error_m": 0.0,
        "max_weld_angle_error_deg": 0.0,
        "max_grip_error_m": 0.0,
        "max_range_violation_deg": 0.0,
        "min_joint_limit_margin_deg": math.inf,
        "max_abs_activation": 0.0,
        "saturated_steps": 0.0,
        "max_momentum_residual_n_s": 0.0,
        "max_knee_tracking_error_deg": 0.0,
        "max_sagittal_tracking_error_deg": 0.0,
        "max_feedforward_residual": 0.0,
        "max_bar_tilt_deg": 0.0,
    }
    work = {
        phase.value: {
            "positive_j": 0.0,
            "negative_j": 0.0,
            "damping_dissipation_j": 0.0,
            "mechanical_energy_change_j": 0.0,
            "duration_s": 0.0,
        }
        for phase in movement.Phase
    }
    samples: dict[str, list[Any]] = {
        key: []
        for key in (
            "t",
            "sample_index",
            "phase",
            "depth_intent_deg",
            "joint_angle_deg",
            "joint_velocity_deg_s",
            "joint_torque_nm",
            "reference_angle_deg",
            "joint_angle_rad",
            "joint_velocity_rad_s",
            "reference_angle_rad",
            "bar_tilt_rad",
            "trunk_inclination_rad",
            "qvel",
            "act",
            "activation_max",
            "bar_position_m",
            "bar_velocity_m_s",
            "bar_tilt_deg",
            "com_position_m",
            "com_velocity_m_s",
            "pelvis_height_m",
            "grf_left_n",
            "grf_right_n",
            "grf_planned_vertical_n",
            "cop_m",
            "cop_left_m",
            "cop_right_m",
            "contact_position_m",
            "cop_margin_m",
            "xcom_margin_m",
            "contact_normal_n",
            "contact_tangential_n",
            "friction_utilization",
            "loaded_contacts",
            "heel_load_fraction",
            "actuator_power_w",
            "shelf_force_n",
            "trunk_inclination_deg",
            "qpos",
            "body_position_m",
            "body_quaternion",
        )
    }
    events: list[dict[str, Any]] = [{"phase": movement.Phase.STANDING.value, "t": 0.0}]
    body_ids = sorted(lay.bodies.values())

    @dataclass(slots=True)
    class Interval:
        """Bookkeeping carried from one synchronized snapshot to the next."""

        time_s: float
        phase: movement.Phase
        torque: FloatArray
        energy: float
        momentum: FloatArray
        impulse: FloatArray

    previous: Interval | None = None
    momentum0 = np.zeros(3)
    reference_angles = np.asarray(keyframe_qpos[lay.joint_qpos], dtype=np.float64)
    depth = synergy.standing_depth_deg
    planned_vertical = lay.total_mass * anth.GRAVITY_M_S2

    def observe(
        step_index: int,
        time_s: float,
        qpos: FloatArray,
        qvel: FloatArray,
        act: FloatArray,
        phase: movement.Phase,
    ) -> None:
        """Measure one synchronized snapshot at ``time_s``.

        ``qpos``, ``qvel`` and ``act`` are the state at ``time_s``; everything ``data`` holds
        besides them (kinematics, centre of mass, contacts, constraint and actuator forces) was
        computed by MuJoCo at that same state. Nothing here is evaluated at a later state.
        """
        nonlocal previous, momentum0
        # Centre of mass and momentum, kinetic and potential energy at time_s.
        mujoco.mj_subtreeVel(model, data)
        com = np.array(data.subtree_com[0], dtype=np.float64)
        com_velocity = np.array(data.subtree_linvel[0], dtype=np.float64)
        momentum = mass * com_velocity
        inertia_times_velocity = np.zeros(model.nv)
        mujoco.mj_mulM(model, data, inertia_times_velocity, qvel)
        energy = 0.5 * float(qvel @ inertia_times_velocity) - mass * float(gravity @ com)
        torque = np.array(data.actuator_force, dtype=np.float64)
        loads = contact_loads(model, data, lay)

        if previous is None:
            momentum0 = momentum.copy()
            impulse = np.zeros(3)
        else:
            # The step [previous.time_s, time_s] applied the previous instant's forces; the
            # integrator moved positions with the new velocity, so that is the discrete work.
            interval = time_s - previous.time_s
            bucket = work[previous.phase.value]
            power = float(previous.torque @ qvel[lay.joint_dof])
            bucket["positive_j"] += max(power, 0.0) * interval
            bucket["negative_j"] += min(power, 0.0) * interval
            bucket["damping_dissipation_j"] += float(damping @ (qvel * qvel)) * interval
            bucket["mechanical_energy_change_j"] += energy - previous.energy
            bucket["duration_s"] += interval
            impulse = previous.impulse
        extrema["max_momentum_residual_n_s"] = max(
            extrema["max_momentum_residual_n_s"],
            float(np.max(np.abs(momentum - momentum0 - impulse))),
        )

        # Contact loads at time_s.
        extrema["min_geometric_sole_contacts"] = min(
            extrema["min_geometric_sole_contacts"], float(np.sum(loads.in_contact))
        )
        extrema["min_loaded_sole_contacts"] = min(
            extrema["min_loaded_sole_contacts"], float(np.sum(loads.loaded))
        )
        extrema["min_contact_point_load_n"] = min(
            extrema["min_contact_point_load_n"], float(np.min(loads.normal_n))
        )
        heel = min(loads.heel_share("l"), loads.heel_share("r"))
        forefoot = min(loads.forefoot_share("l"), loads.forefoot_share("r"))
        extrema["min_heel_load_fraction_per_foot"] = min(
            extrema["min_heel_load_fraction_per_foot"], heel
        )
        extrema["min_forefoot_load_fraction_per_foot"] = min(
            extrema["min_forefoot_load_fraction_per_foot"], forefoot
        )
        extrema["max_friction_utilization"] = max(
            extrema["max_friction_utilization"], float(np.max(loads.friction_utilization))
        )
        extrema["max_penetration_m"] = max(
            extrema["max_penetration_m"], float(np.max(loads.penetration_m))
        )
        extrema["max_contact_load_sum_error_n"] = max(
            extrema["max_contact_load_sum_error_n"],
            abs(
                float(np.sum(loads.normal_n))
                + loads.other_floor_vertical_n
                - float(loads.total_force_n[2])
            ),
        )
        extrema["max_other_floor_load_n"] = max(
            extrema["max_other_floor_load_n"], abs(loads.other_floor_vertical_n)
        )
        sole_now = np.array([np.array(data.geom_xpos[g][:2]) for g in sole_geoms])
        extrema["max_sole_point_slip_m"] = max(
            extrema["max_sole_point_slip_m"],
            float(np.max(np.linalg.norm(sole_now - sole_start, axis=1))),
        )
        for side, start in feet_start.items():
            moved = np.asarray(data.xpos[lay.bodies[f"foot_{side}"]][:2]) - start
            extrema["max_foot_slip_m"] = max(
                extrema["max_foot_slip_m"], float(np.linalg.norm(moved))
            )

        # Coupling, joints, actuators at time_s.
        weld_p, weld_a, grip = _equality_errors(data, lay)
        extrema["max_weld_position_error_m"] = max(extrema["max_weld_position_error_m"], weld_p)
        extrema["max_weld_angle_error_deg"] = max(extrema["max_weld_angle_error_deg"], weld_a)
        extrema["max_grip_error_m"] = max(extrema["max_grip_error_m"], grip)
        angles = np.asarray(qpos[lay.joint_qpos], dtype=np.float64)
        below = lay.joint_range[:, 0] - angles
        above = angles - lay.joint_range[:, 1]
        extrema["max_range_violation_deg"] = max(
            extrema["max_range_violation_deg"],
            math.degrees(max(0.0, float(np.max(below)), float(np.max(above)))),
        )
        extrema["min_joint_limit_margin_deg"] = min(
            extrema["min_joint_limit_margin_deg"],
            math.degrees(float(np.min(np.minimum(-below, -above)))),
        )
        extrema["max_abs_activation"] = max(
            extrema["max_abs_activation"], float(np.max(np.abs(act)))
        )
        error = np.degrees(np.abs(angles - reference_angles))
        extrema["max_knee_tracking_error_deg"] = max(
            extrema["max_knee_tracking_error_deg"], float(np.max(error[knee]))
        )
        extrema["max_sagittal_tracking_error_deg"] = max(
            extrema["max_sagittal_tracking_error_deg"], float(np.max(error[sagittal]))
        )
        bar_axis = np.asarray(data.xmat[bar_body], dtype=np.float64).reshape(3, 3)[:, 1]
        tilt = math.degrees(math.asin(min(1.0, abs(float(bar_axis[2])))))
        extrema["max_bar_tilt_deg"] = max(extrema["max_bar_tilt_deg"], tilt)

        previous = Interval(
            time_s=time_s,
            phase=phase,
            torque=torque,
            energy=energy,
            momentum=momentum,
            impulse=impulse + (loads.total_force_n + mass * gravity) * timestep,
        )

        if step_index % sample_every != 0:
            return
        speeds = np.asarray(qvel[lay.joint_dof], dtype=np.float64)
        hull = loads.support_polygon()
        cop = loads.centre_of_pressure()
        omega = math.sqrt(anth.GRAVITY_M_S2 / max(float(com[2]), 1e-6))
        xcom = com[:2] + com_velocity[:2] / omega
        per_foot = _floor_forces_by_foot(model, data, lay)
        bar_velocity = np.zeros(6)
        mujoco.mj_objectVelocity(
            model, data, int(mujoco.mjtObj.mjOBJ_BODY), bar_body, bar_velocity, 0
        )
        trunk = np.asarray(data.xpos[lay.bodies["head"]] - data.xpos[pelvis])
        samples["t"].append(round(step_index * timestep, 9))
        samples["sample_index"].append(step_index // sample_every)
        samples["phase"].append(phase.value)
        samples["depth_intent_deg"].append(depth)
        samples["joint_angle_deg"].append(np.degrees(angles))
        samples["joint_velocity_deg_s"].append(np.degrees(speeds))
        samples["joint_torque_nm"].append(torque)
        samples["reference_angle_deg"].append(np.degrees(reference_angles))
        samples["joint_angle_rad"].append(np.array(angles, dtype=np.float64))
        samples["joint_velocity_rad_s"].append(np.array(speeds, dtype=np.float64))
        samples["reference_angle_rad"].append(np.array(reference_angles, dtype=np.float64))
        samples["bar_tilt_rad"].append(math.radians(tilt))
        samples["activation_max"].append(float(np.max(np.abs(act))))
        samples["bar_position_m"].append(np.array(data.xpos[bar_body]))
        samples["bar_velocity_m_s"].append(bar_velocity[3:].copy())
        samples["bar_tilt_deg"].append(tilt)
        samples["com_position_m"].append(com)
        samples["com_velocity_m_s"].append(com_velocity)
        samples["pelvis_height_m"].append(float(data.xpos[pelvis][2]))
        samples["grf_left_n"].append(per_foot["l"])
        samples["grf_right_n"].append(per_foot["r"])
        samples["grf_planned_vertical_n"].append(planned_vertical)
        samples["cop_m"].append(cop)
        samples["cop_left_m"].append(loads.centre_of_pressure("l"))
        samples["cop_right_m"].append(loads.centre_of_pressure("r"))
        samples["contact_position_m"].append(loads.position_xy.copy())
        samples["cop_margin_m"].append(_signed_margin(cop, hull))
        samples["xcom_margin_m"].append(_signed_margin(xcom, hull))
        samples["contact_normal_n"].append(loads.normal_n.copy())
        samples["contact_tangential_n"].append(loads.tangential_n.copy())
        samples["friction_utilization"].append(loads.friction_utilization.copy())
        samples["loaded_contacts"].append(int(np.sum(loads.loaded)))
        samples["heel_load_fraction"].append(heel)
        samples["actuator_power_w"].append(float(torque @ speeds))
        samples["shelf_force_n"].append(_shelf_force(model, data))
        inclination = math.acos(float(trunk[2]) / float(np.linalg.norm(trunk)))
        samples["trunk_inclination_deg"].append(math.degrees(inclination))
        samples["trunk_inclination_rad"].append(inclination)
        samples["qpos"].append(np.array(qpos, dtype=np.float64))
        samples["qvel"].append(np.array(qvel, dtype=np.float64))
        samples["act"].append(np.array(act, dtype=np.float64))
        # World pose of every body at time_s (MuJoCo's kinematics of this same state).
        samples["body_position_m"].append(np.array(data.xpos[body_ids], dtype=np.float64))
        samples["body_quaternion"].append(np.array(data.xquat[body_ids], dtype=np.float64))

    steps = 0
    current_phase = movement.Phase.STANDING
    for _step in range(max_steps):
        time_s = float(data.time)
        state_qpos = np.array(data.qpos, dtype=np.float64)
        state_qvel = np.array(data.qvel, dtype=np.float64)
        state_act = np.array(data.act, dtype=np.float64)
        angles = np.asarray(data.qpos[lay.joint_qpos], dtype=np.float64)
        speeds = np.asarray(data.qvel[lay.joint_dof], dtype=np.float64)
        previous_phase = machine.phase
        current_phase = machine.update(
            time_s,
            knee_flexion_deg=math.degrees(float(np.mean(angles[knee]))),
            knee_speed_deg_s=math.degrees(float(np.mean(speeds[knee]))),
            sagittal_error_deg=math.degrees(
                float(np.max(np.abs(angles[sagittal] - keyframe_qpos[lay.joint_qpos[sagittal]])))
            ),
        )
        if machine.failed is not None:
            break
        if current_phase is not previous_phase:
            events.append({"phase": current_phase.value, "t": time_s})
        if (
            current_phase is movement.Phase.RETURN
            and time_s - machine.phase_start_s >= plan.return_s
        ):
            break
        depth, rate, acceleration = machine.intent(time_s)
        ref_qpos, ref_qvel, ref_qacc = synergy.reference(model, depth, rate, acceleration)
        if gain == 1.0:
            planned_qvel, planned_qacc = ref_qvel, ref_qacc
        elif gain == 0.0:
            planned_qvel, planned_qacc = zero, zero
        else:
            planned_qvel, planned_qacc = gain * ref_qvel, gain * ref_qacc
        feedforward, planned_wrench, residual = inverse_dynamics_feedforward(
            model, scratch, lay, ref_qpos, planned_qvel, planned_qacc
        )
        blend, _, _ = movement.smoothstep(
            (depth - synergy.standing_depth_deg) / plan.blend_width_deg
        )
        feedforward = feedforward + (1.0 - blend) * (keyframe_torque - standing_torque)
        reference_angles = np.asarray(ref_qpos[lay.joint_qpos], dtype=np.float64)
        reference_speeds = np.asarray(ref_qvel[lay.joint_dof], dtype=np.float64)
        planned_vertical = float(planned_wrench[2] + planned_wrench[8])
        extrema["max_feedforward_residual"] = max(extrema["max_feedforward_residual"], residual)
        data.ctrl[:] = controller.tracking_excitation(
            angles,
            speeds,
            reference_angles=reference_angles,
            reference_velocities=reference_speeds,
            feedforward_torque=feedforward,
        )
        mujoco.mj_step(model, data)
        if not (np.all(np.isfinite(data.qpos)) and np.all(np.isfinite(data.qvel))):
            raise EngineError(f"the repetition became non-finite at t={float(data.time):.4f} s")
        hasher.update(np.ascontiguousarray(data.qpos, dtype="<f8").tobytes())
        hasher.update(np.ascontiguousarray(data.qvel, dtype="<f8").tobytes())
        # Everything MuJoCo derived in this step describes the state *before* integration,
        # so the snapshot is taken at time_s with the state copied before the step.
        observe(steps, time_s, state_qpos, state_qvel, state_act, current_phase)
        extrema["saturated_steps"] += float(np.any(np.abs(np.asarray(data.ctrl)) >= 1.0))
        steps += 1

    # Close the last interval with the final state, evaluated at its own instant.
    mujoco.mj_forward(model, data)
    observe(
        steps,
        float(data.time),
        np.array(data.qpos, dtype=np.float64),
        np.array(data.qvel, dtype=np.float64),
        np.array(data.act, dtype=np.float64),
        current_phase,
    )

    completed = machine.failed is None and machine.phase is movement.Phase.RETURN
    extrema["saturated_fraction"] = extrema.pop("saturated_steps") / max(steps, 1)
    return RepetitionRecord(
        timestep_s=timestep,
        duration_s=float(data.time),
        steps=steps,
        completed=completed,
        failure=machine.failed,
        trajectory_sha256=hasher.hexdigest(),
        command_events=events,
        joint_names=lay.joint_names,
        samples=samples,
        extrema=extrema,
        work=work,
        synergy_knots=synergy.knot_count,
        synergy_off_axis_rotation_rad=synergy.max_off_axis_rotation_rad,
        feedforward_max_residual=extrema["max_feedforward_residual"],
        body_names=tuple(name for name, _i in sorted(lay.bodies.items(), key=lambda kv: kv[1])),
    )


def _floor_forces_by_foot(
    model: mujoco.MjModel, data: mujoco.MjData, lay: Layout
) -> dict[str, FloatArray]:
    """World ground-reaction force on each foot (N)."""
    result = {"l": np.zeros(3), "r": np.zeros(3)}
    local = np.zeros(6)
    for index in range(data.ncon):
        contact = data.contact[index]
        geoms = (int(contact.geom1), int(contact.geom2))
        if lay.floor_geom not in geoms:
            continue
        other = geoms[1] if geoms[0] == lay.floor_geom else geoms[0]
        side = "l" if other in lay.sole_geoms["l"] else "r" if other in lay.sole_geoms["r"] else ""
        if not side:
            continue
        mujoco.mj_contactForce(model, data, index, local)
        frame = np.asarray(contact.frame, dtype=np.float64).reshape(3, 3)
        world = frame.T @ local[:3]
        if geoms[0] != lay.floor_geom:
            world = -world
        result[side] += world
    return result


# --------------------------------------------------------------------------------------------
# Model description for the laboratory


_GEOM_TYPES: Final = {
    2: "sphere",
    3: "capsule",
    4: "ellipsoid",
    5: "cylinder",
    6: "box",
    0: "plane",
}


def describe_model(model: mujoco.MjModel) -> dict[str, Any]:
    """The compiled model as plain data: bodies, geoms in their body frames, joints, sites.

    Read from the compiled ``MjModel`` (not from the declarations), so what the laboratory draws
    is exactly what MuJoCo simulated.
    """
    lay = layout(model)

    def name(kind: int, index: int) -> str:
        return _name(model, kind, index)

    bodies = []
    for b in range(1, model.nbody):
        bodies.append(
            {
                "name": name(mujoco.mjtObj.mjOBJ_BODY, b),
                "parent": name(mujoco.mjtObj.mjOBJ_BODY, int(model.body_parentid[b])) or "world",
                "mass_kg": float(model.body_mass[b]),
                "com_m": [float(v) for v in model.body_ipos[b]],
                "principal_inertia_kg_m2": [float(v) for v in model.body_inertia[b]],
                "position_m": [float(v) for v in model.body_pos[b]],
                "quaternion": [float(v) for v in model.body_quat[b]],
            }
        )
    geoms = []
    for g in range(model.ngeom):
        geom_name = name(mujoco.mjtObj.mjOBJ_GEOM, g)
        body = int(model.geom_bodyid[g])
        if geom_name == mjcf.FLOOR_GEOM:
            role = "floor"
        elif geom_name.startswith("bar_"):
            role = "barbell"
        elif any(geom_name.endswith(f"_{point}") for point in mjcf.SOLE_POINTS):
            role = "sole"
        elif int(model.geom_contype[g]) == 0 and int(model.geom_conaffinity[g]) == 0:
            role = "visual"
        else:
            role = "segment"
        geoms.append(
            {
                "name": geom_name,
                "body": name(mujoco.mjtObj.mjOBJ_BODY, body) if body else "world",
                "type": _GEOM_TYPES.get(int(model.geom_type[g]), "other"),
                "size_m": [float(v) for v in model.geom_size[g]],
                "position_m": [float(v) for v in model.geom_pos[g]],
                "quaternion": [float(v) for v in model.geom_quat[g]],
                "role": role,
            }
        )
    joints = []
    for k, joint_name in enumerate(lay.joint_names):
        joint = _id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
        joints.append(
            {
                "name": joint_name,
                "body": name(mujoco.mjtObj.mjOBJ_BODY, int(model.jnt_bodyid[joint])),
                "axis": [float(v) for v in model.jnt_axis[joint]],
                "range_deg": [math.degrees(float(v)) for v in model.jnt_range[joint]],
                "torque_capacity_nm": [
                    float(-model.actuator_forcerange[k, 0]),
                    float(model.actuator_forcerange[k, 1]),
                ],
                "damping_n_m_s": float(model.dof_damping[int(model.jnt_dofadr[joint])]),
                "position_m": [float(v) for v in model.jnt_pos[joint]],
            }
        )
    return {
        "model_sha256": contract.MODEL_SHA256,
        "counts": {
            "nq": int(model.nq),
            "nv": int(model.nv),
            "nu": int(model.nu),
            "nbody": int(model.nbody),
            "ngeom": int(model.ngeom),
            "neq": int(model.neq),
            "npair": int(model.npair),
        },
        "total_mass_kg": float(np.sum(model.body_mass)),
        "bodies": bodies,
        "geoms": geoms,
        "joints": joints,
        "sole_points": list(mjcf.SOLE_POINTS),
        "timestep_s": float(model.opt.timestep),
        "integrator": mjcf.INTEGRATOR,
        "gravity_m_s2": float(-model.opt.gravity[2]),
        "subject": {
            "body_mass_kg": anth.BODY_MASS_KG,
            "stature_m": anth.STATURE_M,
            "barbell_mass_kg": anth.BARBELL.mass,
            "grip_half_width_m": anth.BARBELL.grip_half_width,
        },
        "contact": {
            "sole_point_radius_m": anth.SOLE_CONTACT_RADIUS_M,
            "friction": list(mjcf.CONTACT_FRICTION),
            # Read from the compiled pairs, so a configured friction time constant is what
            # the description reports (every sole pair carries the same values).
            "normal_time_constant_s": float(model.pair_solref[0, 0])
            if model.npair
            else mjcf.CONTACT_SOLREF[0],
            "friction_time_constant_s": float(model.pair_solreffriction[0, 0])
            if model.npair
            else mjcf.FRICTION_SOLREF[0],
            "loaded_threshold_n": LOADED_CONTACT_THRESHOLD_N,
        },
    }
