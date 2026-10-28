"""Real MuJoCo execution of the fixed reference pendulum.

This is the only production module that imports MuJoCo. It loads the reviewed model from
package bytes (never from an absolute path), verifies the physical and solver structure the
adapter claims, integrates with MuJoCo's ``mj_step``, and rejects any non-finite or
unexpected constrained state before it can become a diagnostic.

The model is deliberately simple enough that its motion can be checked independently:
one frictionless hinge, a point mass at radius 1 m, standard gravity, no contacts, no
actuators and no damping. The corresponding equation is

    I * theta_ddot + m * g * L * sin(theta) = 0,

with ``I`` the hinge-axis inertia. Nothing in this module decides whether agreement with
that equation is a *validated* result; it only produces the native run and its bounded
diagnostic. The qualification suite performs the independent comparison.
"""

from __future__ import annotations

import hashlib
import math
import struct
import sys
from dataclasses import dataclass
from typing import Final

import mujoco
import numpy as np

from dynamisbench.adapters.mujoco import reference
from dynamisbench.adapters.mujoco.diagnostics import ReferenceDiagnostic, StateSample

__all__ = [
    "PhysicsError",
    "ReferenceRun",
    "RunContext",
    "engine_version",
    "hinge_parameters",
    "load_model",
    "nonfinite_probe",
    "run_reference",
]

_NUMERIC_TOLERANCE: Final = 1e-12
_TIME_TOLERANCE: Final = 1e-12


class PhysicsError(reference.ReferenceAdapterError):
    """A real MuJoCo run could not establish the declared reference state."""


@dataclass(frozen=True, slots=True)
class RunContext:
    """The request identity the diagnostic must reproduce.

    This is a plain value rather than a ``WorkerRequest`` so the physics layer does not
    depend on the wire protocol. The worker constructs it only after every identity check
    has passed.
    """

    run_id: str
    execution_fingerprint: str
    benchmark: str
    scenario: str
    realization: str
    environment_id: str
    seed: int
    outcomes: tuple[str, ...]
    adapter_version: str
    engine_version: str
    implementation_digest: str


@dataclass(frozen=True, slots=True)
class ReferenceRun:
    """One completed native run: its diagnostic and every sampled state."""

    diagnostic: ReferenceDiagnostic
    samples: tuple[StateSample, ...]


def engine_version() -> str:
    """The actual MuJoCo version of the running worker environment."""
    return str(mujoco.__version__)


def _name(model: mujoco.MjModel, object_type: int, object_id: int) -> str:
    value = mujoco.mj_id2name(model, object_type, object_id)
    return "" if value is None else str(value)


def _close(actual: float, expected: float, tolerance: float = _NUMERIC_TOLERANCE) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)


