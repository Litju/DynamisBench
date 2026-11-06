"""Collect the real data the Codex design plates are drawn from.

Design tooling, not product code. Run with the isolated worker interpreter (it has MuJoCo):

    python/worker-mujoco/.venv/bin/python apps/workbench/design/tools/plate_data.py <out.json>

It runs the packaged model's controlled repetition once, and stores: the synchronized samples,
the model's geometry, and every geom's world pose at a few chosen instants. The plates then
show the model and numbers the workbench will actually display.
"""

from __future__ import annotations

import json
import sys

import mujoco
import numpy as np

from dynamisbench.adapters.mujoco.squat import analysis, anthropometry, engine, mjcf, movement


def main() -> int:
    output = sys.argv[1]
    model = engine.load_model()
    record = engine.simulate_repetition(model)
    summary = analysis.summarize_repetition(
        record.samples,
        record.joint_names,
        athlete_mass_kg=75.0,
        total_mass_kg=95.0,
        gravity_m_s2=9.80665,
    )
    data = mujoco.MjData(model)
    frames = {}
    for t in (0.0, 1.6, 2.0, 2.2, 2.7, 3.3, 4.0):
        index = int(round(t / 0.01))
        data.qpos[:] = record.samples["qpos"][index]
        mujoco.mj_forward(model, data)
        geoms = []
        for g in range(model.ngeom):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
            geoms.append(
                {
                    "name": name,
                    "type": int(model.geom_type[g]),
                    "size": model.geom_size[g].tolist(),
                    "pos": data.geom_xpos[g].tolist(),
                    "mat": data.geom_xmat[g].tolist(),
                    "body": mujoco.mj_id2name(
                        model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[g])
                    ),
                }
            )
        bodies = {
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b): data.xpos[b].tolist()
            for b in range(1, model.nbody)
        }
        frames[f"{t:.1f}"] = {
            "geoms": geoms,
            "bodies": bodies,
            "com": data.subtree_com[0].tolist(),
            "index": index,
        }

    def plain(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (list, tuple)):
            return [plain(v) for v in value]
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, (np.integer,)):
            return int(value)
        return value

    def light(rec):
        keep = ("t", "phase", "heel_load_fraction", "loaded_contacts", "cop_margin_m",
                "grf_left_n", "grf_right_n", "grf_planned_vertical_n", "com_position_m",
                "joint_angle_deg")
        return {
            "samples": plain({k: rec.samples[k] for k in keep}),
            "extrema": plain(rec.extrema),
            "hash": rec.trajectory_sha256,
            "completed": rec.completed,
        }

    ablations = {}
    ablations["no_internal_model"] = light(engine.simulate_repetition(model, dynamic_feedforward=False))
    soft = engine.load_model()
    for pair in range(soft.npair):
        soft.pair_solreffriction[pair, 0] = 0.015
    ablations["soft_friction"] = light(engine.simulate_repetition(soft))
    fine = engine.load_model()
    fine.opt.timestep = 0.0005
    ablations["half_timestep"] = light(engine.simulate_repetition(fine))

    payload = {
        "ablations": ablations,
        "joint_names": list(record.joint_names),
        "samples": plain({k: v for k, v in record.samples.items() if k != "qpos"}),
        "events": record.command_events,
        "summary": plain(summary),
        "extrema": plain(record.extrema),
        "work": plain(record.work),
        "trajectory_sha256": record.trajectory_sha256,
        "frames": frames,
        "segments": [
            {"body": s.body, "segment": s.segment, "mass": s.mass, "com": list(s.com),
             "inertia": list(s.inertia)}
            for s in anthropometry.segment_inertias()
        ],
        "joints": [
            {"name": j.name, "body": j.body, "range": list(j.range_deg),
             "torque": list(j.torque_nm), "damping": j.damping}
            for j in anthropometry.joint_specs()
        ],
        "sole_points": list(mjcf.SOLE_POINTS),
        "plan": {k: getattr(movement.REPETITION, k) for k in (
            "bottom_knee_flexion_deg", "standing_s", "descent_s", "bottom_pause_s",
            "ascent_s", "return_s")},
    }
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
