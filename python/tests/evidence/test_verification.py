"""Verifying a sealed bundle: the exact file-set rule, and every way to fail it.

The property under test throughout is RES-231's invariant — *a directory is not authoritative
merely because it is named like a run* — expressed as an exact equality between the actual
file set and the declared one plus the two seal files. Every test below is one way that
equality can fail, and the claim being made in each case is that it is **detected and
reported**, never tolerated.

Three things are separated deliberately, because conflating them would make a diagnostic
useless:

* **validity** — the bundle agrees with itself;
* **expected output** — the bundle is the one an external reference names, which only an
  externally supplied evidence digest can establish;
* **canonicality** — the manifest is in the form its evidence digest is defined over, which
  is a different fault from the manifest being invalid or the bytes being wrong.

And one limit is stated rather than hidden: a bundle whose payload, manifest *and* checksum
file were all rewritten together is internally consistent, and no self-contained seal can
detect that. Only the external-digest path finds it, and the tests say so.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dynamisbench.evidence import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    ArtifactRole,
    EvidenceDigest,
    RunOutcome,
    create_staging_bundle,
    verify_sealed_bundle,
)
from dynamisbench.evidence.manifest import (
    Manifest,
    ManifestEntry,
    canonical_manifest_bytes,
    evidence_digest_of_canonical_manifest_bytes,
    render_checksums,
)
from dynamisbench.evidence.sealed import Defect, DefectKind, VerificationResult, verify_bundle_seal
from dynamisbench.workspace import PersistenceClass, Workspace
from tests.evidence.seal import SAMPLE_PAYLOAD, build_manifest, seal_in_place, write_payload
from tests.workspace.links import DirectoryLinkFactory, require_directory_link

RUN = "run-1"


def promote(workspace: Workspace, run_id: str = RUN) -> Path:
    """Seal a bundle straight into ``runs/``, the way promotion would leave it."""
    destination = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, run_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    seal_in_place(destination, run_id)
    return destination


def kinds(result: VerificationResult) -> set[DefectKind]:
    return {defect.kind for defect in result.defects}


# --- a valid seal --------------------------------------------------------------------------------


def test_a_correctly_sealed_bundle_verifies(workspace: Workspace) -> None:
    promote(workspace)
    result = verify_sealed_bundle(workspace, RUN)
    assert result.is_valid
    assert result.defects == ()
    assert result.bundle is not None
    assert result.bundle.run_id == RUN
    assert result.bundle.manifest.outcome is RunOutcome.SUCCEEDED


def test_a_valid_bundle_exposes_its_inventory_and_digest(workspace: Workspace) -> None:
    promote(workspace)
    bundle = verify_sealed_bundle(workspace, RUN).bundle
    assert bundle is not None
    assert bundle.payload_paths == ("native/table.parquet", "run.json")
    assert len(bundle.evidence_digest.hex) == 64
    assert {entry.relative_path for entry in bundle.checksums} == {
        "native/table.parquet",
        "run.json",
        MANIFEST_FILE_NAME,
    }


def test_a_sealed_bundle_carries_the_portable_reference_not_a_path(workspace: Workspace) -> None:
    """The reference is what a read model stores; the path is where it is right now."""
    promote(workspace)
    bundle = verify_sealed_bundle(workspace, RUN).bundle
    assert bundle is not None
    assert bundle.reference.text == f"runs/{RUN}"
    assert str(workspace.evidence_root) not in bundle.reference.text


def test_a_failed_execution_can_be_validly_sealed(workspace: Workspace) -> None:
    """A sealed failed run is authoritative evidence *of the failure*."""
    destination = promote(workspace)
    seal_in_place(destination, RUN, outcome=RunOutcome.FAILED)
    result = verify_sealed_bundle(workspace, RUN)
    assert result.is_valid
    assert result.bundle is not None
    assert result.bundle.manifest.outcome is RunOutcome.FAILED


def test_a_failed_run_and_a_successful_run_have_different_evidence_digests(
    workspace: Workspace,
) -> None:
    """The outcome is inside the bytes the digest is taken over, so it is part of identity."""
    first = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, "run-a")
    second = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, "run-b")
    first.parent.mkdir(parents=True, exist_ok=True)
    first.mkdir()
    second.mkdir()
    succeeded = seal_in_place(first, "run-a", outcome=RunOutcome.SUCCEEDED)
    failed = seal_in_place(second, "run-b", outcome=RunOutcome.FAILED)
    assert succeeded != failed


def test_a_directory_named_like_a_run_that_was_never_sealed_is_not_authoritative(
    workspace: Workspace,
) -> None:
    """The invariant itself: the name is not the authority, the seal is."""
    destination = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, RUN)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    write_payload(destination)
    result = verify_sealed_bundle(workspace, RUN)
    assert not result.is_valid
    assert kinds(result) == {DefectKind.MANIFEST_MISSING, DefectKind.CHECKSUMS_MISSING}


def test_a_run_with_no_bundle_at_all_reports_missing_rather_than_raising(
    workspace: Workspace,
) -> None:
    result = verify_sealed_bundle(workspace, "never-run")
    assert kinds(result) == {DefectKind.BUNDLE_MISSING}
    assert "not validly sealed" in result.summary


# --- the exact file-set rule ---------------------------------------------------------------


def test_a_missing_declared_file_is_invalid(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / "run.json").unlink()
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_MISSING in kinds(result)


def test_an_extra_undeclared_file_is_invalid(workspace: Workspace) -> None:
    """Not ignored, not tolerated: an undeclared file is not covered by the evidence digest."""
    destination = promote(workspace)
    (destination / "smuggled.parquet").write_bytes(b"extra")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_UNEXPECTED in kinds(result)
    assert any("smuggled.parquet" in str(defect) for defect in result.defects)


def test_a_file_added_beneath_an_existing_directory_is_also_unexpected(
    workspace: Workspace,
) -> None:
    destination = promote(workspace)
    (destination / "native" / "extra.parquet").write_bytes(b"extra")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_UNEXPECTED in kinds(result)


def test_an_empty_directory_is_allowed_because_directories_are_not_payload(
    workspace: Workspace,
) -> None:
    """The authority is explicit: directories need no digest entries, and no *files* may
    exist beneath them without being declared."""
    destination = promote(workspace)
    (destination / "logs").mkdir()
    assert verify_sealed_bundle(workspace, RUN).is_valid


def test_a_modified_payload_is_invalid(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / "native" / "table.parquet").write_bytes(b"PAR1payload!")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_MODIFIED in kinds(result)
    assert DefectKind.CHECKSUM_MISMATCH in kinds(result)


def test_a_payload_whose_length_changed_is_invalid(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / "native" / "table.parquet").write_bytes(b"")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_MODIFIED in kinds(result)


def test_a_manifest_that_is_not_a_manifest_is_invalid(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / MANIFEST_FILE_NAME).write_bytes(b"{ not json")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.MANIFEST_INVALID in kinds(result)


def test_a_manifest_declaring_an_empty_file_set_is_invalid(workspace: Workspace) -> None:
    """A manifest read back is held to the same rules as one just written."""
    destination = promote(workspace)
    forged = json.dumps(
        {
            "schema_version": 1,
            "run_id": RUN,
            "outcome": "succeeded",
            "files": [],
        }
    ).encode("utf-8")
    (destination / MANIFEST_FILE_NAME).write_bytes(forged)
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.MANIFEST_INVALID in kinds(result)


def test_a_manifest_stored_in_a_non_canonical_form_is_invalid(workspace: Workspace) -> None:
    """The same facts in the same order would describe the same bundle — but its evidence
    digest would then depend on the serialiser, so the bytes must be the canonical ones.

    The stored manifest also stops matching the digest its checksum file recorded, so this
    produces more than one finding; both are true and both are reported.
    """
    destination = promote(workspace)
    manifest = build_manifest(RUN, SAMPLE_PAYLOAD)
    (destination / MANIFEST_FILE_NAME).write_bytes(
        json.dumps(manifest.model_dump(mode="json"), indent=2).encode("utf-8")
    )
    found = kinds(verify_sealed_bundle(workspace, RUN))
    assert DefectKind.MANIFEST_NOT_CANONICAL in found
    assert DefectKind.MANIFEST_MODIFIED in found


def test_a_manifest_whose_declared_digest_was_rewritten_is_invalid(workspace: Workspace) -> None:
    """Rewriting the manifest changes the bundle, so the payload no longer matches it."""
    destination = promote(workspace)
    manifest = build_manifest(RUN, SAMPLE_PAYLOAD)
    rewritten = Manifest(
        run_id=manifest.run_id,
        outcome=manifest.outcome,
        files=(
            ManifestEntry(
                relative_path="native/table.parquet",
                sha256=hashlib.sha256(b"a different payload").hexdigest(),
                size_bytes=manifest.files[0].size_bytes,
            ),
            manifest.files[1],
        ),
    )
    canonical = canonical_manifest_bytes(rewritten)
    (destination / MANIFEST_FILE_NAME).write_bytes(canonical)
    (destination / CHECKSUMS_FILE_NAME).write_bytes(render_checksums(rewritten, canonical))
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_MODIFIED in kinds(result)


def test_a_manifest_rewritten_without_its_checksum_file_is_reported_as_modified(
    workspace: Workspace,
) -> None:
    """A manifest edited on its own is caught by the independent record beside it.

    The edit is a *canonical* one — a different but still valid outcome — so the only thing
    that can catch it is the digest the checksum file independently recorded.
    """
    destination = promote(workspace)
    manifest = build_manifest(RUN, SAMPLE_PAYLOAD)
    (destination / MANIFEST_FILE_NAME).write_bytes(
        canonical_manifest_bytes(manifest).replace(b'"succeeded"', b'"failed"')
    )
    result = verify_sealed_bundle(workspace, RUN)
    assert kinds(result) == {DefectKind.MANIFEST_MODIFIED}


def test_a_manifest_with_a_trailing_newline_is_invalid(workspace: Workspace) -> None:
    """One byte of difference, and a different identity. Canonical means canonical."""
    destination = promote(workspace)
    path = destination / MANIFEST_FILE_NAME
    path.write_bytes(path.read_bytes() + b"\n")
    assert DefectKind.MANIFEST_NOT_CANONICAL in kinds(verify_sealed_bundle(workspace, RUN))


def test_a_manifest_with_a_rewritten_digest_is_invalid(workspace: Workspace) -> None:
    """Rewriting the manifest *and* its checksum file together stays self-consistent, so the
    only thing that finds it is an external expected digest — asserted separately below."""
    destination = promote(workspace)
    manifest = build_manifest(RUN, SAMPLE_PAYLOAD)
    rewritten = Manifest(
        run_id=manifest.run_id,
        outcome=manifest.outcome,
        files=(
            ManifestEntry(
                relative_path="native/table.parquet",
                sha256=hashlib.sha256(b"a different payload").hexdigest(),
                size_bytes=manifest.files[0].size_bytes,
            ),
            manifest.files[1],
        ),
    )
    canonical = canonical_manifest_bytes(rewritten)
    (destination / MANIFEST_FILE_NAME).write_bytes(canonical)
    (destination / CHECKSUMS_FILE_NAME).write_bytes(render_checksums(rewritten, canonical))
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.PAYLOAD_MODIFIED in kinds(result)


def test_a_missing_checksum_file_is_invalid(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / CHECKSUMS_FILE_NAME).unlink()
    assert DefectKind.CHECKSUMS_MISSING in kinds(verify_sealed_bundle(workspace, RUN))


def test_a_malformed_checksum_file_is_invalid(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / CHECKSUMS_FILE_NAME).write_bytes(b"not a checksum file")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.CHECKSUMS_MALFORMED in kinds(result)


def test_a_checksum_file_that_disagrees_with_the_manifest_is_invalid(workspace: Workspace) -> None:
    """A well-formed checksum file that omits a declared file still describes a different
    bundle, so the disagreement is a finding of its own.

    Written as bytes on purpose: the seal writes bytes, and a text-mode write on Windows would
    turn every ``\\n`` into ``\\r\\n`` and make this a test of newline translation instead.
    """
    destination = promote(workspace)
    path = destination / CHECKSUMS_FILE_NAME
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(line for line in lines if MANIFEST_FILE_NAME.encode() not in line))
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.COVERAGE_MISMATCH in kinds(result)


def test_a_checksum_file_covering_an_undeclared_file_is_invalid(workspace: Workspace) -> None:
    """The two records must describe the same bundle, not overlapping ones."""
    destination = promote(workspace)
    path = destination / CHECKSUMS_FILE_NAME
    lines = path.read_bytes().splitlines(keepends=True)
    phantom = f"{hashlib.sha256(b'x').hexdigest()}  native/phantom.parquet\n".encode()
    path.write_bytes(b"".join(sorted([*lines, phantom], key=_checksum_sort_key)))
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.COVERAGE_MISMATCH in kinds(result)


def _checksum_sort_key(line: bytes) -> bytes:
    """Sort checksum lines by their path, so an inserted line keeps the file well-formed."""
    return line[66:].rstrip(b"\n")


def test_leftover_seal_debris_is_reported_rather_than_ignored(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / f"{MANIFEST_FILE_NAME}.seal-tmp").write_bytes(b"partial")
    result = verify_sealed_bundle(workspace, RUN)
    assert DefectKind.SEAL_DEBRIS in kinds(result)


def test_a_junction_inside_a_sealed_bundle_is_reported_as_a_link(
    workspace: Workspace, link_maker: DirectoryLinkFactory
) -> None:
    """A link planted inside a sealed bundle is refused even though the bundle is otherwise
    perfect, and the bundle root itself is nowhere near the link's target."""
    destination = promote(workspace)
    elsewhere = workspace.evidence_root / "outside"
    elsewhere.mkdir()
    (elsewhere / "leak.json").write_bytes(b"{}")
    mechanism = require_directory_link(
        link_maker(destination / "linked", elsewhere),
        "link rejection inside a sealed bundle is unproved on this host",
    )
    assert mechanism
    result = verify_sealed_bundle(workspace, RUN)
    assert kinds(result) == {DefectKind.LINK_IN_BUNDLE}


