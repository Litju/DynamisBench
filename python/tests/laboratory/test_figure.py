"""The anatomical figure is a closed, correctly bound surface derived from the published model.

The asset is held to facts stated here, not imported from its generator: the model it names is
the laboratory model; its skeleton is that model's; its bind pose is the model's reference
configuration rotated by the published bind angles (recomputed here with an independent forward
kinematics); its surface is a closed 2-manifold with outward normals whose enclosed volume is a
75 kg body's; every calibrated segment encloses its mass over Dempster's density; the outsole
lies on the sole contact spheres; and each fist closes around the bar where the weld holds it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from importlib.resources import files
from typing import Any, cast

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dynamisbench.api import API_V1_PREFIX, create_app
from dynamisbench.laboratory import dataset
from dynamisbench.laboratory.figure import (
    FIGURE_MEDIA_TYPE,
    FIGURE_SHA256,
    figure_bytes,
    figure_header,
)

ATHLETE_MASS_KG = 75.0
BODY_DENSITY_RANGE_KG_M3 = (1000.0, 1100.0)
"""Whole-body density of a lean adult male (hydrostatic weighing literature)."""

KINEMATIC_NEIGHBOURS = {
    frozenset(pair)
    for pair in (
        ("pelvis", "torso_middle"),
        ("torso_middle", "torso_upper"),
        ("torso_upper", "head"),
        ("torso_upper", "upper_arm_l"),
        ("torso_upper", "upper_arm_r"),
        ("upper_arm_l", "forearm_l"),
        ("upper_arm_r", "forearm_r"),
        ("forearm_l", "hand_l"),
        ("forearm_r", "hand_r"),
        ("pelvis", "thigh_l"),
        ("pelvis", "thigh_r"),
        ("thigh_l", "shank_l"),
        ("thigh_r", "shank_r"),
        ("shank_l", "foot_l"),
        ("shank_r", "foot_r"),
    )
}


def _arrays() -> dict[str, Any]:
    content = figure_bytes()
    header = figure_header()
    base = 12 + int.from_bytes(content[8:12], "little")
    dtypes = {"float32": "<f4", "uint8": "u1", "int16": "<i2", "uint32": "<u4"}
    out: dict[str, Any] = {}
    for section in header["sections"]:
        start = base + section["offset"]
        out[section["name"]] = np.frombuffer(
            content[start : start + section["bytes"]], dtype=dtypes[section["dtype"]]
        )
    n = header["counts"]["vertices"]
    return {
        "header": header,
        "position": out["position"].reshape(n, 3).astype(np.float64),
        "normal": out["normal"].reshape(n, 3).astype(np.float64),
        "joints": out["joints"].reshape(n, 4),
        "weights": out["weights"].reshape(n, 4),
        "garment": out["garment"].reshape(n, 5) / header["garment_scale"],
        "index": out["index"].reshape(-1, 3).astype(np.int64),
    }


@pytest.fixture(scope="module")
def figure() -> dict[str, Any]:
    return _arrays()


def _quat_matrix(q: list[float]) -> np.ndarray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def _rotation(axis: list[float], angle: float) -> np.ndarray:
    # Rodrigues' formula
    k = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    cross = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * cross + (1 - math.cos(angle)) * cross @ cross


def _bind_frames(header: dict[str, Any]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    model = dataset.laboratory_model()
    angles = header["bind_angles_deg"]
    frames: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for body in model["bodies"]:
        if body["name"] == "barbell":
            continue
        parent_r, parent_p = frames.get(body["parent"], (np.eye(3), np.zeros(3)))
        r = parent_r @ _quat_matrix(body["quaternion"])
        p = parent_p + parent_r @ np.asarray(body["position_m"])
        for joint in model["joints"]:
            if joint["body"] == body["name"] and joint["name"] in angles:
                r = r @ _rotation(joint["axis"], math.radians(angles[joint["name"]]))
        frames[body["name"]] = (r, p)
    return frames


def test_the_served_figure_is_the_pinned_one() -> None:
    packed = files("dynamisbench.laboratory").joinpath("data", "figure.bin.gz").read_bytes()
    assert hashlib.sha256(gzip.decompress(packed)).hexdigest() == FIGURE_SHA256
    response = TestClient(create_app()).get(f"{API_V1_PREFIX}/laboratory/figure")
    assert response.status_code == 200
    assert response.headers["content-type"] == FIGURE_MEDIA_TYPE
    assert hashlib.sha256(response.content).hexdigest() == FIGURE_SHA256


def test_the_figure_names_the_laboratory_model_and_its_skeleton(figure: dict[str, Any]) -> None:
    header = figure["header"]
    model = dataset.laboratory_model()
    assert header["model_sha256"] == model["model_sha256"]
    athletes = [body for body in model["bodies"] if body["name"] != "barbell"]
    assert [body["name"] for body in header["skeleton"]] == [body["name"] for body in athletes]
    for mine, theirs in zip(header["skeleton"], athletes, strict=True):
        assert mine["parent"] == theirs["parent"]
        assert mine["position_m"] == theirs["position_m"]
        assert mine["quaternion"] == theirs["quaternion"]
    assert "not part of the mechanical model" in header["claim"]


def test_the_bind_pose_is_the_reference_configuration_at_the_bind_angles(
    figure: dict[str, Any],
) -> None:
    header = figure["header"]
    frames = _bind_frames(header)
    assert set(header["bind_angles_deg"]) <= {
        joint["name"] for joint in dataset.laboratory_model()["joints"]
    }
    for bone in header["bones"]:
        r, p = frames[bone["name"]]
        assert np.allclose(bone["bind_position_m"], p, atol=1e-9)
        assert np.allclose(_quat_matrix(bone["bind_quaternion"]), r, atol=1e-9)


def test_the_surface_is_a_closed_oriented_manifold(figure: dict[str, Any]) -> None:
    triangles = figure["index"]
    positions = figure["position"]
    edges = np.sort(
        np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1
    )
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert set(counts.tolist()) == {2}, "every edge has exactly two faces"
    # consistent orientation: every directed edge appears once
    directed = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    assert len(np.unique(directed, axis=0)) == len(directed)
    a, b, c = (positions[triangles[:, i]] for i in range(3))
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    assert areas.min() > 1e-10, "no degenerate triangle"
    volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
    assert volume > 0, "the normals point outward"
    assert np.allclose(np.linalg.norm(figure["normal"], axis=1), 1.0, atol=1e-4)


def test_the_enclosed_volume_is_a_75_kg_body_and_segments_match_their_masses(
    figure: dict[str, Any],
) -> None:
    header = figure["header"]
    triangles = figure["index"]
    a, b, c = (figure["position"][triangles[:, i]] for i in range(3))
    volume_m3 = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
    assert header["mesh_volume_l"] == pytest.approx(volume_m3 * 1000, abs=0.01)
    # The shoes add volume that is not body mass; they are reported, not calibrated.
    shoes_excess = (
        2
        * (header["volumes_l"]["foot"]["figure"] - header["volumes_l"]["foot"]["mass_over_density"])
        / 1000
    )
    density = ATHLETE_MASS_KG / (volume_m3 - shoes_excess)
    assert BODY_DENSITY_RANGE_KG_M3[0] <= density <= BODY_DENSITY_RANGE_KG_M3[1]
    for kind, entry in header["volumes_l"].items():
        if entry["calibrated"]:
            assert entry["figure"] == pytest.approx(entry["mass_over_density"], rel=0.05), kind


def test_the_figure_stands_at_the_declared_stature(figure: dict[str, Any]) -> None:
    z = figure["position"][:, 2]
    assert float(z.max()) == pytest.approx(
        dataset.laboratory_model()["subject"]["stature_m"], abs=0.012
    )


def test_weights_sum_to_one_and_bind_only_kinematic_neighbours(figure: dict[str, Any]) -> None:
    bones = [bone["name"] for bone in figure["header"]["bones"]]
    weights = figure["weights"].astype(int)
    joints = figure["joints"]
    assert np.all(weights.sum(axis=1) == 255)
    assert np.all(joints[weights > 0] < len(bones))
    pairs = set()
    for row_joints, row_weights in zip(joints, weights, strict=True):
        used = sorted({bones[j] for j, w in zip(row_joints, row_weights, strict=True) if w > 0})
        for i, first in enumerate(used):
            for second in used[i + 1 :]:
                pairs.add(frozenset((first, second)))
    # any two bones sharing a vertex are joined through at most one intermediate segment
    chains = {pair for pair in pairs if pair not in KINEMATIC_NEIGHBOURS}
    for pair in chains:
        first, second = sorted(pair)
        assert any(
            frozenset((first, middle)) in KINEMATIC_NEIGHBOURS
            and frozenset((middle, second)) in KINEMATIC_NEIGHBOURS
            for middle in bones
        ), pair


def test_the_outsole_lies_on_the_sole_contact_spheres(figure: dict[str, Any]) -> None:
    header = figure["header"]
    frames = _bind_frames(header)
    model = dataset.laboratory_model()
    radius = model["contact"]["sole_point_radius_m"]
    bones = [bone["name"] for bone in header["bones"]]
    for side in ("l", "r"):
        foot = bones.index(f"foot_{side}")
        mine = (figure["joints"][:, 0] == foot) & (figure["weights"][:, 0] == 255)
        r, p = frames[f"foot_{side}"]
        local = (figure["position"][mine] - p) @ r
        spheres = [g for g in model["geoms"] if g["body"] == f"foot_{side}" and g["role"] == "sole"]
        sole_plane = min(g["position_m"][2] for g in spheres) - radius
        assert float(local[:, 2].min()) == pytest.approx(sole_plane, abs=0.0015)
        # every contact point is under the outsole's footprint
        for g in spheres:
            x, y, _ = g["position_m"]
            near = local[np.abs(local[:, 2] - sole_plane) < 0.004]
            assert np.min(np.hypot(near[:, 0] - x, near[:, 1] - y)) < 0.02, g["name"]


def test_each_fist_closes_around_the_bar_where_the_weld_holds_it(figure: dict[str, Any]) -> None:
    header = figure["header"]
    frames = _bind_frames(header)
    pose = dict(dataset.frame_columns("repetition", "pose"))
    bones = [bone["name"] for bone in header["bones"]]
    for side in ("l", "r"):
        hand = f"hand_{side}"
        hand_p = np.array([pose[f"{hand}.p{c}"][0] for c in "xyz"])
        hand_r = _quat_matrix([pose[f"{hand}.q{c}"][0] for c in "wxyz"])
        bar_p = np.array([pose[f"barbell.p{c}"][0] for c in "xyz"])
        bar_axis = _quat_matrix([pose[f"barbell.q{c}"][0] for c in "wxyz"]) @ np.array(
            [0.0, 1.0, 0.0]
        )
        centre = hand_r.T @ (bar_p - hand_p)
        axis = hand_r.T @ bar_axis
        r, p = frames[hand]
        mine = figure["joints"][:, 0] == bones.index(hand)
        local = (figure["position"][mine] - p) @ r
        d = local - centre
        s = d @ axis
        radial = np.linalg.norm(d - np.outer(s, axis), axis=1)
        # within the fist's width along the bar, the skin surrounds it at 1.4-4 cm from its axis
        inside = np.abs(s - np.median(s)) < 0.03
        assert radial[inside].min() > 0.014 * 0.9
        angles = np.arctan2(
            *(
                np.stack(
                    [
                        d[inside] @ np.cross(axis, [1, 0, 0]),
                        d[inside] @ np.cross(axis, np.cross(axis, [1, 0, 0])),
                    ]
                )
            )
        )
        assert np.ptp(np.unwrap(np.sort(angles))) > 1.5 * math.pi, "the grip wraps around the bar"


def test_garments_form_a_plausible_athlete(figure: dict[str, Any]) -> None:
    garment = figure["garment"]
    z = figure["position"][:, 2]
    shirt, shorts, shoe, sole, hair = (garment[:, i] > 0 for i in range(5))
    assert np.median(z[shirt]) > 1.1 and np.median(z[shorts]) == pytest.approx(0.85, abs=0.12)
    assert z[shoe].max() < 0.16 and z[sole].max() < 0.06
    assert z[hair].min() > 1.55
    assert json.dumps(figure["header"]["garments"]) == json.dumps(
        ["shirt", "shorts", "shoe", "sole", "hair"]
    )


@pytest.mark.skipif(
    __import__("os").environ.get("DYNAMISBENCH_FIGURE_REGENERATION") != "1",
    reason=(
        "regenerating the figure takes about three minutes; set "
        "DYNAMISBENCH_FIGURE_REGENERATION=1 (or run tools/mujoco_squat_figure.py --check)"
    ),
)
def test_the_packaged_figure_is_the_regenerated_one() -> None:
    generator = cast(
        Any,
        pytest.importorskip(
            "tools.mujoco_squat_figure",
            reason="the MuJoCo figure generator is integrated in the M2 execution slice",
        ),
    )

    assert hashlib.sha256(generator.encode(generator.build())).hexdigest() == FIGURE_SHA256
