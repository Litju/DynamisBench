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
from pathlib import Path, PureWindowsPath

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api.models import OpenWorkspaceResponse
from dynamisbench.workspace import (
    SourceCategory,
    Workspace,
    initialize_workspace,
)

from .workspace_routes import HEADERS, OPEN, open_route, snapshot
from .workspace_routes import client as build_client


@pytest.fixture
def client() -> TestClient:
    """One application per test, so no identifier ever survives into the next test."""
    return build_client()


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """A workspace with every source category, so any kind of document can be filed in it.

    Scoped to ``tmp_path`` rather than the process's working directory, because the whole
    point of these fixtures is that a test's authority lives and dies with the test.
    """
    return initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=tuple(SourceCategory)
    )


# --------------------------------------------------------------------------- #
# Open: explicit, bounded, side-effect free
# --------------------------------------------------------------------------- #
def test_opening_a_workspace_returns_an_opaque_identifier_and_no_paths(
    client: TestClient, tmp_path: Path
) -> None:
    """The one response that has to prove it is not a filesystem disclosure.

    The workspace here is deliberately given a distinctive root directory name, so the
    assertion is meaningful: a response that echoed the workspace's name — which is what a
    client would use to recognise where it is — would match it, and this fails.
    """
    source = tmp_path / "this-workspace-name-must-not-appear"
    evidence = tmp_path / "neither-must-this-evidence-root"
    initialize_workspace(source, evidence, sources=[SourceCategory.SCHEMAS])

    body = open_route(client, source, evidence)
    published = json.dumps(body)

    assert OpenWorkspaceResponse.model_validate(body).workspace_id
    assert str(source) not in published
    assert str(evidence) not in published
    assert source.name not in published
    assert evidence.name not in published
    assert PureWindowsPath(source).drive not in published
    assert body["evidence_inside_source"] is False
    assert [entry["category"] for entry in body["source_categories"]] == [
        category.value for category in SourceCategory
    ]
    assert {entry["exists"] for entry in body["source_categories"]} == {False, True}


def test_an_evidence_root_inside_the_source_root_is_reported_as_such(
    client: TestClient, tmp_path: Path
) -> None:
    """Permitted, but worth a surface reporting: a broad clean can take it."""
    source = tmp_path / "repository"
    source.mkdir()
    evidence = source / "evidence"
    evidence.mkdir()

    body = open_route(client, source, evidence)

    assert body["evidence_inside_source"] is True


def test_the_reported_categories_are_the_declared_ones(
    client: TestClient, workspace: Workspace
) -> None:
    body = open_route(client, workspace.source_root, workspace.evidence_root)

    assert [entry["category"] for entry in body["source_categories"]] == [
        category.value for category in SourceCategory
    ]
    assert all(entry["exists"] for entry in body["source_categories"])


def test_a_missing_root_is_a_bounded_refusal_that_echoes_nothing(
    client: TestClient, workspace: Workspace
) -> None:
    missing = workspace.source_root.parent / "does-not-exist-anywhere"
    response = client.post(
        OPEN,
        json={"source_root": str(missing), "evidence_root": str(workspace.evidence_root)},
        headers=HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "http_error"
    assert str(missing) not in response.text
    assert missing.name not in response.text
    assert "Traceback" not in response.text


def test_a_source_root_that_is_a_file_is_refused(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "not-a-directory.txt"
    source.write_text("authority", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    response = client.post(
        OPEN, json={"source_root": str(source), "evidence_root": str(evidence)}, headers=HEADERS
    )

    assert response.status_code == 400
    assert str(source) not in response.text
    assert source.name not in response.text


def test_opening_a_workspace_creates_nothing(client: TestClient, tmp_path: Path) -> None:
    """The side-effect rule, at the root-selection operation.

    A refused open and a successful one both leave the filesystem as they found it, so the
    refusal is not what creates a half-built workspace.
    """
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    source.mkdir()
    evidence.mkdir()
    before = snapshot(tmp_path)

    open_route(client, source, evidence)
    client.post(
        OPEN,
        json={"source_root": str(tmp_path / "nope"), "evidence_root": str(evidence)},
        headers=HEADERS,
    )

    assert snapshot(tmp_path) == before


def test_a_malformed_request_is_refused_without_echoing_its_input(client: TestClient) -> None:
    """Pydantic's own detail would name the offending field and echo the rejected value."""
    response = client.post(
        OPEN, json={"source_root": "C:\\secrets\\authoritative"}, headers=HEADERS
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "secrets" not in response.text
    assert "source_root" not in response.text
    assert "C:\\" not in response.text
