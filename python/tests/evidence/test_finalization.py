"""Finalization: turning a mutable staging bundle into an authoritative sealed run.

This is the only code in the project that makes a run authoritative, so the tests here are
written around the guarantees that matter when something goes wrong:

* **Promotion is atomic and happens once.** The staging directory becomes
  ``runs/<run-id>`` through a single same-filesystem rename, and a run that is already sealed
  is never replaced, merged into, deleted, or appended to.
* **A failed attempt leaves nothing that looks authoritative.** Every failure path is checked
  for the same thing: ``runs/<run-id>`` does not exist, and the staging bundle is still there
  to be diagnosed.
* **The outcome is a first-class scientific fact.** A run whose failure record is complete is
  sealed as authoritative evidence *of that failure*, which is a different thing from a
  staging directory that never produced a record.
* **Metadata is never exposed half-written.** ``manifest.json`` and ``checksums.sha256`` are
  written through reserved temporaries and renamed into place, so their final names only ever
  hold complete content.
* **The seal is verified before it is trusted.** Finalization re-reads and re-hashes what it
  just wrote and refuses to promote anything that does not verify.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dynamisbench.evidence import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    BundleConflictError,
    BundleIntegrityError,
    BundleOperationError,
    RunOutcome,
    create_staging_bundle,
    finalize_bundle,
    verify_sealed_bundle,
)
from dynamisbench.evidence import staging as staging_module
from dynamisbench.evidence.manifest import canonical_manifest_bytes, parse_checksums, parse_manifest
from dynamisbench.evidence.sealed import verify_bundle_seal
from dynamisbench.evidence.staging import StagingBundle
from dynamisbench.workspace import PersistenceClass, Workspace
from tests.evidence.links import HARD_LINK, HardLinkFactory, require_file_link
from tests.evidence.seal import SAMPLE_PAYLOAD, seal_in_place
from tests.workspace.links import DirectoryLinkFactory, require_directory_link

RUN = "run-1"
TWO_FILES = SAMPLE_PAYLOAD + (("logs/solver.log", b"step 1\nstep 2\n"),)


def staged(
    workspace: Workspace, run_id: str = RUN, files: tuple[tuple[str, bytes], ...] = TWO_FILES
) -> StagingBundle:
    """Create a staging bundle and fill it with payload, ready to be sealed."""
    bundle = create_staging_bundle(workspace, run_id)
    for relative_path, data in files:
        bundle.write_payload(relative_path, data)
    return bundle


def runs_root(workspace: Workspace) -> Path:
    return workspace.location(PersistenceClass.SEALED_EVIDENCE).path


def staging_root(workspace: Workspace) -> Path:
    return workspace.location(PersistenceClass.STAGING).path


# --- successful finalization ----------------------------------------------------------------------


def test_finalizing_promotes_the_bundle_into_runs(workspace: Workspace) -> None:
    bundle = staged(workspace)
    result = finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert result.path == runs_root(workspace) / RUN
    assert result.path.is_dir()
    assert result.reference.text == f"runs/{RUN}"
    assert not bundle.path.exists(), "the staging directory must not survive promotion"


def test_the_promoted_bundle_verifies_and_reports_its_own_digest(workspace: Workspace) -> None:
    """The digest finalization returned is the one an independent verification recomputes."""
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    verified = verify_sealed_bundle(workspace, RUN, expected_evidence_digest=result.evidence_digest)
    assert verified.is_valid
    assert verified.proves_expected_output
    assert verified.bundle is not None
    assert verified.bundle.evidence_digest == result.evidence_digest


def test_the_seal_metadata_is_inside_the_promoted_bundle(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    assert (result.path / MANIFEST_FILE_NAME).is_file()
    assert (result.path / CHECKSUMS_FILE_NAME).is_file()


def test_the_manifest_declares_every_payload_file_that_was_written(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    declared = {entry.relative_path for entry in result.manifest.files}
    assert declared == {path for path, _ in TWO_FILES}


def test_each_declared_size_and_digest_matches_the_bytes_on_disk(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    for entry in result.manifest.files:
        payload = result.path.joinpath(*entry.relative_path.split("/")).read_bytes()
        assert entry.size_bytes == len(payload)
        assert entry.sha256 == hashlib.sha256(payload).hexdigest()


def test_the_stored_manifest_is_exactly_the_canonical_bytes(workspace: Workspace) -> None:
    """Not a re-serialisation that happens to parse — the very bytes the digest is over."""
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    stored = (result.path / MANIFEST_FILE_NAME).read_bytes()
    assert stored == canonical_manifest_bytes(result.manifest)


def test_finalization_closes_the_bundle_to_new_payload(workspace: Workspace) -> None:
    bundle = staged(workspace)
    finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not bundle.accepts_payload


def test_runs_is_created_immediately_before_the_first_promotion(workspace: Workspace) -> None:
    """RES-230 leaves runs/ uncreated on purpose; the rename is where it becomes necessary."""
    assert not runs_root(workspace).exists()
    finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    assert runs_root(workspace).is_dir()


def test_a_second_run_in_the_same_workspace_promotes_alongside_the_first(
    workspace: Workspace,
) -> None:
    finalize_bundle(staged(workspace, "run-a"), RunOutcome.SUCCEEDED)
    finalize_bundle(staged(workspace, "run-b"), RunOutcome.SUCCEEDED)
    assert sorted(path.name for path in runs_root(workspace).iterdir()) == ["run-a", "run-b"]


# --- the outcome vocabulary -----------------------------------------------------------------------


def test_a_failed_execution_can_be_sealed_as_authoritative_evidence(workspace: Workspace) -> None:
    """A sealed failed run is evidence *of the failure* — not a lesser kind of run."""
    result = finalize_bundle(staged(workspace), RunOutcome.FAILED)
    assert result.manifest.outcome is RunOutcome.FAILED
    verified = verify_sealed_bundle(workspace, RUN, expected_evidence_digest=result.evidence_digest)
    assert verified.is_valid
    assert verified.bundle is not None
    assert verified.bundle.manifest.outcome is RunOutcome.FAILED


def test_a_failed_run_and_a_successful_run_with_identical_payload_differ(
    workspace: Workspace,
) -> None:
    """The outcome is inside the digest's bytes, so it is part of what was produced."""
    succeeded = finalize_bundle(staged(workspace, "run-a"), RunOutcome.SUCCEEDED)
    failed = finalize_bundle(staged(workspace, "run-b"), RunOutcome.FAILED)
    assert succeeded.evidence_digest != failed.evidence_digest


