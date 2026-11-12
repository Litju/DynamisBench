"""RES-640 mechanism receipt: where the standing reference's world heading comes from.

Run from ``python/`` with the isolated worker interpreter (MuJoCo is required):

    PYTHONPATH=src worker-mujoco/.venv/Scripts/python.exe \
        ../evidence/qa/RES-640/analysis/mechanism.py

It writes one JSON object to stdout. Read-only: it never touches the packaged asset. Every
number it prints is measured from a fresh ``generator_model()``. It reuses
``engine._inverse_residual`` deliberately: the question is what the production contact settle
sees, so the residual must be the production one.
"""

from __future__ import annotations

import json

import mujoco
import numpy as np

from dynamisbench.adapters.mujoco.squat import engine, reference


def heading(qpos: np.ndarray) -> float:
    return reference.pelvis_heading_rad([float(value) for value in qpos])


def rotation_matrix(qpos: np.ndarray, address: int) -> np.ndarray:
    quat = np.asarray(qpos[address + 3 : address + 7], dtype=float)
    w, x, y, z = quat / np.linalg.norm(quat)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def rotation_dof_is_world_frame(model, qpos, lay) -> bool:
    """Whether a free joint's rotational dofs rotate the body about world axes."""
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    mujoco.mj_kinematics(model, data)
    before = np.asarray(data.xmat[lay.bodies["pelvis"]], dtype=float).reshape(3, 3)
    perturbation = np.zeros(model.nv)
    perturbation[5] = 1e-6
    probe = np.array(qpos, dtype=float)
    mujoco.mj_integratePos(model, probe, perturbation, 1.0)
    data.qpos[:] = probe
    mujoco.mj_kinematics(model, data)
    after = np.asarray(data.xmat[lay.bodies["pelvis"]], dtype=float).reshape(3, 3)
    quat = np.zeros(4)
    vector = np.zeros(3)
    mujoco.mju_mat2Quat(quat, np.ascontiguousarray(after @ before.T).reshape(9))
    mujoco.mju_quat2Vel(vector, quat, 1e-6)
    return bool(abs(vector[2]) > 0.9)


def free_pose_mode(model, qpos, *, translation, rotation, world_frame_rotation) -> np.ndarray:
    """A tangent vector that moves both free bodies by the same world-frame twist."""
    lay = engine.layout(model)
    perturbation = np.zeros(model.nv)
    for address, dof in ((lay.root_qpos, 0), (lay.bar_qpos, lay.bar_dof)):
        position = np.asarray(qpos[address : address + 3], dtype=float)
        perturbation[dof : dof + 3] = translation + np.cross(rotation, position)
        body_rotation = (
            rotation if world_frame_rotation else rotation_matrix(qpos, address).T @ rotation
        )
        perturbation[dof + 3 : dof + 6] = body_rotation
    return perturbation


