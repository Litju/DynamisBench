"""The read-only laboratory routes: publish the packaged laboratory dataset, and nothing else.

``GET /laboratory``, ``/laboratory/model``, ``/laboratory/recordings/{id}`` answer with JSON
read models; ``/laboratory/recordings/{id}/frames/{group}`` answers with an Arrow IPC stream,
the bulk-numeric transport (ADR-019). Every byte comes from :mod:`dynamisbench.laboratory`,
which verifies the packaged files against their pinned digests on read.

What these routes never do: run, resume or parameterise a simulation (ADR-017), accept a path
or file name, or import an engine. A recording is a diagnostic record of a model run, not
sealed evidence; the read models say so in the ``claim`` they carry.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from dynamisbench.api.errors import ROUTE_ERROR_RESPONSES, ErrorResponse, refusal_responses
from dynamisbench.api.models import ApiModel
from dynamisbench.laboratory import (
    FRAME_GROUPS,
    LaboratoryDataError,
    frame_columns,
    laboratory_index,
    laboratory_model,
    recording_view,
)

__all__ = [
    "LaboratoryIndexResponse",
    "LaboratoryModelResponse",
    "LaboratoryRecordingResponse",
    "RECORDING_NOT_FOUND",
    "laboratory_router",
]

RECORDING_NOT_FOUND: Final = "The laboratory has no such recording or frame group."

laboratory_router = APIRouter()


class LaboratoryRecordingEntry(ApiModel):
    recording_id: str
    label: str
    kind: Literal["nominal", "timestep-companion", "ablation", "run"]
    description: str
    timestep_s: float
    duration_s: float
    frame_count: int
    trajectory_sha256: str
    completed: bool
    checks_passed: int
    checks_failed: int
    checks_not_evaluated: int


class LaboratoryIndexResponse(ApiModel):
    dataset_schema: str
    dataset_id: str
    manifest_sha256: str
    generated_with: dict[str, str]
    claim: str
    plan: dict[str, float]
    recordings: tuple[LaboratoryRecordingEntry, ...]


class LaboratoryBody(ApiModel):
    name: str
    parent: str
    mass_kg: float
    com_m: tuple[float, float, float]
    principal_inertia_kg_m2: tuple[float, float, float]
    position_m: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]


class LaboratoryGeom(ApiModel):
    name: str
    body: str
    type: Literal["sphere", "capsule", "ellipsoid", "cylinder", "box", "plane", "other"]
    size_m: tuple[float, float, float]
    position_m: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]
    role: Literal["floor", "barbell", "sole", "visual", "segment"]


class LaboratoryJoint(ApiModel):
    name: str
    body: str
    axis: tuple[float, float, float]
    range_deg: tuple[float, float]
    torque_capacity_nm: tuple[float, float]
    damping_n_m_s: float
    position_m: tuple[float, float, float]


class LaboratorySubject(ApiModel):
    body_mass_kg: float
    stature_m: float
    barbell_mass_kg: float
    grip_half_width_m: float


class LaboratoryContact(ApiModel):
    sole_point_radius_m: float
    friction: tuple[float, float, float]
    normal_time_constant_s: float
    friction_time_constant_s: float
    loaded_threshold_n: float


class LaboratoryModelResponse(ApiModel):
    model_sha256: str
    counts: dict[str, int]
    total_mass_kg: float
    bodies: tuple[LaboratoryBody, ...]
    geoms: tuple[LaboratoryGeom, ...]
    joints: tuple[LaboratoryJoint, ...]
    sole_points: tuple[str, ...]
    timestep_s: float
    integrator: str
    gravity_m_s2: float
    subject: LaboratorySubject
    contact: LaboratoryContact


class LaboratoryEvent(ApiModel):
    phase: str
    t: float


class LaboratoryPhaseSpan(ApiModel):
    phase: str
    start_s: float
    end_s: float


class LaboratoryCheck(ApiModel):
    criterion_id: str
    group: str
    label: str
    unit: str
    bound: str
    rationale: str
    value: float | None
    status: Literal["pass", "fail", "not_evaluated"]


class LaboratoryRecordingResponse(ApiModel):
    recording_id: str
    label: str
    kind: Literal["nominal", "timestep-companion", "ablation", "run"]
    description: str
    timestep_s: float
    duration_s: float
    steps: int
    completed: bool
    failure: str
    trajectory_sha256: str
    command_events: tuple[LaboratoryEvent, ...]
    phase_spans: tuple[LaboratoryPhaseSpan, ...]
    summary: dict[str, Any]
    extrema: dict[str, float]
    work: dict[str, dict[str, float]]
    numerics: dict[str, float]
    checks: tuple[LaboratoryCheck, ...]
    frame_count: int
    sample_period_s: float
    body_names: tuple[str, ...]
    frame_groups: dict[str, tuple[str, ...]]


_NOT_FOUND_RESPONSES: Final = refusal_responses(
    {404: {"model": ErrorResponse, "description": RECORDING_NOT_FOUND}}
)


@laboratory_router.get(
    "/laboratory", response_model=LaboratoryIndexResponse, responses=ROUTE_ERROR_RESPONSES
)
def read_laboratory() -> LaboratoryIndexResponse:
    """The dataset's identity, its claim and the recordings it publishes."""
    index = laboratory_index()
    return LaboratoryIndexResponse(
        dataset_schema=index["schema"],
        dataset_id=index["dataset_id"],
        manifest_sha256=index["manifest_sha256"],
        generated_with=index["generated_with"],
        claim=index["claim"],
        plan=index["plan"],
        recordings=tuple(LaboratoryRecordingEntry(**entry) for entry in index["recordings"]),
    )


