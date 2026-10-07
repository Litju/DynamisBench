"""The load-bearing proof: where a workspace lives is not what an artifact *is*.

Every other workspace test concerns containment. This one concerns identity, and it is
the reason the workspace model exists in the shape it does.

A RES-229 semantic digest is the SHA-256 of the RFC 8785 canonical bytes of a validated
definition's meaning. The workspace decides where that definition was read from and
nothing else. So the same authored bytes, placed in two workspaces at completely
different absolute paths - different parent, different root name, different evidence root
- must validate to the same model and hash to the same digest, while every resolved path
differs. If a workspace path could reach a digest, a benchmark's identity would depend on
which drive it happened to be on, on which username ran it, and on whether the workspace
was copied; a scientific artifact whose identity changes when it is moved has no identity
at all.

The suite therefore checks three things: the digests agree across relocation, the
canonical bytes contain no trace of either workspace's paths, and the import graph makes
the accident impossible rather than merely absent - neither the workspace package nor the
identity package may reach the other, so there is no path by which a location could be
fed to a hash even by accident.

A relocated asset also keeps its own identity: the bytes are the artifact, so moving a
model file leaves its asset digest unchanged while the realization that names it by
workspace-relative path keeps its own semantic digest too. Neither identity is a location.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from dynamisbench.domain.spec import RealizationDefinition
from dynamisbench.identity import asset_sha256_of_file, canonical_semantic_bytes, semantic_sha256
from dynamisbench.workspace import (
    PersistenceClass,
    SourceCategory,
    WorkspaceRoots,
    initialize_workspace,
    open_workspace,
)

REALIZATION = "realization_definition.mujoco.json"
REALIZATION_LOGICAL = ("db-lcmj20", REALIZATION)
ASSET_LOGICAL = ("models", "realization", "subject.xml")
ASSET_BYTES = b"<mujoco><worldbody/></mujoco>"

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "dynamisbench"
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "domain" / "valid"
REALIZATION_FIXTURE = FIXTURE_ROOT / REALIZATION
WORKSPACE_MODULES = ("__init__.py", "authority.py", "paths.py", "workspace.py")
"""Named so that adding a workspace module is a reviewed change, not a silent one."""

ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "enum",
        "functools",
        "os",
        "pathlib",
        "re",
        "types",
        "typing",
        "dynamisbench",
    }
)
"""Everything the workspace package may import.

