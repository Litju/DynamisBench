"""The strict authoring loader, and the identity of what it validated.

RES-377 reads YAML and JSON at runtime, so it needs a loader that refuses the
ambiguities scientific authoring cannot afford: two keys of the same name, several
documents in one file, a root that is not a mapping, bytes that are not UTF-8, a
document too large to be an authoring document, and a definition that does not
satisfy its model. Every one of those is a *bounded* refusal, and every one of them
never echoes the rejected bytes.

The other half of this suite is the positive claim, which is the reason the loader is
strict: identity comes from the validated model and not from the authoring syntax.
One definition written as JSON, as ``.yaml``, as ``.yml``, with different key order
and different whitespace, is one meaning with one semantic digest — and a digest is
reset to nothing the moment a document stops validating.

Nothing here opens a document by a path the filesystem handed over. Every locator is
resolved through the workspace, because that is the door RES-377 uses everywhere else,
and a loader that could be exercised without it would qualify a different module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from dynamisbench.domain.spec import AUTHORITY_KINDS, authority_kind
from dynamisbench.identity import semantic_sha256
from dynamisbench.workspace import (
    SourceCategory,
    Workspace,
    initialize_workspace,
    open_workspace,
)
from dynamisbench.workspace.source_authority import (
    AUTHORING_SUFFIXES,
    CATEGORY_KINDS,
    MAX_AUTHORING_DOCUMENT_BYTES,
    AuthoringFormat,
    DiagnosticCode,
    SourceAuthorityError,
    SourceLocator,
    parse_document,
    read_document_bytes,
    validate_document,
)
from tests.workspace.authority_fixtures import KIND_CATEGORIES, MODEL_FACTORIES, write_document

ALL_KINDS = tuple(MODEL_FACTORIES)


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    """A source root inside an initialised workspace, plus the workspace itself."""
    workspace = initialize_workspace(
        tmp_path / "source", tmp_path / "evidence", sources=tuple(SourceCategory)
    )
    return workspace.source_root


def kind_locator(kind: str, name: str) -> SourceLocator:
    """The locator one kind's document at ``name`` would have."""
    category = KIND_CATEGORIES[kind]
    return SourceLocator(category=category, kind=kind, segments=(kind, name))


def _valid_mapping(kind: str) -> dict:
    return json.loads(json.dumps(MODEL_FACTORIES[kind]().model_dump(mode="json")))


def _source_workspace(source_root: Path) -> Workspace:
    return open_workspace(source_root, source_root.parent / "evidence")


# --------------------------------------------------------------------------- #
# The declared layout, and the vocabulary it is built from
# --------------------------------------------------------------------------- #


def test_the_layout_covers_exactly_the_registry_vocabulary() -> None:
    """Where a kind is filed is not what a kind is, but the two must agree.

    A kind the domain declared and the layout forgot would be silently undiscoverable;
    a directory the layout declared and the domain never named would validate against
    nothing. Both are one kind of mistake, so both are checked from one direction.
    """
    filed = {kind for kinds in CATEGORY_KINDS.values() for kind in kinds}
    assert filed == set(AUTHORITY_KINDS)


def test_every_declared_category_declares_at_least_one_kind() -> None:
    assert set(CATEGORY_KINDS) == set(SourceCategory)
    assert all(kinds for kinds in CATEGORY_KINDS.values())


def test_factor_is_the_only_kind_without_a_version() -> None:
    versionless = {name for name, kind in AUTHORITY_KINDS.items() if kind.version_field is None}
    assert versionless == {"factor"}


def test_a_kind_names_its_own_directory_and_model_field() -> None:
    for name, kind in AUTHORITY_KINDS.items():
        assert kind.name == name
        assert kind.identifier_field.endswith("_id")
        assert kind.identifier_field in kind.model.model_fields
        if kind.version_field is not None:
            assert kind.version_field in kind.model.model_fields


def test_only_the_three_declared_suffixes_are_authoring_candidates() -> None:
    assert set(AUTHORING_SUFFIXES) == {".json", ".yaml", ".yml"}


