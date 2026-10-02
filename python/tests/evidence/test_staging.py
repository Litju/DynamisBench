"""The staging bundle: one run, one directory, writes refused after finalization begins.

The properties here are the ones a caller must be able to rely on while a run is still
happening, and the ones that stop being true the moment this package gets them wrong:

* **One directory per run, created and never adopted.** A ``.staging/<run-id>`` that
  already exists is a conflict, because it may be a half-written bundle from an interrupted
  execution, and appending to it would produce a manifest describing two runs' work.
* **Writes are scoped by the workspace resolver.** A payload path cannot escape, cannot be
  absolute, and cannot name a file outside the staging root — and the proof is that the
  RES-230 resolver was used, not that this module re-checked it.
* **A closed bundle stays closed.** Once finalization begins the handle refuses payload, so
  a writer holding a stale reference cannot add a file to a bundle whose inventory has
  already been taken.
* **The inventory is deterministic and complete.** Same files in, same snapshot out,
  whatever order they were written in; the reserved seal names are not payload; a link, a
  hard-linked file, an irregular file, or an unnameable file makes the bundle unsealable.
* **Nothing is ever deleted.** There is no method to remove a staging bundle, which is what
  keeps "the run was interrupted" and "the application tidied up" from being the same event.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamisbench.evidence import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    BundleConflictError,
    BundleIntegrityError,
    BundleNamingError,
    create_staging_bundle,
)
from dynamisbench.evidence.staging import StagingBundle, inventory_payload
from dynamisbench.workspace import PersistenceClass, Workspace
from tests.evidence.links import HARD_LINK, HardLinkFactory, require_file_link
from tests.workspace.links import DirectoryLinkFactory, require_directory_link


def make_bundle(workspace: Workspace, run_id: str = "run-1") -> StagingBundle:
    return create_staging_bundle(workspace, run_id)


def test_a_new_staging_bundle_exists_where_the_workspace_declares(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    declared = workspace.location(PersistenceClass.STAGING).path
    assert bundle.path == declared / "run-1"
    assert bundle.path.is_dir()


def test_the_staging_location_is_created_when_a_workspace_was_only_opened(
    workspace: Workspace,
) -> None:
    """A caller does not have to initialize a workspace before it can start a run."""
    import shutil

    shutil.rmtree(workspace.location(PersistenceClass.STAGING).path)
    bundle = make_bundle(workspace, "run-x")
    assert bundle.path.is_dir()


def test_the_portable_reference_names_staging_without_the_machine(workspace: Workspace) -> None:
    """The reference is the name; the repr says which one and whether it still takes writes."""
    bundle = make_bundle(workspace)
    assert bundle.reference.text == ".staging/run-1"
    assert repr(bundle) == "<StagingBundle '.staging/run-1' (open)>"
    bundle.close_for_payload()
    assert repr(bundle) == "<StagingBundle '.staging/run-1' (closed for payload)>"


def test_creating_a_staging_bundle_that_already_exists_is_a_conflict(workspace: Workspace) -> None:
    make_bundle(workspace)
    with pytest.raises(BundleConflictError):
        make_bundle(workspace)


def test_an_existing_staging_directory_is_never_adopted(workspace: Workspace) -> None:
    """Adopting it would let two runs share one manifest, or lose a file either wrote."""
    staging = workspace.location(PersistenceClass.STAGING).path / "run-1"
    staging.mkdir(parents=True)
    (staging / "run.json").write_bytes(b"{}")
    with pytest.raises(BundleConflictError):
        make_bundle(workspace)
    assert (staging / "run.json").read_bytes() == b"{}"


def test_a_malformed_run_id_is_refused_before_anything_is_created(
    workspace: Workspace,
) -> None:
    with pytest.raises(BundleNamingError):
        create_staging_bundle(workspace, "../escape")
    assert not (workspace.location(PersistenceClass.STAGING).path / "escape").exists()


# --- writing payload -------------------------------------------------------------------------


def test_a_written_payload_lands_at_the_requested_relative_path(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    written = bundle.write_payload("native/table.parquet", b"PAR1")
    assert written == bundle.path / "native" / "table.parquet"
    assert written.read_bytes() == b"PAR1"


def test_a_streamed_payload_is_fully_written_and_closed(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    with bundle.open_payload("canonical/vgrf.parquet") as handle:
        handle.write(b"first")
        handle.write(b"second")
    assert (bundle.path / "canonical" / "vgrf.parquet").read_bytes() == b"firstsecond"


def test_a_payload_path_cannot_escape_the_staging_root(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    with pytest.raises(BundleNamingError):
        bundle.write_payload("../../escaped.json", b"{}")


def test_an_absolute_payload_path_is_refused(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    outside = workspace.evidence_root / "outside.json"
    with pytest.raises(BundleNamingError):
        bundle.write_payload(str(outside), b"{}")
    assert not outside.exists()


def test_a_payload_cannot_be_written_under_the_seal_metadata_names(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    for name in (MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME):
        with pytest.raises(BundleNamingError):
            bundle.write_payload(name, b"{}")


def test_a_closed_bundle_refuses_new_payload(workspace: Workspace) -> None:
    """The reason the handle is an object and not a record: a stale writer must not win."""
    bundle = make_bundle(workspace)
    bundle.write_payload("run.json", b"{}")
    bundle.close_for_payload()
    assert not bundle.accepts_payload
    with pytest.raises(BundleConflictError):
        bundle.write_payload("late.json", b"{}")
    with pytest.raises(BundleConflictError):
        with bundle.open_payload("late.json"):
            pass
    assert not (bundle.path / "late.json").exists()


def test_closing_a_bundle_twice_is_harmless(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    bundle.close_for_payload()
    bundle.close_for_payload()
    assert not bundle.accepts_payload


# --- inventory -------------------------------------------------------------------------------


def test_an_empty_bundle_has_an_empty_inventory(workspace: Workspace) -> None:
    assert make_bundle(workspace).payload_inventory() == ()


def test_the_inventory_holds_every_written_payload(workspace: Workspace) -> None:
    bundle = make_bundle(workspace)
    bundle.write_payload("run.json", b"{}")
    bundle.write_payload("logs/solver.log", b"x" * 10)
    bundle.write_payload("native/a.parquet", b"y" * 3)
    inventory = bundle.payload_inventory()
    assert {item.relative_path for item in inventory} == {
        "run.json",
        "logs/solver.log",
        "native/a.parquet",
    }
    assert {item.relative_path: item.size_bytes for item in inventory}["run.json"] == 2


def test_the_inventory_is_ordered_by_path_not_by_write_order(workspace: Workspace) -> None:
    """Filesystem enumeration order must not reach the snapshot, let alone the manifest."""
    first = make_bundle(workspace, "run-a")
    for name in ("z/last.parquet", "a/first.parquet", "m/middle.parquet"):
        first.write_payload(name, b"x")
    second = make_bundle(workspace, "run-b")
    for name in ("m/middle.parquet", "z/last.parquet", "a/first.parquet"):
        second.write_payload(name, b"x")
    paths = [item.relative_path for item in first.payload_inventory()]
    assert paths == ["a/first.parquet", "m/middle.parquet", "z/last.parquet"]
    assert paths == [item.relative_path for item in second.payload_inventory()]


def test_the_inventory_excludes_the_reserved_seal_names(workspace: Workspace) -> None:
    """Leftovers from a failed attempt are not evidence, so they are not payload."""
    bundle = make_bundle(workspace)
    bundle.write_payload("run.json", b"{}")
    (bundle.path / MANIFEST_FILE_NAME).write_bytes(b"{}")
    (bundle.path / f"{MANIFEST_FILE_NAME}.seal-tmp").write_bytes(b"part")
    assert [item.relative_path for item in bundle.payload_inventory()] == ["run.json"]


def test_a_junction_inside_a_bundle_makes_it_unsealable(
    workspace: Workspace, link_maker: DirectoryLinkFactory
) -> None:
    """The realistic escape: a link planted where a payload directory should be.

    A directory junction is used because it needs no privilege on Windows, and it is the
    harder case anyway — ``is_symlink()`` reports a junction as an ordinary directory, so a
    symlink-only check would walk straight into it.
    """
    bundle = make_bundle(workspace)
    elsewhere = workspace.evidence_root / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "leak.json").write_bytes(b"{}")
    mechanism = require_directory_link(
        link_maker(bundle.path / "native", elsewhere),
        "link rejection inside a bundle is unproved on this host",
    )
    assert mechanism
    with pytest.raises(BundleIntegrityError, match="link or reparse point"):
        bundle.payload_inventory()


def test_a_hard_linked_payload_file_makes_a_bundle_unsealable(
    workspace: Workspace, hard_link_maker: HardLinkFactory
) -> None:
    """The other way out of a bundle: not a redirect, but a second way *in*.

    The inventory is where a run's payload is declared, so a file whose bytes are also
    reachable under a pathname the bundle never enumerated cannot be declared honestly — the
    manifest would describe content whose sealing guarantees the bundle cannot make. Refused
    through the shared walker, so the same rule reaches finalization and verification without
    either of them repeating the check.
    """
    bundle = make_bundle(workspace)
    bundle.write_payload("run.json", b'{"seed":7}')
    mechanism = require_file_link(
        hard_link_maker(bundle.path / "run-copy.json", bundle.path / "run.json"),
        "hard-link rejection inside a staging bundle is unproved on this host",
    )
    assert mechanism == HARD_LINK
    with pytest.raises(BundleIntegrityError, match="hard link"):
        bundle.payload_inventory()


def test_a_file_that_cannot_be_named_in_a_manifest_blocks_the_seal(
    workspace: Workspace,
) -> None:
    """A space in a name is outside the manifest language, so there is no manifest for it.

    Written directly rather than through the API, because the API refuses to write it —
    which is the point being tested from the other side: a bundle can be assembled behind
    the API's back, and the inventory has to notice.
    """
    bundle = make_bundle(workspace)
    (bundle.path / "solver 1.log").write_bytes(b"x")
    with pytest.raises(BundleIntegrityError, match="cannot be named in a manifest"):
        bundle.payload_inventory()


def test_a_reserved_name_used_as_a_directory_blocks_the_seal(workspace: Workspace) -> None:
    """A directory called ``manifest.json`` would make the atomic seal rename impossible."""
    bundle = make_bundle(workspace)
    (bundle.path / MANIFEST_FILE_NAME).mkdir()
    with pytest.raises(BundleIntegrityError, match="is a directory"):
        bundle.payload_inventory()


def test_inventory_of_a_bundle_root_that_is_a_file_is_refused(tmp_path: Path) -> None:
    from dynamisbench.evidence.bundle import walk_bundle

    target = tmp_path / "not-a-directory"
    target.write_bytes(b"")
    with pytest.raises(BundleIntegrityError, match="not a directory"):
        walk_bundle(target)


def test_inventory_payload_and_the_method_agree(workspace: Workspace) -> None:
    """One snapshot function, so the two entry points cannot drift apart."""
    bundle = make_bundle(workspace)
    bundle.write_payload("run.json", b"{}")
    assert inventory_payload(bundle) == bundle.payload_inventory()
