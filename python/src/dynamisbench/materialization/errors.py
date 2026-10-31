"""Bounded refusals for content-addressed execution-input materialization.

DB-3.3A fails closed. A definition that does not match the RunSpec, an asset that
does not match its declared digest, a path that leaves the source root, a store
object that exists with different bytes, or an unsupported SUT interface is a
refusal — never a best-effort materialization.

The codes are a closed vocabulary so a caller, an operator and a later review can
compare refusals without parsing prose. Messages are bounded and never include an
absolute path: the materializer knows machine locations, but a refusal does not need
to hand them to a reader.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

MAX_REFUSAL_MESSAGE_LENGTH: Final = 256


class MaterializationRefusalCode(StrEnum):
    """Every reason this package may refuse to materialize one execution input set."""

    INPUT_DEFINITION_MISMATCH = "input_definition_mismatch"
    INPUT_MANIFEST_MISMATCH = "input_manifest_mismatch"
    INPUT_OBJECT_MISSING = "input_object_missing"
    INPUT_OBJECT_CORRUPT = "input_object_corrupt"
    INPUT_LIMIT_EXCEEDED = "input_limit_exceeded"
    INPUT_LINK_REFUSED = "input_link_refused"
    INPUT_PATH_REFUSED = "input_path_refused"
    INPUT_SOURCE_CHANGED = "input_source_changed"
    INPUT_SET_INCOMPLETE = "input_set_incomplete"
    INPUT_SET_UNEXPECTED = "input_set_unexpected"
    SUT_EXECUTABLE_CLOSURE_UNSUPPORTED = "sut_executable_closure_unsupported"
    STORE_PUBLICATION_FAILED = "store_publication_failed"


class MaterializationError(Exception):
    """One bounded refusal from the materialization boundary."""

    def __init__(self, code: MaterializationRefusalCode, message: str) -> None:
        if not message:
            raise ValueError("a materialization refusal must state a reason")
        if len(message) > MAX_REFUSAL_MESSAGE_LENGTH:
            message = message[: MAX_REFUSAL_MESSAGE_LENGTH - 3].rstrip() + "..."
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"


__all__ = [
    "MAX_REFUSAL_MESSAGE_LENGTH",
    "MaterializationError",
    "MaterializationRefusalCode",
]
