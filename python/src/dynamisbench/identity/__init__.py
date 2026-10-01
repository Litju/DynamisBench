"""Deterministic identity for validated authority and referenced assets.

Three identities are kept apart throughout DynamisBench and are never allowed to
collapse into one another (ADR-006, Evidence & Provenance Model "Identity",
Architecture section 7):

* the **human or scientific identifier** — ``BenchmarkId``, ``Version``, ``SUTId``,
  ``StudyId``, and the rest of the nominal identity vocabulary — which names an
  artifact for people and is never a hash;
* the **semantic digest**, the SHA-256 of the RFC 8785 canonical bytes of a validated
  definition's meaning, so that two authorings of one meaning agree and two different
  meanings do not;
* the **asset digest**, the SHA-256 of an asset's raw bytes, so that the same bytes are
  the same artifact wherever they are stored.

A digest supplements the human identifier and never replaces it, so an authoritative
reference can say ``id: DB-LCMJ20``, ``version: 0.1.0``, and
``semantic_digest: {algorithm: sha256, hex: ...}`` without the hash becoming the
name.

DB-1.3 (RES-229) implements both digests. Manifests, staging, and sealed evidence
bundles are deliberately out of scope here; they belong to DB-1.5 (RES-231).
"""

from dynamisbench.identity.canonical import (
    CanonicalizationError,
    JsonValue,
    canonical_bytes,
)
from dynamisbench.identity.digests import (
    READ_CHUNK_BYTES,
    AssetAccessError,
    AssetDigest,
    BinarySource,
    DigestAlgorithm,
    SemanticDigest,
    asset_sha256,
    asset_sha256_of_file,
    asset_sha256_of_stream,
    semantic_sha256_of_canonical_bytes,
)

__all__ = [
    "READ_CHUNK_BYTES",
    "AssetAccessError",
    "AssetDigest",
    "BinarySource",
    "CanonicalizationError",
    "DigestAlgorithm",
    "JsonValue",
    "SemanticDigest",
    "asset_sha256",
    "asset_sha256_of_file",
    "asset_sha256_of_stream",
    "canonical_bytes",
    "semantic_sha256_of_canonical_bytes",
]
