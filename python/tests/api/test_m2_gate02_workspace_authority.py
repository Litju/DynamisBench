"""Gate 2: the live secured API over a real temporary DynamisBench workspace.

The workspace suites in this directory prove the routes' read models against an in-process
application. This suite makes the M2 end-to-end claim instead: a real
``python -m dynamisbench api serve`` child, a real bearer credential, a real origin policy,
and two real temporary roots on this machine.

The lifecycle exercised is the one the workbench performs:

```text
POST open   → one opaque workspace identifier, no roots in the response
GET  discover → the current source artifacts, with their validation state
GET  inspect  → the selected artifact, re-read and revalidated now, with its semantic digest
GET  inspect again → the same bytes, the same digest
external edit → the next inspection reflects the edit, because nothing was cached
```

Every operation is bracketed by a full snapshot of both roots — file names, content digests,
sizes and modification times — so the suite measures the inertness it claims rather than
asserting it. Paths are never published: the refusals are the fixed ones the application
defines, and a linked escape is reported without its target.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from dynamisbench.api import API_V1_PREFIX
from dynamisbench.api.workspaces import (
    ARTIFACT_NOT_FOUND,
    WORKSPACE_NOT_FOUND,
    WORKSPACE_OPEN_REFUSED,
)
from dynamisbench.domain.spec import authority_kind
from dynamisbench.workspace import SourceCategory, initialize_workspace
from dynamisbench.workspace.source_authority import document_identity, validate_document

from ..workspace.links import make_directory_link, require_directory_link
from .live_sidecar import (
    DEVELOPMENT_ORIGIN,
    LiveSidecar,
    assert_clean_shutdown,
    payload,
    running_sidecar,
    workspace_snapshot,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "domain"
VALID_SCENARIO = FIXTURES / "valid" / "scenario_definition.loaded_cmj.json"
INVALID_SCENARIO = FIXTURES / "invalid" / "scenario_definition.non_positive_duration.json"

OPEN = f"{API_V1_PREFIX}/workspaces/open"
ARTIFACTS = f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts"
ARTIFACT = f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts/{{artifact_id}}"

SCENARIO_KIND = "scenario"


def _independent_digest(path: Path) -> str:
    """The semantic digest of one file, computed without the workspace or API layer.

    The same authority pipeline is used — a validated model and its canonical bytes — but it
    is reached from the file directly, so this is not the API repeating its own answer.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    kind = authority_kind(SCENARIO_KIND)
    model = validate_document(kind, document)
    return document_identity(kind, model).digest.hex


@pytest.fixture
def workspace_roots(tmp_path: Path) -> Iterator[tuple[Path, Path, Path, Path]]:
    """Two initialised workspaces with one valid and one invalid scenario each.

    The valid document is the committed M1 fixture, so its successful validation is the
    scientific authority's own; the invalid one is a committed invalid fixture, so the
    diagnostics are a real refusal rather than an invented malformed file.
    """
    roots: list[Path] = []
    for name in ("first", "second"):
        source = tmp_path / name / "authority-repository"
        evidence = tmp_path / name / "sealed-evidence"
        initialize_workspace(source, evidence, sources=tuple(SourceCategory))
        scenario = source / "benchmarks" / "scenario"
        scenario.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(VALID_SCENARIO, scenario / "valid_scenario.json")
        shutil.copyfile(INVALID_SCENARIO, scenario / "invalid_scenario.json")
        roots.append(source)
        roots.append(evidence)
    first_source, first_evidence, second_source, second_evidence = roots
    yield first_source, first_evidence, second_source, second_evidence


def _open(sidecar: LiveSidecar, source: Path, evidence: Path) -> dict:
    status, headers, body = sidecar.request(
        "POST",
        OPEN,
        origin=DEVELOPMENT_ORIGIN,
        body={"source_root": str(source), "evidence_root": str(evidence)},
    )
    assert status == 200, body
    assert headers.get("access-control-allow-origin") == DEVELOPMENT_ORIGIN
    return payload((status, headers, body))


def _discover(sidecar: LiveSidecar, workspace_id: str) -> dict:
    status, headers, body = sidecar.request(
        "GET",
        ARTIFACTS.format(workspace_id=workspace_id),
        origin=DEVELOPMENT_ORIGIN,
    )
    assert status == 200, body
    assert headers.get("access-control-allow-origin") == DEVELOPMENT_ORIGIN
    return payload((status, headers, body))


def _inspect(sidecar: LiveSidecar, workspace_id: str, artifact_id: str) -> dict:
    status, headers, body = sidecar.request(
        "GET",
        ARTIFACT.format(workspace_id=workspace_id, artifact_id=artifact_id),
        origin=DEVELOPMENT_ORIGIN,
    )
    assert status == 200, body
    assert headers.get("access-control-allow-origin") == DEVELOPMENT_ORIGIN
    return payload((status, headers, body))


def _by_reference(discovery: dict) -> dict[str, dict]:
    return {
        artifact["logical_reference"]: artifact for artifact in discovery["artifacts"]["artifacts"]
    }


