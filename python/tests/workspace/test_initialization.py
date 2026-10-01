"""Creating a workspace on purpose, and losing the parts that may be lost.

Two properties are separated here, and conflating them is the failure this suite exists
to prevent.

**Creating is explicit.** Initialisation is the only operation that makes a directory
appear, so the caller who wants a workspace to exist says so and nowhere else, and what
appears is exactly the declared structure — nothing more. Opening and inspecting stay
side-effect free, so asking whether a workspace is set up is never the thing that sets it
up. The absence of ``runs/`` matters most: an empty directory is not sealed evidence, and
the first authoritative bundle belongs to the promotion RES-231 owns, so a workspace
initialised here is not yet holding authority and does not pretend to be.

**Losing is classed.** Derived state, cache, scratch space, and product preferences are
disposable, so removing them costs a rebuild and nothing else. Source authority and sealed
evidence are not, and the suite proves it by deleting everything disposable and showing
the authoritative bytes are still there, byte for byte. Staging sits deliberately between
the two: mutable, so it can be discarded, but *not* disposable, because whether an
interrupted execution is preserved or dropped is a scientific decision rather than a
cache eviction, and the API must say so to anything that writes a cleanup routine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dynamisbench.workspace import (
    INITIALISED_CLASSES,
    PathScopeError,
    PersistenceClass,
    SourceCategory,
    WorkspaceError,
    WorkspaceRootError,
    initialize_workspace,
    open_workspace,
)

DISPOSABLE_CLASSES = (
    PersistenceClass.DERIVED,
    PersistenceClass.CACHE,
    PersistenceClass.TMP,
)


def relative_tree(root: Path) -> set[str]:
    """Every path beneath ``root`` as a portable relative name, including ``root``."""
    names = {path.relative_to(root).as_posix() for path in [root, *root.rglob("*")]}
    return {"" if name == "." else name for name in names}


@pytest.fixture
def declared_workspace(tmp_path: Path):
    """A workspace created from nothing by the explicit initialisation operation."""
    return initialize_workspace(tmp_path / "source", tmp_path / "evidence")


def test_initialisation_creates_exactly_the_declared_structure(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")

    assert workspace.source_root == (tmp_path / "source").resolve()
    assert workspace.evidence_root == (tmp_path / "evidence").resolve()
    assert relative_tree(workspace.evidence_root) == {
        "",
        ".staging",
        "cache",
        "derived",
        "tmp",
    }
    assert relative_tree(workspace.source_root) == {""}


def test_initialisation_does_not_create_sealed_evidence(tmp_path: Path) -> None:
    """``runs/`` is not created: an empty directory is not sealed evidence, and the first
    authoritative bundle arrives by the promotion RES-231 owns."""
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    assert not workspace.location(PersistenceClass.SEALED_EVIDENCE).path.exists()
    assert PersistenceClass.SEALED_EVIDENCE not in INITIALISED_CLASSES


def test_initialisation_does_not_create_source_categories_wholesale(tmp_path: Path) -> None:
    """Version-controlled content is added by a repository, not by an application."""
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    assert not workspace.inspect().existing_sources


def test_initialisation_creates_only_the_source_categories_named(tmp_path: Path) -> None:
    workspace = initialize_workspace(
        tmp_path / "source",
        tmp_path / "evidence",
        sources=[SourceCategory.BENCHMARKS, SourceCategory.SCHEMAS],
    )
    assert relative_tree(workspace.source_root) == {"", "benchmarks", "schemas"}


def test_source_categories_are_created_in_canonical_order_regardless_of_request_order(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(
        tmp_path / "source",
        tmp_path / "evidence",
        sources=[SourceCategory.SCHEMAS, SourceCategory.BENCHMARKS, SourceCategory.SCHEMAS],
    )
    assert workspace.inspect().existing_sources == {
        SourceCategory.BENCHMARKS,
        SourceCategory.SCHEMAS,
    }


def test_initialisation_never_creates_a_user_state_root(tmp_path: Path) -> None:
    """The product owns that directory; this issue supplies only the boundary."""
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    assert workspace.user_state_root is None
    assert not (tmp_path / "preferences").exists()


def test_a_declared_user_state_root_is_never_created_but_is_opened(tmp_path: Path) -> None:
    preferences = tmp_path / "preferences"
    preferences.mkdir()
    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", user_state_root=preferences
    )
    assert workspace.user_state_root == preferences.resolve()
    assert relative_tree(preferences) == {""}


def test_initialisation_is_idempotent_and_reusable_to_grow_a_workspace(tmp_path: Path) -> None:
    first = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    before = relative_tree(first.evidence_root)

    second = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.STUDIES]
    )
    assert relative_tree(second.evidence_root) == before
    assert relative_tree(second.source_root) == {"", "studies"}
    assert second.evidence_root == first.evidence_root


def test_an_unusable_request_creates_nothing(tmp_path: Path) -> None:
    """Every root is settled before any directory is made, so a request that cannot
    produce a valid workspace leaves no half-built one behind."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"

    with pytest.raises(WorkspaceRootError, match="different directories"):
        initialize_workspace(source, source)
    assert not source.exists()

    with pytest.raises(WorkspaceError, match="unknown source categories"):
        initialize_workspace(source, evidence, sources=["benchmarks"])  # type: ignore[list-item]
    assert not source.exists()
    assert not evidence.exists()