def test_every_defect_is_reported_not_just_the_first(workspace: Workspace) -> None:
    """A caller diagnosing corruption wants the whole picture in one call."""
    destination = promote(workspace)
    (destination / "run.json").unlink()
    (destination / "smuggled.json").write_bytes(b"x")
    (destination / CHECKSUMS_FILE_NAME).write_bytes(b"garbage")
    assert kinds(verify_sealed_bundle(workspace, RUN)) == {
        DefectKind.PAYLOAD_MISSING,
        DefectKind.PAYLOAD_UNEXPECTED,
        DefectKind.CHECKSUMS_MALFORMED,
    }


def test_a_defect_names_the_artifact_without_naming_the_machine(workspace: Workspace) -> None:
    destination = promote(workspace)
    (destination / "smuggled.json").write_bytes(b"x")
    defect = next(
        item
        for item in verify_sealed_bundle(workspace, RUN).defects
        if item.kind is DefectKind.PAYLOAD_UNEXPECTED
    )
    assert defect.relative_path == "smuggled.json"
    assert str(workspace.evidence_root) not in str(defect)
    assert str(defect).startswith("payload_unexpected [smuggled.json]")


def test_a_defect_renders_readably_without_optional_detail() -> None:
    plain = Defect(DefectKind.BUNDLE_MISSING, "nothing was promoted")
    assert str(plain) == "bundle_missing: nothing was promoted"