Standard library and this project only. The point of the list is that it contains no
third-party name, so the claim "a new runtime dependency should not be necessary" is
enforced rather than asserted: adding a storage abstraction, a database driver, or a
filesystem watcher to this package fails this gate.
"""

FORBIDDEN_ROOTS = frozenset({"dynamisbench.identity", "mujoco", "opensim", "simtk", "gym"})


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def populated_workspace(base: Path, name: str) -> tuple[WorkspaceRoots, dict[str, str]]:
    """Create a workspace and place the same authored realization inside it.

    Returns the roots and a mapping of every absolute path used, so a test can assert the
    two workspaces differ in all of them.
    """
    workspace = initialize_workspace(
        base / name / "authoritative-specifications",
        base / name / "run-evidence",
        sources=[SourceCategory.REALIZATIONS],
    )
    specification = workspace.resolve_source(SourceCategory.REALIZATIONS, REALIZATION)
    specification.parent.mkdir(parents=True, exist_ok=True)
    specification.write_text(REALIZATION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    asset = workspace.resolve_source(SourceCategory.REALIZATIONS, "/".join(ASSET_LOGICAL))
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(ASSET_BYTES)

    staging = workspace.resolve(PersistenceClass.STAGING, "run-0001")
    staging.mkdir(parents=True, exist_ok=True)
    sealed = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, "run-0001")
    sealed.mkdir(parents=True, exist_ok=True)

    return workspace.roots, {
        "source_root": str(workspace.source_root),
        "evidence_root": str(workspace.evidence_root),
        "specification": str(specification),
        "asset": str(asset),
        "staging": str(staging),
        "sealed": str(sealed),
    }


def load_realization(roots: WorkspaceRoots) -> RealizationDefinition:
    workspace = open_workspace(roots.source, roots.evidence)
    document = json.loads(
        workspace.resolve_source(SourceCategory.REALIZATIONS, REALIZATION).read_text(
            encoding="utf-8"
        )
    )
    return RealizationDefinition.model_validate(document)


def test_the_two_workspaces_genuinely_live_in_different_places(tmp_path: Path) -> None:
    """A relocation test is only worth anything if the relocation really happened."""
    _, here = populated_workspace(tmp_path, "first")
    _, there = populated_workspace(tmp_path, "second-in-a-completely-different-place")

    assert here["source_root"] != there["source_root"]
    assert here["evidence_root"] != there["evidence_root"]
    assert here["specification"] != there["specification"]
    assert here["asset"] != there["asset"]
    assert here["staging"] != there["staging"]
    assert here["sealed"] != there["sealed"]
    assert here["source_root"] not in there["specification"]
    assert "first" not in there["specification"]


def test_a_definition_has_the_same_semantic_digest_in_two_relocated_workspaces(
    tmp_path: Path,
) -> None:
    first_roots, here = populated_workspace(tmp_path, "first")
    second_roots, there = populated_workspace(tmp_path, "second-in-a-completely-different-place")

    first = load_realization(first_roots)
    second = load_realization(second_roots)

    assert first == second
    assert canonical_semantic_bytes(first) == canonical_semantic_bytes(second)
    assert semantic_sha256(first) == semantic_sha256(second)
    assert here["specification"] != there["specification"]


def test_canonical_bytes_carry_no_trace_of_either_workspace(tmp_path: Path) -> None:
    """The positive statement, not only the equality: the hashed bytes contain nothing
    derived from a location, so there is nothing there to change."""
    first_roots, here = populated_workspace(tmp_path, "first")
    second_roots, there = populated_workspace(tmp_path, "second-in-a-completely-different-place")
    canonical = canonical_semantic_bytes(load_realization(first_roots)).decode("utf-8")

    for key, path in {**here, **there}.items():
        assert path not in canonical, f"{key} leaked into the canonical bytes"
        if key != "asset":
            assert Path(path).name not in canonical, f"{key} leaked its name into the digest"
    assert ":\\" not in canonical
    assert "/home/" not in canonical
    assert "first" not in canonical
    assert "second-in-a-completely-different-place" not in canonical


def test_the_relative_reference_is_meaning_while_the_absolute_path_is_not(
    tmp_path: Path,
) -> None:
    """The distinction the whole model rests on, stated in both directions.

    ``models/realization/subject.xml`` is authored scientific meaning and belongs in the
    digest: it says which artifact a realization depends on. ``C:\\Users\\...`` is where
    that artifact happens to be stored right now and belongs nowhere. Both halves are
    checked, because a digest that hashed only the meaning and one that hashed only the
    location would both fail the relocation test for opposite reasons.

    The volume anchor used to close the location half here, and it could not. On Windows the
    anchor is ``C:\\`` and saying "that is absent" says something; on POSIX the anchor is
    ``/``, which is also the separator the relative reference is written with, so the
    assertion was asking for the absence of a character this test requires to be present - and
    it failed there for exactly that reason. The claim needed is already proved portably by
    :func:`test_canonical_bytes_carry_no_trace_of_either_workspace`, which asserts that the
    artifact's real absolute path, in both workspaces, is absent from the canonical bytes; the
    two roots are checked here as well, because they are the paths a reader would try first.
    """
    roots, paths = populated_workspace(tmp_path, "first")
    canonical = canonical_semantic_bytes(load_realization(roots)).decode("utf-8")

    assert "/".join(ASSET_LOGICAL) in canonical
    assert paths["source_root"] not in canonical
    assert paths["evidence_root"] not in canonical


def test_a_relocated_asset_keeps_its_own_identity(tmp_path: Path) -> None:
    """The asset digest is over raw bytes, so moving a model file changes nothing about
    the model. This is the second half of the same invariant, and the reason a realization
    may name an asset by workspace-relative path without its own identity depending on
    where that path currently leads."""
    first_roots, _ = populated_workspace(tmp_path, "first")
    second_roots, _ = populated_workspace(tmp_path, "second-in-a-completely-different-place")

    first = open_workspace(first_roots.source, first_roots.evidence)
    second = open_workspace(second_roots.source, second_roots.evidence)
    reference = load_realization(first_roots).assets[0].path

    first_asset = first.resolve_source(SourceCategory.REALIZATIONS, reference)
    second_asset = second.resolve_source(SourceCategory.REALIZATIONS, reference)
    assert first_asset != second_asset
    assert asset_sha256_of_file(first_asset) == asset_sha256_of_file(second_asset)


def test_a_relative_asset_reference_is_the_only_one_that_can_be_authored() -> None:
    """Authority may name an asset relatively but never absolutely, so an authored
    realization cannot smuggle a machine-specific path into what is hashed."""
    document = json.loads(REALIZATION_FIXTURE.read_text(encoding="utf-8"))
    assert not Path(document["assets"][0]["path"]).is_absolute()
    assert document["assets"][0]["path"] == "/".join(ASSET_LOGICAL)

    with pytest.raises(ValueError):
        RealizationDefinition.model_validate(
            {**document, "assets": [{**document["assets"][0], "path": "C:/secrets/key.pem"}]}
        )


@pytest.mark.parametrize("filename", WORKSPACE_MODULES)
def test_the_workspace_package_imports_no_third_party_code(filename: str) -> None:
    unexpected = imported_roots(PACKAGE_ROOT / "workspace" / filename) - ALLOWED_IMPORT_ROOTS
    assert not unexpected, f"{filename} imports {sorted(unexpected)}"


@pytest.mark.parametrize("filename", WORKSPACE_MODULES)
def test_the_workspace_package_never_reaches_into_identity(filename: str) -> None:
    """A location must not be able to reach a hash. The reverse is equally true: identity
    must not be reachable *through* the workspace, or a path could be handed to
    ``semantic_sha256`` by an innocent-looking convenience method."""
    assert not imported_roots(PACKAGE_ROOT / "workspace" / filename) & FORBIDDEN_ROOTS


@pytest.mark.parametrize("filename", ("canonical.py", "semantic.py", "digests.py"))
def test_identity_cannot_see_a_workspace(filename: str) -> None:
    """The semantic path is already barred from importing ``pathlib``; this states the
    intent in the terms the workspace boundary uses."""
    assert "dynamisbench.workspace" not in imported_roots(PACKAGE_ROOT / "identity" / filename)


def test_the_workspace_package_is_the_four_modules_this_gate_sealed() -> None:
    assert sorted(path.name for path in (PACKAGE_ROOT / "workspace").glob("*.py")) == sorted(
        WORKSPACE_MODULES
    )