def _verify_model(model: mujoco.MjModel) -> None:
    """Refuse a model that is not the reviewed one-body, one-hinge reference structure."""
    expectations: tuple[tuple[str, object, object], ...] = (
        ("nq", int(model.nq), 1),
        ("nv", int(model.nv), 1),
        ("nu", int(model.nu), 0),
        ("na", int(model.na), 0),
        ("njnt", int(model.njnt), 1),
        ("nbody", int(model.nbody), 2),
        ("ngeom", int(model.ngeom), 0),
        ("nsite", int(model.nsite), 1),
        ("nmesh", int(model.nmesh), 0),
        ("ntex", int(model.ntex), 0),
        ("nsensor", int(model.nsensor), 0),
        ("nkey", int(model.nkey), 0),
    )
    for label, actual, expected in expectations:
        if actual != expected:
            raise PhysicsError(
                f"the reference model has {label}={actual}, not the reviewed {expected}"
            )
    if _name(model, mujoco.mjtObj.mjOBJ_BODY, 1) != "pendulum":
        raise PhysicsError("the reference model body 1 is not the base 'pendulum' body")
    if _name(model, mujoco.mjtObj.mjOBJ_JOINT, 0) != "hinge":
        raise PhysicsError("the reference model joint 0 is not the base 'hinge' joint")
    if int(model.jnt_type[0]) != int(mujoco.mjtJoint.mjJNT_HINGE):
        raise PhysicsError("the reference joint is not a hinge")
    if int(model.jnt_bodyid[0]) != 1:
        raise PhysicsError("the reference hinge is not attached to the pendulum body")
    if int(model.jnt_limited[0]) != 0:
        raise PhysicsError("the reference hinge must not have a joint limit")
    if int(model.opt.integrator) != int(mujoco.mjtIntegrator.mjINT_RK4):
        raise PhysicsError("the reference model integrator is not RK4")
    if int(model.opt.solver) != int(mujoco.mjtSolver.mjSOL_NEWTON):
        raise PhysicsError("the reference model solver is not Newton")
    if int(model.opt.iterations) != reference.ITERATIONS:
        raise PhysicsError("the reference model solver iteration count changed")
    if not _close(float(model.opt.tolerance), reference.TOLERANCE):
        raise PhysicsError("the reference model solver tolerance changed")
    if not _close(float(model.opt.timestep), reference.TIMESTEP_S):
        raise PhysicsError("the reference model timestep changed")
    expected_gravity = np.array([0.0, 0.0, -reference.GRAVITY_M_S2])
    if not np.allclose(model.opt.gravity, expected_gravity, rtol=0.0, atol=_NUMERIC_TOLERANCE):
        raise PhysicsError("the reference model gravity is not standard gravity along -z")
    expected_axis = np.array([0.0, 1.0, 0.0])
    if not np.allclose(model.jnt_axis[0], expected_axis, rtol=0.0, atol=_NUMERIC_TOLERANCE):
        raise PhysicsError("the reference hinge axis is not +y")
    if not np.allclose(model.jnt_pos[0], np.zeros(3), rtol=0.0, atol=_NUMERIC_TOLERANCE):
        raise PhysicsError("the reference hinge is not at the body origin")
    if not _close(float(model.body_mass[1]), reference.MASS_KG):
        raise PhysicsError("the reference body mass changed")
    expected_com = np.array([0.0, 0.0, -reference.COM_DISTANCE_M])
    if not np.allclose(model.body_ipos[1], expected_com, rtol=0.0, atol=_NUMERIC_TOLERANCE):
        raise PhysicsError("the reference body centre of mass changed")
    expected_inertia = np.full(3, reference.COM_INERTIA_KG_M2)
    if not np.allclose(model.body_inertia[1], expected_inertia, rtol=0.0, atol=_NUMERIC_TOLERANCE):
        raise PhysicsError("the reference body centre-of-mass inertia changed")
    expected_iquat = np.array([1.0, 0.0, 0.0, 0.0])
    if not np.allclose(model.body_iquat[1], expected_iquat, rtol=0.0, atol=_NUMERIC_TOLERANCE):
        raise PhysicsError("the reference body inertial-frame orientation changed")
    if not _close(float(model.dof_damping[0]), 0.0):
        raise PhysicsError("the reference hinge has damping")
    if not _close(float(model.dof_armature[0]), 0.0):
        raise PhysicsError("the reference hinge has armature inertia")
    if not _close(float(model.dof_frictionloss[0]), 0.0):
        raise PhysicsError("the reference hinge has friction loss")


def hinge_parameters(model: mujoco.MjModel) -> tuple[float, float, float]:
    """Return ``(mass_kg, com_distance_m, hinge_inertia_kg_m2)`` from the loaded model.

    The hinge inertia is computed from the model's own inertial data rather than copied from
    the declaration: centre-of-mass inertia plus the parallel-axis term about the hinge axis.
    """
    mass = float(model.body_mass[1])
    axis = np.asarray(model.jnt_axis[0], dtype=np.float64)
    axis = axis / float(np.linalg.norm(axis))
    relative_com = np.asarray(model.body_ipos[1], dtype=np.float64) - np.asarray(
        model.jnt_pos[0], dtype=np.float64
    )
    distance = float(np.linalg.norm(relative_com - np.dot(relative_com, axis) * axis))
    inertia_com = np.diag(np.asarray(model.body_inertia[1], dtype=np.float64))
    parallel_axis = mass * (
        float(np.dot(relative_com, relative_com)) * np.eye(3) - np.outer(relative_com, relative_com)
    )
    inertia = float(axis @ (inertia_com + parallel_axis) @ axis)
    return mass, distance, inertia


def load_model() -> mujoco.MjModel:
    """Load and verify the reviewed model, without touching an absolute path."""
    xml = reference.model_bytes().decode("utf-8")
    try:
        model = mujoco.MjModel.from_xml_string(xml)
    except Exception as error:
        raise PhysicsError(f"MuJoCo refused the reviewed reference model: {error}") from error
    _verify_model(model)
    return model


