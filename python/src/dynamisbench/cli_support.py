"""JSON-only loader for the ``dbench`` inspection and compilation primitives.

The registry below is the complete set of spec kinds the command line knows how to
load. It is explicit by design: a kind names one existing validated Pydantic model
and never an import path, so the CLI can never be steered into importing an
arbitrary class, a registry service, or a simulator binding. JSON is the only
authoring surface here; YAML and workspace discovery are M2 work and stay out of
this module.

Every failure a caller can trigger — malformed JSON, a non-object document, a
validation error, an unknown kind — is reported as a bounded :class:`CliInputError`,
never as a traceback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dynamisbench.domain.spec import (
    BenchmarkRelease,
    EnvironmentDefinition,
    MetricDefinition,
    QuantityDefinition,
    RealizationDefinition,
    ReferenceDefinition,
    ScenarioDefinition,
    SUTDefinition,
    StudyDefinition,
    UncertaintyFactorDefinition,
)
from dynamisbench.domain.spec.base import DomainModel

__all__ = [
    "CliInputError",
    "SPEC_KINDS",
    "SpecKind",
    "describe_identity",
    "load_json_model",
    "load_spec",
    "spec_summary",
]


class CliInputError(Exception):
    """A user-facing failure: bounded message, nonzero exit, no traceback."""


@dataclass(frozen=True)
class SpecKind:
    """One kind's validation surface: its model and where its nominal identity lives."""

    name: str
    model: type[DomainModel]
    identifier_field: str
    version_field: str | None


SPEC_KINDS: dict[str, SpecKind] = {
    "benchmark": SpecKind("benchmark", BenchmarkRelease, "benchmark_id", "version"),
    "realization": SpecKind("realization", RealizationDefinition, "realization_id", "version"),
    "scenario": SpecKind("scenario", ScenarioDefinition, "scenario_id", "version"),
    "quantity": SpecKind("quantity", QuantityDefinition, "quantity_id", "version"),
    "metric": SpecKind("metric", MetricDefinition, "metric_id", "version"),
    "reference": SpecKind("reference", ReferenceDefinition, "reference_id", "version"),
    "sut": SpecKind("sut", SUTDefinition, "sut_id", "version"),
    "environment": SpecKind("environment", EnvironmentDefinition, "environment_id", "version"),
    "study": SpecKind("study", StudyDefinition, "study_id", "version"),
    "factor": SpecKind("factor", UncertaintyFactorDefinition, "factor_id", None),
}
"""The explicit kind registry. ``factor`` has no version field by design."""


def _bounded_errors(exc: ValidationError, *, limit: int = 3) -> str:
    shown = [
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
        for error in exc.errors()[:limit]
    ]
    remaining = exc.error_count() - len(shown)
    if remaining > 0:
        shown.append(f"... and {remaining} more")
    return "; ".join(shown)


def _read_json_object(path: Path) -> Any:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliInputError(f"cannot read {path.name}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise CliInputError(f"{path.name}: malformed JSON ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(raw, dict):
        raise CliInputError(f"{path.name}: expected a JSON object at the top level")
    return raw


def load_json_model[ModelT: DomainModel](model: type[ModelT], path: Path) -> ModelT:
    """Parse one JSON file and validate it against one explicit model type."""
    raw = _read_json_object(path)
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise CliInputError(
            f"{path.name}: invalid {model.__name__} ({_bounded_errors(exc)})"
        ) from exc


def load_spec(kind: str, path: Path) -> DomainModel:
    """Parse one JSON file and validate it as the named kind."""
    spec = SPEC_KINDS.get(kind)
    if spec is None:
        supported = ", ".join(sorted(SPEC_KINDS))
        raise CliInputError(f"unknown kind {kind!r}; supported kinds: {supported}")
    return load_json_model(spec.model, path)


def spec_summary(kind: str, model: DomainModel) -> dict[str, Any]:
    """The validated summary shared by ``spec validate`` and ``identity inspect``."""
    spec = SPEC_KINDS[kind]
    summary: dict[str, Any] = {
        "kind": kind,
        "identifier": getattr(model, spec.identifier_field),
    }
    if spec.version_field is not None:
        summary["version"] = getattr(model, spec.version_field)
    return summary


def describe_identity(kind: str, model: DomainModel) -> dict[str, Any]:
    """The deterministic identity record for ``identity inspect``."""
    from dynamisbench.identity import semantic_sha256

    # Imported lazily so that ``spec validate`` does not pay for the identity
    # pipeline it does not use, the same way ``dbench --version`` avoids the
    # application stack.
    digest = semantic_sha256(model)
    return {
        **spec_summary(kind, model),
        "algorithm": "sha256",
        "digest": digest.hex,
    }