def _assert_bounded_refusal(
    response: tuple[int, dict[str, str], bytes], status: int, message: str
) -> None:
    code, _, body = response
    assert code == status, body
    refusal = json.loads(body)["error"]
    assert refusal["message"] == message
    assert "Traceback" not in body.decode("utf-8")


def test_a_live_workspace_is_opened_discovered_selected_and_re_read_without_a_cache(
    workspace_roots: tuple[Path, Path, Path, Path],
) -> None:
    source, evidence, _, _ = workspace_roots
    valid_file = source / "benchmarks" / "scenario" / "valid_scenario.json"
    expected_digest = _independent_digest(valid_file)

    with running_sidecar() as sidecar:
        before = workspace_snapshot(source), workspace_snapshot(evidence)

        opened = _open(sidecar, source, evidence)
        workspace_id = opened["workspace_id"]
        published = json.dumps(opened)
        assert source.name not in published
        assert evidence.name not in published
        assert str(source) not in published
        assert str(evidence) not in published
        assert "/" not in workspace_id and "\\" not in workspace_id

        discovery = _discover(sidecar, workspace_id)
        assert discovery["workspace_id"] == workspace_id
        artifacts = _by_reference(discovery)
        assert set(artifacts) == {
            "benchmarks/scenario/invalid_scenario.json",
            "benchmarks/scenario/valid_scenario.json",
        }

        valid_summary = artifacts["benchmarks/scenario/valid_scenario.json"]
        invalid_summary = artifacts["benchmarks/scenario/invalid_scenario.json"]
        assert valid_summary["validation_status"] == "valid"
        assert valid_summary["identifier"] == "sc.loaded-cmj"
        assert valid_summary["version"] == "1.0.0"
        assert valid_summary["semantic_digest"] == {
            "algorithm": "sha256",
            "hex": expected_digest,
        }
        assert invalid_summary["validation_status"] == "invalid"
        assert invalid_summary["identifier"] is None
        assert invalid_summary["version"] is None
        assert invalid_summary["semantic_digest"] is None

        # Selection is the identifier the discovery response minted. The inspection re-reads
        # the file now and publishes the independently computed digest, not one remembered
        # from discovery.
        valid = _inspect(sidecar, workspace_id, valid_summary["artifact_id"])
        assert valid["artifact_id"] == valid_summary["artifact_id"]
        assert valid["validation_status"] == "valid"
        assert valid["semantic_digest"]["hex"] == expected_digest
        assert valid["content"] is not None
        assert valid["content"]["scenario_id"] == "sc.loaded-cmj"

        invalid = _inspect(sidecar, workspace_id, invalid_summary["artifact_id"])
        assert invalid["validation_status"] == "invalid"
        assert invalid["semantic_digest"] is None
        assert invalid["content"] is None
        assert invalid["diagnostics"], "an invalid artifact must explain its refusal"
        for diagnostic in invalid["diagnostics"]:
            assert diagnostic["code"]
            assert diagnostic["message"]
            assert len(diagnostic["message"]) <= 512

        # A second inspection of the same identifier is a second read of the same bytes.
        assert _inspect(sidecar, workspace_id, valid_summary["artifact_id"]) == valid

        after = workspace_snapshot(source), workspace_snapshot(evidence)
        assert after == before, "an open, a discovery or an inspection must write nothing"

        # An external edit is the only thing that changes the answer. The API's next read
        # reflects it, because no validated result was retained between requests.
        document = json.loads(valid_file.read_text(encoding="utf-8"))
        document["label"] = "Loaded countermovement jump (edited outside the API)"
        valid_file.write_text(json.dumps(document, indent=2), encoding="utf-8")
        edited = workspace_snapshot(source), workspace_snapshot(evidence)
        assert edited != before

        changed = _inspect(sidecar, workspace_id, valid_summary["artifact_id"])
        assert changed["validation_status"] == "valid"
        assert changed["content"]["label"] == document["label"]
        assert changed["semantic_digest"]["hex"] != expected_digest
        assert workspace_snapshot(source) == edited[0]

        assert_clean_shutdown(sidecar)