# --------------------------------------------------------------------------- #
# Strict parsing: every refusal is bounded and echoes nothing
# --------------------------------------------------------------------------- #
def _refuses(raw: bytes, authoring: AuthoringFormat) -> list[DiagnosticCode]:
    """The codes a parse refusal reports, in order, or an empty list when it parses."""
    try:
        parse_document(raw, authoring)
    except SourceAuthorityError as error:
        return [entry.code for entry in error.diagnostics]
    return []


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_valid_json_and_yaml_both_parse_and_validate(kind: str, source_root: Path) -> None:
    """The coverage matrix's positive half, for every declared kind.

    One definition, two spellings. Writing through the fixture helper means the two
    documents are the same model serialised twice, so the assertion that follows —
    that identity came out the same — is a real property and not a coincidence of
    hand-written fixtures that happen to agree.
    """
    for suffix in (".json", ".yaml", ".yml"):
        workspace = _source_workspace(source_root)
        path = write_document(source_root, kind, f"release{suffix}", suffix=suffix)
        assert path.exists(), f"{kind} {suffix} was not written"

        raw = read_document_bytes(
            workspace.resolve_source(KIND_CATEGORIES[kind], f"{kind}/release{suffix}")
        )
        document = parse_document(
            raw, next(f for s, f in AUTHORING_SUFFIXES.items() if s == suffix)
        )
        model = validate_document(authority_kind(kind), document)
        assert str(getattr(model, AUTHORITY_KINDS[kind].identifier_field))


def test_a_document_is_one_meaning_whatever_its_authoring_syntax(source_root: Path) -> None:
    """Identity is over the validated model, so key order and syntax cannot move it.

    JSON and YAML of the same mapping, one of them re-sorted, digest identically. This
    is the property that makes a workspace relocatable and a repository bilingual without
    a benchmark changing its identity.
    """
    from dynamisbench.workspace.source_authority import inspect_locator

    document = _valid_mapping("benchmark")
    digests: set[str] = set()
    for suffix in (".json", ".yaml", ".yml"):
        workspace = _source_workspace(source_root)
        write_document(
            source_root, "benchmark", f"release{suffix}", suffix=suffix, content=document
        )
        inspection = inspect_locator(workspace, kind_locator("benchmark", f"release{suffix}"))
        assert inspection.valid, inspection.diagnostics
        digests.add(inspection.identity.digest.hex if inspection.identity else "")

    assert len(digests) == 1


def test_a_reordered_json_document_has_the_same_identity(source_root: Path) -> None:
    from dynamisbench.workspace.source_authority import inspect_locator

    document = _valid_mapping("benchmark")
    reordered = {key: document[key] for key in reversed(list(document))}
    workspace = _source_workspace(source_root)
    write_document(source_root, "benchmark", "a.json", content=document)
    write_document(source_root, "benchmark", "b.json", content=reordered)

    first = inspect_locator(workspace, kind_locator("benchmark", "a.json"))
    second = inspect_locator(workspace, kind_locator("benchmark", "b.json"))
    assert first.valid and second.valid
    assert first.identity is not None and second.identity is not None
    assert first.identity.digest == second.identity.digest


@pytest.mark.parametrize(
    ("code", "raw", "authoring"),
    [
        (DiagnosticCode.PARSE_ERROR, b"{ not json at all", AuthoringFormat.JSON),
        (DiagnosticCode.PARSE_ERROR, b"a: b: c\n", AuthoringFormat.YAML),
        (DiagnosticCode.PARSE_ERROR, b"key: [unclosed\n", AuthoringFormat.YAML),
        (DiagnosticCode.DUPLICATE_KEY, b'{"a": 1, "a": 2}', AuthoringFormat.JSON),
        (DiagnosticCode.DUPLICATE_KEY, b"a: 1\na: 2\n", AuthoringFormat.YAML),
        (DiagnosticCode.DUPLICATE_KEY, b'{"outer": {"b": 1, "b": 2}}', AuthoringFormat.JSON),
        (DiagnosticCode.DUPLICATE_KEY, b"outer:\n  b: 1\n  b: 2\n", AuthoringFormat.YAML),
        (DiagnosticCode.PARSE_ERROR, b"---\na: 1\n---\nb: 2\n", AuthoringFormat.YAML),
        (
            DiagnosticCode.PARSE_ERROR,
            b"!!python/object/apply:os.system ['echo hi']\n",
            AuthoringFormat.YAML,
        ),
        (DiagnosticCode.EXPECTED_OBJECT, b"[1, 2, 3]", AuthoringFormat.JSON),
        (DiagnosticCode.EXPECTED_OBJECT, b"- 1\n- 2\n", AuthoringFormat.YAML),
        (DiagnosticCode.EXPECTED_OBJECT, b'"a bare string"', AuthoringFormat.JSON),
        (DiagnosticCode.EXPECTED_OBJECT, b"just text\n", AuthoringFormat.YAML),
        (DiagnosticCode.INVALID_UTF8, b'{"a": "\xff\xfe"}', AuthoringFormat.JSON),
        (DiagnosticCode.INVALID_UTF8, b"a: \xff\xfe\n", AuthoringFormat.YAML),
    ],
)
def test_the_loader_refuses_in_scope_and_says_only_what_happened(
    code: DiagnosticCode, raw: bytes, authoring: str
) -> None:
    """The matrix's negative half. Each case refuses with one bounded code.

    ``authoring`` is the format name the case declares, spelled as a string rather than
    imported so that a case could not accidentally read as the other format.
    """
    from dynamisbench.workspace.source_authority import AuthoringFormat

    assert _refuses(raw, AuthoringFormat(authoring)) == [code]


