"""Refusing every way out of a workspace, and proving the refusal is structural.

Two independent defences guard a reference, and this suite attacks both. The lexical gate
is attacked with the shapes an untrusted reference actually takes — absolute injection,
``..`` traversal, drive and UNC qualification, separator and Windows-normalisation
tricks, alternate data streams, reserved device names. The structural gate is attacked
with a filesystem that lies: a symlink or junction inside the workspace pointing at
something outside it, including one placed on a class location itself.

Containment is checked the way the authority requires it, structurally: the suite proves
that a sibling directory whose name *starts with* the root's name is not inside the root,
which is the failure a naive string-prefix check would have. On Windows it also proves
that case-insensitivity makes a differently spelled reference resolve to the same file
while a case-sensitive filesystem keeps the two distinct, because that is the platform
rule ``is_relative_to`` applies and the rule must be the platform's, not a guess.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dynamisbench.workspace import (
    MAX_LOGICAL_REFERENCE_LENGTH,
    LogicalReference,
    PathScopeError,
    PersistenceClass,
    SourceCategory,
    open_workspace,
    validate_logical_reference,
)
from tests.workspace.links import DirectoryLinkFactory, require_directory_link

IS_WINDOWS = sys.platform == "win32"

TRAVERSAL_REFERENCES = (
    "..",
    "../file",
    "../../other-project/file",
    "..\\..\\other-project\\file",
    "a/../../b",
    "a\\..\\..\\b",
    "./a",
    ".\\a",
    "a/./b",
    ".",
    "./",
    "a/..",
)

ABSOLUTE_REFERENCES = (
    "/etc/passwd",
    "/",
    "\\",
    "\\Windows\\System32",
    "C:\\Windows\\System32\\config",
    "c:/windows/system32",
    "D:/evidence/runs",
    "Z:\\x",
    "\\\\server\\share\\runs\\r1",
    "//server/share/runs/r1",
    "\\\\?\\C:\\Windows",
    "\\\\.\\PIPE\\something",
    "//?/C:/Windows",
    "C:relative-with-drive",
)

CROSS_ROOT_REFERENCES = (
    "../evidence/runs/r1",
    "../source/benchmarks",
    "..",
    "runs/../../source/benchmarks",
)

EMPTY_AND_TRICK_REFERENCES = (
    "",
    "a//b",
    "a///b",
    "a/",
    "/a",
    "a/\\b",
    ".. ",
    "..　",
    " . ",
    "a/.. /b",
    "a/. /b",
    "a/.../b",
    "   ",
)

ORDINARY_NAME_REFERENCES = (
    "a\\b",
    "a/ b",
    "a b/c d",
    "run 0001/native data",
    "-leading-dash",
    "...hidden",
    "file.tar.gz",
    "naïve/ünïcode",
)
"""References whose segments are ordinary POSIX names and must therefore also be accepted.

