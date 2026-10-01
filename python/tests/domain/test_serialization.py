"""Deterministic serialisation semantics required by RES-229 (ADR-006).

RES-229 implements RFC-8785 canonicalisation and SHA-256 over these objects. This
module does not canonicalise and does not hash; it proves the properties that
canonicalisation will depend on:

* a validated definition is immutable, so nothing can change after validation;
* a definition serialises to exactly one JSON body, whatever order it was authored in;
* one meaning has exactly one body, so equal units and equal collections cannot
  produce two different digests;
* a round trip through JSON is lossless;
* two versions that differ only in SemVer build metadata stay two different artifacts.

Number canonical formatting is deliberately not asserted here: JCS specifies the
ECMAScript number-to-string algorithm, and owning it belongs to RES-229.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.identifiers import Version
from dynamisbench.domain.spec.quantities import CanonicalUnit

from .factories import benchmark_release, realization_definition, study_definition, sut_definition
from .test_corpus import VALID_CORPUS, model_for

KEYED_COLLECTIONS = ("quantities", "scenarios", "metrics", "references")

MODELS = (
    benchmark_release,
    realization_definition,
    study_definition,
    sut_definition,
)


@pytest.mark.parametrize("build", MODELS, ids=[build.__name__ for build in MODELS])
def test_a_definition_is_immutable_after_validation(build: Any) -> None:
    definition = build()
    assert isinstance(definition, DomainModel)
    field = next(iter(type(definition).model_fields))
    with pytest.raises(ValueError):
        setattr(definition, field, "mutated")
    assert definition.model_dump_json() == build().model_dump_json()


@pytest.mark.parametrize("build", MODELS, ids=[build.__name__ for build in MODELS])
def test_a_definition_is_hashable_so_it_can_key_a_digest_table(build: Any) -> None:
    definition = build()
    assert hash(definition) == hash(build())
    assert len({definition, build()}) == 1


@pytest.mark.parametrize("build", MODELS, ids=[build.__name__ for build in MODELS])
def test_serialisation_is_repeatable(build: Any) -> None:
    definition = build()
    bodies = {definition.model_dump_json() for _ in range(5)}
    assert len(bodies) == 1
    assert definition.model_dump(mode="json") == definition.model_dump(mode="json")


@pytest.mark.parametrize("build", MODELS, ids=[build.__name__ for build in MODELS])
def test_json_round_trip_is_lossless(build: Any) -> None:
    definition = build()
    body = definition.model_dump_json()
    assert type(definition).model_validate_json(body) == definition
    assert type(definition).model_validate_json(body).model_dump_json() == body


@pytest.mark.parametrize("build", MODELS, ids=[build.__name__ for build in MODELS])
def test_a_python_dump_round_trips_through_json_identically(build: Any) -> None:
    definition = build()
    python_dump = definition.model_dump()
    json_dump = definition.model_dump(mode="json")
    assert json.loads(json.dumps(python_dump)) == json_dump


def test_authoring_order_of_a_keyed_collection_does_not_change_the_body() -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    reordered = {
        key: list(reversed(value)) if key in KEYED_COLLECTIONS else value
        for key, value in payload.items()
    }
    assert reordered["quantities"] != payload["quantities"]
    assert type(release).model_validate(reordered).model_dump_json() == release.model_dump_json()


def test_a_genuinely_ordered_field_still_rejects_a_reversed_order() -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    payload["credibility_hierarchy"] = list(reversed(payload["credibility_hierarchy"]))
    with pytest.raises(ValueError):
        type(release).model_validate(payload)


def test_a_list_from_json_and_a_tuple_from_python_serialise_identically() -> None:
    definition = benchmark_release()
    as_tuple = definition.model_dump(mode="json")
    as_list = json.loads(definition.model_dump_json())
    assert isinstance(as_list["quantities"], list)
    assert type(definition).model_validate(as_list).model_dump(mode="json") == as_tuple


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("m/s", "m*s^-1"),
        ("kg*m^2/s^3", "W"),
        ("1e-3*m", "mm"),
        ("N/Pa", "m^2"),
        ("1.50*kg", "1.5*kg"),
    ],
)
def test_one_unit_has_one_body_however_it_is_authored(first: str, second: str) -> None:
    assert CanonicalUnit(expression=first).model_dump_json() == (
        CanonicalUnit(expression=second).model_dump_json()
    )


def test_build_metadata_keeps_two_versions_apart() -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    plain = type(release).model_validate(payload)
    payload["version"] = "1.0.0+build.5"
    with_metadata = type(release).model_validate(payload)
    assert with_metadata.version != plain.version
    assert with_metadata.model_dump_json() != plain.model_dump_json()


def test_a_version_is_validated_as_semantic_versioning() -> None:
    class _Versioned(DomainModel):
        version: Version

    assert _Versioned(version="1.0.0+build.5").version == "1.0.0+build.5"
    with pytest.raises(ValueError):
        _Versioned(version="1.0")


def test_no_serialised_number_is_non_finite() -> None:
    for build in MODELS:
        body = build().model_dump_json()
        for token in ("NaN", "Infinity", "-Infinity"):
            assert token not in body


def test_every_valid_fixture_round_trips_to_the_same_bytes() -> None:
    for filename, document in VALID_CORPUS:
        model = model_for(filename)
        definition = model.model_validate(document)
        body = definition.model_dump_json()
        assert model.model_validate_json(body).model_dump_json() == body


def test_a_definition_never_serialises_a_nominal_identity_as_a_subclass() -> None:
    body = benchmark_release().model_dump_json()
    for identifier in (
        json.loads(body)["quantities"][0]["quantity_id"],
        json.loads(body)["scenarios"][0]["scenario_id"],
    ):
        assert isinstance(identifier, str)
        assert type(identifier) is str
