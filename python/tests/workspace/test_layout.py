"""Two independent roots, a declared layout, and an open that changes nothing.

The properties checked here are the ones a caller has to be able to rely on before any
evidence exists: that source authority and evidence are separate places, that every
persistence class declares what it is for, that the declared locations are the ones the
architecture names, and — the one that would poison everything downstream — that opening
and inspecting a workspace performs no filesystem mutation whatsoever.

None of these tests hash anything. That a workspace's *location* is operational state
rather than scientific identity is proved where it can bite, against the RES-229 semantic
digest, in ``test_identity_invariance.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dynamisbench.workspace import (
    CLASS_LOCATION_SEGMENTS,
    CLASS_SEMANTICS,
    INITIALISED_CLASSES,
    LogicalReference,
    PersistenceClass,
    SourceCategory,
    WorkspaceError,
    WorkspaceRootError,
    open_workspace,
)
from tests.workspace.links import UNAVAILABLE, DirectoryLinkFactory

AUTHORITATIVE_CLASSES = frozenset(
    persistence_class
    for persistence_class, semantics in CLASS_SEMANTICS.items()
    if semantics.authoritative
)
"""Source authority and sealed evidence, and nothing else (ADR-004, ADR-021)."""

DISPOSABLE_CLASSES = frozenset(
    persistence_class
    for persistence_class, semantics in CLASS_SEMANTICS.items()
    if semantics.disposable
)


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Three independent directories standing in for the three roots."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    user_state = tmp_path / "user-state"
    for directory in (source, evidence, user_state):
        directory.mkdir()
    return source, evidence, user_state


@pytest.fixture
def workspace(roots: tuple[Path, Path, Path]) -> Any:
    source, evidence, user_state = roots
    return open_workspace(source, evidence, user_state_root=user_state)


def tree(root: Path) -> set[str]:
    """Every path beneath ``root``, as portable ``/``-separated relative names.

    Used to prove that an operation changed nothing. Names are recorded relative to
    ``root`` so that the comparison is about *what exists*, not about where the temporary
    directory happened to be created.
    """
    return {path.relative_to(root).as_posix() for path in root.rglob("*")} | {""}


def test_source_and_evidence_roots_are_independent_directories(roots: tuple[Path, ...]) -> None:
    source, evidence, _ = roots
    workspace = open_workspace(source, evidence)
    assert workspace.source_root != workspace.evidence_root
    assert workspace.source_root == source.resolve()
    assert workspace.evidence_root == evidence.resolve()
    assert not workspace.evidence_is_inside_source


def test_evidence_may_be_nested_inside_source_and_is_reported_as_such(
    tmp_path: Path,
) -> None:
    """Nesting is a legitimate layout — a repository may keep evidence in a gitignored
    subtree — but it is worth a surface reporting, so it is never silent."""
    source = tmp_path / "repo"
    evidence = source / "evidence"
    evidence.mkdir(parents=True)
    workspace = open_workspace(source, evidence)
    assert workspace.evidence_is_inside_source
    assert workspace.evidence_root == evidence.resolve()


def test_the_two_scientific_roots_may_not_be_the_same_directory(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    with pytest.raises(WorkspaceRootError, match="different directories"):
        open_workspace(shared, shared)


def test_a_root_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(WorkspaceRootError, match="not an existing directory"):
        open_workspace(tmp_path / "absent", evidence)


def test_a_root_that_is_a_file_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_text("not a directory", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(WorkspaceRootError, match="not an existing directory"):
        open_workspace(source, evidence)


def test_a_root_is_resolved_so_the_authorised_directory_is_its_real_target(
    tmp_path: Path,
    link_maker: DirectoryLinkFactory,
) -> None:
    """The authorised directory is the one the root *names*, not a link to it, so a root
    that is itself a link cannot later be re-pointed and inherit the authorisation."""
    target = tmp_path / "target"
    target.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    link = tmp_path / "link"
    mechanism = link_maker(link, target)
    if mechanism == UNAVAILABLE:
        pytest.fail("no directory-link mechanism is available on this host")

    workspace = open_workspace(link, evidence)
    assert workspace.source_root == target.resolve()
    assert workspace.source_root != link


def test_user_state_must_be_outside_scientific_authority(tmp_path: Path) -> None:
    """Preferences may neither live inside authority nor contain it, so no cleanup
    routine scoped to product state can reach an evidence bundle."""
    source = tmp_path / "source"
    source.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    inside = source / "prefs"
    inside.mkdir()

    with pytest.raises(WorkspaceRootError, match="outside scientific authority"):
        open_workspace(source, evidence, user_state_root=inside)
    with pytest.raises(WorkspaceRootError, match="outside scientific authority"):
        open_workspace(source, evidence, user_state_root=tmp_path)


def test_user_state_is_optional_and_absent_by_default(roots: tuple[Path, ...]) -> None:
    source, evidence, _ = roots
    workspace = open_workspace(source, evidence)
    assert workspace.user_state_root is None


def test_every_persistence_class_declares_a_location() -> None:
    assert set(CLASS_LOCATION_SEGMENTS) == set(PersistenceClass)
    assert set(CLASS_SEMANTICS) == set(PersistenceClass)


def test_only_source_authority_and_sealed_evidence_are_authoritative() -> None:
    assert AUTHORITATIVE_CLASSES == {
        PersistenceClass.SOURCE_AUTHORITY,
        PersistenceClass.SEALED_EVIDENCE,
    }


def test_disposable_state_is_never_authoritative() -> None:
    """Deleting a derived projection, a cache, scratch space, or product preferences must
    not be able to destroy scientific meaning (ADR-010, RES-230 invariant)."""
    assert DISPOSABLE_CLASSES == {
        PersistenceClass.DERIVED,
        PersistenceClass.CACHE,
        PersistenceClass.TMP,
        PersistenceClass.USER_STATE,
    }
    assert not DISPOSABLE_CLASSES & AUTHORITATIVE_CLASSES


def test_authority_is_never_mutable_or_disposable() -> None:
    for persistence_class in AUTHORITATIVE_CLASSES:
        semantics = CLASS_SEMANTICS[persistence_class]
        assert not semantics.mutable
        assert not semantics.disposable


def test_staging_is_mutable_but_not_disposable() -> None:
    """An abandoned staging directory is incomplete work whose fate is a scientific
    decision, not a cache entry: RES-231 decides whether it is sealed as a failed
    outcome or discarded."""
    staging = CLASS_SEMANTICS[PersistenceClass.STAGING]
    assert staging.mutable
    assert not staging.authoritative
    assert not staging.disposable


def test_sealed_staging_derived_cache_and_tmp_are_distinguishable_in_the_api() -> None:
    """Sealed evidence, staging, derived state, cache, and scratch space must never be
    nameable as one another."""
    distinguishable = {
        PersistenceClass.SEALED_EVIDENCE,
        PersistenceClass.STAGING,
        PersistenceClass.DERIVED,
        PersistenceClass.CACHE,
        PersistenceClass.TMP,
    }
    assert distinguishable <= set(PersistenceClass)
    assert len({PersistenceClass(persistence_class) for persistence_class in distinguishable}) == 5
    locations = {class_location for class_location in CLASS_LOCATION_SEGMENTS.values()}
    assert len(locations) == len(set(locations)), "two classes share one directory"


def test_the_layout_is_the_one_the_architecture_names(workspace: Any) -> None:
    evidence = workspace.evidence_root
    assert workspace.location(PersistenceClass.SOURCE_AUTHORITY).path == workspace.source_root
    assert workspace.location(PersistenceClass.SEALED_EVIDENCE).path == evidence / "runs"
    assert workspace.location(PersistenceClass.STAGING).path == evidence / ".staging"
    assert workspace.location(PersistenceClass.DERIVED).path == evidence / "derived"
    assert workspace.location(PersistenceClass.CACHE).path == evidence / "cache"
    assert workspace.location(PersistenceClass.TMP).path == evidence / "tmp"


def test_every_source_category_is_under_the_source_root(workspace: Any) -> None:
    for category in SourceCategory:
        location = workspace.source_location(category)
        assert location.persistence_class is PersistenceClass.SOURCE_AUTHORITY
        assert location.source_category is category
        assert location.path == workspace.source_root / category.value
        assert location.authoritative


def test_the_source_side_accommodates_the_project_concepts(workspace: Any) -> None:
    assert {category.value for category in SourceCategory} == {
        "benchmarks",
        "realizations",
        "studies",
        "references",
        "schemas",
    }


def test_evidence_classes_live_under_the_evidence_root(workspace: Any) -> None:
    for persistence_class in (
        PersistenceClass.SEALED_EVIDENCE,
        PersistenceClass.STAGING,
        PersistenceClass.DERIVED,
        PersistenceClass.CACHE,
        PersistenceClass.TMP,
    ):
        assert workspace.location(persistence_class).root == workspace.evidence_root


def test_locations_expose_their_authority_contract(workspace: Any) -> None:
    sealed = workspace.location(PersistenceClass.SEALED_EVIDENCE)
    assert (sealed.authoritative, sealed.mutable, sealed.disposable) == (True, False, False)
    derived = workspace.location(PersistenceClass.DERIVED)
    assert (derived.authoritative, derived.mutable, derived.disposable) == (False, True, True)


def test_a_logical_reference_carries_no_machine_specific_content() -> None:
    """The portable name is what may be stored, sent to an API, and compared across
    workspaces. It must not embed an absolute path, a drive, a separator root, or ``..``."""
    for persistence_class in PersistenceClass:
        for parts in (CLASS_LOCATION_SEGMENTS[persistence_class], ()):
            reference = LogicalReference(persistence_class, parts)
            text = reference.text
            assert "\\" not in text
            assert not text.startswith("/")
            assert ".." not in text.split("/")
            assert all(part not in {".", "..", ""} for part in reference.parts)
            assert reference.is_root is (not parts)
            assert str(reference) == text


def test_a_logical_reference_is_identical_across_relocated_workspaces(
    roots: tuple[Path, Path, Path],
) -> None:
    source, evidence, user_state = roots
    elsewhere = source.parent / "somewhere-else-on-another-machine"
    elsewhere.mkdir()
    other_evidence = source.parent / "other-evidence"
    other_evidence.mkdir()

    here = open_workspace(source, evidence, user_state_root=user_state)
    there = open_workspace(elsewhere, other_evidence, user_state_root=user_state)

    for persistence_class in (PersistenceClass.SEALED_EVIDENCE, PersistenceClass.STAGING):
        assert here.location(persistence_class).reference == (
            there.location(persistence_class).reference
        )
        assert here.location(persistence_class).path != there.location(persistence_class).path
    assert here.source_location(SourceCategory.BENCHMARKS).reference == (
        there.source_location(SourceCategory.BENCHMARKS).reference
    )
    assert here.source_location(SourceCategory.BENCHMARKS).path != (
        there.source_location(SourceCategory.BENCHMARKS).path
    )


def test_a_workspace_without_a_user_state_root_has_no_user_state_location(
    roots: tuple[Path, ...],
) -> None:
    source, evidence, _ = roots
    workspace = open_workspace(source, evidence)
    with pytest.raises(WorkspaceRootError, match="no user state root"):
        workspace.location(PersistenceClass.USER_STATE)


def test_a_declared_user_state_root_is_the_user_state_location(
    workspace: Any,
) -> None:
    location = workspace.location(PersistenceClass.USER_STATE)
    assert location.path == workspace.user_state_root
    assert location.reference.is_root
    assert location.disposable
    assert not location.authoritative


def test_an_undeclared_class_or_category_is_refused(workspace: Any) -> None:
    with pytest.raises(WorkspaceError, match="unknown persistence class"):
        workspace.location("not-a-class")  # type: ignore[arg-type]
    with pytest.raises(WorkspaceError, match="unknown source category"):
        workspace.source_location("not-a-category")  # type: ignore[arg-type]


def test_inspection_creates_nothing(roots: tuple[Path, ...]) -> None:
    """Opening and inspecting are reads. A caller may ask whether a workspace is set up
    without that question being the thing that sets it up."""
    source, evidence, user_state = roots
    before = tree(source.parent)

    workspace = open_workspace(source, evidence, user_state_root=user_state)
    report = workspace.inspect()
    open_workspace(source, evidence, user_state_root=user_state).inspect()

    assert tree(source.parent) == before
    assert report.existing_classes == {
        PersistenceClass.SOURCE_AUTHORITY,
        PersistenceClass.USER_STATE,
    }
    assert report.existing_sources == frozenset()


def test_inspection_reports_what_is_missing_and_what_exists(workspace: Any) -> None:
    report = workspace.inspect()
    assert report.missing_classes == (
        PersistenceClass.SEALED_EVIDENCE,
        PersistenceClass.STAGING,
        PersistenceClass.DERIVED,
        PersistenceClass.CACHE,
        PersistenceClass.TMP,
    )
    assert report.missing_sources == tuple(SourceCategory)
    assert {location.persistence_class for location in report.locations} == set(PersistenceClass)

    workspace.location(PersistenceClass.CACHE).path.mkdir()
    (workspace.source_root / SourceCategory.SCHEMAS.value).mkdir()
    updated = workspace.inspect()
    assert updated.existing_classes == {
        PersistenceClass.SOURCE_AUTHORITY,
        PersistenceClass.CACHE,
        PersistenceClass.USER_STATE,
    }
    assert updated.existing_sources == {SourceCategory.SCHEMAS}
    assert updated.missing_classes == (
        PersistenceClass.SEALED_EVIDENCE,
        PersistenceClass.STAGING,
        PersistenceClass.DERIVED,
        PersistenceClass.TMP,
    )
    assert updated.missing_sources == (
        SourceCategory.BENCHMARKS,
        SourceCategory.REALIZATIONS,
        SourceCategory.STUDIES,
        SourceCategory.REFERENCES,
    )


def test_inspection_includes_user_state_only_when_it_is_declared(
    roots: tuple[Path, Path, Path],
) -> None:
    source, evidence, user_state = roots
    without = open_workspace(source, evidence).inspect()
    with_state = open_workspace(source, evidence, user_state_root=user_state).inspect()
    assert PersistenceClass.USER_STATE not in without.existing_classes
    assert PersistenceClass.USER_STATE in with_state.existing_classes


def test_initialisation_declares_only_mutable_non_authoritative_classes() -> None:
    """``runs/`` is not created, because an empty directory is not sealed evidence and
    the first authoritative bundle arrives by the promotion RES-231 owns; the source
    root's categories are not created wholesale, because version-controlled content is
    added by a repository; and product preferences are never created here."""
    assert INITIALISED_CLASSES == (
        PersistenceClass.STAGING,
        PersistenceClass.DERIVED,
        PersistenceClass.CACHE,
        PersistenceClass.TMP,
    )
    assert not set(INITIALISED_CLASSES) & AUTHORITATIVE_CLASSES
    assert PersistenceClass.USER_STATE not in INITIALISED_CLASSES
    assert all(
        CLASS_SEMANTICS[persistence_class].mutable for persistence_class in INITIALISED_CLASSES
    )
