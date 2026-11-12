"""RES-640: non-vacuous, static gravitational-energy controls (SI units).

Run with the isolated worker Python; stdout is the diagnostic receipt. No stepping,
asset write or accepted model-option change occurs. The independent calculation uses
body inertial offsets transformed by world body poses, rather than mjData.energy or
MuJoCo's xipos energy summation. Kinematics remains supplied by MuJoCo, so this is
an independent energy oracle, not an independent simulator.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from pathlib import Path

import mujoco
import numpy as np

from dynamisbench.adapters.mujoco.squat import contract, engine, reference

ANGLES_RAD = (-math.pi, -1.0, -0.1, 0.001, 0.1, 1.0, math.pi / 2, math.pi)
LIFT_M = 0.125


def main() -> None:
    model = engine.load_model()
    assert mujoco.__version__ == "3.17.0"
    qpos, _ = engine.keyframe_state(model)
    original_flags = int(model.opt.enableflags)
    bit = int(mujoco.mjtEnableBit.mjENBL_ENERGY)
    assert original_flags & bit == 0
    assert np.array_equal(model.opt.gravity, [0.0, 0.0, -9.80665])
    assert math.isclose(math.fsum(model.body_mass), 95.0, abs_tol=1e-12)
    assert not np.any(model.jnt_stiffness)
    assert not np.any(model.jnt_stiffnesspoly)
    assert not np.any(model.tendon_stiffness)
    assert model.nflex == 0

    # Predeclared before observations: gamma_N * energy scale, with N=256*nbody
    # conservatively allowing 256 scalar roundings per link over a chain no longer
    # than nbody (quaternion/pose transforms plus energy arithmetic). This is an
    # engineering floating-point budget conditional on ordinary binary64/libm
    # accuracy, not a formal libm proof or empirical/measurement uncertainty.
    count = 256 * (model.nbody + 1)
    epsilon = sys.float_info.epsilon
    gamma = count * epsilon / (1 - count * epsilon)
    scale_j = 95.0 * 9.80665 * 4.0  # verified COM |height| < 4 m in every sample
    budget_j = gamma * scale_j

    def sample(pose: list[float]) -> dict[str, object]:
        data = mujoco.MjData(model)
        data.energy[:] = [123.0, 456.0]  # demonstrate overwrite, not merely fresh-data zeros
        data.qpos[:] = pose
        mujoco.mj_forward(model, data)
        heights = [
            float(data.xpos[i, 2])
            + math.fsum(
                float(data.xmat[i, 6 + axis]) * float(model.body_ipos[i, axis]) for axis in range(3)
            )
            for i in range(1, model.nbody)
        ]
        assert max(abs(h) for h in heights) < 4.0
        terms = [float(model.body_mass[i]) * 9.80665 * h for i, h in enumerate(heights, start=1)]
        return {
            "analytical_potential_j": math.fsum(terms),
            "mujoco_potential_j": float(data.energy[0]),
            "mujoco_kinetic_j": float(data.energy[1]),
            "body_com_heights_m": heights,
            "body_gravitational_energy_j": terms,
        }

    disabled = sample(list(qpos))
    # This flag is changed on this diagnostic instance only, never persisted.
    model.opt.enableflags = original_flags | bit
    baseline = sample(list(qpos))
    rows = []
    for angle in ANGLES_RAD:
        row = sample(reference.rotate_world_frame(list(qpos), angle))
        for key in ("analytical_potential_j", "mujoco_potential_j"):
            row[key + "_delta"] = float(row[key]) - float(baseline[key])
        row["angle_rad"] = angle
        rows.append(row)
    lifted_qpos = list(qpos)
    for address in (reference.ROOT_QPOS, reference.BAR_QPOS):
        lifted_qpos[address + 2] += LIFT_M
    lifted = sample(lifted_qpos)
    expected_j = 95.0 * 9.80665 * LIFT_M
    for key in ("analytical_potential_j", "mujoco_potential_j"):
        delta = float(lifted[key]) - float(baseline[key])
        lifted[key + "_delta"] = delta
        lifted[key + "_residual_j"] = delta - expected_j
        assert abs(delta - expected_j) <= 2 * budget_j
        assert abs(delta) > 1000 * budget_j
    for row in [baseline, lifted, *rows]:
        assert (
            abs(float(row["analytical_potential_j"]) - float(row["mujoco_potential_j"]))
            <= 2 * budget_j
        )
        assert row["mujoco_kinetic_j"] == 0.0
    for row in rows:
        assert abs(float(row["analytical_potential_j_delta"])) <= 2 * budget_j
        assert abs(float(row["mujoco_potential_j_delta"])) <= 2 * budget_j

    repository = Path(__file__).resolve().parents[4]
    sources = [
        Path(__file__).resolve(),
        Path(engine.__file__),
        Path(reference.__file__),
        repository / "python/worker-mujoco/uv.lock",
        Path(sys.executable),
    ]
    package = Path(mujoco.__file__).parent
    sources.extend(sorted(package.rglob("*.dll")))
    sources.extend(sorted(package.rglob("*.pyd")))
    print(
        json.dumps(
            {
                "schema": "dynamisbench.qa.squat-energy-qualification/1",
                "supersedes": (
                    "energy fields only in raw/mechanism-windows-local.json; "
                    "historical disabled-energy zeros are not measurements"
                ),
                "scope": (
                    "static potential energy; zero velocity; "
                    "no trajectory-energy conservation claim"
                ),
                "official_documentation": "https://mujoco.readthedocs.io/en/3.17.0/XMLreference.html#option-flag-energy",
                "official_source": (
                    "https://github.com/google-deepmind/mujoco/blob/3.17.0/"
                    "src/engine/engine_forward.c#L1795-L1813"
                ),
                "environment": {
                    "python": sys.version,
                    "executable": sys.executable,
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                    "mujoco": mujoco.__version__,
                    "numpy": np.__version__,
                },
                "model_sha256": contract.MODEL_SHA256,
                "source_sha256": {
                    str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
                },
                "body_names": [
                    mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i)
                    for i in range(1, model.nbody)
                ],
                "body_masses_kg": list(map(float, model.body_mass[1:])),
                "gravity_m_s2": list(map(float, model.opt.gravity)),
                "original_enableflags": original_flags,
                "diagnostic_enableflags": int(model.opt.enableflags),
                "disabled_energy_sample": disabled,
                "baseline": baseline,
                "lift_m": LIFT_M,
                "expected_lift_energy_j": expected_j,
                "lifted": lifted,
                "roundoff_operation_allowance": count,
                "roundoff_scale_j": scale_j,
                "per_energy_roundoff_budget_j": budget_j,
                "difference_roundoff_budget_j": 2 * budget_j,
                "yaw_controls": rows,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