def test_the_live_api_refuses_unknown_cross_workspace_and_path_shaped_requests(
    workspace_roots: tuple[Path, Path, Path, Path],
) -> None:
    first_source, first_evidence, second_source, second_evidence = workspace_roots

    with running_sidecar() as sidecar:
        first = _open(sidecar, first_source, first_evidence)
        second = _open(sidecar, second_source, second_evidence)
        second_artifacts = _by_reference(_discover(sidecar, second["workspace_id"]))
        borrowed = second_artifacts["benchmarks/scenario/valid_scenario.json"]["artifact_id"]

        # An identifier from another workspace is the same refusal as one never minted.
        _assert_bounded_refusal(
            sidecar.request(
                "GET",
                ARTIFACT.format(workspace_id=first["workspace_id"], artifact_id=borrowed),
            ),
            404,
            ARTIFACT_NOT_FOUND,
        )
        _assert_bounded_refusal(
            sidecar.request("GET", ARTIFACTS.format(workspace_id="not-a-workspace")),
            404,
            WORKSPACE_NOT_FOUND,
        )
        _assert_bounded_refusal(
            sidecar.request(
                "POST",
                OPEN,
                body={
                    "source_root": str(first_source / "does-not-exist"),
                    "evidence_root": str(first_evidence),
                },
            ),
            400,
            WORKSPACE_OPEN_REFUSED,
        )

        # There is no route that accepts a path, a logical reference, or a file name and
        # returns its content. A traversal-shaped value is not a locator; it is a string
        # that matches no route or no minted identifier.
        probes = [
            f"{API_V1_PREFIX}/files?path=../../etc/passwd",
            f"{API_V1_PREFIX}/workspaces/{first['workspace_id']}/file",
            f"{API_V1_PREFIX}/workspaces/{first['workspace_id']}/artifacts/{borrowed}/content",
            f"{API_V1_PREFIX}/workspaces/..%2F..%2Fetc/artifacts",
            f"{API_V1_PREFIX}/workspaces/{first['workspace_id']}/artifacts/"
            "..%2F..%2Fscenario_definition.loaded_cmj.json",
        ]
        for path in probes:
            response = sidecar.request("GET", path)
            code, _, body = response
            assert code in {404, 405}, (path, code, body)
            text = body.decode("utf-8", "replace")
            assert "sc.loaded-cmj" not in text
            assert "scenario_definition" not in text
            assert str(first_source) not in text
            assert "Traceback" not in text

        assert_clean_shutdown(sidecar)


def test_a_linked_escape_is_never_read_or_disclosed(
    workspace_roots: tuple[Path, Path, Path, Path], tmp_path: Path
) -> None:
    source, evidence, _, _ = workspace_roots
    outside = tmp_path / "linked-target" / "scenario"
    outside.mkdir(parents=True)
    secret = "outside-authority-must-never-be-read"
    (outside / "secret_scenario.json").write_text(
        json.dumps({"scenario_id": secret}), encoding="utf-8"
    )
    link = source / "benchmarks" / "scenario" / "linked"
    mechanism = require_directory_link(
        make_directory_link(link, outside),
        "a live discovery of a directory link escaping the source root",
    )
    assert mechanism in {"junction", "symlink"}

    with running_sidecar() as sidecar:
        opened = _open(sidecar, source, evidence)
        discovery = _discover(sidecar, opened["workspace_id"])
        text = json.dumps(discovery)

        assert secret not in text
        assert "secret_scenario.json" not in text
        assert str(outside) not in text
        for artifact in discovery["artifacts"]["artifacts"]:
            inspected = _inspect(sidecar, opened["workspace_id"], artifact["artifact_id"])
            assert secret not in json.dumps(inspected)
            assert (
                inspected["logical_reference"] != "benchmarks/scenario/linked/secret_scenario.json"
            )

        assert any(issue["code"] == "path_scope_violation" for issue in discovery["issues"]), (
            "a refused link must be reported as a bounded structural finding"
        )

        assert_clean_shutdown(sidecar)

    if link.is_symlink():
        link.unlink()
    else:
        os.rmdir(link)


def test_a_restarted_live_api_invalidates_identifiers_and_preserves_authority(
    workspace_roots: tuple[Path, Path, Path, Path],
) -> None:
    source, evidence, _, _ = workspace_roots
    before = workspace_snapshot(source), workspace_snapshot(evidence)

    with running_sidecar() as first:
        opened = _open(first, source, evidence)
        workspace_id = opened["workspace_id"]
        discovery = _by_reference(_discover(first, workspace_id))
        valid_id = discovery["benchmarks/scenario/valid_scenario.json"]["artifact_id"]
        digest = _inspect(first, workspace_id, valid_id)["semantic_digest"]["hex"]
        old_credential = first.credential
        assert_clean_shutdown(first)

    with running_sidecar() as second:
        # A different process, a different credential, and no state carried across.
        assert second.credential != old_credential
        _assert_bounded_refusal(
            second.request(
                "GET", ARTIFACTS.format(workspace_id=workspace_id), token=old_credential
            ),
            401,
            "Authentication required.",
        )
        _assert_bounded_refusal(
            second.request("GET", ARTIFACTS.format(workspace_id=workspace_id)),
            404,
            WORKSPACE_NOT_FOUND,
        )

        reopened = _open(second, source, evidence)
        assert reopened["workspace_id"] != workspace_id
        rediscovery = _by_reference(_discover(second, reopened["workspace_id"]))
        new_valid = rediscovery["benchmarks/scenario/valid_scenario.json"]
        assert new_valid["artifact_id"] != valid_id
        reinspection = _inspect(second, reopened["workspace_id"], new_valid["artifact_id"])
        assert reinspection["semantic_digest"]["hex"] == digest

        after = workspace_snapshot(source), workspace_snapshot(evidence)
        assert after == before, "a restart and a reopen must not change scientific files"

        assert_clean_shutdown(second)
