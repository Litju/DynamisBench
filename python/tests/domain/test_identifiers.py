"""Identifier, version, and reference invariants (ADR-002, ADR-006).

Type violations are exercised through ``model_validate`` because that is the path
authored YAML and JSON take. Pyright already rejects them statically, so the
runtime assertion here proves the *validation* layer refuses them too rather than
reinterpreting a foreign identity.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError, create_model

from dynamisbench.domain.spec.base import DomainModel, Token
from dynamisbench.domain.spec.identifiers import (
    IDENTIFIER_MAX_LENGTH,
    IDENTIFIER_PATTERN,
    BenchmarkId,
    BenchmarkRef,
    Comparator,
    EnvironmentId,
    FactorId,
    Identifier,
    MetricId,
    QuantityId,
    RealizationId,
    ReferenceId,
    ScenarioId,
    Sha256Hex,
    StudyId,
    SUTId,
    Version,
    VersionedRef,
    VersionSpecifier,
    WorkspaceRelativePath,
)

IDENTIFIER_BODY = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"

NOMINAL_IDENTITY_TYPES = (
    BenchmarkId,
    RealizationId,
    SUTId,
    StudyId,
    EnvironmentId,
    QuantityId,
    ScenarioId,
    MetricId,
    ReferenceId,
    FactorId,
)

ADR002_IDENTITY_TYPES = (BenchmarkId, RealizationId, SUTId, StudyId, EnvironmentId)


class _Envelope(DomainModel):
    value: Identifier


class _BenchmarkEnvelope(DomainModel):
    value: BenchmarkId


class _Versioned(DomainModel):
    version: Version


class _Token(DomainModel):
    value: Token


class _Digest(DomainModel):
    sha256: Sha256Hex


class _Path(DomainModel):
    path: WorkspaceRelativePath


def test_every_named_identity_is_its_own_type() -> None:
    assert len(set(NOMINAL_IDENTITY_TYPES)) == len(NOMINAL_IDENTITY_TYPES)
    for identity_type in NOMINAL_IDENTITY_TYPES:
        assert issubclass(identity_type, Identifier)
        assert identity_type is not Identifier


def test_the_five_adr_002_concepts_have_distinct_identity_types() -> None:
    assert len(set(ADR002_IDENTITY_TYPES)) == 5


@pytest.mark.parametrize("identity_type", NOMINAL_IDENTITY_TYPES)
def test_identifier_round_trips_as_its_nominal_type(identity_type: type[Identifier]) -> None:
    instance = identity_type("db.lcmj20")
    assert instance == "db.lcmj20"
    assert isinstance(instance, identity_type)
    assert type(instance) is identity_type


def _envelope_for(identity_type: type[Identifier]) -> type[BaseModel]:
    return create_model("_Envelope", value=(identity_type, ...))


@pytest.mark.parametrize("target", ADR002_IDENTITY_TYPES)
@pytest.mark.parametrize("supplied", ADR002_IDENTITY_TYPES)
def test_identities_from_different_concepts_never_interchange(
    target: type[Identifier], supplied: type[Identifier]
) -> None:
    envelope = _envelope_for(target)
    if target is supplied:
        accepted = envelope.model_validate({"value": supplied("db.lcmj20")})
        assert accepted.model_dump() == {"value": "db.lcmj20"}
        return
    with pytest.raises(ValidationError) as excinfo:
        envelope.model_validate({"value": supplied("db.lcmj20")})
    assert f"expected {target.__name__}, got {supplied.__name__}" in str(excinfo.value)


def test_a_plain_string_is_accepted_as_the_expected_identity_type() -> None:
    assert type(_BenchmarkEnvelope.model_validate({"value": "db.lcmj20"}).value) is BenchmarkId


def test_identifier_serialises_as_a_plain_json_string() -> None:
    payload = _BenchmarkEnvelope.model_validate({"value": "db.lcmj20"}).model_dump_json()
    assert payload == '{"value":"db.lcmj20"}'
    assert _BenchmarkEnvelope.model_validate_json(payload).value == "db.lcmj20"


def test_the_identifier_convention_is_a_single_unambiguous_word() -> None:
    assert IDENTIFIER_PATTERN == f"^{IDENTIFIER_BODY}$"


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "Bench",
        "DB.LCMJ20",
        "db..lcmj20",
        "db--lcmj20",
        "db.-lcmj20",
        "db.lcmj20-",
        "-db",
        ".db",
        "_db",
        "db lcmj20",
        "db/lcmj20",
        "db\\lcmj20",
        "C:db",
        "db\n",
        "db\t",
        "db$",
        "a" * (IDENTIFIER_MAX_LENGTH + 1),
    ],
)
def test_malformed_identifiers_fail_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        _Envelope.model_validate({"value": value})


@pytest.mark.parametrize(
    "value",
    [
        "a",
        "1",
        "db.lcmj20",
        "db-lcmj20",
        "db_lcmj20",
        "env.mujoco.3-2-3",
        "x" * IDENTIFIER_MAX_LENGTH,
    ],
)
def test_well_formed_identifiers_are_accepted(value: str) -> None:
    assert _Envelope.model_validate({"value": value}).value == value


@pytest.mark.parametrize(
    "value",
    [
        "0.0.0",
        "1.2.3",
        "10.20.30",
        "1.0.0-alpha.1",
        "1.0.0+build.5",
        "1.0.0-rc.1+exp.sha.5114f85",
    ],
)
def test_semantic_versions_are_accepted(value: str) -> None:
    assert _Versioned.model_validate({"version": value}).version == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "1",
        "1.0",
        "1.0.0.0",
        "01.0.0",
        "1.0.0-",
        "v1.0.0",
        "1.0.0+",
        "1.0.0 ",
        "1.0.0\n",
        "latest",
    ],
)
def test_malformed_versions_fail_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        _Versioned.model_validate({"version": value})


@pytest.mark.parametrize("value", ["3.12", "1.0.0+cu124", "windows", "x86_64"])
def test_tokens_may_be_non_numeric(value: str) -> None:
    assert _Token.model_validate({"value": value}).value == value


@pytest.mark.parametrize("value", ["", " ", "a b", "a\tb", "a\nb"])
def test_malformed_tokens_fail_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        _Token.model_validate({"value": value})


def test_sha256_digests_are_validated_but_not_computed() -> None:
    digest = "0" * 64
    assert _Digest.model_validate({"sha256": digest}).sha256 == digest
    for malformed in ("", "0" * 63, "0" * 65, "F" * 64, "z" * 64, " " + "0" * 63):
        with pytest.raises(ValidationError):
            _Digest.model_validate({"sha256": malformed})


def test_version_specifier_rejects_a_repeated_comparator() -> None:
    with pytest.raises(ValidationError) as excinfo:
        VersionSpecifier.model_validate(
            {
                "clauses": [
                    {"comparator": "greater_than_or_equal", "version": "3.12"},
                    {"comparator": "greater_than_or_equal", "version": "3.10"},
                ]
            }
        )
    assert "duplicate comparator" in str(excinfo.value)


def test_version_specifier_requires_at_least_one_clause() -> None:
    with pytest.raises(ValidationError):
        VersionSpecifier.model_validate({"clauses": []})


def test_version_specifier_stores_clauses_in_canonical_order() -> None:
    specifier = VersionSpecifier.model_validate(
        {
            "clauses": [
                {"comparator": "exact", "version": "3.3.0"},
                {"comparator": "greater_than_or_equal", "version": "3.12"},
            ]
        }
    )
    assert [clause.comparator for clause in specifier.clauses] == [
        Comparator.EXACT,
        Comparator.GREATER_THAN_OR_EQUAL,
    ]


def test_versioned_ref_parametrisation_keeps_identities_distinct() -> None:
    assert BenchmarkRef is not VersionedRef[RealizationId]
    benchmark_ref = BenchmarkRef.model_validate({"identifier": "db.lcmj20", "version": "1.0.0"})
    assert isinstance(benchmark_ref.identifier, BenchmarkId)
    with pytest.raises(ValidationError):
        VersionedRef[SUTId].model_validate(
            {"identifier": benchmark_ref.identifier, "version": "1.0.0"}
        )


def test_a_versioned_ref_requires_both_an_identity_and_a_version() -> None:
    with pytest.raises(ValidationError):
        BenchmarkRef.model_validate({"identifier": "db.lcmj20"})
    with pytest.raises(ValidationError):
        BenchmarkRef.model_validate({"version": "1.0.0"})


@pytest.mark.parametrize(
    "value",
    [
        "benchmarks/db.lcmj20/1.0.0/manifest.json",
        "a",
        "models/leg.xml",
        "dir/sub-dir/file.yaml",
    ],
)
def test_workspace_relative_paths_are_accepted(value: str) -> None:
    assert _Path.model_validate({"path": value}).path == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/abs/path",
        "C:/abs/path",
        "c:\\abs\\path",
        "dir\\file",
        "dir//file",
        "dir/./file",
        "dir/../file",
        "..",
        "../file",
        "dir/",
        "dir /file",
        "dir\n/file",
    ],
)
def test_non_relative_or_traversing_paths_fail_closed(value: str) -> None:
    with pytest.raises(ValidationError):
        _Path.model_validate({"path": value})


identifier_strategy = st.builds(
    lambda head, tail: head + "".join(pair for _, pair in tail),
    st.from_regex(r"[a-z0-9]", fullmatch=True),
    st.lists(
        st.tuples(
            st.from_regex(r"[._-]", fullmatch=True), st.from_regex(r"[a-z0-9]", fullmatch=True)
        ),
        max_size=8,
    ),
)


@given(identifier=identifier_strategy)
def test_any_identifier_matching_the_convention_validates(identifier: str) -> None:
    assert _Envelope.model_validate({"value": identifier}).value == identifier


@given(identifier=identifier_strategy)
def test_a_well_formed_identifier_binds_to_its_declared_nominal_type(identifier: str) -> None:
    for identity_type in NOMINAL_IDENTITY_TYPES:
        assert type(identity_type(identifier)) is identity_type
