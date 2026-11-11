"""The world-frame gauge of the standing reference (RES-640).

The squat model is exactly invariant under a rigid rotation of the whole system about the world
vertical axis: the floor is an infinite plane, gravity is vertical, and every actuator is an
internal joint torque. The reference generator therefore cannot determine the athlete's heading,
and the packaged keyframe is compared in the declared representative (pelvis heading zero)
instead of in whatever heading the contact settle's singular solve happened to sample.

These tests prove the invariance, the projection and the negative control: a physical change is
still rejected at the unchanged tolerance.
"""

from __future__ import annotations

import math

import pytest
from tools.mujoco_squat_model import KEYFRAME_TOLERANCE, keyframe_of

from dynamisbench.adapters.mujoco.squat import contract, reference
from tests.execution.mujoco_squat.support import run_worker_code

_H = 7.66326e-6
"""Heading difference of the protected-main failure: 3.829e-6 in a quaternion component.

The quaternion component moves by ``sin(h/2) * w`` for a heading change ``h`` about a pelvis
whose ``qpos[3]`` (w) is 0.99931, so this heading reproduces the observed 3.829e-6 exactly.
"""


def _packaged() -> tuple[list[float], list[float]]:
    return keyframe_of(contract.model_bytes())


# ---------------------------------------------------------------------------------------------
# Pure projection algebra


def test_the_declared_gauge_is_exactly_the_two_free_poses() -> None:
    qpos, _act = _packaged()
    rotated = reference.rotate_world_frame(qpos, 0.25)
    for index, (before, after) in enumerate(zip(qpos, rotated, strict=True)):
        if index in reference.GAUGE_QPOS_INDICES:
            continue
        assert after == before, f"qpos[{index}] is not gauge and moved"
    assert reference.GAUGE_QPOS_INDICES == (
        0,
        1,
        3,
        4,
        5,
        6,
        36,
        37,
        39,
        40,
        41,
        42,
    )


def test_the_projection_zeroes_the_heading_and_preserves_the_physical_state() -> None:
    qpos, _act = _packaged()
    assert abs(reference.pelvis_heading_rad(qpos)) > 1e-7
    canonical = reference.canonical_world_frame(qpos)
    assert abs(reference.pelvis_heading_rad(canonical)) < 1e-15
    # A second projection is a no-op up to the rounding of a rotation of ~1e-23 rad.
    assert reference.canonical_world_frame(canonical) == pytest.approx(canonical, abs=1e-21)
    before = reference.physical_state(qpos)
    after = reference.physical_state(canonical)
    for group, values in before.items():
        assert after[group] == pytest.approx(values, abs=1e-12), group


def test_a_rotation_of_the_whole_system_preserves_the_physical_state() -> None:
    qpos, _act = _packaged()
    for angle in (1e-9, 1e-6, 1e-3, 0.5):
        rotated = reference.rotate_world_frame(qpos, angle)
        assert reference.pelvis_heading_rad(rotated) == pytest.approx(
            reference.pelvis_heading_rad(qpos) + angle, abs=1e-12
        )
        before = reference.physical_state(qpos)
        after = reference.physical_state(rotated)
        for group, values in before.items():
            assert after[group] == pytest.approx(values, abs=1e-12), group


def test_the_projection_refuses_anything_that_is_not_a_standing_qpos() -> None:
    qpos, _act = _packaged()
    with pytest.raises(ValueError):
        reference.canonical_world_frame(qpos[:-1])
    with pytest.raises(ValueError):
        reference.canonical_world_frame([0.0] * len(qpos))
    with pytest.raises(ValueError):
        reference.rotate_world_frame(qpos, math.nan)
    with pytest.raises(ValueError):
        reference.physical_state(qpos[:-1])


@pytest.mark.parametrize(
    ("index", "change"),
    [
        (2, 2e-6),  # pelvis height
        (7, 2e-6),  # a hinge angle
        (reference.BAR_QPOS, 2e-6),  # bar position
        (reference.ROOT_QPOS + 5, 2e-6),  # pelvis pitch (a physical rotation, not a heading)
    ],
)
def test_a_physical_change_of_the_reference_is_still_rejected(index: int, change: float) -> None:
    qpos, _act = _packaged()
    perturbed = list(qpos)
    perturbed[index] += change
    packaged = reference.canonical_world_frame(qpos)
    regenerated = reference.canonical_world_frame(perturbed)
    worst = max(abs(a - b) for a, b in zip(packaged, regenerated, strict=True))
    assert worst > KEYFRAME_TOLERANCE, f"qpos[{index}] change of {change} was excused"


def test_a_pure_heading_change_of_the_failure_magnitude_is_not_a_physical_difference() -> None:
    # This is the protected-main failure exactly: a regeneration with a different heading.
    qpos, _act = _packaged()
    drifted = reference.rotate_world_frame(qpos, _H)
    raw = max(abs(a - b) for a, b in zip(qpos, drifted, strict=True))
    assert raw == pytest.approx(3.829e-6, abs=1e-9)
    assert raw > KEYFRAME_TOLERANCE  # the old comparison failed here
    canonical = max(
        abs(a - b)
        for a, b in zip(
            reference.canonical_world_frame(qpos),
            reference.canonical_world_frame(drifted),
            strict=True,
        )
    )
    assert canonical < 1e-15  # the physical comparison does not