# --- the external expected digest -----------------------------------------------------


def test_an_expected_evidence_digest_that_matches_proves_the_expected_output(
    workspace: Workspace,
) -> None:
    promote(workspace)
    bundle = verify_sealed_bundle(workspace, RUN).bundle
    assert bundle is not None
    result = verify_sealed_bundle(workspace, RUN, expected_evidence_digest=bundle.evidence_digest)
    assert result.is_valid
    assert result.proves_expected_output
    assert "expected output" in result.summary


def test_an_expected_evidence_digest_that_does_not_match_is_reported(workspace: Workspace) -> None:
    promote(workspace)
    wrong = EvidenceDigest(hex=hashlib.sha256(b"a different run").hexdigest())
    result = verify_sealed_bundle(workspace, RUN, expected_evidence_digest=wrong)
    assert not result.is_valid
    assert DefectKind.EVIDENCE_DIGEST_MISMATCH in kinds(result)
    assert not result.proves_expected_output


def test_the_result_records_whether_an_expected_digest_was_supplied(workspace: Workspace) -> None:
    """Without one, a valid result is explicitly scoped to internal consistency."""
    promote(workspace)
    result = verify_sealed_bundle(workspace, RUN)
    assert result.is_valid
    assert not result.proves_expected_output
    assert "internally consistent" in result.summary