A backslash is treated as a separator and an interior space as a name character, because
both mean the same thing on Windows and both are legal file-name characters on POSIX.
Splitting on the backslash means ``a\\b`` stops being one literal name and becomes a
directory and a file, which is the safe direction: the alternative is a reference whose
meaning depends on which platform reads it.
"""

WINDOWS_HOSTILE_REFERENCES = (
    "run.json:stream",
    "run.json:$DATA",
    "C:file",
    "NUL",
    "nul.txt",
    "CON",
    "con.log",
    "PRN",
    "AUX",
    "COM1",
    "com9.dat",
    "LPT1",
    "conin$",
    "a?b",
    "a*b",
    "a<b",
    "a>b",
    "a|b",
    'a"b',
    "report.",
    "report ",
    "a/./b",
)


@pytest.fixture
def workspace(tmp_path: Path):
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    source.mkdir()
    evidence.mkdir()
    return open_workspace(source, evidence)


def test_a_well_formed_reference_resolves_inside_its_class(workspace) -> None:
    location = workspace.location(PersistenceClass.STAGING)
    resolved = workspace.resolve(PersistenceClass.STAGING, "run-0001/native/frames.parquet")
    assert resolved == location.path / "run-0001" / "native" / "frames.parquet"
    assert resolved.is_relative_to(workspace.evidence_root)


def test_a_reference_that_does_not_exist_yet_still_resolves(workspace) -> None:
    resolved = workspace.resolve(PersistenceClass.DERIVED, "index/projection.duckdb")
    assert not resolved.exists()
    assert resolved.is_relative_to(workspace.evidence_root / "derived")


def test_a_source_reference_resolves_inside_its_category(workspace) -> None:
    resolved = workspace.resolve_source(SourceCategory.BENCHMARKS, "db-lcmj20/release.yaml")
    assert resolved == workspace.source_root / "benchmarks" / "db-lcmj20" / "release.yaml"


@pytest.mark.parametrize("reference", TRAVERSAL_REFERENCES)
def test_traversal_is_refused(workspace, reference: str) -> None:
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.STAGING, reference)


@pytest.mark.parametrize("reference", ABSOLUTE_REFERENCES)
def test_absolute_injection_is_refused_on_every_platform(workspace, reference: str) -> None:
    """Both path grammars are consulted on every platform, so a reference validated on
    Linux is accepted on Windows and vice versa. A language only one platform can resolve
    is not a language."""
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.CACHE, reference)


@pytest.mark.parametrize("reference", CROSS_ROOT_REFERENCES)
def test_a_reference_cannot_cross_from_evidence_into_source(workspace, reference: str) -> None:
    """An evidence-side reference may not reach the source root, and a source-side one may
    not reach the evidence root: the two are independent places, not one tree."""
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.SEALED_EVIDENCE, reference)
    with pytest.raises(PathScopeError):
        workspace.resolve_source(SourceCategory.REALIZATIONS, reference)


@pytest.mark.parametrize("reference", ORDINARY_NAME_REFERENCES)
def test_ordinary_names_resolve_consistently_on_every_platform(workspace, reference: str) -> None:
    resolved = workspace.resolve(PersistenceClass.STAGING, reference)
    assert resolved.is_relative_to(workspace.location(PersistenceClass.STAGING).path)
    assert resolved == workspace.location(PersistenceClass.STAGING).path.joinpath(
        *validate_logical_reference(reference)
    )


@pytest.mark.parametrize("reference", EMPTY_AND_TRICK_REFERENCES)
def test_empty_and_trick_segments_are_refused(workspace, reference: str) -> None:
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.TMP, reference)


@pytest.mark.parametrize("reference", WINDOWS_HOSTILE_REFERENCES)
def test_names_windows_cannot_store_are_refused_on_every_platform(
    workspace, reference: str
) -> None:
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.TMP, reference)


def test_a_reference_longer_than_the_bound_is_refused(workspace) -> None:
    workspace.resolve(PersistenceClass.TMP, "a" * MAX_LOGICAL_REFERENCE_LENGTH)
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.TMP, "a" * (MAX_LOGICAL_REFERENCE_LENGTH + 1))


def test_a_reference_that_is_not_a_string_is_refused(workspace) -> None:
    for value in (None, 1, ["a"], b"a", Path("a")):
        with pytest.raises(PathScopeError):
            workspace.resolve(PersistenceClass.TMP, value)  # type: ignore[arg-type]


def test_the_error_names_the_reference_and_the_class(workspace) -> None:
    with pytest.raises(PathScopeError) as refusal:
        workspace.resolve(PersistenceClass.STAGING, "../escape")
    assert refusal.value.logical_reference == "../escape"
    assert refusal.value.persistence_class is PersistenceClass.STAGING
    assert "../escape" in str(refusal.value)


def test_a_refusal_names_the_class_and_reference_but_not_the_path_outside(
    tmp_path: Path,
    link_maker: DirectoryLinkFactory,
) -> None:
    """A refusal must be actionable without handing the caller the path it was refused."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    source.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    mechanism = link_maker(evidence / "derived", outside)
    require_directory_link(mechanism, "the structural escape defence")

    workspace = open_workspace(source, evidence)
    with pytest.raises(PathScopeError) as refusal:
        workspace.resolve(PersistenceClass.DERIVED, "index.duckdb")

    message = str(refusal.value)
    assert "index.duckdb" in message
    assert PersistenceClass.DERIVED.value in message
    assert "private" not in message
    assert str(outside) not in message


def test_segments_never_carry_a_separator_so_joining_cannot_re_anchor() -> None:
    for reference in ("a/b", "a\\b", "a/b/c"):
        segments = validate_logical_reference(reference)
        assert segments
        assert all("/" not in segment and "\\" not in segment for segment in segments)
        assert all(segment not in {".", ".."} for segment in segments)


def test_a_sibling_whose_name_extends_the_root_is_not_inside_it(tmp_path: Path) -> None:
    """Containment is component-wise, never a string prefix: ``ws-evil`` starts with
    ``ws`` and is a different directory."""
    source = tmp_path / "ws"
    evidence = tmp_path / "ws-evil"
    source.mkdir()
    evidence.mkdir()
    (evidence / "runs").mkdir()
    workspace = open_workspace(source, evidence)

    assert workspace.evidence_root.name.startswith(workspace.source_root.name)
    assert not workspace.evidence_root.is_relative_to(workspace.source_root)
    with pytest.raises(PathScopeError):
        workspace.resolve_source(SourceCategory.BENCHMARKS, "../ws-evil/runs/r1")


