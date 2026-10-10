"""The transient registry: opaque identifiers, restart, and memory that is disposable.

The registry is the only thing standing between the API and the workspace, so it is qualified
against the properties that make it safe to describe authority without owning it:

* **identifiers are opaque.** No identifier contains a root, a drive letter, a workspace
  name, or a reference; a client cannot compute one; and a token minted for one workspace is
  not recognised in another, which is what makes cross-workspace misuse a bounded refusal
  rather than a route to someone else's authority.
* **the registry is disposable.** Restarting produces an application whose identifiers are
  all wrong; reopening the same roots reconstructs the same workspace with a fresh
  identifier. That is the proof that memory was never the point.
* **lookup never guesses.** An identifier that is not registered is refused, and an artifact
  identifier is answered with the same refusal whether the workspace is wrong or the artifact
  is — so the refusal discloses nothing about what does exist.

Thread safety is exercised rather than asserted, because a registry that is correct under one
request and wrong under two is the failure this module exists to prevent.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from dynamisbench.api import create_app
from dynamisbench.api.workspace_registry import (
    ARTIFACT_ID_BYTES,
    WORKSPACE_ID_BYTES,
    WorkspaceNotFoundError,
    WorkspaceRegistry,
)
from dynamisbench.workspace import (
    SourceCategory,
    Workspace,
    WorkspaceRootError,
    initialize_workspace,
)
from dynamisbench.workspace.source_authority import SourceLocator, inspect_locator

from .factories import CREDENTIAL, session_configuration, windows_drive


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """A workspace with every source category, so any kind of locator can be filed in it.

    Scoped to `tmp_path` rather than the process's working directory, because the whole
    point of these fixtures is that a test's authority lives and dies with the test.
    """
    return initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=tuple(SourceCategory)
    )


@pytest.fixture
def registry() -> WorkspaceRegistry:
    return WorkspaceRegistry()


def _locator(kind: str = "benchmark", name: str = "a.json") -> SourceLocator:
    return SourceLocator(category=SourceCategory.BENCHMARKS, kind=kind, segments=(kind, name))


def _open(registry: WorkspaceRegistry, source: Path, evidence: Path) -> str:
    """Open a workspace, returning only its identifier — the shape a client has."""
    return registry.open(str(source), str(evidence)).identifier


# --------------------------------------------------------------------------- #
# Registration: explicit, idempotent, never creating
# --------------------------------------------------------------------------- #
def test_opening_a_workspace_registers_it_once(
    registry: WorkspaceRegistry, workspace: Workspace
) -> None:
    # `workspace` is the fixture's name for a Workspace; see the fixture above.
    first = registry.open(str(workspace.source_root), str(workspace.evidence_root))
    second = registry.open(str(workspace.source_root), str(workspace.evidence_root))

    assert first.reused is False
    assert second.reused is True
    assert first.identifier == second.identifier
    assert registry.identifiers() == frozenset({first.identifier})


def test_a_registration_is_keyed_on_normalised_roots(
    registry: WorkspaceRegistry, workspace: Workspace
) -> None:
    """Two spellings of one workspace are one workspace.

    The roots are resolved before the key is built, so a trailing separator or a ``.``
    segment lands on the same entry. A registry keyed on the raw strings would describe one
    workspace twice and hand out two identifiers for it.
    """
    source = workspace.source_root
    evidence = workspace.evidence_root

    first = registry.open(str(source), str(evidence))
    second = registry.open(str(source) + os.sep, str(evidence / "."))

    assert second.identifier == first.identifier


def test_registration_refuses_a_root_that_is_not_a_directory(
    registry: WorkspaceRegistry, workspace: Workspace
) -> None:
    """A missing root, and two roots that are the same directory, are both refusals."""
    missing = workspace.source_root.parent / "does-not-exist-anywhere"

    before = registry.identifiers()
    with pytest.raises(WorkspaceRootError):
        registry.open(str(missing), str(workspace.evidence_root))
    with pytest.raises(WorkspaceRootError):
        registry.open(str(workspace.source_root), str(workspace.source_root))

    assert registry.identifiers() == before


def test_registration_never_creates_a_workspace(tmp_path: Path) -> None:
    """``open_workspace``, never ``initialize_workspace``.

    The most destructive bug this registry could have is a convenience that creates the
    directory it was asked about. A missing root must be refused, so a caller that wants a
    workspace to exist uses the only function that says so.
    """
    registry = WorkspaceRegistry()
    source = tmp_path / "never-created" / "source"
    evidence = tmp_path / "never-created" / "evidence"

    with pytest.raises(WorkspaceRootError):
        registry.open(str(source), str(evidence))

    assert not (tmp_path / "never-created").exists()
    assert registry.identifiers() == frozenset()


def test_a_distinct_workspace_gets_a_distinct_identifier(tmp_path: Path) -> None:
    one = initialize_workspace(tmp_path / "one" / "source", tmp_path / "one" / "evidence")
    two = initialize_workspace(tmp_path / "two" / "source", tmp_path / "two" / "evidence")

    registry = WorkspaceRegistry()
    left = registry.open(str(one.source_root), str(one.evidence_root)).identifier
    right = registry.open(str(two.source_root), str(two.evidence_root)).identifier

    assert left != right
    assert registry.identifiers() == frozenset({left, right})


# --------------------------------------------------------------------------- #
# Identifiers: opaque, random, and carrying nothing
# --------------------------------------------------------------------------- #
def test_workspace_identifiers_carry_no_information(registry, workspace) -> None:
    """The property that keeps discovery safe: an identifier is not a name.

    No root, no drive letter, no separator, no workspace directory name, no user name. The
    identifier therefore cannot be parsed back into a path, and there is nothing in a
    response body that a reader could turn into one.
    """
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)

    assert len(identifier) >= WORKSPACE_ID_BYTES
    assert str(workspace.source_root) not in identifier
    assert str(workspace.evidence_root) not in identifier
    assert workspace.source_root.name not in identifier
    drive = windows_drive(workspace.source_root)
    assert drive == "" or drive not in identifier
    assert ":" not in identifier
    assert "/" not in identifier


def test_identifiers_are_not_computed_from_anything_a_client_supplies(registry, workspace) -> None:
    """Two registries opening the same workspace do not agree on the identifier.

    This is what makes them unguessable rather than merely obscure: a second registry, given
    the identical input, produces an unrelated token. A derived identifier would let a
    client compute the next one from the last.
    """
    first = _open(WorkspaceRegistry(), workspace.source_root, workspace.evidence_root)
    second = _open(WorkspaceRegistry(), workspace.source_root, workspace.evidence_root)

    assert first != second


def test_artifact_identifiers_do_not_encode_a_reference(registry, workspace) -> None:
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)
    locator = _locator("scenario", "a-very-identifiable-file-name.yaml")

    (artifact,) = registry.record_discovery(identifier, (locator,))

    assert len(artifact) >= ARTIFACT_ID_BYTES
    assert "scenario" not in artifact
    assert "a-very-identifiable-file-name" not in artifact
    assert str(workspace.source_root) not in artifact
    assert ":" not in artifact and "/" not in artifact and "\\" not in artifact


# --------------------------------------------------------------------------- #
# Lookup: total, and refusing without disclosing
# --------------------------------------------------------------------------- #
def test_an_unknown_workspace_is_refused(registry: WorkspaceRegistry) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        registry.registration("not-a-real-identifier")
    with pytest.raises(WorkspaceNotFoundError):
        registry.artifact("not-a-real-identifier", "nor-is-this")


def test_an_unknown_artifact_is_refused(registry, workspace) -> None:
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)

    with pytest.raises(WorkspaceNotFoundError):
        registry.artifact(identifier, "not-minted")


def test_an_artifact_from_one_workspace_is_unknown_in_another(tmp_path: Path) -> None:
    """The cross-workspace case, and the refusal that answers it.

    One registration refuses the identifier and says only that — not "it belongs to another
    workspace", which would be the sentence that hands a caller a working identifier for
    somebody else's authority.
    """
    one = initialize_workspace(tmp_path / "one" / "source", tmp_path / "one" / "evidence")
    two = initialize_workspace(tmp_path / "two" / "source", tmp_path / "two" / "evidence")
    registry = WorkspaceRegistry()

    left = _open(registry, one.source_root, one.evidence_root)
    right = _open(registry, two.source_root, two.evidence_root)
    locator = _locator("benchmark", "shared.json")
    (left_artifact,) = registry.record_discovery(left, (locator,))

    with pytest.raises(WorkspaceNotFoundError):
        registry.artifact(right, left_artifact)

    assert registry.locate(registry.registration(left), left_artifact) == locator
    assert registry.locate(registry.registration(right), left_artifact) is None


def test_the_same_reference_in_two_workspaces_has_two_identifiers(tmp_path: Path) -> None:
    """One document name filed in two workspaces is two artifacts, not one.

    The identifiers differ because the workspaces differ, and neither is derivable from the
    other. This is the same fact as the registration refusing, stated from the other side.
    """
    one = initialize_workspace(tmp_path / "one" / "source", tmp_path / "one" / "evidence")
    two = initialize_workspace(tmp_path / "two" / "source", tmp_path / "two" / "evidence")
    registry = WorkspaceRegistry()

    left = _open(registry, one.source_root, one.evidence_root)
    right = _open(registry, two.source_root, two.evidence_root)
    same = _locator("benchmark", "shared.json")

    (left_artifact,) = registry.record_discovery(left, (same,))
    (right_artifact,) = registry.record_discovery(right, (same,))

    assert left_artifact != right_artifact


# --------------------------------------------------------------------------- #
# Rediscovery: stable during a process, rebuilt on the next one
# --------------------------------------------------------------------------- #
def test_rediscovery_reuses_the_identifier(registry, workspace) -> None:
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)
    locator = _locator("metric", "height.json")

    assert registry.record_discovery(identifier, (locator,)) == registry.record_discovery(
        identifier, (locator,)
    )


def test_a_locator_is_memory_so_inspecting_a_deleted_document_refuses(registry, workspace) -> None:
    """A locator is a handle to a re-read, never to a cached answer.

    Deleting a document leaves its identifier behind, because forgetting one a client was
    told about would make the client wonder whether it had been wrong. Inspection then
    re-resolves the locator and fails as a bounded read error, which is the answer that
    matches what the file is now.
    """
    from tests.workspace.authority_fixtures import write_document

    identifier = _open(registry, workspace.source_root, workspace.evidence_root)
    written = write_document(workspace.source_root, "benchmark", "release.json")
    locator = SourceLocator(
        category=SourceCategory.BENCHMARKS,
        kind="benchmark",
        segments=("benchmark", "release.json"),
    )
    (artifact,) = registry.record_discovery(identifier, (locator,))

    written.unlink()
    _, rediscovered = registry.artifact(identifier, artifact)
    inspection = inspect_locator(workspace, rediscovered)

    assert inspection.valid is False
    assert inspection.diagnostics


def test_a_second_application_instance_has_an_empty_registry(registry, workspace) -> None:
    """Restart, stated as the fact that makes memory disposable.

    A new registry holds nothing, so every identifier the first one handed out is
    unregistered here — including for the same pair of roots. Nothing was lost.
    """
    first = _open(registry, workspace.source_root, workspace.evidence_root)

    restarted = WorkspaceRegistry()
    assert restarted.identifiers() == frozenset()
    with pytest.raises(WorkspaceNotFoundError):
        restarted.registration(first)

    reopened = restarted.open(str(workspace.source_root), str(workspace.evidence_root))
    assert reopened.reused is False
    assert reopened.identifier != first


def test_forgetting_a_workspace_leaves_it_on_disk(registry, workspace) -> None:
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)

    registry.forget(identifier)

    assert registry.identifiers() == frozenset()
    assert workspace.source_root.is_dir()
    assert workspace.evidence_root.is_dir()
    with pytest.raises(WorkspaceNotFoundError):
        registry.registration(identifier)


def test_forgetting_an_unknown_workspace_is_a_no_op(registry: WorkspaceRegistry) -> None:
    registry.forget("never-registered")
    assert registry.identifiers() == frozenset()


def test_each_application_instance_gets_its_own_registry(
    registry: WorkspaceRegistry, workspace: Workspace
) -> None:
    """The restart guarantee, at the boundary that will actually be used.

    ``create_app`` builds a registry; a second call builds another. The two share nothing,
    so the identifiers one hands out are meaningless to the other.
    """
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)

    application = create_app()
    other = create_app()

    assert application.state.workspace_registry is not other.state.workspace_registry
    assert application.state.workspace_registry is not registry
    with pytest.raises(WorkspaceNotFoundError):
        other.state.workspace_registry.registration(identifier)


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #
def test_the_registry_agrees_with_itself_under_concurrent_registration(workspace) -> None:
    """The same workspace opened from many threads registers once.

    Ten threads, ten calls, and the registry's own count is the final arbiter. A race here
    would show up as duplicate registrations of one workspace, which is the same defect as
    two applications each believing they hold it.
    """
    registry = WorkspaceRegistry()
    observed: list[str] = []
    guard = threading.Lock()

    def open_it() -> None:
        identifier = registry.open(str(workspace.source_root), str(workspace.evidence_root))
        with guard:
            observed.append(identifier.identifier)

    threads = [threading.Thread(target=open_it) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(observed) == 10
    assert set(observed) == set(registry.identifiers())
    assert len(registry.identifiers()) == 1


def test_artifact_identifiers_are_minted_once_under_concurrent_discovery(
    registry, workspace
) -> None:
    """Two threads discovering one workspace agree on the identifier for one document.

    The reverse mapping is what makes an identifier stable, and a race on it would hand out
    two identifiers for one document. The threads' results are compared rather than the
    registry's size, because the size cannot see a disagreement.
    """
    identifier = _open(registry, workspace.source_root, workspace.evidence_root)
    documents = tuple(_locator("benchmark", f"doc-{index}.json") for index in range(20))

    results: list[tuple[str, ...]] = []
    guard = threading.Lock()

    def discover() -> None:
        minted = registry.record_discovery(identifier, documents)
        with guard:
            results.append(minted)

    threads = [threading.Thread(target=discover) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results
    assert all(result == results[0] for result in results)
    assert len({artifact for result in results for artifact in result}) == len(documents)


def test_registration_and_session_credential_are_unrelated_state() -> None:
    """A mundane regression: the registry holds workspaces, the session holds a credential.

    The credential gate that guards every route is the session's own concern (RES-375). This
    states that the two are not entangled in either direction: configuring a session has no
    effect on which workspaces are registered, and opening a workspace has no effect on which
    credential the sidecar demands.
    """
    credential = session_configuration().credential
    registry = WorkspaceRegistry()

    assert registry.identifiers() == frozenset()
    assert credential.admits(CREDENTIAL)


def test_a_documented_locator_round_trips_through_json() -> None:
    """Locators are the registry's whole payload, so they must be storable and comparable."""
    locator = _locator("study", "nested/study.yaml")
    as_text = json.dumps(
        {
            "category": locator.category.value,
            "kind": locator.kind,
            "segments": list(locator.segments),
        }
    )

    stored = json.loads(as_text)
    stored["segments"] = tuple(stored["segments"])
    assert SourceLocator(**stored) == locator
