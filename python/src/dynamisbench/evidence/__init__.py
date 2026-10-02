"""Manifests, hashing, sealed run bundles, provenance, and evidence verification.

A run becomes authoritative only after outcome capture, schema validation, manifest
construction, complete SHA-256 verification, and atomic promotion; sealed bundles are
never overwritten (ADR-008). Scientific authority is Git, specs, Parquet, and SHA-256
rather than a mutable service database (ADR-004).

This package is DB-1.5 (RES-231) implementing those steps against the two boundaries
already in place: :mod:`dynamisbench.identity` supplies RFC 8785 canonical bytes and typed
SHA-256 values, and :mod:`dynamisbench.workspace` supplies the evidence root, ``.staging/``,
``runs/``, and the one resolver that hands out a path proved to be inside a root. Nothing
here re-implements either. The evidence package may only add *bundle-content* constraints
on top — no links, exact file sets, no self-reference — which is why it is a different
layer and not a second copy of the same one.

The seal, and the reason it is shaped this way:

* **The manifest is not self-referential.** ``manifest.json`` enumerates every payload
  artifact by normalized relative path and raw-byte SHA-256, and never enumerates or
  hashes itself. It cannot contain its own evidence digest even by accident, because the
  model forbids unknown fields.
* **The evidence digest is the root identity of the sealed output** — the SHA-256 of the
  canonical ``manifest.json`` bytes. It is returned to the caller and travels beside the
  run id, never inside the manifest it identifies.
* **The checksum file is an aid, not the identity.** ``checksums.sha256`` covers every
  payload file *and* ``manifest.json``, excludes itself, and exists so a human or a
  standard tool can re-check the bundle without this package.
* **Authority is a file-set equality, not a naming convention.** A directory named like a
  run is not a run. ``verify_sealed_bundle`` requires the actual file set to equal exactly
  the manifest's payload plus the two seal files, so an extra or missing file invalidates
  the seal rather than being ignored.
* **Immutability is discipline plus verification, not filesystem permissions.** The
  application never mutates a sealed bundle, verification detects corruption, and an
  externally trusted evidence digest identifies the expected bundle. Windows read-only
  bits, ACLs and the like are deliberately not the source of scientific immutability, and
  a self-contained seal is never described as tamper-proof against an actor able to rewrite
  the whole bundle.

Modules, in the order they build on each other:

* :mod:`dynamisbench.evidence.bundle` — the vocabulary: run id, outcome, artifact role, the
  bundle path language, the reserved seal names, the no-links rule, the bundle walk, and
  the errors. Every other module in this package takes its terms from that one.
* :mod:`dynamisbench.evidence.staging` — the mutable staging bundle a run writes into, and
  the deterministic inventory of the payload it holds.
"""

from dynamisbench.evidence.bundle import (
    CHECKSUMS_FILE_NAME,
    CHECKSUMS_TEMP_FILE_NAME,
    MANIFEST_FILE_NAME,
    MANIFEST_TEMP_FILE_NAME,
    RESERVED_BUNDLE_FILE_NAMES,
    SEAL_FILE_NAMES,
    ArtifactRole,
    BundleConflictError,
    BundleEntry,
    BundleIntegrityError,
    BundleNamingError,
    BundleOperationError,
    BundleRelativePath,
    EvidenceError,
    RunId,
    RunOutcome,
    is_link_or_reparse_point,
    parse_bundle_relative_path,
    parse_run_id,
    walk_bundle,
)
from dynamisbench.evidence.staging import (
    PayloadFile,
    StagingBundle,
    create_staging_bundle,
    inventory_payload,
)

__all__ = [
    "CHECKSUMS_FILE_NAME",
    "CHECKSUMS_TEMP_FILE_NAME",
    "MANIFEST_FILE_NAME",
    "MANIFEST_TEMP_FILE_NAME",
    "RESERVED_BUNDLE_FILE_NAMES",
    "SEAL_FILE_NAMES",
    "ArtifactRole",
    "BundleConflictError",
    "BundleEntry",
    "BundleIntegrityError",
    "BundleNamingError",
    "BundleOperationError",
    "BundleRelativePath",
    "EvidenceError",
    "PayloadFile",
    "RunId",
    "RunOutcome",
    "StagingBundle",
    "create_staging_bundle",
    "inventory_payload",
    "is_link_or_reparse_point",
    "parse_bundle_relative_path",
    "parse_run_id",
    "walk_bundle",
]