def test_an_overlapping_user_state_root_is_refused_before_anything_is_created(
    tmp_path: Path,
) -> None:
    """Preferences inside scientific authority are refused before any directory is made,
    because discovering the overlap afterwards would leave a workspace holding product
    state inside authority."""
    evidence = tmp_path / "evidence"
    inside_evidence = evidence / "preferences"
    inside_evidence.mkdir(parents=True)

    with pytest.raises(WorkspaceRootError, match="outside scientific authority"):
        initialize_workspace(tmp_path / "source", evidence, user_state_root=inside_evidence)
    assert not (tmp_path / "source").exists()

    source = tmp_path / "source"
    inside_source = source / "preferences"
    inside_source.mkdir(parents=True)
    untouched_evidence = tmp_path / "untouched-evidence"
    with pytest.raises(WorkspaceRootError, match="outside scientific authority"):
        initialize_workspace(source, untouched_evidence, user_state_root=inside_source)
    assert not untouched_evidence.exists()


def test_opening_an_initialised_workspace_reports_it_ready(declared_workspace) -> None:
    report = declared_workspace.inspect()
    assert report.existing_classes == {
        PersistenceClass.SOURCE_AUTHORITY,
        PersistenceClass.STAGING,
        PersistenceClass.DERIVED,
        PersistenceClass.CACHE,
        PersistenceClass.TMP,
    }
    assert report.missing_classes == (PersistenceClass.SEALED_EVIDENCE,)
    assert report.missing_sources == tuple(SourceCategory)


def test_a_workspace_can_be_opened_again_with_the_same_declaration(tmp_path: Path) -> None:
    initialised = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.BENCHMARKS]
    )
    reopened = open_workspace(tmp_path / "source", tmp_path / "evidence")
    assert reopened.roots == initialised.roots
    assert reopened.location(PersistenceClass.CACHE).path == (
        initialised.location(PersistenceClass.CACHE).path
    )


def test_a_root_occupied_by_something_else_is_refused(tmp_path: Path) -> None:
    """A filesystem failure is reported, never swallowed into a workspace that looks
    ready."""
    evidence = tmp_path / "evidence"
    evidence.write_text("not a directory", encoding="utf-8")

    with pytest.raises(WorkspaceRootError, match="exists but is not a directory"):
        initialize_workspace(tmp_path / "source", evidence)
    assert not (tmp_path / "source").exists()


