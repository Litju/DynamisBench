"""Safe discovery: what the walk finds, what it refuses, and what it never touches.

RES-377 exposes source authority through the API, so discovery is the first place a
workspace can be made to disclose something it should not. This suite holds the line
that makes that impossible rather than unlikely:

* **nothing but declared locations is walked.** No category that does not exist, no
  directory that is not a declared kind, no evidence, staging, derived, cache, tmp, or
  user-state content, and no suffix that is not ``.json``, ``.yaml`` or ``.yml``;
* **links are reported, never followed.** A directory link or junction inside a kind
  directory is a bounded structural issue and is not descended into; a document whose
  link resolves outside the authorised root is refused before its bytes are read, and
  the refusal does not say where it pointed;
* **the order is the walk's own, not the filesystem's.** Two discoveries of one
  workspace produce the same sequence, which is what lets an opaque identifier be
  stable across calls.

The walk is also read-only, and that is qualified directly: a full snapshot of the
workspace's names, sizes, and modification times is identical before and after every
operation in this suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dynamisbench.workspace import (
    SourceCategory,
    Workspace,
    initialize_workspace,
)
from dynamisbench.workspace.discovery import NON_SOURCE_DIRECTORIES, discover_sources
from dynamisbench.workspace.source_authority import (
    AuthoringFormat,
    DiagnosticCode,
    SourceLocator,
    inspect_locator,
)
from tests.workspace.authority_fixtures import KIND_CATEGORIES, write_document

ALL_KINDS = tuple(KIND_CATEGORIES)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return initialize_workspace(tmp_path / "source", tmp_path / "evidence")


def _snapshot(root: Path) -> dict[str, tuple[int, float]]:
    """Everything a walk could disturb: name, size, and modification time.

    Not a hash of contents. Discovery is qualified as *inert*, and a hash would only show
    that nothing changed in what the suite wrote; the size and the mtime are the facts a
    create, a rewrite, a normalisation, or a touch would move.
    """
    observed: dict[str, tuple[int, float]] = {}
    for entry in sorted(root.rglob("*")):
        key = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            observed[key] = (-1, -1)
            continue
        if entry.is_dir():
            observed[key] = (-1, -1)
            continue
        stat = entry.stat()
        observed[key] = (stat.st_size, stat.st_mtime)
    return observed


# --------------------------------------------------------------------------- #
# What discovery finds
# --------------------------------------------------------------------------- #
def test_every_declared_kind_is_discovered(workspace: Workspace) -> None:
    """The coverage matrix's layout half: one document per kind, in its own place."""
    source_root = workspace.source_root
    for kind in ALL_KINDS:
        write_document(source_root, kind, f"{kind}.json")

    found = discover_sources(workspace)
    references = [locator.logical_reference for locator in found.locators]

    assert len(found.locators) == len(ALL_KINDS)
    for kind in ALL_KINDS:
        category = KIND_CATEGORIES[kind]
        expected = f"{category.value}/{kind}/{kind}.json"
        assert expected in references


def test_all_three_suffixes_are_discovered(workspace: Workspace) -> None:
    for suffix in (".json", ".yaml", ".yml"):
        write_document(workspace.source_root, "scenario", f"case{suffix}")

    found = discover_sources(workspace)
    assert len(found.locators) == 3
    assert {locator.authoring_format for locator in found.locators} == {
        AuthoringFormat.JSON,
        AuthoringFormat.YAML,
    }


def test_a_document_below_a_kind_directory_is_discovered_at_any_depth(
    workspace: Workspace,
) -> None:
    """The declared layout is ``<category>/<kind>/**``, so depth is repository structure.

    A definition two directories below its kind is as authoritative as one at the top,
    and a reader that only looked at the top level would silently drop it.
    """
    write_document(workspace.source_root, "study", "nested/deeper/study.yaml")
    write_document(workspace.source_root, "study", "a.yaml")
    write_document(workspace.source_root, "study", "z.yaml")

    found = discover_sources(workspace)
    references = [locator.logical_reference for locator in found.locators]
    assert references == [
        "studies/study/a.yaml",
        "studies/study/nested/deeper/study.yaml",
        "studies/study/z.yaml",
    ]