def test_a_duplicated_key_is_refused_in_both_formats_even_nested() -> None:
    """A mapping anywhere in the document, not only the root, must be unambiguous."""
    from dynamisbench.workspace.source_authority import AuthoringFormat

    for raw, authoring in (
        (b'{"root": {"version": "1.0.0", "version": "1.0.0"}}', AuthoringFormat.JSON),
        (b"root:\n  version: 1.0.0\n  version: 1.0.0\n", AuthoringFormat.YAML),
    ):
        assert _refuses(raw, authoring) == [DiagnosticCode.DUPLICATE_KEY]


def test_a_yaml_alias_is_refused_rather_than_expanded() -> None:
    """An alias is the one YAML feature whose cost is not proportional to the text.

    Eight mebibytes of anchors can expand without any bound the size check could see,
    so the alias itself is refused. This costs a feature that carries no meaning in a
    definition: a scientific document restates what it means rather than sharing it.
    """
    from dynamisbench.workspace.source_authority import AuthoringFormat

    raw = b"first: &anchor\n  a: 1\nsecond: *anchor\n"
    assert _refuses(raw, AuthoringFormat.YAML) == [DiagnosticCode.PARSE_ERROR]


def test_an_oversized_document_is_refused_without_reading_past_the_bound() -> None:
    """``read_document_bytes`` stops at one byte over the ceiling.

    The bound is applied to what was read rather than to a stat, so a document that grew
    between the two is refused too — which is what the one-read implementation gets for
    free, and the reason it is not a stat followed by a read.
    """
    assert _refuses(b'{"audit": "' + b"x" * MAX_AUTHORING_DOCUMENT_BYTES, AuthoringFormat.JSON) == [
        DiagnosticCode.TOO_LARGE
    ]


def test_a_valid_document_just_under_the_ceiling_is_accepted() -> None:
    """The ceiling excludes nothing an authoring document can actually contain."""
    from dynamisbench.workspace.source_authority import AuthoringFormat

    # A JSON string of exactly the right length, counting the closing quote.
    body = b"n" * (MAX_AUTHORING_DOCUMENT_BYTES - len(b'{"note": ""}'))
    raw = b'{"note": "' + body + b'"}'
    assert len(raw) == MAX_AUTHORING_DOCUMENT_BYTES

    parsed = parse_document(raw, AuthoringFormat.JSON)
    assert len(parsed["note"]) == MAX_AUTHORING_DOCUMENT_BYTES - len(b'{"note": ""}')


def test_a_schema_failure_reports_field_locations_and_no_rejected_values() -> None:
    """Pydantic knows which field failed; its message knows the value too, and ours must not.

    Only the dotted field location and the error category are carried. The assertion
    that the rejected value is absent is the one that matters, because the boundary
    holding this process holds a repository.
    """

    kind = authority_kind("benchmark")
    document = _valid_mapping("benchmark")
    document["quantities"] = [{"bursts": True}]

    try:
        validate_document(kind, document)
    except SourceAuthorityError as error:
        diagnostics = error.diagnostics
    else:  # pragma: no cover - the fixture must fail validation
        pytest.fail("a broken benchmark document validated")

    assert diagnostics
    for entry in diagnostics:
        assert entry.code is DiagnosticCode.SCHEMA_VALIDATION
        assert entry.location is not None and entry.location.startswith("quantities")
        assert entry.category
        assert "bursts" not in json.dumps([entry.location, entry.category])
        assert "bursts" not in entry.message


