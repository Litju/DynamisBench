"""Reproducible implementation identity of the MuJoCo reference adapter.

The worker adapter identity carried by the accepted protocol has an optional
``implementation_digest``. For a real engine adapter that field is not decoration: it is how
the supervisor's selected environment identity is bound to the source, model bytes, engine
version, Python version and platform that will actually execute. This module computes that
identity from the installed adapter itself.

The identity is a SHA-256 over the RFC 8785 canonical bytes of one JSON object. The object
lists every production adapter file with its own raw-byte SHA-256, plus the reviewed model
digest, engine version, Python version and platform. It is deliberately non-self-referential:
the digest is not embedded in the object it hashes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from dynamisbench.adapters.mujoco import reference
from dynamisbench.execution.contracts import WORKER_PROTOCOL_VERSION
from dynamisbench.identity import canonical_semantic_bytes

__all__ = [
    "ImplementationIdentity",
    "build_implementation_identity",
]


@dataclass(frozen=True, slots=True)
class ImplementationIdentity:
    """One computed adapter identity and the canonical payload it hashes."""

    payload: dict[str, Any]
    digest: str

    def as_json_object(self) -> dict[str, Any]:
        """The qualification-interface object, including the computed digest."""
        return {**self.payload, "implementation_digest": self.digest}


def _source_manifest() -> list[dict[str, str]]:
    """Hash every production adapter file, in sorted relative-path order.

    The model is included here as well as in ``model_sha256`` because it is a production
    input whose bytes change the adapter's behavior. The explicit file list is owned by
    :mod:`dynamisbench.adapters.mujoco.reference`; a new production file is a reviewed
    addition rather than an automatic directory walk.
    """
    root = files("dynamisbench.adapters.mujoco")
    manifest: list[dict[str, str]] = []
    for relative_path in sorted(reference.ADAPTER_SOURCE_FILES):
        content = root.joinpath(relative_path).read_bytes()
        manifest.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return manifest


def build_implementation_identity(
    *,
    engine_version: str,
    python_version: str,
    platform_tag: str,
) -> ImplementationIdentity:
    """Compute the adapter identity from the installed files and the running environment.

    ``engine_version`` is supplied by the physics layer after importing MuJoCo, so this
    module remains importable without the engine. ``python_version`` and ``platform_tag``
    are supplied by the worker for the same reason, and because the identity must describe
    the process that will execute rather than a declaration.
    """
    reference.model_bytes()  # verify the reviewed model before identifying the adapter
    payload: dict[str, Any] = {
        "schema": reference.IMPLEMENTATION_IDENTITY_SCHEMA,
        "adapter_id": reference.ADAPTER_ID,
        "adapter_version": reference.ADAPTER_VERSION,
        "engine": reference.ENGINE,
        "engine_version": engine_version,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "capabilities": sorted(capability.value for capability in reference.CAPABILITIES),
        "platform": platform_tag,
        "python_version": python_version,
        "model_sha256": reference.MODEL_SHA256,
        "source_manifest": _source_manifest(),
    }
    digest = hashlib.sha256(canonical_semantic_bytes(payload)).hexdigest()
    return ImplementationIdentity(payload=payload, digest=digest)
