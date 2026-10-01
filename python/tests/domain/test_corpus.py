"""The DB-1.2 valid/invalid fixture corpus.

Every domain concept on the public surface has at least one committed valid document
and at least one committed invalid document, and the whole corpus executes on every
run. A new concept or a new invariant rule is not qualified until the corpus covers
it.

A fixture file is named ``<model_in_snake_case>.<case>.json`` and resolves to its
model through the package's public surface, so a fixture can never name a model that
does not exist. Each invalid fixture is paired, in ``invalid/expected.json``, with a
fragment of the failure it must produce: a rule that silently stopped firing fails
this gate instead of passing on a technicality.

YAML is only an authoring representation (RES-228). These JSON documents are authored
fixtures, not the in-memory authority. Each is validated into a domain object, and
the domain object is what the determinism gates serialise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import dynamisbench.domain.spec as spec

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "domain"

REQUIRED_CONCEPTS = (
    "BenchmarkRelease",
    "RealizationDefinition",
    "ScenarioDefinition",
    "QuantityDefinition",
    "MetricDefinition",
    "ReferenceDefinition",
    "SUTDefinition",
    "EnvironmentDefinition",
    "EnvironmentRequirement",
    "StudyDefinition",
    "UncertaintyFactorDefinition",
    "CapabilityDeclaration",
    "CapabilityRequirement",
    "EngineBinding",
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake_case(class_name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", class_name).lower()


def exported_models() -> dict[str, type[BaseModel]]:
    return {
        name: value
        for name, value in vars(spec).items()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__.startswith("dynamisbench.domain.spec")
    }


MODELS_BY_SNAKE = {snake_case(name): name for name in exported_models()}


def model_for(filename: str) -> type[BaseModel]:
    prefix = filename.split(".")[0]
    class_name = MODELS_BY_SNAKE.get(prefix)
    assert class_name is not None, (
        f"{prefix!r} does not resolve to a definition on the public surface"
    )
    return exported_models()[class_name]


def load(directory: str) -> list[tuple[str, dict[str, Any]]]:
    files = sorted(path for path in (CORPUS / directory).glob("*.json") if path.stem != "expected")
    assert files, f"the {directory} corpus is empty"
    return [(path.name, json.loads(path.read_text(encoding="utf-8"))) for path in files]


EXPECTED_FAILURES: dict[str, str] = json.loads(
    (CORPUS / "invalid" / "expected.json").read_text(encoding="utf-8")
)

VALID_CORPUS = load("valid")
INVALID_CORPUS = load("invalid")


def test_every_invalid_fixture_declares_the_failure_it_must_produce() -> None:
    assert {filename for filename, _ in INVALID_CORPUS} == set(EXPECTED_FAILURES)


@pytest.mark.parametrize(
    ("filename", "document"), VALID_CORPUS, ids=[name for name, _ in VALID_CORPUS]
)
def test_every_valid_fixture_validates_and_serialises_unchanged(
    filename: str, document: dict[str, Any]
) -> None:
    model = model_for(filename)
    validated = model.model_validate(document)
    assert validated.model_dump(mode="json") == document


@pytest.mark.parametrize(
    ("filename", "document"), INVALID_CORPUS, ids=[name for name, _ in INVALID_CORPUS]
)
def test_every_invalid_fixture_fails_closed_for_the_stated_reason(
    filename: str, document: dict[str, Any]
) -> None:
    model = model_for(filename)
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(document)
    assert EXPECTED_FAILURES[filename] in str(excinfo.value)


def _covered(directory: str) -> set[str]:
    return {filename.split(".")[0] for filename, _ in load(directory)}


@pytest.mark.parametrize("concept", REQUIRED_CONCEPTS)
def test_every_required_concept_has_valid_and_invalid_fixtures(concept: str) -> None:
    prefix = snake_case(concept)
    assert prefix in MODELS_BY_SNAKE, f"{concept} is not on the public surface"
    assert prefix in _covered("valid"), f"{concept} has no valid fixture"
    assert prefix in _covered("invalid"), f"{concept} has no invalid fixture"


def test_the_corpus_is_not_trivially_small() -> None:
    assert len(VALID_CORPUS) >= len(REQUIRED_CONCEPTS)
    assert len(INVALID_CORPUS) >= 2 * len(REQUIRED_CONCEPTS)