def test_a_bundle_rewritten_wholesale_is_caught_only_by_an_external_digest(
    workspace: Workspace,
) -> None:
    """The honest limit of a self-contained seal, asserted rather than glossed over.

    Rewriting the payload, the manifest and the checksum file together produces a bundle that
    is perfectly self-consistent. No checksum file can detect that, and this package does not
    pretend otherwise — the only thing that can is a digest the verifier was told to expect.
    """
    destination = promote(workspace)
    original = verify_sealed_bundle(workspace, RUN).bundle
    assert original is not None

    forged_payload = (("run.json", b'{"seed":8}'), ("native/table.parquet", b"PAR1forged"))
    for name in (MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME):
        (destination / name).unlink()
    forged_digest = seal_in_place(destination, RUN, files=forged_payload)
    assert forged_digest != original.evidence_digest.hex

    without_expectation = verify_sealed_bundle(workspace, RUN)
    assert without_expectation.is_valid
    assert not without_expectation.proves_expected_output

    with_expectation = verify_sealed_bundle(
        workspace, RUN, expected_evidence_digest=original.evidence_digest
    )
    assert not with_expectation.is_valid
    assert DefectKind.EVIDENCE_DIGEST_MISMATCH in kinds(with_expectation)


# --- verification before promotion -----------------------------------------------------