def test_the_artifacts_are_in_a_documented_stable_order(workspace: Workspace) -> None:
    """Determinism is a property of the walk, not of the filesystem.

    Two walks of one workspace must agree, so that a client can diff one against the
    other and so that an identifier minted from this order stays valid.
    """
    for kind in ALL_KINDS:
        write_document(workspace.source_root, kind, f"{kind}.yaml", suffix=".yaml")

    first = [locator.logical_reference for locator in discover_sources(workspace).locators]
    second = [locator.logical_reference for locator in discover_sources(workspace).locators]

    assert first == second
    assert first == sorted(first)


def test_an_absent_category_is_reported_rather_than_searched(tmp_path: Path) -> None:
    """A workspace that has not been given every category yet is a normal state.

    The report says so without the walk pretending to have looked, and without creating
    anything.
    """
    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.STUDIES]
    )
    before = _snapshot(tmp_path)

    found = discover_sources(workspace)
    assert found.categories[0].category is SourceCategory.BENCHMARKS
    assert found.categories[0].exists is False
    assert found.categories[2].category is SourceCategory.STUDIES
    assert found.categories[2].exists is True
    assert not found.locators
    assert found.issues == ()
    assert _snapshot(tmp_path) == before


def test_an_empty_category_yields_no_artifacts_and_no_issues(tmp_path: Path) -> None:
    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.SCHEMAS]
    )
    found = discover_sources(workspace)
    assert found.categories[4].exists is True
    assert found.locators == ()
    assert found.issues == ()


# --------------------------------------------------------------------------- #
# What discovery refuses to walk
# --------------------------------------------------------------------------- #
def test_an_unknown_kind_directory_is_reported_not_walked(workspace: Workspace) -> None:
    """A directory the layout does not declare is a bounded issue.

    It is not reinterpreted as some other kind, because the directory's name is the only
    thing that says what a definition is. Refusing to guess is the whole rule.
    """
    category = KIND_CATEGORIES["benchmark"]
    (workspace.source_root / category.value / "not-a-kind").mkdir(parents=True)
    write_document(workspace.source_root, "scenario", "case.json")

    found = discover_sources(workspace)
    assert [locator.kind for locator in found.locators] == ["scenario"]
    assert len(found.issues) == 1
    issue = found.issues[0]
    assert issue.diagnostic.code is DiagnosticCode.UNSUPPORTED_ENTRY
    assert issue.category is category
    assert issue.reference == "not-a-kind"


def test_a_source_document_beside_a_kind_directory_is_reported(workspace: Workspace) -> None:
    """A ``.json`` directly under a category is misplaced, not an artifact of some kind."""
    category = KIND_CATEGORIES["quantity"]
    (workspace.source_root / category.value).mkdir(parents=True, exist_ok=True)
    path = workspace.source_root / category.value / "stray.json"
    path.write_text(json_text(), encoding="utf-8")

    found = discover_sources(workspace)
    assert not found.locators
    assert [issue.reference for issue in found.issues] == ["stray.json"]


def json_text() -> str:

    return json.dumps({"a": 1})


def test_a_non_authoring_file_is_not_a_candidate(workspace: Workspace) -> None:
    """Only the three declared suffixes are read. A realization's asset is not one.

    An ``.osim`` model or a ``.xml`` beside a definition belongs to that realization,
    which references it by workspace-relative path and digests its bytes separately; it
    is not itself a source-authority document.
    """
    write_document(workspace.source_root, "sut", "controller.sut.json")
    (workspace.source_root / "realizations" / "sut" / "subject.osim").write_bytes(
        b"binary model bytes"
    )
    (workspace.source_root / "realizations" / "sut" / "README.md").write_text(
        "notes", encoding="utf-8"
    )

    found = discover_sources(workspace)
    assert len(found.locators) == 1
    assert found.locators[0].logical_reference == "realizations/sut/controller.sut.json"


def test_the_walk_never_reads_a_non_source_persistence_class(workspace: Workspace) -> None:
    """Evidence, staging, derived, cache, tmp, and runs are not source authority.

    The walk starts at source categories, so these are unreachable by construction;
    the gate is stated anyway, because unreachable-by-construction is a property that
    decays the moment someone adds a second traversal.
    """
    for name in NON_SOURCE_DIRECTORIES:
        target = workspace.source_root / "studies" / "study" / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "secret.json").write_text(json_text(), encoding="utf-8")

    found = discover_sources(workspace)
    assert not found.locators
    assert not [
        locator.logical_reference
        for locator in found.locators
        for name in NON_SOURCE_DIRECTORIES
        if name in locator.logical_reference
    ]


