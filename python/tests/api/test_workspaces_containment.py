"""The workspace routes: no path API, bounded refusals, memory that is not authority.

Everything this suite checks is about a client trying to make the API do something it should
not, or about the API answering something it should not.

The attacks are structural rather than enumerated. There is no endpoint that accepts a path,
so ``../../secrets``, ``/etc/passwd``, ``C:\\Windows``, a UNC prefix and an extended-length
prefix are refused by the *absence of a parameter that could carry them* — which is proved by
inspecting the published routes, not by guessing at inputs. What is left is the containment
that still matters: a link inside a workspace that points outside, a traversal smuggled into
a locator, and an artifact identifier borrowed from another workspace. Each must fail closed,
and each must fail without saying where it pointed.

The API-memory-is-not-authority gates are the other half. Restarting produces an application
whose identifiers all mean nothing; reopening the same roots reconstructs the same authority
with a fresh identifier and an identical digest. Relocating identical authority to a different
root produces the identical digest and hides the root from every field of every response.
Editing a source file between two inspections changes the next response, because the second
one re-read the file.

Side-effect-freedom is measured, not asserted: a full snapshot of the workspace's names, sizes
and mtimes is identical before and after every operation here, so an open, a discovery, or an
inspection that created a cache directory, wrote an index, or touched a modification time
fails here rather than in someone else's clean-up rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api import API_V1_PREFIX, create_app
from dynamisbench.workspace import (
    SourceCategory,
    Workspace,
    initialize_workspace,
    open_workspace,
)

from .workspace_routes import (
    ARTIFACT,
    ARTIFACTS,
    HEADERS,
    OPEN,
    discover,
    inspect_artifact,
    open_route,
    snapshot,
)
from .workspace_routes import (
    client as build_client,
)


@pytest.fixture
def client() -> TestClient:
    """One application per test, so no identifier ever survives into the next test."""
    return build_client()


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """A workspace with every source category, so any kind of document can be filed in it.

    Scoped to ``tmp_path`` rather than the process's working directory, because the
    whole point of the fixtures is that a test's authority lives and dies with the test.
    """
    return initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=tuple(SourceCategory)
    )


def _filed(client: TestClient, workspace: Workspace, kind: str, name: str) -> str:
    """File one document and return the artifact identifier discovery minted for it."""
    from tests.workspace.authority_fixtures import write_document

    write_document(workspace.source_root, kind, name)
    discovered = discover(
        client,
        open_route(client, workspace.source_root, workspace.evidence_root)["workspace_id"],
    )
    return next(artifact["artifact_id"] for artifact in discovered["artifacts"]["artifacts"])


# --------------------------------------------------------------------------- #
# There is no path API
# --------------------------------------------------------------------------- #
def test_no_published_route_accepts_a_path_or_a_reference(client: TestClient) -> None:
    """The structural proof, stated on the published surface.

    An endpoint that took a path would have a parameter for one. None of these does: the
    inspection route's only parameters are a workspace identifier and an artifact
    identifier, both opaque tokens the application handed out. This is the assertion that
    makes every other containment test a second line of defence rather than the only one.
    """

    paths = create_app().openapi()["paths"]
    for path, operations in paths.items():
        for verb, operation in operations.items():
            parameters = {parameter["name"] for parameter in operation.get("parameters", [])}
            assert not {"path", "reference", "logical", "file", "filename"} & parameters, (
                f"{path} {verb} publishes {parameters}, which could carry a path"
            )


def test_a_traversal_string_is_not_a_route(client: TestClient) -> None:
    """A traversal is not a request path, so it does not match a route.

    Checked through the real client rather than through the schema, because a path that
    happened to be accepted would be accepted by the router whatever the document said.
    """
    with TestClient(create_app()) as probe:
        for traversal in (
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/passwd",
            "C:/Windows/System32",
            "//server/share/authority",
            "\\\\?\\C:\\authority",
            "api/v1/files",
            "api/v1/read",
            "api/v1/browse",
        ):
            response = probe.get(
                f"{API_V1_PREFIX}/workspaces/anything/artifacts/{traversal}", headers=HEADERS
            )
            assert response.status_code in {404, 405, 422}, traversal
            assert "passwd" not in response.text
            assert "root:x:" not in response.text


def test_no_read_endpoint_exists_at_any_path(client: TestClient) -> None:
    """The generic surfaces this API must not grow, checked on the document.

    A client generating a client from the OpenAPI document is the client most likely to
    discover one if it existed, so the document is where the claim is proved.
    """
    published = set(create_app().openapi()["paths"])
    forbidden = {
        f"{API_V1_PREFIX}/files",
        f"{API_V1_PREFIX}/read",
        f"{API_V1_PREFIX}/browse",
        f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts/{{artifact_id}}/content",
    }

    assert not published & forbidden
    assert not any(path.endswith(("/files", "/read", "/browse")) for path in published)


# --------------------------------------------------------------------------- #
# Bounded refusals
# --------------------------------------------------------------------------- #
def test_an_unknown_workspace_identifier_is_a_bounded_404(client: TestClient) -> None:
    response = client.get(ARTIFACTS.format(workspace_id="not-a-workspace"), headers=HEADERS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert (
        response.json()["error"]["message"] == "No workspace is registered under that identifier."
    )


def test_an_unknown_artifact_identifier_is_a_bounded_404(
    client: TestClient, workspace: Workspace
) -> None:
    registered = open_route(client, workspace.source_root, workspace.evidence_root)["workspace_id"]

    response = client.get(
        ARTIFACT.format(workspace_id=registered, artifact_id="not-an-artifact"), headers=HEADERS
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_restarted_application_refuses_every_identifier_it_once_handed_out(
    client: TestClient, workspace: Workspace
) -> None:
    """An identifier means nothing to an application that did not mint it.

    The second application here is a fresh ``create_app``, which is exactly what a
    sidecar restart produces. Reopening the same roots then yields the same authority
    with a *fresh* identifier, which is the property that proves memory was never the
    point: the workspace comes back, and the handle to it does not.
    """
    first = open_route(client, workspace.source_root, workspace.evidence_root)
    artifact = _filed(client, workspace, "scenario", "release.json")

    with TestClient(create_app()) as restarted:
        stale = restarted.get(
            ARTIFACT.format(workspace_id=first["workspace_id"], artifact_id=artifact),
            headers=HEADERS,
        )
        assert stale.status_code == 404

        reopened = open_route(restarted, workspace.source_root, workspace.evidence_root)
        assert reopened["workspace_id"] != first["workspace_id"]
        rediscovered = discover(restarted, reopened["workspace_id"])

        assert (rediscovered["artifacts"]["artifacts"][0]["artifact_id"]) != artifact
        original = next(
            entry
            for entry in client.get(
                ARTIFACTS.format(workspace_id=first["workspace_id"]), headers=HEADERS
            ).json()["artifacts"]["artifacts"]
        )
        assert (
            rediscovered["artifacts"]["artifacts"][0]["semantic_digest"]["hex"]
            == original["semantic_digest"]["hex"]
        )


def test_an_artifact_identifier_from_another_workspace_is_refused_identically(
    tmp_path: Path,
) -> None:
    """The refusal says the same thing either way, on purpose.

    A message that distinguished "this artifact belongs to another workspace" would be the
    sentence that hands a caller a working identifier for somebody else's authority.
    """
    one = initialize_workspace(tmp_path / "one" / "source", tmp_path / "one" / "evidence")
    two = initialize_workspace(tmp_path / "two" / "source", tmp_path / "two" / "evidence")
    with TestClient(create_app()) as client:
        mine = _filed(client, one, "scenario", "same-name.json")
        _filed(client, two, "scenario", "same-name.json")
        other = open_route(client, two.source_root, two.evidence_root)["workspace_id"]

        borrowed = client.get(
            ARTIFACT.format(workspace_id=other, artifact_id=mine), headers=HEADERS
        )
        unknown = client.get(
            ARTIFACT.format(workspace_id=other, artifact_id="never-minted"), headers=HEADERS
        )

    assert borrowed.status_code == 404 == unknown.status_code
    assert borrowed.json() == unknown.json()


def test_a_credential_is_required_for_every_workspace_route(workspace: Workspace) -> None:
    """RES-375's own gate covers these routes without any extra wiring.

    Asserted here because a route that reached the registry without presenting the
    session credential would be a route the credential gate had missed, and this is the
    surface where that would be worth something.
    """

    from dynamisbench.api.session import (
        SessionCredential,
        secured_application,
    )

    application = secured_application(
        SessionCredential(digest=bytes(32)), ("http://tauri.localhost",)
    )
    with TestClient(application) as client:
        opened = client.post(
            OPEN,
            json={
                "source_root": str(workspace.source_root),
                "evidence_root": str(workspace.evidence_root),
            },
        )
        listed = client.get(ARTIFACTS.format(workspace_id="anything"))

    assert opened.status_code == 401 == listed.status_code
    assert opened.headers["WWW-Authenticate"] == "Bearer"
    assert opened.json() == {
        "error": {"code": "unauthorized", "message": "Authentication required."}
    }


# --------------------------------------------------------------------------- #
# Containment: links, traversals, and cross-category attempts
# --------------------------------------------------------------------------- #
def test_a_document_link_escaping_the_source_root_is_never_read(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    """The one escape a directory listing can make, and the refusal that closes it.

    Discovery reports the link as a bounded structural issue rather than an artifact, and
    the artifact route therefore never has an identifier to hand out for it. The refusal
    carries the portable reference and not the target.
    """
    from tests.workspace.links import make_directory_link, require_directory_link

    outside = tmp_path / "outside"
    (outside / "real-secret").mkdir(parents=True)
    (outside / "real-secret" / "inside.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

    kind = workspace.source_root / "benchmarks" / "scenario"
    kind.mkdir(parents=True, exist_ok=True)
    require_directory_link(
        make_directory_link(kind / "escape.json", outside / "real-secret"),
        "a symlinked document escaping the source root",
    )

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert not found["artifacts"]["artifacts"]
    assert [issue["code"] for issue in found["issues"]] == ["path_scope_violation"]
    assert str(outside) not in json.dumps(found)
    assert "real-secret" not in json.dumps(found)


def test_a_directory_link_escaping_the_source_root_is_not_followed(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    from tests.workspace.links import make_directory_link, require_directory_link

    outside = tmp_path / "outside"
    (outside / "scenario").mkdir(parents=True)
    (outside / "scenario" / "escape.yaml").write_text("a: 1\n", encoding="utf-8")

    kind = workspace.source_root / "benchmarks" / "scenario"
    kind.mkdir(parents=True, exist_ok=True)
    require_directory_link(
        make_directory_link(kind / "linked", outside / "scenario"),
        "a directory link escaping the source root",
    )

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert not found["artifacts"]["artifacts"]
    assert "escape.yaml" not in json.dumps(found)
    assert str(outside) not in json.dumps(found)


def test_a_symlinked_category_is_not_walked(client: TestClient, tmp_path: Path) -> None:
    """A category that is a link looks like authority and points somewhere else."""
    from tests.workspace.links import make_directory_link, require_directory_link

    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.BENCHMARKS]
    )
    outside = tmp_path / "outside-source"
    (outside / "benchmarks" / "benchmark").mkdir(parents=True)
    (outside / "benchmarks" / "benchmark" / "escape.json").write_text(
        json.dumps({"a": 1}), encoding="utf-8"
    )

    (workspace.source_root / "benchmarks").rmdir()
    require_directory_link(
        make_directory_link(workspace.source_root / "benchmarks", outside / "benchmarks"),
        "a category directory that is a link",
    )

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert not found["artifacts"]["artifacts"]
    assert any(issue["code"] == "path_scope_violation" for issue in found["issues"])


def test_discovery_reads_no_non_source_persistence_class(workspace: Workspace) -> None:
    """A second traversal, held at the workspace layer where it lives.

    Reported as a bounded structural issue rather than walked, so a ``tmp`` directory
    nested inside a kind directory is not described as source authority.
    """
    for name in ("runs", ".staging", "derived", "cache", "tmp"):
        nested = workspace.source_root / "studies" / "study" / name
        nested.mkdir(parents=True)
        (nested / "secret.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

    from dynamisbench.workspace.discovery import discover_sources

    found = discover_sources(open_workspace(workspace.source_root, workspace.evidence_root))

    assert not [locator for locator in found.locators if "secret" in locator.logical_reference]
    assert {issue.diagnostic.code.value for issue in found.issues} == {"unsupported_entry"}
    assert "secret" not in str(found.locators)


# --------------------------------------------------------------------------- #
# API memory is not authority
# --------------------------------------------------------------------------- #
def test_relocating_identical_authority_gives_an_identical_digest(tmp_path: Path) -> None:
    """The same authority at two roots is one meaning, and neither root appears.

    Each workspace has a different parent, a different root name, and a different evidence
    root, and the digests agree one for one. That is what makes an artifact's identity
    independent of where the machine happened to keep it.
    """
    digests: dict[str, str] = {}
    with TestClient(create_app()) as client:
        for label in ("here", "a-completely-different-place"):
            workspace = initialize_workspace(
                tmp_path / label / "authoritative-specifications",
                tmp_path / label / "run-evidence",
            )
            from tests.workspace.authority_fixtures import KIND_CATEGORIES, write_document

            for kind in KIND_CATEGORIES:
                write_document(workspace.source_root, kind, f"{kind}.json")

            workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)
            found = discover(client, workspace_id["workspace_id"])
            published = json.dumps(found)
            assert str(workspace.source_root) not in published
            assert str(workspace.evidence_root) not in published

            for artifact in found["artifacts"]["artifacts"]:
                digest = artifact["semantic_digest"]["hex"]
                assert digests.setdefault(artifact["logical_reference"], digest) == digest

    assert len(digests) == len(KIND_CATEGORIES)


def test_an_external_edit_changes_the_next_inspection(
    client: TestClient, workspace: Workspace
) -> None:
    """The re-read gate, stated as the thing it protects against.

    The first inspection reports one digest; the file is edited underneath; the next
    inspection of the same identifier reports the current bytes' digest. A cached
    validated object would have answered with the stale one, which is precisely the
    defect this suite exists to catch.
    """
    from tests.workspace.authority_fixtures import write_document

    path = write_document(workspace.source_root, "scenario", "release.json")
    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    artifact = next(
        entry["artifact_id"] for entry in discover(client, workspace_id)["artifacts"]["artifacts"]
    )
    before = inspect_artifact(client, workspace_id, artifact)

    # The same meaning, re-authored in a form that changes nothing about identity.
    document = json.loads(path.read_text(encoding="utf-8"))
    document["description"] = "A different description of an identical scenario."
    path.write_text(json.dumps(document, indent=4), encoding="utf-8")

    edited = inspect_artifact(client, workspace_id, artifact)
    assert edited["identifier"] == before["identifier"]
    assert edited["semantic_digest"]["hex"] != before["semantic_digest"]["hex"]
    assert edited["content"]["description"] == document["description"]

    # And an edit that invalidates it removes the identity and the digest with it.
    path.write_text("not a mapping", encoding="utf-8")
    broken = inspect_artifact(client, workspace_id, artifact)

    assert broken["validation_status"] == "invalid"
    assert broken["identifier"] is None
    assert broken["version"] is None
    assert broken["semantic_digest"] is None
    assert broken["content"] is None
    assert broken["diagnostics"]


def test_discovery_rescans_rather_than_reporting_what_it_saw(
    client: TestClient, workspace: Workspace
) -> None:
    """A live repository is edited while the application runs."""
    from tests.workspace.authority_fixtures import write_document

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    assert not discover(client, workspace_id)["artifacts"]["artifacts"]

    write_document(workspace.source_root, "metric", "new.json")
    assert len(discover(client, workspace_id)["artifacts"]["artifacts"]) == 1

    (workspace.source_root / "schemas" / "metric" / "new.json").unlink()
    assert not discover(client, workspace_id)["artifacts"]["artifacts"]


def test_an_open_a_discovery_and_an_inspection_change_nothing(
    client: TestClient, workspace: Workspace
) -> None:
    """The side-effect rule, measured across every operation this API offers.

    A snapshot before and after an open, a discovery, and an inspection of everything
    found. A ``mkdir``, a cache file, a lock file, an index, a normalisation, and an
    ``mtime`` touch each move one of those facts.
    """
    from tests.workspace.authority_fixtures import KIND_CATEGORIES, write_document

    for kind in KIND_CATEGORIES:
        write_document(workspace.source_root, kind, f"{kind}.json")
    baseline = {**snapshot(workspace.source_root), **snapshot(workspace.evidence_root)}

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)
    for artifact in found["artifacts"]["artifacts"]:
        inspect_artifact(client, workspace_id, artifact["artifact_id"])
    discover(client, workspace_id)

    assert {**snapshot(workspace.source_root), **snapshot(workspace.evidence_root)} == baseline