# ---------------------------------------------------------------------------------------------
# Real MuJoCo: the symmetry and the arithmetic-path independence


def test_the_model_is_exactly_invariant_under_a_whole_body_rotation() -> None:
    payload = run_worker_code(
        """
import json
import numpy as np
import mujoco
from dynamisbench.adapters.mujoco.squat import engine, reference

model = engine.load_model()
lay = engine.layout(model)
qpos, act = engine.keyframe_state(model)
controller = engine.controller_for(model, qpos, act)

def rest_bias(data):
    bias = np.asarray(data.qfrc_bias, dtype=float)
    return [
        float(np.abs(bias[lay.joint_dof]).max()),
        float(np.linalg.norm(bias[0:3])),
        float(np.linalg.norm(bias[3:6])),
        float(np.linalg.norm(bias[lay.bar_dof:lay.bar_dof + 3])),
        float(np.linalg.norm(bias[lay.bar_dof + 3:lay.bar_dof + 6])),
    ]

def run(q, seconds=1.0):
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[:] = q
    data.act[:] = act
    data.ctrl[:] = act
    mujoco.mj_forward(model, data)
    energy = float(data.energy[0] + data.energy[1])
    bias = rest_bias(data)
    for _ in range(int(round(seconds / float(model.opt.timestep)))):
        data.ctrl[:] = controller.excitation(
            np.asarray(data.qpos[lay.joint_qpos], dtype=float),
            np.asarray(data.qvel[lay.joint_dof], dtype=float),
        )
        mujoco.mj_step(model, data)
    return np.array(data.qpos), energy, bias

angle = 1e-2
base_q, base_e, base_b = run(qpos)
rotated_q, rotated_e, rotated_b = run(reference.rotate_world_frame(list(qpos), angle))
base_physical = reference.physical_state(list(base_q))
rotated_physical = reference.physical_state(list(rotated_q))
print(json.dumps({
    "physical_delta": max(
        abs(a - b)
        for group in base_physical
        for a, b in zip(base_physical[group], rotated_physical[group])
    ),
    "canonical_delta": max(
        abs(a - b)
        for a, b in zip(
            reference.canonical_world_frame(list(base_q)),
            reference.canonical_world_frame(list(rotated_q)),
        )
    ),
    "energy_delta": abs(rotated_e - base_e),
    "bias_delta": max(abs(a - b) for a, b in zip(base_b, rotated_b)),
    "base_bias": base_b,
    "final_heading_shift": reference.pelvis_heading_rad(list(rotated_q))
    - reference.pelvis_heading_rad(list(base_q))
    - angle,
}))
"""
    )
    # The rotated and unrotated runs are the same physical trajectory: every gauge-invariant
    # observable of the final state agrees to machine precision, as do the initial rest bias
    # and the total mechanical energy.
    assert payload["physical_delta"] < 1e-12
    assert payload["energy_delta"] < 1e-9
    assert payload["bias_delta"] < 1e-9
    # The rotated run really did keep the injected heading (so the test is not vacuous).
    assert abs(payload["final_heading_shift"]) < 1e-9
    # Un-rotating about the *final* pelvis leaves only the translation gauge (the pivot moved
    # during the second, so this is a whole-system translation of ~1e-9 m, not a difference).
    assert payload["canonical_delta"] < 1e-6


def test_the_reference_state_is_independent_of_last_bit_rounding() -> None:
    payload = run_worker_code(
        """
import json
import math
import numpy as np
from dynamisbench.adapters.mujoco.squat import engine, reference

model = engine.generator_model()
q0 = engine.solve_posture(model)
base = engine.settle(model, q0)

perturbed = [float(value) for value in q0]
for index in (0, 4, 9, 18, 24, 31, 37, 41):
    perturbed[index] = math.nextafter(perturbed[index], math.inf)
other = engine.settle(model, np.asarray(perturbed, dtype=float))

base_physical = reference.physical_state(list(base))
other_physical = reference.physical_state(list(other))
print(json.dumps({
    "raw_delta": max(abs(float(a) - float(b)) for a, b in zip(base, other)),
    "heading_delta": abs(
        reference.pelvis_heading_rad(list(other)) - reference.pelvis_heading_rad(list(base))
    ),
    "canonical_delta": max(
        abs(a - b)
        for a, b in zip(
            reference.canonical_world_frame(list(base)),
            reference.canonical_world_frame(list(other)),
        )
    ),
    "physical_delta": max(
        abs(a - b)
        for group in base_physical
        for a, b in zip(base_physical[group], other_physical[group])
    ),
}))
"""
    )
    # One-ulp input differences move the settle's arbitrary world placement by 1e-7 or more...
    assert payload["raw_delta"] > 1e-8
    assert payload["heading_delta"] > 1e-9
    # ...but the physical state is the same to machine precision, and the declared
    # representative removes the heading (only the much smaller translation gauge remains).
    assert payload["physical_delta"] < 1e-12
    assert payload["canonical_delta"] < 1e-7
    assert payload["heading_delta"] > payload["canonical_delta"]