def test_containment_follows_the_platform_case_rule(tmp_path: Path) -> None:
    """Windows compares paths case-insensitively, so a differently spelled reference
    resolves to the same file. A case-sensitive filesystem keeps them distinct. Either
    way the reference stays inside the root, which is the property that matters."""
    source = tmp_path / "MixedCase"
    source.mkdir()
    (source / "benchmarks" / "Data").mkdir(parents=True)
    (source / "benchmarks" / "Data" / "Release.yaml").write_text("x", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    workspace = open_workspace(source, evidence)

    resolved = workspace.resolve_source(SourceCategory.BENCHMARKS, "DATA/release.YAML")
    assert resolved.is_relative_to(workspace.source_root / "benchmarks")
    assert resolved.is_file() is IS_WINDOWS


def test_a_root_spelled_with_different_case_opens_the_same_directory(tmp_path: Path) -> None:
    source = tmp_path / "MixedCase"
    source.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    spelled = str(source)
    flipped = spelled.swapcase() if IS_WINDOWS else spelled
    workspace = open_workspace(flipped, evidence)
    assert workspace.source_root == source.resolve()


def test_a_link_inside_the_workspace_cannot_escape_it(
    tmp_path: Path,
    link_maker: DirectoryLinkFactory,
) -> None:
    """The structural gate. Every component of ``link/escape.txt`` is legitimate; only the
    filesystem disagrees about where it points."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    (evidence / ".staging").mkdir(parents=True)
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escape.txt").write_text("not ours", encoding="utf-8")

    mechanism = link_maker(evidence / ".staging" / "link", outside)
    require_directory_link(mechanism, "the structural escape defence")

    workspace = open_workspace(source, evidence)
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.STAGING, "link/escape.txt")


def test_a_link_escape_is_refused_before_the_file_is_reached(
    tmp_path: Path,
    link_maker: DirectoryLinkFactory,
) -> None:
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    (evidence / "derived").mkdir(parents=True)
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "projection.duckdb").write_text("derived elsewhere", encoding="utf-8")

    mechanism = link_maker(evidence / "derived" / "elsewhere", outside)
    require_directory_link(mechanism, "the structural escape defence")

    workspace = open_workspace(source, evidence)
    with pytest.raises(PathScopeError) as refusal:
        workspace.resolve(PersistenceClass.DERIVED, "elsewhere/projection.duckdb")
    assert "elsewhere" in str(refusal.value)


def test_a_link_on_the_class_location_itself_is_refused(
    tmp_path: Path,
    link_maker: DirectoryLinkFactory,
) -> None:
    """The class directory is resolved and checked before the reference is joined onto it,
    so replacing ``derived`` with a link out of the evidence root denies every reference
    rather than laundering them all."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    source.mkdir()
    evidence.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.duckdb").write_text("derived elsewhere", encoding="utf-8")

    mechanism = link_maker(evidence / "derived", outside)
    require_directory_link(mechanism, "the structural escape defence")

    workspace = open_workspace(source, evidence)
    with pytest.raises(PathScopeError):
        workspace.resolve(PersistenceClass.DERIVED, "index.duckdb")


def test_a_link_to_a_sibling_inside_the_same_root_is_still_allowed(
    tmp_path: Path,
    link_maker: DirectoryLinkFactory,
) -> None:
    """Containment is about leaving the root, not about links. Refusing every link would
    make a legitimate layout impossible and would not improve safety."""
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    (evidence / "derived").mkdir(parents=True)
    (evidence / "cache").mkdir()
    source.mkdir()
    (evidence / "cache" / "frames.bin").write_text("cached", encoding="utf-8")

    require_directory_link(
        link_maker(evidence / "derived" / "warm", evidence / "cache"),
        "a linked layout inside one root",
    )

    workspace = open_workspace(source, evidence)
    resolved = workspace.resolve(PersistenceClass.DERIVED, "warm/frames.bin")
    assert resolved.is_file()
    assert resolved.is_relative_to(workspace.evidence_root)


def test_building_a_reference_by_hand_cannot_bypass_the_same_gate() -> None:
    reference = LogicalReference(PersistenceClass.SEALED_EVIDENCE, ("runs",))
    assert reference.child("run-0001").text == "runs/run-0001"
    with pytest.raises(PathScopeError):
        reference.child("..", "escape")
    with pytest.raises(PathScopeError):
        reference.child("/absolute")