def main() -> None:
    model = engine.generator_model()
    lay = engine.layout(model)
    receiver = mujoco.MjData(model)

    posture = engine.solve_posture(model)
    settled = engine.settle(model, posture)
    activation = engine.static_equilibrium(model, settled).activation
    relaxed, _relaxed_activation, speed = engine.relax_to_rest(model, settled, activation)
    reference_state = reference.canonical_world_frame([float(value) for value in relaxed])

    # 1. Stage headings: the settle injects the heading, the relaxation preserves it.
    stages = {
        "after_posture_solve_rad": heading(posture),
        "after_contact_settle_rad": heading(settled),
        "after_relaxation_rad": heading(relaxed),
        "declared_representative_rad": reference.pelvis_heading_rad(reference_state),
        "relaxation_final_max_speed": speed,
    }

    # 2. The settle Jacobian: singular values and the stiffness of the rigid placements.
    dofs = lay.unactuated_dof
    base_residual = engine._inverse_residual(model, receiver, settled, dofs)
    jacobian = np.zeros((len(dofs), len(dofs)))
    step = 1e-8
    for column, dof in enumerate(dofs):
        perturbation = np.zeros(model.nv)
        perturbation[dof] = step
        probe = settled.copy()
        mujoco.mj_integratePos(model, probe, perturbation, 1.0)
        jacobian[:, column] = (
            engine._inverse_residual(model, receiver, probe, dofs) - base_residual
        ) / step
    singular_values = np.linalg.svd(jacobian, compute_uv=False)
    world_frame_rotation = rotation_dof_is_world_frame(model, settled, lay)
    modes = {
        "translation_x": (np.array([1.0, 0.0, 0.0]), np.zeros(3)),
        "translation_y": (np.array([0.0, 1.0, 0.0]), np.zeros(3)),
        "yaw": (np.zeros(3), np.array([0.0, 0.0, 1.0])),
        "translation_z": (np.array([0.0, 0.0, 1.0]), np.zeros(3)),
        "pitch": (np.zeros(3), np.array([0.0, 1.0, 0.0])),
        "roll": (np.zeros(3), np.array([1.0, 0.0, 0.0])),
    }
    stiffness = {}
    for name, (translation, rotation) in modes.items():
        mode = free_pose_mode(
            model,
            settled,
            translation=translation,
            rotation=rotation,
            world_frame_rotation=world_frame_rotation,
        )
        delta = 1e-8
        probe = settled.copy()
        mujoco.mj_integratePos(model, probe, mode * delta, 1.0)
        moved = engine._inverse_residual(model, receiver, probe, dofs)
        stiffness[name] = float(np.abs(moved - base_residual).max() / delta)
    settle = {
        "singular_values": [float(value) for value in singular_values],
        "condition_number": float(singular_values[0] / singular_values[-1]),
        "gap_above_the_third_smallest": float(singular_values[-3] / singular_values[-4]),
        "rotation_dofs_are_world_frame": world_frame_rotation,
        "rigid_mode_stiffness_n_per_unit": stiffness,
        "residual_at_settled_state_n": [float(value) for value in base_residual],
    }

    # 3. Potential energy under a whole-system rotation: exactly invariant.
    data = mujoco.MjData(model)

    def energy(qpos) -> float:
        data.qpos[:] = qpos
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
        return float(data.energy[0] + data.energy[1])

    base_energy = energy(settled)
    energy_delta = {
        label: energy(reference.rotate_world_frame(list(settled), float(label))) - base_energy
        for label in ("1e-3", "1e-1", "1")
    }

    # 4. Last-bit sensitivity of the settle's arbitrary placement.
    rng = np.random.default_rng(20261111)
    headings = []
    canonical = []
    physical = []
    base_canonical = reference.canonical_world_frame([float(value) for value in settled])
    base_physical = reference.physical_state([float(value) for value in settled])
    for _trial in range(40):
        perturbed = np.array(posture)
        for index in rng.choice(model.nq, size=4, replace=False):
            perturbed[index] = np.nextafter(perturbed[index], perturbed[index] + 1.0)
        output = engine.settle(model, perturbed)
        headings.append(heading(output))
        values = [float(value) for value in output]
        canonical.append(
            max(
                abs(a - b)
                for a, b in zip(
                    reference.canonical_world_frame(values), base_canonical, strict=True
                )
            )
        )
        state = reference.physical_state(values)
        physical.append(
            max(
                abs(a - b)
                for group, group_values in base_physical.items()
                for a, b in zip(group_values, state[group], strict=True)
            )
        )
    sensitivity = {
        "trials": len(headings),
        "heading_min_rad": min(headings),
        "heading_max_rad": max(headings),
        "heading_spread_rad": max(headings) - min(headings),
        "canonical_qpos_max_rad": max(canonical),
        "physical_max_rad": max(physical),
    }

    # 5. Closed-loop invariance: 1 s of standing from the packaged keyframe, rotated 1e-2 rad.
    packaged = engine.load_model()
    keyframe, keyframe_activation = engine.keyframe_state(packaged)
    controller = engine.controller_for(packaged, keyframe, keyframe_activation)

    def stand(qpos, seconds: float = 1.0):
        state = mujoco.MjData(packaged)
        mujoco.mj_resetData(packaged, state)
        state.qpos[:] = qpos
        state.act[:] = keyframe_activation
        state.ctrl[:] = keyframe_activation
        mujoco.mj_forward(packaged, state)
        total = float(state.energy[0] + state.energy[1])
        for _step in range(int(round(seconds / float(packaged.opt.timestep)))):
            state.ctrl[:] = controller.excitation(
                np.asarray(state.qpos[lay.joint_qpos], dtype=float),
                np.asarray(state.qvel[lay.joint_dof], dtype=float),
            )
            mujoco.mj_step(packaged, state)
        return np.array(state.qpos), total

    base_q, base_total = stand(list(keyframe))
    rotated_q, rotated_total = stand(reference.rotate_world_frame(list(keyframe), 1e-2))
    a = reference.physical_state([float(value) for value in base_q])
    b = reference.physical_state([float(value) for value in rotated_q])
    invariance = {
        "physical_state_max_difference": max(
            abs(x - y) for group in a for x, y in zip(a[group], b[group], strict=True)
        ),
        "mechanical_energy_difference_j": abs(rotated_total - base_total),
        "heading_shift_minus_injected_rad": reference.pelvis_heading_rad(
            [float(value) for value in rotated_q]
        )
        - reference.pelvis_heading_rad([float(value) for value in base_q])
        - 1e-2,
    }

    print(
        json.dumps(
            {
                "schema": "dynamisbench.qa.squat-world-frame-mechanism/1",
                "claim": "diagnostic_only_not_a_scientific_or_release_qualification",
                "energy_evidence_status": "INVALID: energy disabled; use energy_qualification.py",
                "stages": stages,
                "settle": settle,
                "potential_energy_delta_j": energy_delta,
                "last_bit_sensitivity": sensitivity,
                "closed_loop_invariance": invariance,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
