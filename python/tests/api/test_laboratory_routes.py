"""The M1 Laboratory publishes only the authenticated, pinned diagnostic dataset."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api.session import secured_application
from tests.api.factories import CREDENTIAL, session_configuration

FIGURE_MEDIA_TYPE = "application/vnd.dynamisbench.figure"
ARROW_MEDIA_TYPE = "application/vnd.apache.arrow.stream"
MAX_FIGURE_BYTES = 8 * 1024 * 1024
MAX_FRAME_BYTES = 1 * 1024 * 1024


@pytest.fixture
def client() -> Iterator[TestClient]:
    configuration = session_configuration()
    with TestClient(secured_application(configuration.credential, configuration.origins)) as opened:
        yield opened


@pytest.fixture
def authorization() -> dict[str, str]:
    return {"Authorization": f"Bearer {CREDENTIAL}"}


def test_laboratory_requires_the_existing_session_credential(client: TestClient) -> None:
    assert client.get("/api/v1/laboratory").status_code == 401


def test_index_and_model_are_published_as_read_only_plain_data(
    client: TestClient, authorization: dict[str, str]
) -> None:
    index = client.get("/api/v1/laboratory", headers=authorization)
    assert index.status_code == 200
    body = index.json()
    assert body["dataset_id"] == "laboratory/1"
    assert "not validated against measured human motion" in body["claim"].casefold()
    assert {entry["recording_id"] for entry in body["recordings"]} == {
        "repetition",
        "repetition-half-timestep",
        "ablation-no-internal-model",
        "ablation-soft-friction",
    }

    model = client.get("/api/v1/laboratory/model", headers=authorization)
    assert model.status_code == 200
    assert model.json()["model_sha256"] == body["generated_with"]["model_sha256"]
    assert model.json()["subject"]["body_mass_kg"] == 75.0


def test_recording_frames_and_figure_are_pinned_bounded_read_models(
    client: TestClient, authorization: dict[str, str]
) -> None:
    recording = client.get("/api/v1/laboratory/recordings/repetition", headers=authorization)
    assert recording.status_code == 200
    assert recording.json()["kind"] == "nominal"
    assert recording.json()["completed"] is True

    frames = client.get(
        "/api/v1/laboratory/recordings/repetition/frames/pose", headers=authorization
    )
    assert frames.status_code == 200
    assert frames.headers["content-type"].split(";")[0] == ARROW_MEDIA_TYPE
    assert 0 < len(frames.content) <= MAX_FRAME_BYTES

    figure = client.get("/api/v1/laboratory/figure", headers=authorization)
    assert figure.status_code == 200
    assert figure.headers["content-type"].split(";")[0] == FIGURE_MEDIA_TYPE
    assert 0 < len(figure.content) <= MAX_FIGURE_BYTES
    assert figure.content.startswith(b"DBFIGUR1")


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/laboratory/recordings/not-a-recording",
        "/api/v1/laboratory/recordings/repetition/frames/not-a-group",
    ),
)
def test_unknown_packaged_data_is_a_bounded_not_found(
    client: TestClient, authorization: dict[str, str], path: str
) -> None:
    assert client.get(path, headers=authorization).status_code == 404


def test_workspace_run_routes_are_not_exposed_in_the_read_only_m1_api(
    client: TestClient, authorization: dict[str, str]
) -> None:
    assert client.get("/api/v1/workspaces/opaque/studies", headers=authorization).status_code == 404
    assert client.post("/api/v1/workspaces/opaque/runs", headers=authorization).status_code == 404
