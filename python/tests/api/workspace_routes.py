"""Shared fixtures and helpers for the workspace-route qualification suites.

One client, one open, one discover, one inspect, and one snapshot — defined once so that
every gate in this directory is exercising the same thing about the same inputs, and so the
two suites cannot drift into describing different routes.

:data:`HEADERS` carries a credential-shaped header. ``create_app`` builds an *unsecured*
application (RES-375): the credential gate is the session's own middleware and is tested in
its own suite. These headers record that a credential-bearing client is the client these
routes are for, without depending on the session's policy being installed — and
``test_a_credential_is_required_for_every_workspace_route`` checks the secured composition
separately, so the two halves are each measured by the suite that owns them.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dynamisbench.api import API_V1_PREFIX, create_app

from .factories import CREDENTIAL

OPEN = f"{API_V1_PREFIX}/workspaces/open"
"""The one route that takes absolute operational paths, because it is root selection."""

ARTIFACTS = f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts"
ARTIFACT = f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts/{{artifact_id}}"

HEADERS = {"Authorization": f"Bearer {CREDENTIAL}"}


def client() -> TestClient:
    """One application instance, unsecured: the session applies its own credential gate."""
    return TestClient(create_app())


def open_route(api: TestClient, source: Path, evidence: Path) -> dict:
    """Open an existing workspace, asserting the response is a successful read model."""
    response = api.post(
        OPEN,
        json={"source_root": str(source), "evidence_root": str(evidence)},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def discover(api: TestClient, workspace_id: str) -> dict:
    """Discover a workspace's source authority, asserting a successful read model."""
    response = api.get(ARTIFACTS.format(workspace_id=workspace_id), headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def inspect_artifact(api: TestClient, workspace_id: str, artifact_id: str) -> dict:
    """Inspect one artifact, asserting a successful read model.

    A failing inspection is not a failed request: an invalid document answers with a 200
    whose ``validation_status`` is ``"invalid"`` and whose diagnostics explain it. Asserting
    the status here rather than a validity flag is what keeps that distinction visible.
    """
    response = api.get(
        ARTIFACT.format(workspace_id=workspace_id, artifact_id=artifact_id), headers=HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(root: Path) -> dict[str, tuple[int, float]]:
    """Everything a request could disturb: name, size, and modification time.

    Not a hash of contents. These suites claim that the API is *inert*, and a content hash
    would only show that nothing changed in what a test wrote; the size and the mtime are
    the facts a create, a rewrite, a normalisation, or a touch would move.
    """
    observed: dict[str, tuple[int, float]] = {}
    if not root.exists():
        return observed
    for entry in sorted(root.rglob("*")):
        key = entry.relative_to(root).as_posix()
        if entry.is_symlink() or entry.is_dir():
            observed[key] = (-1, -1)
            continue
        stat = entry.stat()
        observed[key] = (stat.st_size, stat.st_mtime)
    return observed


__all__ = [
    "ARTIFACT",
    "ARTIFACTS",
    "HEADERS",
    "OPEN",
    "client",
    "discover",
    "inspect_artifact",
    "open_route",
    "snapshot",
]
