"""Authoring fixtures for the source-authority qualification suites.

Every document the RES-377 suites read is built from the M1 domain factories, so a fixture
cannot drift from the domain model it is supposed to be an authoring of: if a factory stops
producing a valid ``BenchmarkRelease``, the suite that writes one fails here rather than
in a test that appears to be about discovery.

Two properties are deliberately *not* assumed and are proved by construction instead.
Writing the model with ``model_dump(mode="json")`` means every valid fixture round-trips
through exactly the serialisation the inspection read model publishes; serialising that
same mapping as YAML means the JSON and YAML authorings of one definition are two spellings
of one meaning, which is the relocation- and format-invariance claim the rest of the suite
depends on.

The authoring layouts used here are the declared ones: ``benchmarks/benchmark/``,
``benchmarks/scenario/``, ``studies/factor/``, and so on. Nothing about a document's model
type is inferred from its file name, so ``foo.yaml`` is whatever its directory says it is.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.workspace.authority import SourceCategory
from dynamisbench.workspace.source_authority import CATEGORY_KINDS

from ..domain import factories

KindFactory = Callable[[], DomainModel]

SCENARIO = "scenario"
BENCHMARK = "benchmark"
REALIZATION = "realization"
SUT = "sut"
ENVIRONMENT = "environment"
STUDY = "study"
FACTOR = "factor"
REFERENCE = "reference"
QUANTITY = "quantity"
METRIC = "metric"

MODEL_FACTORIES: dict[str, KindFactory] = {
    SCENARIO: factories.scenario_definition,
    BENCHMARK: factories.benchmark_release,
    REALIZATION: factories.realization_definition,
    SUT: factories.sut_definition,
    ENVIRONMENT: factories.environment_definition,
    STUDY: factories.study_definition,
    FACTOR: factories.uncertainty_factor,
    REFERENCE: factories.reference_definition,
    QUANTITY: factories.quantity_definition,
    METRIC: factories.metric_definition,
}
"""One factory per declared kind, keyed by the kind's own name."""

KIND_CATEGORIES: dict[str, SourceCategory] = {
    kind: category for category, kinds in CATEGORY_KINDS.items() for kind in kinds
}
"""The category each declared kind is filed under."""


def authoring(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON-mode mapping of one model, as the read model would publish it."""
    return json.loads(json.dumps(mapping, sort_keys=True))


def write_document(
    source_root: Path,
    kind: str,
    name: str,
    *,
    suffix: str | None = None,
    model: DomainModel | None = None,
    content: Any | None = None,
) -> Path:
    """Write one authoring document under its declared category and kind directory.

    ``name`` may contain ``/`` segments, which create the intermediate directories: the
    declared layout allows a definition anywhere beneath a kind directory, and a suite
    that only wrote at the top would not prove a nested one is found.
    """
    category = KIND_CATEGORIES[kind]
    directory = source_root / category.value / kind
    directory.mkdir(parents=True, exist_ok=True)
    (directory.joinpath(*name.split("/")[:-1])).mkdir(parents=True, exist_ok=True)
    path = directory.joinpath(*name.split("/"))

    if content is None:
        document = authoring(
            (model if model is not None else MODEL_FACTORIES[kind]()).model_dump(mode="json")
        )
    else:
        document = content

    if suffix is None:
        suffix = path.suffix if path.suffix in {".json", ".yaml", ".yml"} else ".json"
    if suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(document, sort_keys=True, allow_unicode=True), encoding="utf-8"
        )
    else:
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def source_root_for(workspace_root: Path, name: str = "source") -> Path:
    """The source root of a workspace that has already been initialised."""
    return workspace_root / name


__all__ = [
    "KIND_CATEGORIES",
    "MODEL_FACTORIES",
    "authoring",
    "source_root_for",
    "write_document",
]
