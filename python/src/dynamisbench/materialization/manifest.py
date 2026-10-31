"""Canonical bytes, digest and strict read-back for an ``InputManifest``.

The manifest digest is a *derived integrity identity* (ADR-026). It is not a
semantic digest of a single definition, not an asset digest, and not an execution
fingerprint. It is the SHA-256 of the RFC 8785 canonical manifest bytes, so a reader
can recompute it without a second serializer.

Reading is intentionally stricter than parsing: non-canonical bytes are refused even
when they decode to the same object. Otherwise two byte strings with one meaning
would both appear to be the stored manifest, and the store would have two apparent
identities for one input set.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from dynamisbench.domain.spec.identifiers import Sha256Hex
from dynamisbench.identity import DigestAlgorithm, canonical_semantic_bytes
from dynamisbench.materialization.errors import (
    MaterializationError,
    MaterializationRefusalCode,
)
from dynamisbench.materialization.schema import (
    MAX_MANIFEST_BYTES,
    InputManifest,
)


class InputManifestDigest(BaseModel):
    """The SHA-256 of the canonical bytes of one ``InputManifest``.

    A distinct type from :class:`~dynamisbench.identity.SemanticDigest`,
    :class:`~dynamisbench.identity.AssetDigest` and
    :class:`~dynamisbench.planning.ExecutionFingerprint`: it identifies a
    materialized input set, not a single definition, a byte artifact or an
    execution request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal[DigestAlgorithm.SHA256] = DigestAlgorithm.SHA256
    hex: Sha256Hex


def canonical_input_manifest_bytes(manifest: InputManifest) -> bytes:
    """Return the RFC 8785 canonical bytes of ``manifest``.

    :raises MaterializationError: if the canonical manifest exceeds the declared
        manifest-byte bound.
    """
    canonical = canonical_semantic_bytes(manifest)
    if len(canonical) > MAX_MANIFEST_BYTES:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"the canonical input manifest is larger than the {MAX_MANIFEST_BYTES}-byte limit",
        )
    return canonical


def input_manifest_digest(manifest: InputManifest) -> InputManifestDigest:
    """Return the digest of the canonical bytes of ``manifest``."""
    canonical = canonical_input_manifest_bytes(manifest)
    return InputManifestDigest(hex=hashlib.sha256(canonical).hexdigest())


def parse_input_manifest(data: bytes) -> InputManifest:
    """Parse and verify one stored manifest byte string.

    The bytes must be the exact canonical form. A JSON document with the same
    meaning but different whitespace, property order or array order is refused; the
    store has one byte identity per manifest, and accepting a second spelling would
    make the digest ambiguous.

    :raises MaterializationError: for malformed JSON, schema violations, or
        non-canonical bytes.
    """
    if len(data) > MAX_MANIFEST_BYTES:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"the stored input manifest is larger than the {MAX_MANIFEST_BYTES}-byte limit",
        )
    try:
        manifest = InputManifest.model_validate_json(data)
    except ValidationError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
            f"the stored input manifest is not a valid DB-3.3A manifest: {error}",
        ) from error
    if canonical_input_manifest_bytes(manifest) != data:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
            "the stored input manifest is not in canonical RFC 8785 form",
        )
    return manifest


__all__ = [
    "InputManifestDigest",
    "canonical_input_manifest_bytes",
    "input_manifest_digest",
    "parse_input_manifest",
]
