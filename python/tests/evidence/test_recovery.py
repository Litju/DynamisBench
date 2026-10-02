"""Finding and classifying the staging an interrupted run left behind.

Recovery is the moment when something is wrong with a workspace, so these tests are mostly
about what the discovery pass *does not* do:

* **It does not use a clock.** There is no age threshold, and the tests prove the
  classification is a function of a directory's contents and the caller's active set — by
  rewriting every file's timestamp and showing the report does not change.
* **It does not delete.** An abandoned staging directory is discovered and reported, and is
  still there afterwards. Whether it is sealed as a failure or discarded is a scientific
  decision, which is why staging is mutable but not disposable.
* **It does not sweep the disposable classes.** ``derived/``, ``cache/`` and ``tmp/`` are
  untouched, because a routine that could reach them could delete a DuckDB projection on the
  same pass.
* **It does not crash on a surprise.** A directory whose name is not a run id, or that cannot
  be classified, appears in the report as unrecognised — recovery is exactly when a discovery
  pass must not raise.
* **It does not confuse a failed run with an abandoned one.** A sealed failed run is
  authoritative evidence; a staging directory with no record is a recovery candidate.

The four states are the substance of the module, and each is produced from the directory's
own bytes: empty, in progress, interrupted seal, and a complete valid seal that was never
promoted.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from pathlib import Path

from dynamisbench.evidence import (
    MANIFEST_FILE_NAME,
    RunOutcome,
    StagingBundle,
    StagingState,
    create_staging_bundle,
    discover_staging,
    finalize_bundle,
    verify_sealed_bundle,
)
from dynamisbench.workspace import PersistenceClass, Workspace
from tests.evidence.links import HARD_LINK, HardLinkFactory, require_file_link
from tests.evidence.seal import SAMPLE_PAYLOAD, seal_in_place
from tests.workspace.links import DirectoryLinkFactory, require_directory_link

RUN = "run-1"


def staged(
    workspace: Workspace, run_id: str = RUN, files: tuple[tuple[str, bytes], ...] = SAMPLE_PAYLOAD
) -> StagingBundle:
    bundle = create_staging_bundle(workspace, run_id)
    for relative_path, data in files:
        bundle.write_payload(relative_path, data)
    return bundle


def states(workspace: Workspace, *, active_run_ids: Iterable[str] = ()) -> dict[str, StagingState]:
    return {
        item.run_id: item.state
        for item in discover_staging(workspace, active_run_ids=active_run_ids).candidates
    }


def staging_path(workspace: Workspace, run_id: str = RUN) -> Path:
    return workspace.location(PersistenceClass.STAGING).path / run_id


# --- the four states ------------------------------------------------------------------------------


def test_a_workspace_with_no_staging_reports_nothing(workspace: Workspace) -> None:
    report = discover_staging(workspace)
    assert report.candidates == ()
    assert report.unrecognised == ()
    assert not report


def test_an_empty_staging_directory_is_classified_as_empty(workspace: Workspace) -> None:
    """A run that was created and then died before writing anything."""
    create_staging_bundle(workspace, RUN)
    assert states(workspace) == {RUN: StagingState.EMPTY}


def test_payload_with_no_seal_metadata_is_in_progress(workspace: Workspace) -> None:
    staged(workspace)
    assert states(workspace) == {RUN: StagingState.IN_PROGRESS}


def test_a_manifest_with_no_checksum_file_is_an_interrupted_seal(workspace: Workspace) -> None:
    """Finalization wrote the manifest and died before the checksum file."""
    bundle = staged(workspace)
    manifest_path = bundle.path / MANIFEST_FILE_NAME
    manifest_path.write_bytes(b'{"schema_version":1}')
    assert states(workspace) == {RUN: StagingState.INTERRUPTED_SEAL}


def test_a_half_written_manifest_is_an_interrupted_seal(workspace: Workspace) -> None:
    bundle = staged(workspace)
    (bundle.path / f"{MANIFEST_FILE_NAME}.seal-tmp").write_bytes(b'{"schema_ver')
    assert states(workspace) == {RUN: StagingState.INTERRUPTED_SEAL}


def test_a_complete_valid_seal_left_in_staging_is_reported_as_sealed(workspace: Workspace) -> None:
    """The finalization finished and the promotion did not. Not a run yet, but a valid seal."""
    bundle = staged(workspace)
    seal_in_place(bundle.path, RUN)
    report = discover_staging(workspace)
    candidate = report.candidates[0]
    assert candidate.state is StagingState.SEALED_IN_STAGING
    assert candidate.seal is not None
    assert candidate.seal.run_id == RUN


def test_a_seal_whose_payload_was_altered_is_an_interrupted_seal_not_a_seal(
    workspace: Workspace,
) -> None:
    """An invalid seal is never offered as a promotable one, whatever it looks like."""
    bundle = staged(workspace)
    seal_in_place(bundle.path, RUN)
    (bundle.path / "run.json").write_bytes(b"tampered")
    report = discover_staging(workspace)
    assert report.candidates[0].state is StagingState.INTERRUPTED_SEAL
    assert report.candidates[0].seal is None
    assert report.promotable == ()


def test_a_failed_run_left_in_staging_is_a_sealed_candidate_with_its_outcome(
    workspace: Workspace,
) -> None:
    """A failed run with a complete record is a valid seal; its outcome travels with it."""
    bundle = staged(workspace)
    seal_in_place(bundle.path, RUN, outcome=RunOutcome.FAILED)
    candidate = discover_staging(workspace).candidates[0]
    assert candidate.state is StagingState.SEALED_IN_STAGING
    assert candidate.seal is not None
    assert candidate.seal.manifest.outcome is RunOutcome.FAILED


def test_an_empty_directory_is_not_a_recovery_candidate(workspace: Workspace) -> None:
    """There is no work to recover and no decision to make about a directory with nothing."""
    create_staging_bundle(workspace, RUN)
    assert discover_staging(workspace).recovery_candidates == ()


# --- active versus recovery -----------------------------------------------------------------------


def test_a_caller_can_declare_a_run_active(workspace: Workspace) -> None:
    staged(workspace)
    report = discover_staging(workspace, active_run_ids=[RUN])
    assert report.active[0].run_id == RUN
    assert report.recovery_candidates == ()


def test_a_run_that_is_not_active_is_a_recovery_candidate(workspace: Workspace) -> None:
    staged(workspace)
    report = discover_staging(workspace)
    assert report.recovery_candidates[0].run_id == RUN
    assert report.active == ()


def test_declaring_an_unknown_run_active_is_harmless(workspace: Workspace) -> None:
    """The active set is a statement about work, not a claim that a directory must exist."""
    staged(workspace)
    report = discover_staging(workspace, active_run_ids=["some-other-run"])
    assert report.candidates[0].run_id == RUN
    assert not report.candidates[0].active


def test_a_malformed_active_run_id_is_refused_rather_than_ignored(workspace: Workspace) -> None:
    from dynamisbench.evidence import BundleNamingError

    staged(workspace)
    try:
        discover_staging(workspace, active_run_ids=["../escape"])
    except BundleNamingError:
        return
    raise AssertionError("a malformed active run id must not be silently dropped")


# --- no clock --------------------------------------------------------------------------------


def test_classification_does_not_depend_on_how_old_a_directory_is(workspace: Workspace) -> None:
    """The central negative claim: no age threshold anywhere, and this is the proof.

    Every file in the staging tree is given a modification time two years in the past. A
    wall-clock heuristic would reclassify all of it as abandoned; a content-and-context
    classifier produces exactly the report it produced before.
    """
    staged(workspace, "run-payload")
    create_staging_bundle(workspace, "run-empty")
    bundle = staged(workspace, "run-sealed")
    seal_in_place(bundle.path, "run-sealed")
    before = states(workspace)
    assert before == {
        "run-empty": StagingState.EMPTY,
        "run-payload": StagingState.IN_PROGRESS,
        "run-sealed": StagingState.SEALED_IN_STAGING,
    }

    ancient = time.time() - 2 * 365 * 24 * 3600
    for path in workspace.location(PersistenceClass.STAGING).path.rglob("*"):
        os.utime(path, (ancient, ancient))

    assert states(workspace) == before


def test_the_report_is_reproducible_for_an_unchanged_workspace(workspace: Workspace) -> None:
    staged(workspace, "run-b")
    staged(workspace, "run-a")
    first = discover_staging(workspace, active_run_ids=["run-b"])
    second = discover_staging(workspace, active_run_ids=["run-b"])
    assert first == second
    assert [item.run_id for item in first.candidates] == ["run-a", "run-b"]


def test_discovery_never_deletes_anything(workspace: Workspace) -> None:
    """The whole point of staging being non-disposable: a report is not a cleanup."""
    staged(workspace)
    bundle_path = staging_path(workspace)
    before = {path.relative_to(bundle_path).as_posix() for path in bundle_path.rglob("*")}
    discover_staging(workspace)
    discover_staging(workspace, active_run_ids=[])
    after = {path.relative_to(bundle_path).as_posix() for path in bundle_path.rglob("*")}
    assert after == before


def test_discovery_never_touches_the_disposable_classes(workspace: Workspace) -> None:
    """A sweep that could reach derived/ or cache/ could delete a projection on the same pass."""
    marker = workspace.location(PersistenceClass.DERIVED).path / "projection.duckdb"
    marker.write_bytes(b"rebuildable")
    cache = workspace.location(PersistenceClass.CACHE).path / "computed.bin"
    cache.write_bytes(b"disposable")
    tmp = workspace.location(PersistenceClass.TMP).path / "scratch.bin"
    tmp.write_bytes(b"disposable")

    staged(workspace)
    report = discover_staging(workspace)
    assert [item.run_id for item in report.candidates] == [RUN]
    for path in (marker, cache, tmp):
        assert path.is_file()
        assert path.read_bytes()


# --- surprises are reported, not raised ---------------------------------------------------------


def test_a_directory_named_like_nothing_recognisable_is_reported_unrecognised(
    workspace: Workspace,
) -> None:
    staging = workspace.location(PersistenceClass.STAGING).path
    (staging / "not a run id").mkdir()
    (staging / "UPPERCASE").mkdir()
    (staging / "con").mkdir()
    report = discover_staging(workspace)
    assert report.unrecognised == ("UPPERCASE", "con", "not a run id")
    assert report.candidates == ()
    assert report, "a report with unrecognised entries is not empty"


def test_a_stray_file_in_staging_is_reported_unrecognised(workspace: Workspace) -> None:
    staging = workspace.location(PersistenceClass.STAGING).path
    (staging / "stray.txt").write_bytes(b"x")
    assert discover_staging(workspace).unrecognised == ("stray.txt",)


def test_a_junction_in_staging_is_reported_unrecognised(
    workspace: Workspace, link_maker: DirectoryLinkFactory
) -> None:
    """A redirected staging entry is not a run, and is not followed to find out what it is."""

    staging = workspace.location(PersistenceClass.STAGING).path
    elsewhere = workspace.evidence_root / "elsewhere"
    elsewhere.mkdir()
    mechanism = require_directory_link(
        link_maker(staging / "run-x", elsewhere),
        "link rejection during discovery is unproved on this host",
    )
    assert mechanism
    assert discover_staging(workspace).unrecognised == ("run-x",)


def test_a_staging_directory_holding_a_link_is_reported_unrecognised(
    workspace: Workspace, link_maker: DirectoryLinkFactory
) -> None:

    bundle = staged(workspace)
    elsewhere = workspace.evidence_root / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "leak.json").write_bytes(b"{}")
    mechanism = require_directory_link(
        link_maker(bundle.path / "linked", elsewhere),
        "link rejection during discovery is unproved on this host",
    )
    assert mechanism
    assert discover_staging(workspace).unrecognised == (RUN,)


def test_a_staging_directory_holding_a_hard_link_is_reported_unrecognised(
    workspace: Workspace, hard_link_maker: HardLinkFactory
) -> None:
    """Discovery must survive a bundle it is no longer allowed to classify.

    A hard-linked payload file makes the walk refuse the directory, and recovery treats a
    refusal as *unrecognised* rather than letting it escape: a discovery pass is exactly when
    a crash is least acceptable, because it is what a supervisor runs after an unclean
    shutdown. It also deletes nothing, so the diagnosis survives the pass.
    """
    bundle = staged(workspace)
    mechanism = require_file_link(
        hard_link_maker(bundle.path / "run-copy.json", bundle.path / "run.json"),
        "hard-link handling during discovery is unproved on this host",
    )
    assert mechanism == HARD_LINK
    report = discover_staging(workspace)
    assert report.unrecognised == (RUN,)
    assert not report.candidates
    assert bundle.path.is_dir()


def test_a_run_that_was_already_promoted_is_not_a_staging_candidate(workspace: Workspace) -> None:
    """Promotion moves the directory; there is nothing left in .staging/ to find."""
    staged(workspace, "still-staged")
    result = finalize_bundle(staged(workspace, "moved"), RunOutcome.SUCCEEDED)
    report = discover_staging(workspace)
    assert [item.run_id for item in report.candidates] == ["still-staged"]
    assert verify_sealed_bundle(workspace, result.run_id).is_valid


# --- a sealed failed run is not a recovery candidate --------------------------------------------


def test_a_sealed_failed_run_under_runs_is_not_reported_as_staging_work(
    workspace: Workspace,
) -> None:
    """It is authoritative evidence, not abandoned work, and must never be swept."""
    bundle = staged(workspace)
    result = finalize_bundle(bundle, RunOutcome.FAILED)
    assert discover_staging(workspace).candidates == ()
    assert verify_sealed_bundle(workspace, RUN).is_valid
    assert result.manifest.outcome is RunOutcome.FAILED


def test_the_report_names_a_candidate_by_portable_reference(workspace: Workspace) -> None:
    staged(workspace)
    candidate = discover_staging(workspace).candidates[0]
    assert candidate.reference.text == f".staging/{RUN}"
    assert str(workspace.evidence_root) not in candidate.reference.text