def test_a_valid_staging_seal_verifies_before_it_is_promoted(workspace: Workspace) -> None:
    """The pre-promotion gate: verify where the bundle actually is, promote only if it passes."""
    bundle = create_staging_bundle(workspace, RUN)
    write_payload(bundle.path)
    manifest = build_manifest(RUN, SAMPLE_PAYLOAD)
    canonical = canonical_manifest_bytes(manifest)
    (bundle.path / MANIFEST_FILE_NAME).write_bytes(canonical)
    (bundle.path / CHECKSUMS_FILE_NAME).write_bytes(render_checksums(manifest, canonical))
    result = verify_bundle_seal(bundle.path, RUN)
    assert result.is_valid
    assert result.bundle is not None
    assert result.bundle.evidence_digest == evidence_digest_of_canonical_manifest_bytes(canonical)


def test_a_verified_bundle_exposes_no_way_to_write_through_it(workspace: Workspace) -> None:
    """Immutability is lifecycle discipline, not filesystem permission, and the API says so."""
    promote(workspace)
    bundle = verify_sealed_bundle(workspace, RUN).bundle
    assert bundle is not None
    assert not any(
        name.startswith(("write", "delete", "remove", "open", "unlink", "mutate"))
        for name in dir(bundle)
    )


def test_the_role_a_manifest_records_survives_verification(workspace: Workspace) -> None:
    """A role is a reader's hint about a file, so it must come back out of a sealed bundle."""
    destination = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, RUN)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    seal_in_place(destination, RUN, role_for={"run.json": ArtifactRole.RUN_METADATA})
    bundle = verify_sealed_bundle(workspace, RUN).bundle
    assert bundle is not None
    roles = {entry.relative_path: entry.role for entry in bundle.manifest.files}
    assert roles == {"native/table.parquet": None, "run.json": ArtifactRole.RUN_METADATA}