# --------------------------------------------------------------------------- #
# Links: reported, never followed
# --------------------------------------------------------------------------- #
def test_a_directory_link_inside_a_kind_directory_is_not_followed(
    workspace: Workspace, tmp_path: Path
) -> None:
    """A link inside a workspace must not decide what that workspace exposes.

    The link is not descended into, and the issue names the kind directory rather than
    the target. ``require_directory_link`` states the mechanism used, so a host that
    permits neither says what is unproved instead of skipping silently.
    """
    from tests.workspace.links import make_directory_link, require_directory_link

    outside = tmp_path / "outside"
    (outside / "escape.json").parent.mkdir(parents=True, exist_ok=True)
    (outside / "escape.json").write_text(json_text(), encoding="utf-8")

    link = workspace.source_root / "benchmarks" / "scenario" / "linked"
    link.parent.mkdir(parents=True, exist_ok=True)
    mechanism = require_directory_link(
        make_directory_link(link, outside), "a directory symlink/junction escape"
    )

    found = discover_sources(workspace)
    assert not found.locators
    assert [issue.reference for issue in found.issues] == ["benchmarks/scenario/linked"]
    assert found.issues[0].diagnostic.code is DiagnosticCode.PATH_SCOPE_VIOLATION
    assert mechanism in {"junction", "symlink"}


def test_a_document_link_escaping_the_root_is_refused_not_read(
    workspace: Workspace, tmp_path: Path
) -> None:
    """The one case the walk cannot catch: a link that looks like a document."""
    from tests.workspace.links import make_directory_link

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "real-secret.json").write_text(json_text(), encoding="utf-8")

    inside = workspace.source_root / "benchmarks" / "scenario"
    inside.mkdir(parents=True, exist_ok=True)
    assert make_directory_link(inside / "document.json", outside) in {"junction", "symlink"}

    locator = SourceLocator(
        category=SourceCategory.BENCHMARKS, kind="scenario", segments=("scenario", "document.json")
    )
    inspection = inspect_locator(workspace, locator)

    assert inspection.valid is False
    assert inspection.diagnostics[0].code is DiagnosticCode.PATH_SCOPE_VIOLATION
    assert "secret" not in inspection.diagnostics[0].message
    assert str(outside) not in inspection.diagnostics[0].message


def test_a_traversal_reference_is_refused_by_the_reference_language(
    workspace: Workspace, tmp_path: Path
) -> None:
    """``../outside`` is refused before the filesystem is consulted."""
    (tmp_path / "outside.json").write_text(json_text(), encoding="utf-8")
    for segments in (
        ("scenario", "..", "outside.json"),
        ("scenario", "..", "..", "..", "evidence"),
    ):
        locator = SourceLocator(
            category=SourceCategory.BENCHMARKS, kind="scenario", segments=segments
        )
        inspection = inspect_locator(workspace, locator)
        assert inspection.valid is False
        assert inspection.diagnostics[0].code is DiagnosticCode.PATH_SCOPE_VIOLATION


def test_an_absolute_reference_is_refused(workspace: Workspace) -> None:
    """A drive, a UNC prefix, and an extended-length prefix are not reference language."""
    for prefix in ("C:\\", "\\\\server\\share\\", "\\\\?\\C:\\"):
        locator = SourceLocator(
            category=SourceCategory.BENCHMARKS,
            kind="scenario",
            segments=(f"{prefix}windows", "scenario"),
        )
        inspection = inspect_locator(workspace, locator)
        assert inspection.diagnostics[0].code is DiagnosticCode.PATH_SCOPE_VIOLATION, prefix