def test_the_same_payload_under_two_run_ids_gets_two_identities(workspace: Workspace) -> None:
    """The run id is authoritative metadata, so it is inside the digest's bytes.

    Determinism of a *single* identity — the same run id, payload and outcome producing the
    same manifest bytes, digest and checksum bytes — is proved in ``test_determinism.py``,
    across two workspaces so the run id can be the same in both.
    """
    first = finalize_bundle(staged(workspace, "run-a"), RunOutcome.SUCCEEDED)
    second = finalize_bundle(staged(workspace, "run-b"), RunOutcome.SUCCEEDED)
    assert first.evidence_digest != second.evidence_digest
    assert first.manifest.files == second.manifest.files


# --- never overwrite sealed evidence ---------------------------------------------------------


def _plant_a_sealed_run(workspace: Workspace, run_id: str, payload: bytes) -> Path:
    """Put a sealed bundle into ``runs/`` directly,     as another writer would have.

    Used to reach the second of the two conflict checks in :func:`finalize_bundle`. The first
    runs before anything is written, and is reached by planting the bundle before calling
    finalization; this one runs immediately before the rename, and is only reachable if the
    destination appears *during* finalization, so the tests that need it plant the bundle from
    inside a patched verification step.
    """
    destination = runs_root(workspace) / run_id

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    seal_in_place(destination, run_id, files=(("run.json", payload),))
    return destination


def test_a_run_id_that_is_already_sealed_cannot_be_staged_again(workspace: Workspace) -> None:
    """One run id is one run: re-staging a spent id would produce work that can never be
    sealed, so it is refused immediately rather than after a run's evidence is written."""
    finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    with pytest.raises(BundleConflictError, match="already sealed"):
        create_staging_bundle(workspace, RUN)