def _require_finite_state(data: mujoco.MjData, *, when: str) -> None:
    """Refuse a non-finite or unexpectedly constrained physical state."""
    state = np.concatenate(
        (
            np.asarray(data.qpos, dtype=np.float64),
            np.asarray(data.qvel, dtype=np.float64),
            np.asarray(data.qacc, dtype=np.float64),
        )
    )
    if not bool(np.all(np.isfinite(state))):
        raise PhysicsError(f"the reference state is not finite {when}")
    if not math.isfinite(float(data.time)) or float(data.time) < 0.0:
        raise PhysicsError(
            f"the reference simulation time is not a finite non-negative value {when}"
        )
    if int(data.ncon) != 0:
        raise PhysicsError(f"the reference model produced a contact {when}")
    if int(data.nefc) != 0:
        raise PhysicsError(f"the reference model produced an unexpected constraint {when}")


def _energy(theta: float, omega: float, mass: float, distance: float, inertia: float) -> float:
    """The pendulum energy relative to its lowest point: kinetic plus gravitational."""
    return 0.5 * inertia * omega * omega + mass * reference.GRAVITY_M_S2 * distance * (
        1.0 - math.cos(theta)
    )


def _state_sample(
    data: mujoco.MjData,
    *,
    mass: float,
    distance: float,
    inertia: float,
) -> StateSample:
    theta = float(data.qpos[0])
    omega = float(data.qvel[0])
    return StateSample(
        time_s=float(data.time),
        angle_rad=theta,
        angular_velocity_rad_s=omega,
        energy_j=_energy(theta, omega, mass, distance, inertia),
    )


def _steps_for(duration_s: float, timestep_s: float) -> int:
    if not math.isfinite(duration_s) or duration_s <= 0.0:
        raise PhysicsError("the reference duration must be a finite positive number")
    if not math.isfinite(timestep_s) or timestep_s <= 0.0:
        raise PhysicsError("the reference timestep must be a finite positive number")
    steps = int(round(duration_s / timestep_s))
    if steps <= 0 or not math.isclose(
        steps * timestep_s, duration_s, rel_tol=0.0, abs_tol=_TIME_TOLERANCE
    ):
        raise PhysicsError("the reference duration is not an integer number of timesteps")
    return steps


def _trajectory_update(hasher, sample: StateSample) -> None:
    """Hash the native state with an explicit little-endian IEEE-754 double layout."""
    hasher.update(
        struct.pack(
            "<ddd",
            sample.time_s,
            sample.angle_rad,
            sample.angular_velocity_rad_s,
        )
    )