@laboratory_router.get(
    "/laboratory/model", response_model=LaboratoryModelResponse, responses=ROUTE_ERROR_RESPONSES
)
def read_laboratory_model() -> LaboratoryModelResponse:
    """The compiled model the recordings were integrated with, as plain data."""
    return LaboratoryModelResponse(**laboratory_model())


@laboratory_router.get(
    "/laboratory/recordings/{recording_id}",
    response_model=LaboratoryRecordingResponse,
    responses=_NOT_FOUND_RESPONSES,
)
def read_laboratory_recording(recording_id: str) -> LaboratoryRecordingResponse:
    """One recording's metadata, summary, work ledger, checks and frame catalogue."""
    try:
        view = recording_view(recording_id)
    except LaboratoryDataError as error:
        if "no recording" in str(error):
            raise HTTPException(status_code=404, detail=RECORDING_NOT_FOUND) from None
        raise
    return LaboratoryRecordingResponse(**{**view, "failure": view["failure"] or ""})


@laboratory_router.get(
    "/laboratory/recordings/{recording_id}/frames/{group}",
    responses={
        200: {"content": {"application/vnd.apache.arrow.stream": {}}},
        **_NOT_FOUND_RESPONSES,
    },
)
def read_laboratory_frames(recording_id: str, group: str) -> Response:
    """One frame group of a recording as an Arrow IPC stream (``t`` first, then columns)."""
    if group not in FRAME_GROUPS:
        raise HTTPException(status_code=404, detail=RECORDING_NOT_FOUND)
    try:
        columns = frame_columns(recording_id, group)
    except LaboratoryDataError as error:
        if "no recording" in str(error):
            raise HTTPException(status_code=404, detail=RECORDING_NOT_FOUND) from None
        raise
    # Imported here so that importing the API loads no columnar stack; the session has already
    # loaded it on its main thread (``api.server.serve``), and the encoder reaches it only
    # through the thread-safe loader in ``transport.columnar``.
    from dynamisbench.transport.arrow import ARROW_IPC_STREAM_CONTENT_TYPE, encode_float_columns

    payload = encode_float_columns(columns)
    return Response(content=payload, media_type=ARROW_IPC_STREAM_CONTENT_TYPE)


@laboratory_router.get(
    "/laboratory/figure",
    responses={
        200: {"content": {"application/vnd.dynamisbench.figure": {}}},
        **ROUTE_ERROR_RESPONSES,
    },
)
def read_laboratory_figure() -> Response:
    """The anatomical figure: a skinned presentation surface for the model (pinned asset).

    Derived offline from the model's skeleton, landmarks and segment masses; deformed in the
    workbench by recorded body poses only. It has no role in the mechanics.
    """
    from dynamisbench.laboratory.figure import FIGURE_MEDIA_TYPE, figure_bytes

    return Response(content=figure_bytes(), media_type=FIGURE_MEDIA_TYPE)