def test_diagnostics_are_bounded_however_deep_the_failure() -> None:
    """A document engineered to fail a thousand ways gets at most the cap."""
    from dynamisbench.workspace.source_authority import MAX_SCHEMA_DIAGNOSTICS

    kind = authority_kind("benchmark")
    document = _valid_mapping("benchmark")
    document["quantities"] = [{f"field_{index}": index} for index in range(500)]

    with pytest.raises(SourceAuthorityError) as raised:
        validate_document(kind, document)
    assert len(raised.value.diagnostics) <= MAX_SCHEMA_DIAGNOSTICS


def test_an_invalid_document_has_no_identity_no_digest_and_no_content(
    source_root: Path,
) -> None:
    """The boundary that keeps a hash from meaning "authority" when nothing validated.

    An invalid document reports its diagnostics and nothing else: no identifier, no
    version, no digest, no content. There is no state in which these coexist.
    """
    from dynamisbench.workspace.source_authority import inspect_locator

    workspace = _source_workspace(source_root)
    write_document(
        source_root,
        "benchmark",
        "broken.json",
        content={**_valid_mapping("benchmark"), "claim_ceiling": ""},
    )
    inspection = inspect_locator(workspace, kind_locator("benchmark", "broken.json"))

    assert inspection.valid is False
    assert inspection.identity is None
    assert inspection.content is None
    assert inspection.diagnostics


def test_a_valid_inspection_carries_the_validated_read_model(source_root: Path) -> None:
    """``content`` is the model's JSON-mode read model, not the raw text."""
    from dynamisbench.workspace.source_authority import inspect_locator

    workspace = _source_workspace(source_root)
    write_document(source_root, "study", "study.json")
    inspection = inspect_locator(workspace, kind_locator("study", "study.json"))

    assert inspection.valid is True
    assert inspection.content is not None
    assert inspection.identity is not None
    assert inspection.identity.identifier == "study.contact-stiffness-sensitivity"
    assert inspection.identity.version == "1.0.0"
    assert inspection.content["study_id"] == inspection.identity.identifier
    assert json.dumps(inspection.content, sort_keys=True)


def test_identity_is_the_existing_pipeline_over_the_validated_model(source_root: Path) -> None:
    """The digest is ``semantic_sha256`` of the model, nothing else."""
    from dynamisbench.workspace.source_authority import inspect_locator

    workspace = _source_workspace(source_root)
    write_document(source_root, "quantity", "force.yaml", suffix=".yaml")
    inspection = inspect_locator(workspace, kind_locator("quantity", "force.yaml"))

    model = MODEL_FACTORIES["quantity"]()
    assert inspection.valid is True
    assert inspection.identity is not None
    assert inspection.identity.digest == semantic_sha256(model)


def test_an_unknown_kind_directory_is_refused_rather_than_guessed(source_root: Path) -> None:
    """A directory the layout does not declare has no model behind it."""
    category = KIND_CATEGORIES["benchmark"]
    declared = set(CATEGORY_KINDS[category])
    assert "metric" not in declared
    assert "benchmark" in declared and "scenario" in declared


def test_a_locator_never_carries_an_absolute_path(source_root: Path) -> None:
    from dynamisbench.workspace.source_authority import inspect_locator

    workspace = _source_workspace(source_root)
    write_document(source_root, "scenario", "nested/deep/case.yaml")
    locator = kind_locator("scenario", "nested/deep/case.yaml")
    inspection = inspect_locator(workspace, locator)

    assert inspection.valid is True
    assert locator.logical_reference == "benchmarks/scenario/nested/deep/case.yaml"
    assert str(source_root) not in locator.logical_reference
    assert locator.category_reference == "scenario/nested/deep/case.yaml"


