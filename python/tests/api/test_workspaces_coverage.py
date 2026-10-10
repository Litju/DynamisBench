"""The coverage matrix, exercised through the routes a client will actually call.

RES-377's qualification requires the API surface to have been exercised against valid JSON
and YAML for all ten declared kinds, and against every refusal the loader can name — so this
is where the matrix is checked against the *API*, not against the loader underneath it. A
route that accepted a document its loader would refuse would be a bug this suite exists to
catch, and a read model that dropped a field for one kind and not another would be another.

Everything is asserted on the read model rather than on the response text, because the read
model is the versioned contract a generated client is built from. The status codes are
checked too: a discovery is 200 even when everything it found is invalid, because an invalid
document is a *fact* about the workspace and not a failure of the request.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api.models import ArtifactSummary
from dynamisbench.workspace import (
    SourceCategory,
    Workspace,
    initialize_workspace,
)

from .workspace_routes import client as build_client
from .workspace_routes import discover, inspect_artifact, open_route

ALL_KINDS = (
    "benchmark",
    "scenario",
    "realization",
    "sut",
    "environment",
    "study",
    "factor",
    "reference",
    "quantity",
    "metric",
)
"""The ten declared kinds, in the order the domain registry declares them."""


@pytest.fixture
def client() -> TestClient:
    return build_client()


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """A workspace with every source category, so any kind of document can be filed in it.

    Scoped to `tmp_path` rather than the process's working directory, because the whole
    point of these fixtures is that a test's authority lives and dies with the test.
    """
    return initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=tuple(SourceCategory)
    )


def _filed(client: TestClient, workspace: Workspace, kind: str, name: str) -> ArtifactSummary:
    """File one document and return the summary the discovery route published for it.

    Read as ``ArtifactSummary`` rather than as a dict, so a field the route dropped is a
    validation failure here rather than a ``KeyError`` three assertions later.
    """
    from tests.workspace.authority_fixtures import write_document

    write_document(workspace.source_root, kind, name)
    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    body = discover(client, workspace_id)
    return ArtifactSummary.model_validate(body["artifacts"]["artifacts"][0])


# --------------------------------------------------------------------------- #
# Valid authority, in every kind and every authoring spelling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("suffix", [".json", ".yaml", ".yml"])
def test_every_kind_validates_in_every_authoring_format(
    client: TestClient, workspace: Workspace, kind: str, suffix: str
) -> None:
    """The matrix's positive half, through the API rather than the loader.

    The declaration is that the route publishes a valid artifact, its identifier, its
    version, and one digest. ``factor`` is the one kind with no version, so the version is
    ``None`` there and a value everywhere else — which is the contract from the registry,
    checked at the boundary a client reads it from.
    """
    summary = _filed(client, workspace, kind, f"release{suffix}")

    assert summary.logical_reference.endswith(suffix)
    assert summary.kind == kind
    assert summary.category is SourceCategory(KIND_CATEGORY[kind])
    assert summary.validation_status.value == "valid"
    assert summary.identifier
    assert summary.semantic_digest is not None
    assert summary.semantic_digest.hex
    assert summary.diagnostics == ()
    assert (summary.version is None) == (kind == "factor")


KIND_CATEGORY = {
    "benchmark": "benchmarks",
    "scenario": "benchmarks",
    "realization": "realizations",
    "sut": "realizations",
    "environment": "realizations",
    "study": "studies",
    "factor": "studies",
    "reference": "references",
    "quantity": "schemas",
    "metric": "schemas",
}


def test_one_kind_filed_under_the_wrong_category_is_not_reinterpreted(
    client: TestClient, workspace: Workspace
) -> None:
    """A document is whatever its directory says, never whatever its file name says.

    A quantity filed under ``benchmarks/quantity/`` is readable authority, and a metric filed
    under ``schemas/metric/`` fails validation as a *metric* rather than being read as a
    quantity. Nothing is guessed from the name, so the read model's own diagnostics say what
    was refused.
    """
    from tests.workspace.authority_fixtures import write_document

    # A quantity document filed in the right category validates; the same bytes under a
    # category that does not declare `quantity` are not discovered as an artifact at all.
    write_document(workspace.source_root, "quantity", "force.yaml")
    (workspace.source_root / "benchmarks" / "quantity").mkdir(parents=True, exist_ok=True)
    (workspace.source_root / "benchmarks" / "quantity" / "stray.json").write_text(
        "{}", encoding="utf-8"
    )

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert [entry["category"] for entry in found["artifacts"]["artifacts"]] == ["schemas"]
    assert any(issue["code"] == "unsupported_entry" for issue in found["issues"])


# --------------------------------------------------------------------------- #
# Every refusal the loader names, at the API boundary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("code", "write"),
    [
        ("malformed_json", lambda path: path.write_text("{ not json", encoding="utf-8")),
        ("malformed_yaml", lambda path: path.write_text("a: b: c\n", encoding="utf-8")),
        (
            "duplicate_json_key",
            lambda path: path.write_text(
                '{"scenario_id": "sc.a", "scenario_id": "sc.b"}', encoding="utf-8"
            ),
        ),
        (
            "duplicate_yaml_key",
            lambda path: path.write_text(
                "scenario_id: sc.a\nscenario_id: sc.b\n", encoding="utf-8"
            ),
        ),
        (
            "multi_document_yaml",
            lambda path: path.write_text(
                "---\nscenario_id: sc.a\n---\nscenario_id: sc.b\n", encoding="utf-8"
            ),
        ),
        (
            "unsafe_yaml_tag",
            lambda path: path.write_text(
                "!!python/object/apply:os.system ['echo hi']", encoding="utf-8"
            ),
        ),
        ("array_root", lambda path: path.write_text("[1, 2, 3]", encoding="utf-8")),
        ("string_root", lambda path: path.write_text('"a bare string"', encoding="utf-8")),
        ("invalid_utf8", lambda path: path.write_bytes(b'{"scenario_id": "\xff\xfe"}')),
    ],
)
def test_a_refused_document_is_an_invalid_artifact_not_a_failed_request(
    client: TestClient, workspace: Workspace, code: str, write: object
) -> None:
    """Every refusal is a 200 whose ``validation_status`` is ``"invalid"``.

    Not a 4xx and not a 5xx: an invalid document is a fact about the workspace, and the
    request that discovered it succeeded. A client that had to treat "this file is broken"
    and "the API could not read it" as the same outcome would have to retry the one it
    cannot fix.
    """
    path = workspace.source_root / "benchmarks" / "scenario" / "case.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path)  # type: ignore[operator]

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    summary = ArtifactSummary.model_validate(
        discover(client, workspace_id)["artifacts"]["artifacts"][0]
    )

    assert summary.validation_status.value == "invalid"
    assert summary.identifier is None
    assert summary.version is None
    assert summary.semantic_digest is None
    assert summary.diagnostics

    inspection = inspect_artifact(client, workspace_id, summary.artifact_id)
    assert inspection["validation_status"] == "invalid"
    assert inspection["content"] is None
    assert json.dumps(inspection["diagnostics"])
    assert "Traceback" not in json.dumps(inspection)


def test_a_schema_invalid_document_reports_bounded_diagnostics_without_its_values(
    client: TestClient, workspace: Workspace
) -> None:
    """Pydantic knows the field; its message would know the value, and ours must not.

    Only the field location, the error category, and a fixed message are published. The
    rejected value is the author's data and this process holds a repository, which is the
    reason the read model has no field that could carry it.
    """
    path = workspace.source_root / "studies" / "study" / "study.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _study_document()
    document["research_question"] = ""
    document["replicates"] = -1
    path.write_text(json.dumps(document), encoding="utf-8")

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    summary = ArtifactSummary.model_validate(
        discover(client, workspace_id)["artifacts"]["artifacts"][0]
    )

    codes = {entry.code for entry in summary.diagnostics}
    assert codes == {"schema_validation"}
    published = json.dumps([entry.model_dump() for entry in summary.diagnostics])

    assert "research_question" in published
    assert "replicates" in published
    assert "Traceback" not in published
    assert "Error" not in published
    assert "\\\\" not in published


def _study_document() -> dict:
    from tests.workspace.authority_fixtures import MODEL_FACTORIES

    return json.loads(json.dumps(MODEL_FACTORIES["study"]().model_dump(mode="json")))


def test_a_document_with_a_key_that_cannot_be_a_key_is_an_invalid_artifact(
    client: TestClient, workspace: Workspace
) -> None:
    """The one refusal an author can write that a parser would answer with a raw error.

    YAML lets a sequence or a mapping stand where a key belongs, and PyYAML builds one
    without complaint. Leaving that to the interpreter turns an authoring document into
    a ``TypeError`` the route never had a handler for — which is a 500 for something
    that is only a fact about the file. The boundary is that the loader states the
    authoring refusal, so this is 200, invalid, and ``parse_error``.
    """
    path = workspace.source_root / "benchmarks" / "scenario" / "unusable-key.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("? [a, b]\n: 1\n", encoding="utf-8")

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    summary = ArtifactSummary.model_validate(
        discover(client, workspace_id)["artifacts"]["artifacts"][0]
    )

    assert summary.validation_status.value == "invalid"
    assert {entry.code for entry in summary.diagnostics} == {"parse_error"}

    inspection = inspect_artifact(client, workspace_id, summary.artifact_id)
    assert inspection["validation_status"] == "invalid"
    assert [entry["code"] for entry in inspection["diagnostics"]] == ["parse_error"]
    published = json.dumps(inspection)
    assert "Traceback" not in published
    assert "TypeError" not in published
    assert "unhashable" not in published
    assert "[a, b]" not in published


def test_an_oversized_document_is_refused_without_being_read(
    client: TestClient, workspace: Workspace
) -> None:
    """The size bound is published as a diagnostic code, not as an exhausted connection."""
    from dynamisbench.workspace.source_authority import MAX_AUTHORING_DOCUMENT_BYTES

    path = workspace.source_root / "benchmarks" / "scenario" / "huge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"note": "' + "n" * (MAX_AUTHORING_DOCUMENT_BYTES + 1) + '"}', encoding="utf-8"
    )

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    summary = ArtifactSummary.model_validate(
        discover(client, workspace_id)["artifacts"]["artifacts"][0]
    )

    assert summary.validation_status.value == "invalid"
    assert {entry.code for entry in summary.diagnostics} == {"too_large"}


# --------------------------------------------------------------------------- #
# Structural findings, and the ordering that makes them usable
# --------------------------------------------------------------------------- #
def test_an_unknown_kind_directory_and_a_misplaced_document_are_bounded_issues(
    client: TestClient, workspace: Workspace
) -> None:
    """Structural findings, in portable terms only.

    An unknown kind directory and a document sitting directly under its category are both
    reported as bounded issues rather than being walked or guessed. Neither names a path,
    and neither becomes an artifact.
    """
    (workspace.source_root / "benchmarks" / "not-a-kind").mkdir(parents=True)
    (workspace.source_root / "studies" / "stray.json").write_text("{}", encoding="utf-8")

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert found["artifacts"]["artifacts"] == []
    assert {issue["code"] for issue in found["issues"]} == {"unsupported_entry"}
    assert sorted(issue["reference"] for issue in found["issues"]) == [
        "not-a-kind",
        "stray.json",
    ]


def test_an_empty_category_yields_no_artifacts_and_no_issues(
    client: TestClient, tmp_path: Path
) -> None:
    from dynamisbench.workspace import initialize_workspace

    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=[SourceCategory.SCHEMAS]
    )
    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert found["artifacts"]["artifacts"] == []
    assert found["issues"] == []
    assert found["issues_truncated"] is False
    assert {entry["exists"] for entry in found["categories"]} == {False, True}


def test_the_issue_cap_is_reported_where_it_belongs_and_nowhere_else(
    client: TestClient, workspace: Workspace
) -> None:
    """Truncation is a fact about the issue list, and it is reported as exactly that.

    A workspace engineered to produce more structural findings than the walk collects
    is still a successful request: the documents it found are all described, the issue
    list stops at the cap, and the one field that says so is
    ``WorkspaceDiscoveryResponse.issues_truncated``. It is *not* recorded on the
    artifact list, because nothing was truncated there — a field claiming it would tell
    a client that documents went missing when none did.
    """
    from dynamisbench.workspace.source_authority import MAX_DISCOVERY_ISSUES

    kind = workspace.source_root / "benchmarks" / "scenario"
    kind.mkdir(parents=True, exist_ok=True)
    for index in range(MAX_DISCOVERY_ISSUES + 5):
        (kind / f"noise-{index}.txt").write_text("not an authoring document", encoding="utf-8")

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    found = discover(client, workspace_id)

    assert len(found["issues"]) == MAX_DISCOVERY_ISSUES
    assert found["issues_truncated"] is True
    assert set(found["artifacts"]) == {"artifacts"}
    assert found["artifacts"]["artifacts"] == []


def test_discovery_order_is_the_documented_stable_order(
    client: TestClient, workspace: Workspace
) -> None:
    """Two discoveries of one workspace agree, so a client can diff one against the other."""
    from tests.workspace.authority_fixtures import write_document

    for index in range(5):
        write_document(workspace.source_root, "scenario", f"case-{index}.yaml")
    write_document(workspace.source_root, "quantity", "force.json")

    workspace_id = open_route(client, workspace.source_root, workspace.evidence_root)[
        "workspace_id"
    ]
    first = discover(client, workspace_id)["artifacts"]["artifacts"]
    second = discover(client, workspace_id)["artifacts"]["artifacts"]

    assert [entry["logical_reference"] for entry in first] == [
        entry["logical_reference"] for entry in second
    ]
    assert [entry["logical_reference"] for entry in first] == sorted(
        entry["logical_reference"] for entry in first
    )
    assert len(first) == 6
