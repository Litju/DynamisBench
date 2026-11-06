"""The packaged laboratory dataset and its read-only API publication.

Engine-free: these tests read the packaged bytes, exercise the routes in process and decode the
Arrow frames. The dataset's regeneration from the worker is qualified separately, with the real
engine, in ``tests/execution/mujoco_squat``.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
import sys
from importlib.resources import files
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api.app import create_app
from dynamisbench.laboratory import (
    MANIFEST_SHA256,
    LaboratoryDataError,
    dataset,
    frame_columns,
    laboratory_index,
    laboratory_model,
    recording_view,
)
from dynamisbench.transport.arrow import (
    ARROW_IPC_STREAM_CONTENT_TYPE,
    ArrowTransportError,
    encode_float_columns,
    read_ipc_stream,
)

NOMINAL_TRAJECTORY = "d3b4edafc090b1b1dca76f2af04343febdec9f9a0ff3d02b8e8d54d2aaef678b"
"""The repetition's trajectory hash: the physics the squat qualification suite verifies."""


def _squat_authority() -> tuple[Any, Any]:
    """Load the M2-only execution authority when that source slice is present."""
    authority = cast(
        Any,
        pytest.importorskip(
            "dynamisbench.adapters.mujoco.squat",
            reason="squat execution authority is integrated in M2, not the read-only M1 slice",
        ),
    )
    return authority.anthropometry, authority.criteria


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_the_manifest_is_the_pinned_one_and_pins_every_file() -> None:
    data = files("dynamisbench.laboratory").joinpath("data")
    manifest = data.joinpath("manifest.json").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == MANIFEST_SHA256
    import json

    listed = json.loads(manifest)["files"]
    assert set(listed) == {
        "model.json",
        "recordings/repetition.json.gz",
        "recordings/repetition-half-timestep.json.gz",
        "recordings/ablation-no-internal-model.json.gz",
        "recordings/ablation-soft-friction.json.gz",
    }
    for relative, digest in listed.items():
        assert hashlib.sha256(data.joinpath(relative).read_bytes()).hexdigest() == digest


def test_an_altered_file_is_refused_not_served(monkeypatch: pytest.MonkeyPatch) -> None:
    original = dataset._read

    def tampered(relative: str) -> bytes:
        content = original(relative)
        return content + b" " if relative == "model.json" else content

    monkeypatch.setattr(dataset, "_read", tampered)
    dataset.laboratory_model.cache_clear()
    try:
        with pytest.raises(LaboratoryDataError, match="altered"):
            laboratory_model()
    finally:
        dataset.laboratory_model.cache_clear()


def test_the_index_publishes_the_four_recordings_and_the_claim() -> None:
    index = laboratory_index()
    assert index["dataset_id"] == "laboratory/1"
    assert "not sealed DynamisBench evidence" in index["claim"]
    assert index["generated_with"]["engine_version"] == "3.17.0"
    kinds = {entry["recording_id"]: entry["kind"] for entry in index["recordings"]}
    assert kinds == {
        "repetition": "nominal",
        "repetition-half-timestep": "timestep-companion",
        "ablation-no-internal-model": "ablation",
        "ablation-soft-friction": "ablation",
    }


def test_the_nominal_recording_is_the_qualified_physics_and_passes_every_check() -> None:
    _, criteria = _squat_authority()
    view = recording_view("repetition")
    assert view["trajectory_sha256"] == NOMINAL_TRAJECTORY
    assert view["completed"]
    assert [check["status"] for check in view["checks"]] == ["pass"] * len(criteria.CRITERIA)
    assert [event["phase"] for event in view["command_events"]] == [
        "standing",
        "descent",
        "bottom",
        "ascent",
        "return",
    ]