def run_reference(
    context: RunContext,
    *,
    timestep_s: float = reference.TIMESTEP_S,
    duration_s: float = reference.DURATION_S,
    collect_samples: bool = True,
) -> ReferenceRun:
    """Integrate the fixed reference case with MuJoCo and return its native diagnostic.

    :param context: the request identity the diagnostic must reproduce.
    :param timestep_s: production uses the reviewed 0.001 s; the qualification tool may set
        another positive value that divides the duration exactly.
    :param duration_s: production uses the reviewed 2.0 s.
    :param collect_samples: whether the returned run retains every sample for a qualification
        comparison. The diagnostic is computed from every step either way.
    :raises PhysicsError: if the model, solver, state, time or constraints are not the
        reviewed reference behavior.
    """
    model = load_model()
    mass, distance, inertia = hinge_parameters(model)
    if not _close(inertia, reference.HINGE_INERTIA_KG_M2, tolerance=1e-12):
        raise PhysicsError(
            f"the model hinge inertia {inertia!r} is not the reviewed "
            f"{reference.HINGE_INERTIA_KG_M2!r}"
        )
    steps = _steps_for(duration_s, timestep_s)
    model.opt.timestep = timestep_s

    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    if np.asarray(data.qpos).dtype != np.dtype(np.float64) or np.asarray(
        data.qvel
    ).dtype != np.dtype(np.float64):
        raise PhysicsError("the native reference state is not float64")
    data.qpos[0] = reference.INITIAL_ANGLE_RAD
    data.qvel[0] = reference.INITIAL_ANGULAR_VELOCITY_RAD_S
    mujoco.mj_forward(model, data)
    _require_finite_state(data, when="at initialization")

    samples: list[StateSample] = []
    sample_hasher = hashlib.sha256()
    first = _state_sample(data, mass=mass, distance=distance, inertia=inertia)
    _trajectory_update(sample_hasher, first)
    samples.append(first)

    previous_time = float(data.time)
    for _step in range(steps):
        mujoco.mj_step(model, data)
        _require_finite_state(data, when=f"at step {_step + 1}")
        current_time = float(data.time)
        if not current_time > previous_time:
            raise PhysicsError("the reference simulation time did not advance monotonically")
        if not math.isclose(
            current_time,
            previous_time + timestep_s,
            rel_tol=0.0,
            abs_tol=_TIME_TOLERANCE,
        ):
            raise PhysicsError("the reference simulation time did not advance by one timestep")
        previous_time = current_time
        sample = _state_sample(data, mass=mass, distance=distance, inertia=inertia)
        _trajectory_update(sample_hasher, sample)
        samples.append(sample)

    final = samples[-1]
    if not math.isclose(final.time_s, duration_s, rel_tol=0.0, abs_tol=_TIME_TOLERANCE):
        raise PhysicsError("the reference run did not end at the declared duration")

    checkpoints: list[StateSample] = []
    for checkpoint_time in reference.CHECKPOINT_TIMES_S:
        index = int(round(checkpoint_time / timestep_s))
        if not math.isclose(
            index * timestep_s, checkpoint_time, rel_tol=0.0, abs_tol=_TIME_TOLERANCE
        ):
            raise PhysicsError("a reference checkpoint is not aligned with the selected timestep")
        if index >= len(samples):
            raise PhysicsError("a reference checkpoint lies beyond the run")
        checkpoints.append(samples[index])

    initial_energy = first.energy_j
    if abs(initial_energy) <= 0.0:
        raise PhysicsError("the reference initial energy is zero, so relative drift is undefined")
    max_relative_drift = max(
        abs(sample.energy_j - initial_energy) / abs(initial_energy) for sample in samples
    )
    diagnostic = ReferenceDiagnostic(
        adapter_id=reference.ADAPTER_ID,
        adapter_version=context.adapter_version,
        engine=reference.ENGINE,
        engine_version=context.engine_version,
        implementation_digest=context.implementation_digest,
        model_sha256=reference.MODEL_SHA256,
        platform=reference.platform_tag(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        run_id=context.run_id,
        execution_fingerprint=context.execution_fingerprint,
        benchmark=context.benchmark,
        scenario=context.scenario,
        realization=context.realization,
        environment_id=context.environment_id,
        seed=context.seed,
        outcomes=context.outcomes,
        control_policy=reference.CONTROL_POLICY,
        integrator=reference.INTEGRATOR,
        solver=reference.SOLVER,
        timestep_s=timestep_s,
        duration_s=duration_s,
        steps=steps,
        nq=int(model.nq),
        nv=int(model.nv),
        nu=int(model.nu),
        njnt=int(model.njnt),
        ngeom=int(model.ngeom),
        joint_constraints=reference.JOINT_CONSTRAINTS,
        contact_policy=reference.CONTACT_POLICY,
        solver_iterations=int(model.opt.iterations),
        solver_tolerance=float(model.opt.tolerance),
        randomness_policy=reference.RANDOMNESS_POLICY,
        gravity_m_s2=reference.GRAVITY_M_S2,
        mass_kg=mass,
        com_distance_m=distance,
        hinge_inertia_kg_m2=inertia,
        initial=first,
        final=final,
        checkpoints=tuple(checkpoints),
        energy_initial_j=initial_energy,
        energy_final_j=final.energy_j,
        energy_drift_j=final.energy_j - initial_energy,
        max_relative_energy_drift=max_relative_drift,
        trajectory_sha256=sample_hasher.hexdigest(),
        all_finite=True,
        native_state_layout=reference.NATIVE_STATE_LAYOUT,
        claim=(
            "native MuJoCo forward-dynamics diagnostic only; not canonical or assessment "
            "evidence and not a scientific validation"
        ),
    )
    return ReferenceRun(
        diagnostic=diagnostic,
        samples=tuple(samples) if collect_samples else (),
    )


def nonfinite_probe() -> str:
    """Set a real MuJoCo state non-finite and prove the state guard refuses it.

    This exists so the qualification suite can exercise the guard against a real
    ``MjData`` rather than a synthetic array. It returns the guard's bounded refusal
    message; a guard that accepts the state is a failure and raises ``PhysicsError``.
    """
    model = load_model()
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[0] = math.nan
    mujoco.mj_forward(model, data)
    try:
        _require_finite_state(data, when="in the non-finite probe")
    except PhysicsError as error:
        return str(error)
    raise PhysicsError("the non-finite state guard accepted a NaN hinge angle")