def test_deleting_disposable_state_leaves_authority_byte_for_byte(tmp_path: Path) -> None:
    """Deleting the derived projection, the cache, and scratch space costs a rebuild and
    nothing else (ADR-010)."""
    workspace = initialize_workspace(
        tmp_path / "source",
        tmp_path / "evidence",
        sources=[SourceCategory.BENCHMARKS, SourceCategory.REALIZATIONS],
    )
    specification = workspace.resolve_source(
        SourceCategory.REALIZATIONS, "realization_definition.mujoco.yaml"
    )
    specification.parent.mkdir(parents=True, exist_ok=True)
    specification.write_text("realization: authoritative\n", encoding="utf-8")

    sealed = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, "run-0001/manifest.json")
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_text('{"sealed": true}\n', encoding="utf-8")

    staged = workspace.resolve(PersistenceClass.STAGING, "run-0002/native/frames.parquet")
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"\x00\x01\x02native")

    for persistence_class in DISPOSABLE_CLASSES:
        location = workspace.location(persistence_class)
        location.path.mkdir(parents=True, exist_ok=True)
        (location.path / "projection.duckdb").write_bytes(b"derived")

    authority_before = {path: path.read_bytes() for path in (specification, sealed, staged)}

    for persistence_class in DISPOSABLE_CLASSES:
        shutil.rmtree(workspace.location(persistence_class).path)

    for path, content in authority_before.items():
        assert path.is_file()
        assert path.read_bytes() == content

    reopened = open_workspace(workspace.source_root, workspace.evidence_root)
    assert reopened.inspect().existing_classes >= {
        PersistenceClass.SOURCE_AUTHORITY,
        PersistenceClass.SEALED_EVIDENCE,
        PersistenceClass.STAGING,
    }


def test_a_recreated_derived_location_is_equivalent_to_a_deleted_one(tmp_path: Path) -> None:
    """Disposal is about losing the *contents*, not the location: a rebuilt projection is
    the same place, named the same way, with the same authority contract."""
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    before = workspace.location(PersistenceClass.DERIVED)

    shutil.rmtree(before.path)
    assert not before.path.exists()

    initialize_workspace(workspace.source_root, workspace.evidence_root)
    after = workspace.location(PersistenceClass.DERIVED)
    assert after.path == before.path
    assert after.reference == before.reference
    assert after.semantics == before.semantics
    assert after.disposable
    assert not after.authoritative


def test_staging_is_discarded_by_choice_never_as_a_rebuildable_projection(
    tmp_path: Path,
) -> None:
    """Staging can be thrown away, but it is not cache: the API must not advertise it as
    disposable, or a cleanup routine will delete the record of an interrupted execution."""
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    staging = workspace.location(PersistenceClass.STAGING)
    assert staging.mutable
    assert not staging.disposable
    assert not staging.authoritative
    assert staging.semantics != workspace.location(PersistenceClass.CACHE).semantics


def test_sealed_evidence_and_staging_are_separate_places_that_cannot_reach_each_other(
    tmp_path: Path,
) -> None:
    """A sealed run directory is never reused as mutable working storage, and neither
    location can be reached by naming the other."""
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    (workspace.location(PersistenceClass.SEALED_EVIDENCE).path / "run-0001").mkdir(parents=True)

    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.STAGING, "../runs/run-0001")
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.SEALED_EVIDENCE, "../.staging/run-0002")
    assert (
        workspace.location(PersistenceClass.SEALED_EVIDENCE).path
        != workspace.location(PersistenceClass.STAGING).path
    )


def test_source_authority_is_never_a_mutable_or_disposable_place(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source", tmp_path / "evidence")
    for category in SourceCategory:
        location = workspace.source_location(category)
        assert location.authoritative
        assert not location.mutable
        assert not location.disposable
        assert location.persistence_class is PersistenceClass.SOURCE_AUTHORITY
        assert location.semantics is (
            workspace.location(PersistenceClass.SOURCE_AUTHORITY).semantics
        )