def test_the_ablations_fail_exactly_the_checks_that_expose_them() -> None:
    def failed(recording_id: str) -> set[str]:
        return {
            check["criterion_id"]
            for check in recording_view(recording_id)["checks"]
            if check["status"] == "fail"
        }

    no_model = failed("ablation-no-internal-model")
    assert {"heel", "loaded", "plan-grf"} <= no_model  # heels lift; GRF departs from the plan
    assert "slip" in failed("ablation-soft-friction")  # feet slide
    assert "slip" not in no_model and "heel" not in failed("ablation-soft-friction")
    companion = recording_view("repetition-half-timestep")["checks"]
    assert {check["status"] for check in companion if check["group"] == "Numerics"} == {
        "not_evaluated"
    }


def test_frame_columns_are_synchronized_and_physical() -> None:
    anthropometry, _ = _squat_authority()
    pose = dict(frame_columns("repetition", "pose"))
    kinematics = dict(frame_columns("repetition", "kinematics"))
    kinetics = dict(frame_columns("repetition", "kinetics"))
    count = recording_view("repetition")["frame_count"]
    for group in (pose, kinematics, kinetics):
        assert all(len(values) == count for values in group.values())
    assert pose["t"] == [round(index * 0.01, 9) for index in range(count)]
    for body in recording_view("repetition")["body_names"]:
        for i in range(0, count, 50):
            norm = math.sqrt(
                sum(pose[f"{body}.{axis}"][i] ** 2 for axis in ("qw", "qx", "qy", "qz"))
            )
            assert norm == pytest.approx(1.0, abs=1e-5)
    # The feet stay on the floor: the ankle height of the standing model throughout.
    ankle = anthropometry.geometry().ankle_height
    for side in ("l", "r"):
        assert max(abs(z - ankle) for z in pose[f"foot_{side}.pz"]) < 0.003
    # Kinetics columns are the measured loads: ten plantar points sum to the vertical GRF.
    for i in range(0, count, 25):
        points = sum(values[i] for name, values in kinetics.items() if name.endswith(".normal_n"))
        vertical = kinetics["grf_left.z"][i] + kinetics["grf_right.z"][i]
        assert points == pytest.approx(vertical, rel=1e-5)
        # Each foot's centre of pressure lies under that foot, between its heel and toe points.
        for side in ("l", "r"):
            xs = [kinetics[f"contact.{side}_{p}.x"][i] for p in ("heel_medial", "hallux")]
            assert min(xs) <= kinetics[f"cop_{'left' if side == 'l' else 'right'}.x"][i] <= max(xs)
    assert max(kinematics["knee_flexion_l.angle_deg"]) == pytest.approx(120.1, abs=0.1)


def test_the_published_model_is_the_compiled_squat_model() -> None:
    anthropometry, _ = _squat_authority()
    model = laboratory_model()
    assert model["total_mass_kg"] == pytest.approx(95.0, abs=1e-9)
    assert len(model["joints"]) == len(anthropometry.joint_specs())
    capacities = {spec.name: spec.torque_nm for spec in anthropometry.joint_specs()}
    for joint in model["joints"]:
        assert tuple(joint["torque_capacity_nm"]) == pytest.approx(capacities[joint["name"]])
    roles = {geom["role"] for geom in model["geoms"]}
    assert roles == {"floor", "barbell", "sole", "visual", "segment"}
    assert sum(1 for geom in model["geoms"] if geom["role"] == "sole") == 10
    # What the workbench needs to draw and label the model without re-deriving it.
    assert model["gravity_m_s2"] == pytest.approx(anthropometry.GRAVITY_M_S2)
    assert model["subject"] == {
        "body_mass_kg": anthropometry.BODY_MASS_KG,
        "stature_m": anthropometry.STATURE_M,
        "barbell_mass_kg": anthropometry.BARBELL.mass,
        "grip_half_width_m": anthropometry.BARBELL.grip_half_width,
    }
    assert model["contact"]["loaded_threshold_n"] == 5.0
    assert model["integrator"] == "implicitfast"
    # Every joint anchor is its child body's origin (the proximal joint centre).
    assert all(joint["position_m"] == [0, 0, 0] for joint in model["joints"])


