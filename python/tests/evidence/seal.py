"""Assembling sealed bundles for the evidence suites, by hand and on purpose.

Most of what these suites test is a *deviation* from a valid seal, so they need a valid seal
to deviate from. Building it through :func:`dynamisbench.evidence.finalize_bundle` would be
circular: a defect in the finalizer would then hide behind a defect in the test's expectations.

So a valid bundle is assembled here from the manifest and checksum primitives directly, which
also makes each test's starting point obvious. The two things finalization does that this
helper cannot are *atomic promotion* and *independent re-verification* — and those are tested
against the real finalizer, not against this helper.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from dynamisbench.evidence.bundle import ArtifactRole, RunId, RunOutcome
from dynamisbench.evidence.manifest import (
    Manifest,
    ManifestEntry,
    canonical_manifest_bytes,
    evidence_digest_of_canonical_manifest_bytes,
    render_checksums,
)

SAMPLE_PAYLOAD: Final = (("run.json", b'{"seed":7}'), ("native/table.parquet", b"PAR1payload"))
"""A two-file payload, one metadata file and one binary-looking artifact, plus a subdirectory.

The subdirectory matters: the exact file-set rule is about *files*, and a bundle that has
only top-level files would never exercise the difference between a declared path and the
directories that hold it.
"""


def write_payload(bundle_root: Path, files: tuple[tuple[str, bytes], ...] = SAMPLE_PAYLOAD) -> None:
    """Write the payload of a bundle, creating whatever directories it needs."""
    for relative_path, data in files:
        target = bundle_root.joinpath(*relative_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def build_manifest(
    run_id: RunId,
    files: tuple[tuple[str, bytes], ...] = SAMPLE_PAYLOAD,
    outcome: RunOutcome = RunOutcome.SUCCEEDED,
    role_for: dict[str, ArtifactRole] | None = None,
) -> Manifest:
    """Build the manifest that describes ``files``, exactly as a finalizer would."""
    roles = role_for or {}
    return Manifest(
        run_id=run_id,
        outcome=outcome,
        files=tuple(
            ManifestEntry(
                relative_path=relative_path,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                role=roles.get(relative_path),
            )
            for relative_path, data in files
        ),
    )


def seal_in_place(
    bundle_root: Path,
    run_id: RunId,
    files: tuple[tuple[str, bytes], ...] = SAMPLE_PAYLOAD,
    outcome: RunOutcome = RunOutcome.SUCCEEDED,
    role_for: dict[str, ArtifactRole] | None = None,
) -> str:
    """Write payload, manifest and checksum file into ``bundle_root``; return the digest hex.

    This is the minimum a valid seal is: the declared payload, the canonical manifest, and the
    checksum file covering both. Everything else a bundle may contain is a deviation the tests
    build deliberately.
    """
    write_payload(bundle_root, files)
    manifest = build_manifest(run_id, files, outcome, role_for)
    canonical = canonical_manifest_bytes(manifest)
    (bundle_root / "manifest.json").write_bytes(canonical)
    (bundle_root / "checksums.sha256").write_bytes(render_checksums(manifest, canonical))
    return evidence_digest_of_canonical_manifest_bytes(canonical).hex
