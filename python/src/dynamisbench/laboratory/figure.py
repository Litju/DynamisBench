"""The laboratory's anatomical figure: a pinned, integrity-checked presentation asset.

``data/figure.bin.gz`` is generated offline by ``python/tools/mujoco_squat_figure.py`` from the
laboratory model (its skeleton, landmarks and segment masses) and the nominal recording's
hand–bar relation. It is a skinned surface the workbench deforms with *recorded* body poses —
nothing in it is simulated, and it has no role in the mechanics.

This module only reads it: the decompressed figure stream must have the pinned digest
:data:`FIGURE_SHA256`, start with the format's magic and carry a header that names the model the
dataset publishes. Anything else is refused with :class:`LaboratoryDataError`. It imports no
NumPy and never builds a figure.
"""

from __future__ import annotations

import functools
import gzip
import hashlib
import json
from importlib.resources import files
from typing import Any, Final

from dynamisbench.laboratory.dataset import LaboratoryDataError, laboratory_model

__all__ = [
    "FIGURE_MEDIA_TYPE",
    "FIGURE_SCHEMA",
    "FIGURE_SHA256",
    "figure_bytes",
    "figure_header",
]

FIGURE_SCHEMA: Final = "dynamisbench.laboratory.figure/1"
FIGURE_MEDIA_TYPE: Final = "application/vnd.dynamisbench.figure"
FIGURE_MAGIC: Final = b"DBFIGUR1"
FIGURE_SHA256: Final = "d515469d0e69582ca74a8a490cbc04f908f5fbc2eda27b32e9a440ccc4cc6ed5"
"""SHA-256 of the uncompressed figure stream. A changed pin is a reviewed asset change."""

_PACKAGE: Final = "dynamisbench.laboratory"


@functools.cache
def figure_bytes() -> bytes:
    """The verified figure stream (magic, header, aligned arrays)."""
    try:
        packed = files(_PACKAGE).joinpath("data", "figure.bin.gz").read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise LaboratoryDataError("the laboratory figure is unavailable") from error
    try:
        content = gzip.decompress(packed)
    except (OSError, EOFError) as error:
        raise LaboratoryDataError("the laboratory figure is not a gzip stream") from error
    digest = hashlib.sha256(content).hexdigest()
    if digest != FIGURE_SHA256:
        raise LaboratoryDataError(
            f"the laboratory figure digest {digest} is not the reviewed {FIGURE_SHA256}"
        )
    header = _parse_header(content)
    if header.get("model_sha256") != laboratory_model()["model_sha256"]:
        raise LaboratoryDataError("the laboratory figure was derived from another model")
    return content


def _parse_header(content: bytes) -> dict[str, Any]:
    if not content.startswith(FIGURE_MAGIC) or len(content) < 12:
        raise LaboratoryDataError("the laboratory figure is not a figure stream")
    length = int.from_bytes(content[8:12], "little")
    try:
        header = json.loads(content[12 : 12 + length])
    except ValueError as error:
        raise LaboratoryDataError("the laboratory figure header is not JSON") from error
    if not isinstance(header, dict) or header.get("schema") != FIGURE_SCHEMA:
        raise LaboratoryDataError("the laboratory figure header is not the expected schema")
    return header


@functools.cache
def figure_header() -> dict[str, Any]:
    """The figure's header: provenance, skeleton, bones, volumes, counts and section layout."""
    return _parse_header(figure_bytes())