def test_the_routes_publish_typed_read_models(client: TestClient) -> None:
    index = client.get("/api/v1/laboratory")
    assert index.status_code == 200
    assert index.json()["manifest_sha256"] == MANIFEST_SHA256
    model = client.get("/api/v1/laboratory/model")
    assert model.status_code == 200 and len(model.json()["geoms"]) == 33
    assert model.json()["subject"]["stature_m"] == 1.75
    assert model.json()["joints"][0]["position_m"] == [0.0, 0.0, 0.0]
    recording = client.get("/api/v1/laboratory/recordings/ablation-no-internal-model")
    assert recording.status_code == 200
    body = recording.json()
    assert body["kind"] == "ablation"
    assert set(body["frame_groups"]) == {"pose", "kinematics", "kinetics"}
    assert body["phase_spans"][0]["phase"] == "standing"


@pytest.mark.parametrize("group", ["pose", "kinematics", "kinetics"])
def test_frames_travel_as_arrow_and_decode_to_the_packaged_columns(
    client: TestClient, group: str
) -> None:
    response = client.get(f"/api/v1/laboratory/recordings/repetition/frames/{group}")
    assert response.status_code == 200
    assert response.headers["content-type"] == ARROW_IPC_STREAM_CONTENT_TYPE
    table = read_ipc_stream(response.content)
    columns = frame_columns("repetition", group)
    assert [field.name for field in table.fields] == [name for name, _values in columns]
    assert table.num_rows == len(columns[0][1])
    assert table.rows[100][columns[1][0]] == columns[1][1][100]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/laboratory/recordings/unknown",
        "/api/v1/laboratory/recordings/unknown/frames/pose",
        "/api/v1/laboratory/recordings/repetition/frames/unknown",
    ],
)
def test_unknown_recordings_and_groups_are_not_found(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("verb", ["post", "put", "delete"])
def test_the_laboratory_cannot_be_written_or_run(client: TestClient, verb: str) -> None:
    response = getattr(client, verb)("/api/v1/laboratory")
    assert response.status_code == 405


def test_importing_the_api_loads_no_engine_numpy_or_arrow() -> None:
    probe = (
        "import sys, dynamisbench.api, dynamisbench.api.app, dynamisbench.laboratory\n"
        "print(' '.join(m for m in ('mujoco','numpy','pyarrow','dynamisbench.transport',"
        "'dynamisbench.adapters.mujoco') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_the_float_column_encoder_is_bounded() -> None:
    with pytest.raises(ArrowTransportError):
        encode_float_columns([])
    with pytest.raises(ArrowTransportError):
        encode_float_columns([("a", [1.0, 2.0]), ("b", [1.0])])
    with pytest.raises(ArrowTransportError):
        encode_float_columns([("a", [1.0]), ("a", [2.0])])
    with pytest.raises(ArrowTransportError):
        encode_float_columns([("a", [float("nan")])])
    with pytest.raises(ArrowTransportError):
        encode_float_columns([(f"c{i}", [0.5] * 20_000) for i in range(10)])  # > 1 MiB
    payload = encode_float_columns([("t", [0.0, 0.01]), ("x", [1.5, -2.5])])
    assert payload == encode_float_columns([("t", [0.0, 0.01]), ("x", [1.5, -2.5])])
    assert read_ipc_stream(payload).rows == ({"t": 0.0, "x": 1.5}, {"t": 0.01, "x": -2.5})


def test_criteria_report_not_evaluated_when_a_value_is_absent() -> None:
    _, criteria = _squat_authority()
    view = recording_view("repetition")
    record = {
        "extrema": view["extrema"],
        "summary": view["summary"],
        "work": view["work"],
        "numerics": None,
    }
    statuses = {item["criterion_id"]: item["status"] for item in criteria.evaluate(record)}
    assert statuses["timestep"] == "not_evaluated"
    assert statuses["slip"] == "pass"
    record["extrema"] = {**view["extrema"], "max_sole_point_slip_m": 0.01}
    assert {i["criterion_id"]: i["status"] for i in criteria.evaluate(record)}["slip"] == "fail"