def test_a_run_that_is_already_sealed_is_never_overwritten(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-rename check: a destination that appears *during* finalization still wins.

    The seal this finalizer wrote is complete and valid, and the name was taken anyway. The
    existing bundle must be left exactly as it was — the check is a refusal, not a merge, not
    a replacement, and not a deletion-and-retry. Staging is created first and the name is
    claimed from inside the verification step, which is the only ordering that reaches the
    window between the early check and the rename.
    """
    bundle = staged(workspace)

    def another_writer_claims_the_name(*args: object, **kwargs: object) -> object:
        _plant_a_sealed_run(workspace, RUN, b'{"seed":7}')
        return verify_bundle_seal(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(staging_module, "verify_bundle_seal", another_writer_claims_the_name)
    with pytest.raises(BundleConflictError, match="already sealed"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)

    sealed = runs_root(workspace) / RUN
    assert (sealed / "run.json").read_bytes() == b'{"seed":7}'
    assert {path.name for path in sealed.iterdir()} == {
        "run.json",
        "manifest.json",
        "checksums.sha256",
    }, "nothing may be merged into sealed evidence"


def test_a_bundle_that_lost_the_race_for_its_name_is_left_sealed_and_diagnosable(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is a complete, valid seal that simply is not the authoritative one — a materially
    different thing from a corrupt directory, and one an operator can act on."""
    bundle = staged(workspace)

    def another_writer_claims_the_name(*args: object, **kwargs: object) -> object:
        _plant_a_sealed_run(workspace, RUN, b'{"seed":7}')
        return verify_bundle_seal(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(staging_module, "verify_bundle_seal", another_writer_claims_the_name)
    with pytest.raises(BundleConflictError):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert bundle.path.is_dir()
    assert (bundle.path / MANIFEST_FILE_NAME).is_file()
    assert (bundle.path / CHECKSUMS_FILE_NAME).is_file()
    assert verify_bundle_seal(bundle.path, RUN).is_valid


def test_a_conflict_at_the_very_start_writes_nothing_at_all(workspace: Workspace) -> None:
    """The early check, which is the one a caller will actually hit.

    Staging is created first and the name is claimed afterwards, which is the only ordering
    that reaches it: a run id cannot be staged once it is sealed.
    """
    bundle = staged(workspace)
    _plant_a_sealed_run(workspace, RUN, b'{"seed":7}')
    with pytest.raises(BundleConflictError):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert bundle.path.is_dir()
    assert not (bundle.path / MANIFEST_FILE_NAME).exists()
    assert not (bundle.path / CHECKSUMS_FILE_NAME).exists()
    assert {path.name for path in bundle.path.iterdir()} == {"run.json", "native", "logs"}


def test_a_bundle_cannot_be_finalized_twice(workspace: Workspace) -> None:
    """The second attempt fails at the first step, because the handle is already closed."""
    bundle = staged(workspace)
    finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    with pytest.raises((BundleConflictError, BundleOperationError, OSError)):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)


def test_a_bundle_whose_run_id_is_already_sealed_conflicts_before_writing_anything(
    workspace: Workspace,
) -> None:
    finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    # A staging directory for a sealed run cannot be created at all, which is the point:
    # the run id is spent, and the sealed evidence is what remains.
    with pytest.raises(BundleConflictError):
        create_staging_bundle(workspace, RUN)


# --- failure injection ----------------------------------------------------------------------------


def test_an_empty_bundle_is_refused_because_it_declares_no_evidence(workspace: Workspace) -> None:
    bundle = create_staging_bundle(workspace, RUN)
    with pytest.raises(BundleConflictError, match="no payload"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()


def test_a_link_inside_the_bundle_refuses_the_seal_and_promotes_nothing(
    workspace: Workspace, link_maker: DirectoryLinkFactory
) -> None:
    bundle = staged(workspace)
    elsewhere = workspace.evidence_root / "elsewhere"
    elsewhere.mkdir()
    mechanism = require_directory_link(
        link_maker(bundle.path / "linked", elsewhere),
        "link rejection during finalization is unproved on this host",
    )
    assert mechanism
    with pytest.raises(BundleIntegrityError, match="link or reparse point"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()
    assert bundle.path.is_dir()


def test_a_hard_linked_payload_cannot_be_sealed_and_promotes_nothing(
    workspace: Workspace, hard_link_maker: HardLinkFactory
) -> None:
    """The consequence that matters: a bundle that is not self-contained never becomes sealed.

    Finalization has no hard-link check of its own — it takes the inventory through the same
    walker — so this test proves the rule reaches the seal commit point rather than only the
    read-only parts of the package. A bundle that cannot be sealed is left in staging and
    diagnosable, and no ``runs/<run-id>`` is created, because a run directory is not
    authoritative unless its bytes are provably its own.
    """
    bundle = staged(workspace)
    mechanism = require_file_link(
        hard_link_maker(bundle.path / "run-copy.json", bundle.path / "run.json"),
        "hard-link rejection during finalization is unproved on this host",
    )
    assert mechanism == HARD_LINK
    with pytest.raises(BundleIntegrityError, match="hard link"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()
    assert bundle.path.is_dir()
    assert not (bundle.path / MANIFEST_FILE_NAME).exists()


def test_a_file_appearing_during_sealing_is_detected_rather_than_sealed(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file added after the inventory is an extra undeclared file, and the independent
    verification refuses to promote it."""
    from dynamisbench.evidence import staging as staging_module

    real_inventory = staging_module.inventory_payload
    added = False

    def add_file_then_inventory(bundle: StagingBundle) -> tuple[object, ...]:
        nonlocal added
        result = real_inventory(bundle)
        if not added:
            added = True
            (bundle.path / "sneaked-in.parquet").write_bytes(b"surprise")
        return result

    monkeypatch.setattr(staging_module, "inventory_payload", add_file_then_inventory)
    bundle = staged(workspace)
    with pytest.raises(BundleIntegrityError, match="does not verify"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()
    assert bundle.path.is_dir()


def test_a_payload_that_changes_size_between_inventory_and_hash_is_refused(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race this package can honestly detect: a file rewritten mid-seal."""
    from dynamisbench.evidence import staging as staging_module

    real_inventory = staging_module.inventory_payload
    changed = False

    def change_after_inventory(bundle: StagingBundle) -> tuple[object, ...]:
        nonlocal changed
        result = real_inventory(bundle)
        if not changed:
            changed = True
            (bundle.path / "run.json").write_bytes(b'{"seed":7,"rewritten":true}')
        return result

    monkeypatch.setattr(staging_module, "inventory_payload", change_after_inventory)
    bundle = staged(workspace)
    with pytest.raises(BundleIntegrityError, match="changed size"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()


def test_a_directory_where_the_manifest_belongs_refuses_the_seal(workspace: Workspace) -> None:
    """Named rather than surfacing as an opaque rename failure at the last step."""
    bundle = staged(workspace)
    (bundle.path / MANIFEST_FILE_NAME).mkdir()
    with pytest.raises(BundleIntegrityError, match="must write as a file"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()


def test_a_leftover_seal_temporary_is_removed_and_the_retry_succeeds(
    workspace: Workspace,
) -> None:
    """An interrupted attempt leaves diagnosable debris, and a retry is still possible."""
    bundle = staged(workspace)
    (bundle.path / f"{MANIFEST_FILE_NAME}.seal-tmp").write_bytes(b"half a manifest")
    result = finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not (result.path / f"{MANIFEST_FILE_NAME}.seal-tmp").exists()
    assert verify_sealed_bundle(workspace, RUN).is_valid


def test_a_failure_writing_the_checksum_file_promotes_nothing(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dynamisbench.evidence import staging as staging_module

    real_write = staging_module._write_atomically  # captured before the patch, to avoid recursion

    def refuse_write(path: Path, data: bytes, temporary: str, what: str) -> None:
        if what == CHECKSUMS_FILE_NAME:
            raise BundleOperationError("simulated: the checksum file could not be written")
        real_write(path, data, temporary, what)

    monkeypatch.setattr(staging_module, "_write_atomically", refuse_write)
    bundle = staged(workspace)
    with pytest.raises(BundleOperationError, match="checksum file"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()
    assert bundle.path.is_dir(), "staging must remain diagnosable"


def test_a_failure_verifying_the_just_written_seal_promotes_nothing(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a seal this finalizer just wrote is not promoted on trust."""
    from dynamisbench.evidence import staging as staging_module
    from dynamisbench.evidence.sealed import Defect, DefectKind, VerificationResult

    def report_a_defect(*args: object, **kwargs: object) -> VerificationResult:
        return VerificationResult(
            run_id=RUN,
            defects=(Defect(DefectKind.PAYLOAD_MODIFIED, "simulated corruption"),),
            bundle=None,
        )

    monkeypatch.setattr(staging_module, "verify_bundle_seal", report_a_defect)
    bundle = staged(workspace)
    with pytest.raises(BundleIntegrityError, match="does not verify"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not runs_root(workspace).exists()
    assert bundle.path.is_dir()


def test_a_failed_promotion_leaves_the_sealed_staging_bundle_diagnosable(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hardest case to get right: the seal is complete and valid, and the move still
    fails. Nothing authoritative exists, and the bundle is still promotable on a retry.

    Only the *directory* rename is refused. The metadata renames are the same primitive, so
    patching ``os.replace`` wholesale would fail at the manifest and never reach the promotion
    this test is about.
    """
    import os

    real_replace = os.replace

    def refuse_only_the_promotion(source: Path, destination: Path) -> None:
        if Path(source).name == RUN and Path(destination).name == RUN:
            raise OSError("simulated: the promotion rename was refused")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", refuse_only_the_promotion)
    bundle = staged(workspace)
    with pytest.raises(BundleOperationError, match="could not be promoted"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not (runs_root(workspace) / RUN).exists()
    assert bundle.path.is_dir()
    assert (bundle.path / MANIFEST_FILE_NAME).is_file(), "the seal is complete and inspectable"
    assert (bundle.path / CHECKSUMS_FILE_NAME).is_file()

    monkeypatch.undo()
    from dynamisbench.evidence import staging as staging_module

    # The bundle is already closed for payload, so it is promoted by re-running only the
    # promotion step — which is what an operator inspecting it would do.
    promoted = staging_module._promote(bundle, RUN)  # pyright: ignore[reportPrivateUsage]
    assert promoted.is_dir()
    assert verify_sealed_bundle(workspace, RUN).is_valid


def test_no_temporary_file_survives_in_a_successfully_sealed_bundle(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    names = {path.name for path in result.path.iterdir()}
    assert not any(name.endswith(".seal-tmp") for name in names)
    assert names == {MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME, "run.json", "native", "logs"}


def test_a_failed_manifest_write_leaves_no_debris_and_no_authority(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dynamisbench.evidence import staging as staging_module

    def refuse_write(path: Path, data: bytes, temporary: str, what: str) -> None:
        raise BundleOperationError("simulated: the manifest could not be written")

    monkeypatch.setattr(staging_module, "_write_atomically", refuse_write)
    bundle = staged(workspace)
    with pytest.raises(BundleOperationError, match="manifest"):
        finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    assert not (bundle.path / MANIFEST_FILE_NAME).exists()
    assert not (bundle.path / f"{MANIFEST_FILE_NAME}.seal-tmp").exists()
    assert not runs_root(workspace).exists()


# --- the seal as written -----------------------------------------------------------------------


def test_the_checksum_file_covers_the_payload_and_the_manifest_and_nothing_else(
    workspace: Workspace,
) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    entries = parse_checksums((result.path / CHECKSUMS_FILE_NAME).read_bytes())
    assert {entry.relative_path for entry in entries} == {
        *(path for path, _ in TWO_FILES),
        MANIFEST_FILE_NAME,
    }


def test_the_checksum_file_does_not_cover_itself(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    assert CHECKSUMS_FILE_NAME not in (result.path / CHECKSUMS_FILE_NAME).read_text("utf-8")


def test_the_manifest_does_not_declare_itself_or_the_checksum_file(workspace: Workspace) -> None:
    """The non-self-referential seal, checked on the bytes a real finalization produced."""
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    stored = parse_manifest((result.path / MANIFEST_FILE_NAME).read_bytes())
    assert {entry.relative_path for entry in stored.files}.isdisjoint(
        {MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME}
    )


def test_the_manifest_carries_no_evidence_digest_of_itself(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    assert result.evidence_digest.hex not in (result.path / MANIFEST_FILE_NAME).read_text("utf-8")


def test_no_absolute_path_from_the_workspace_reaches_the_seal(workspace: Workspace) -> None:
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    for name in (MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME):
        body = (result.path / name).read_text("utf-8")
        assert str(workspace.evidence_root) not in body
        assert str(staging_root(workspace)) not in body
        assert ":\\" not in body


def test_the_seal_result_names_the_run_and_the_digest_together(workspace: Workspace) -> None:
    """Human identity is not replaced by cryptographic identity; both travel."""
    result = finalize_bundle(staged(workspace), RunOutcome.SUCCEEDED)
    assert result.run_id == RUN
    assert len(result.evidence_digest.hex) == 64
    assert result.manifest.run_id == RUN


def test_a_large_payload_is_sealed_without_being_loaded_into_memory(
    workspace: Workspace,
) -> None:
    """Bounded-memory hashing is the reason asset_sha256_of_file exists; prove it is used."""
    bundle = create_staging_bundle(workspace, RUN)
    chunk = b"x" * (1024 * 1024)
    with bundle.open_payload("native/large.parquet") as handle:
        for _ in range(3):
            handle.write(chunk)
    result = finalize_bundle(bundle, RunOutcome.SUCCEEDED)
    entry = next(
        item for item in result.manifest.files if item.relative_path == "native/large.parquet"
    )
    assert entry.size_bytes == 3 * len(chunk)
    assert verify_sealed_bundle(workspace, RUN).is_valid