def test_a_locator_resolves_only_against_its_own_category(source_root: Path) -> None:
    """A locator naming one category resolves only against that category.

    ``resolve_source`` scopes a reference to its category, so the same file name filed
    under two categories is two different documents and reading one through the other is
    refused rather than answered. The refusal is bounded and the path is never echoed.
    """
    from dynamisbench.workspace.source_authority import inspect_locator

    write_document(source_root, "benchmark", "same.json")
    write_document(source_root, "quantity", "same.json")

    misplaced = SourceLocator(
        category=SourceCategory.SCHEMAS, kind="benchmark", segments=("benchmark", "same.json")
    )
    misplaced_name = SourceLocator(
        category=SourceCategory.BENCHMARKS,
        kind="benchmark",
        segments=("benchmark", "../scenario/same.json"),
    )

    workspace = _source_workspace(source_root)
    inspection = inspect_locator(workspace, misplaced)
    traversal = inspect_locator(workspace, misplaced_name)

    # The first names a category that does not hold it, so resolution never finds it and
    # the read refuses; the second tries to leave its category, so resolution refuses.
    assert inspection.valid is False
    assert traversal.diagnostics[0].code is DiagnosticCode.PATH_SCOPE_VIOLATION


def test_a_locator_pointing_outside_the_root_is_never_read(
    source_root: Path, tmp_path: Path
) -> None:
    """The containment proof, at the reader's own entry point.

    A document whose link resolves outside the authorised source root is refused before
    its bytes are read, and the refusal does not carry the target. This is the case the
    walk alone cannot catch, because the link is what made the path.
    """
    from dynamisbench.workspace.source_authority import inspect_locator
    from tests.workspace.links import make_directory_link

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "escape.yaml").write_text("a: 1\n", encoding="utf-8")

    inside = source_root / "benchmarks" / "scenario"
    inside.mkdir(parents=True, exist_ok=True)
    assert make_directory_link(inside / "linked", outside) in {"junction", "symlink"}

    workspace = _source_workspace(source_root)
    locator = SourceLocator(
        category=SourceCategory.BENCHMARKS,
        kind="scenario",
        segments=("scenario", "linked", "escape.yaml"),
    )
    inspection = inspect_locator(workspace, locator)

    assert inspection.valid is False
    assert inspection.diagnostics[0].code is DiagnosticCode.PATH_SCOPE_VIOLATION
    assert "escape" not in inspection.diagnostics[0].message
    assert str(outside) not in inspection.diagnostics[0].message


def test_a_traversal_reference_never_reaches_the_filesystem(
    source_root: Path, tmp_path: Path
) -> None:
    """The lexical gate, at the reader's own entry point.

    ``../../outside`` is refused before the filesystem is consulted, because the gate
    that accepts it is the reference language's, not the kernel's.
    """
    from dynamisbench.workspace.source_authority import inspect_locator

    (tmp_path / "outside.yaml").write_text("a: 1\n", encoding="utf-8")
    workspace = _source_workspace(source_root)
    locator = SourceLocator(
        category=SourceCategory.BENCHMARKS,
        kind="scenario",
        segments=("scenario", "..", "..", "..", "outside.yaml"),
    )
    inspection = inspect_locator(workspace, locator)

    assert inspection.valid is False
    assert inspection.diagnostics[0].code is DiagnosticCode.PATH_SCOPE_VIOLATION


def test_parse_document_is_reusable_without_a_workspace() -> None:
    """The loader's contract is bytes plus format: no filesystem dependency."""
    from dynamisbench.workspace.source_authority import AuthoringFormat

    document = parse_document(b'{"a": 1}', AuthoringFormat.JSON)
    assert document == {"a": 1}
    assert parse_document(b"a: 1\n", AuthoringFormat.YAML) == {"a": 1}


def test_yaml_safe_dump_of_every_kind_round_trips(source_root: Path) -> None:
    """A kind whose YAML authoring did not reload would be silently unreadable."""
    from dynamisbench.workspace.source_authority import AuthoringFormat

    for kind in ALL_KINDS:
        text = yaml.safe_dump(_valid_mapping(kind), sort_keys=True)
        parsed = parse_document(text.encode("utf-8"), AuthoringFormat.YAML)
        assert validate_document(authority_kind(kind), parsed)


def test_a_validation_error_never_leaves_an_error_path() -> None:
    """``validate_document`` wraps the domain's own ValidationError rather than raising it."""
    with pytest.raises(SourceAuthorityError):
        validate_document(authority_kind("quantity"), {"mu": 1})


def test_the_existing_pipeline_still_refuses_what_it_refused() -> None:
    """RES-377 adds a reader; it must not reinterpret what M1 already rejected."""
    kind = authority_kind("quantity")
    with pytest.raises(ValidationError):
        kind.model.model_validate({"quantity_id": "not a valid id"})