# --------------------------------------------------------------------------- #
# Discovery is inert, and locators are portable
# --------------------------------------------------------------------------- #
def test_discovery_and_inspection_change_nothing(workspace: Workspace) -> None:
    """The side-effect-free guarantee, measured.

    A full snapshot of names, sizes and mtimes across both roots, taken before and
    after opening, discovering, and inspecting. A ``mkdir``, a cache file, a lock file,
    an index, a normalisation, and an ``mtime`` touch each move one of those facts.
    """
    source_root = workspace.source_root
    for kind in ALL_KINDS:
        write_document(source_root, kind, f"{kind}.json")

    baseline = {**_snapshot(source_root), **_snapshot(workspace.evidence_root)}

    found = discover_sources(workspace)
    from dynamisbench.workspace.source_authority import inspect_locator

    for locator in found.locators:
        inspect_locator(workspace, locator)
    again = discover_sources(workspace)

    assert {**_snapshot(source_root), **_snapshot(workspace.evidence_root)} == baseline
    assert len(again.locators) == len(found.locators)


def test_a_locator_carries_no_absolute_path_or_drive(workspace: Workspace) -> None:
    """Locators are portable names, so they can be published and they survive relocation."""
    write_document(workspace.source_root, "realization", "a/b/c.yaml")
    found = discover_sources(workspace)
    locator = found.locators[0]

    assert locator.logical_reference == "realizations/realization/a/b/c.yaml"
    assert str(workspace.source_root) not in locator.logical_reference
    assert locator.category_reference == "realization/a/b/c.yaml"
    assert ":" not in locator.logical_reference
    assert "\\" not in locator.logical_reference
    assert not locator.logical_reference.startswith("/")


def test_relocation_of_the_same_authority_gives_identical_digests(tmp_path: Path) -> None:
    """The same authority at two different absolute roots is one meaning.

    Both workspaces have a different parent, a different root name, and a different
    evidence root, and both hold documents written from the same factories — so their
    digests must agree one for one, per document. That is what makes an artifact's
    identity independent of where the machine happened to keep it.
    """
    digests: dict[str, str] = {}
    for label in ("here", "a-completely-different-place"):
        workspace = initialize_workspace(
            tmp_path / label / "authoritative-specifications",
            tmp_path / label / "run-evidence",
        )
        for kind in ALL_KINDS:
            write_document(workspace.source_root, kind, f"{kind}.json")

        found = discover_sources(workspace)
        for locator in found.locators:
            inspection = inspect_locator(workspace, locator)
            assert inspection.valid is True
            assert inspection.identity is not None
            digests.setdefault(locator.logical_reference, inspection.identity.digest.hex)
            assert digests[locator.logical_reference] == inspection.identity.digest.hex

    assert len(digests) == len(ALL_KINDS)


def test_the_walk_finds_a_document_a_client_created_after_the_previous_walk(
    workspace: Workspace,
) -> None:
    """Discovery rescans on every call rather than remembering what it found."""
    from dynamisbench.workspace.source_authority import inspect_locator

    assert not discover_sources(workspace).locators

    write_document(workspace.source_root, "metric", "new.json")
    found = discover_sources(workspace)
    assert len(found.locators) == 1

    (workspace.source_root / "schemas" / "metric" / "new.json").unlink()
    (workspace.source_root / "schemas" / "metric").rmdir()
    assert not discover_sources(workspace).locators

    # Re-inspection of a locator whose file is gone is a bounded read refusal, not a crash.
    inspection = inspect_locator(workspace, found.locators[0])
    assert inspection.valid is False
    assert inspection.diagnostics[0].code is DiagnosticCode.READ_ERROR


def test_a_symlinked_category_directory_is_not_walked(tmp_path: Path) -> None:
    """A category that is itself a link is reported rather than followed.

    The category has to exist as a real directory first, because a link cannot be made
    in its place otherwise _ and this is exactly the case the walk must refuse: the
    category looks like authority and points somewhere else entirely.
    """
    from tests.workspace.links import make_directory_link, require_directory_link

    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.BENCHMARKS]
    )
    outside = tmp_path / "outside-source"
    (outside / "benchmarks" / "benchmark").mkdir(parents=True)
    (outside / "benchmarks" / "benchmark" / "escape.json").write_text(json_text(), encoding="utf-8")

    link = workspace.source_root / "benchmarks"
    link.rmdir()
    require_directory_link(make_directory_link(link, outside), "a category link escape")

    found = discover_sources(workspace)
    assert not found.locators
    assert any(
        issue.diagnostic.code is DiagnosticCode.PATH_SCOPE_VIOLATION for issue in found.issues
    )
