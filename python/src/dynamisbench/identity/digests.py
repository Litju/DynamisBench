"""Typed SHA-256 identity values, and raw-byte identity for referenced assets.

ADR-006 keeps two kinds of digest apart and this module keeps them apart in the type
system rather than in documentation:

* :class:`SemanticDigest` identifies the *meaning* of a validated structured
  definition. It is the digest of RFC 8785 canonical bytes and is produced by
  :mod:`dynamisbench.identity.semantic`.
* :class:`AssetDigest` identifies the *bytes* of a referenced asset — a model file, a
  Parquet table, an MJCF document, an ``.osim`` model, a reference trajectory. The
  asset's path and name are not part of its content, so the same bytes in two
  locations are one artifact.

They are separate types on purpose: a digest over canonical meaning and a digest over
raw bytes answer different questions, and neither may be substituted for the other in
a manifest, a reference, or a comparison.

SHA-256 is the only digest algorithm for v0. That is recorded explicitly in every
digest value rather than left implicit, so a future algorithm change is a visible
schema change and two digests can never be compared without saying which algorithm
produced them. This is deliberately not a cryptography abstraction: the algorithm set
is closed, the hash comes from the standard library, and the only non-standard part is
the two value types themselves.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from dynamisbench.domain.spec.identifiers import Sha256Hex

READ_CHUNK_BYTES: Final = 1024 * 1024
"""The largest read issued against a referenced asset.

A scientific asset is a model or a Parquet table, not a text document, so it is read
in bounded chunks and never loaded whole. The bound is one mebibyte: large enough that
a multi-gigabyte file costs a few thousand reads, small enough that peak memory does
not scale with the file.
"""


class DigestAlgorithm(StrEnum):
    """The algorithm a digest was produced with (ADR-006).

    ``sha256`` is the v0 authority for both semantic and asset identity. A second
    algorithm is not anticipated here: adding one is a visible change to every stored
    digest, which is the correct cost for changing what identity means.
    """

    SHA256 = "sha256"


class _DigestValue(BaseModel):
    """Frozen, validated, hashable base for the two digest identity types.

    The field types are the recorded reference form the domain already uses for a
    declared content hash, so a digest value and a declared ``sha256`` field are the
    same language and comparing them is a comparison rather than a string exercise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal[DigestAlgorithm.SHA256] = DigestAlgorithm.SHA256
    hex: Sha256Hex


class SemanticDigest(_DigestValue):
    """The SHA-256 of the RFC 8785 canonical bytes of a validated definition's meaning.

    This is a cryptographic identity, never a name. An authoritative reference states
    it next to — never instead of — the human identity: ``id: DB-LCMJ20``,
    ``version: 0.1.0``, ``semantic_digest: {algorithm: sha256, hex: ...}``.
    """


class AssetDigest(_DigestValue):
    """The SHA-256 of an asset's raw bytes.

    An empty asset is a valid asset with a well-defined digest, and moving an asset
    does not change its digest. Only the bytes count, so this is the identity that
    survives being copied between a workspace, a cache and a sealed evidence bundle.
    """


class AssetAccessError(RuntimeError):
    """A referenced asset could not be read, so it has no asset digest.

    This is an access failure, kept distinct from a digest *mismatch*: a missing or
    unreadable asset means identity could not be established, which is not the same
    claim as "these bytes are not the bytes that were declared".
    """


class BinarySource(Protocol):
    """A byte source that can be read in bounded pieces.

    Stated structurally rather than as ``BinaryIO`` because the only capability used
    is a bounded read: any open binary handle — a file, an entry inside a sealed
    bundle, a pipe — carries raw-byte identity under exactly this guarantee, and none
    of them has to be a concrete file object.
    """

    def read(self, size: int = ..., /) -> bytes: ...


def semantic_sha256_of_canonical_bytes(canonical: bytes) -> SemanticDigest:
    """Digest an already-canonical semantic byte string.

    The argument must be the output of RFC 8785 canonicalisation. Naming it here is
    the guard: there is deliberately no convenience function that hashes arbitrary
    Python objects into a semantic digest, because a digest over non-canonical bytes
    depends on the serialiser rather than on the meaning.
    """
    return SemanticDigest(hex=hashlib.sha256(canonical).hexdigest())


def asset_sha256(data: bytes) -> AssetDigest:
    """Digest bytes already held in memory, exactly as they are."""
    return AssetDigest(hex=hashlib.sha256(data).hexdigest())


def asset_sha256_of_stream(source: BinarySource) -> AssetDigest:
    """Digest a byte source, reading it in chunks of at most :data:`READ_CHUNK_BYTES`.

    :raises AssetAccessError: if the source fails while being read.
    """
    digest = hashlib.sha256()
    try:
        while chunk := source.read(READ_CHUNK_BYTES):
            digest.update(chunk)
    except OSError as error:
        raise AssetAccessError(f"cannot read asset stream: {error}") from error
    return AssetDigest(hex=digest.hexdigest())


def asset_sha256_of_file(path: Path) -> AssetDigest:
    """Digest a referenced asset's raw bytes, streaming it in bounded memory.

    Only the content is hashed. The file name, its directory and the workspace it sits
    in are deliberately excluded, so the same bytes at two paths are one artifact; a
    realization that points at a moved asset therefore keeps its own asset identity
    while its realization identity changes, which is the correct outcome for the two
    being different identities.

    :raises AssetAccessError: if the path cannot be opened or read.
    """
    try:
        with path.open("rb") as handle:
            return asset_sha256_of_stream(handle)
    except OSError as error:
        raise AssetAccessError(f"cannot read asset {path}: {error}") from error
