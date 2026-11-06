"""Published laboratory recordings: read-only access to the packaged laboratory dataset.

The laboratory dataset is generated offline in the isolated MuJoCo worker
(``python/tools/mujoco_squat_laboratory.py``) and packaged here, content-addressed by a pinned
manifest digest. This module only *reads* it: it verifies every file against the manifest and
serves typed views to the application API. It imports no simulator, no NumPy and no Arrow, and
it never produces a recording.

A laboratory recording is a diagnostic record of a model run. It is not sealed DynamisBench
evidence, not canonical output and not an assessment.
"""

from __future__ import annotations

from dynamisbench.laboratory.dataset import (
    DATASET_ID,
    DATASET_SCHEMA,
    FRAME_GROUPS,
    MANIFEST_SHA256,
    LaboratoryDataError,
    frame_columns,
    laboratory_index,
    laboratory_model,
    recording_view,
)

__all__ = [
    "DATASET_ID",
    "DATASET_SCHEMA",
    "FRAME_GROUPS",
    "MANIFEST_SHA256",
    "LaboratoryDataError",
    "frame_columns",
    "laboratory_index",
    "laboratory_model",
    "recording_view",
]
