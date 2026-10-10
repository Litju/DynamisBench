"""JSON-only loader for the ``dbench`` inspection and compilation primitives.

The set of kinds this module can load is the domain's, not this module's: it reads
:data:`dynamisbench.domain.spec.AUTHORITY_KINDS`, which names one existing validated
Pydantic model per kind and never an import path. That direction matters. The kind
vocabulary is scientific — what kinds of definition exist is a domain fact — so the
command line consumes it rather than owning it, and the workspace source reader and
the application API read the same table instead of each keeping their own.

Nothing here imports the domain at module scope in a way ``dbench --version`` pays
for: ``cli.py`` imports this module only after argument parsing has decided a
command that needs it. JSON remains the only authoring surface *here*; YAML and
workspace discovery are the workspace source layer's business.

Every failure a caller can trigger — malformed JSON, a non-object document, a
validation error, an unknown kind — is reported as a bounded :class:`CliInputError`,
never as a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dynamisbench.domain.spec import AUTHORITY_KINDS, AuthorityKind
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


type SpecKind = AuthorityKind
"""One kind's validation surface: its model and where its nominal identity lives.

An alias rather than a second class. The command line used to define this
structurally identical record itself, which meant the workspace source reader and
the application API would each have needed to import ``cli_support`` to learn which
model a kind validates to. There is one record now, owned by the domain.
"""

SPEC_KINDS = AUTHORITY_KINDS
"""The domain's kind vocabulary, read-only.

Re-exported under its previous name because it is the command line's kind table and
has always been named that; it is the domain's table, not a copy of it.
"""


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
    except UnicodeDecodeError as exc:
        raise CliInputError(f"{path.name}: invalid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CliInputError(
            f"{path.name}: malformed JSON ({exc.msg} at line {exc.lineno})"
        ) from exc
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
    """Parse one JSON file and validate it as the named kind.

    The domain's registry refuses the name, and the refusal is translated here into
    the command line's own bounded error so that a wrong ``--kind`` is reported the
    way every other wrong argument is: one line on stderr, nonzero exit, no
    traceback.
    """
    try:
        spec = AUTHORITY_KINDS[kind]
    except KeyError:
        supported = ", ".join(sorted(AUTHORITY_KINDS))
        raise CliInputError(f"unknown kind {kind!r}; supported kinds: {supported}") from None
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
