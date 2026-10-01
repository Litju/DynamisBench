"""Shared primitives for validated domain definitions.

Only primitives that enforce an existing authority requirement belong here:
immutability and fail-closed construction of scientific authority, non-empty
meaningful text, and a canonical collection order that RES-229 needs so that two
equal definitions serialise identically for RFC-8785/SHA-256 identity (ADR-006).

Nothing in this module is scientific. Subjective judgement is never encoded as a
validation rule.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

_MAX_TEXT = 4096
_MAX_SHORT = 256


class DomainModel(BaseModel):
    """Base class for every validated DynamisBench definition.

    ``frozen`` keeps a validated definition immutable, so scientific meaning cannot
    change after validation. ``extra="forbid`` turns an unrecognised field into a
    validation failure instead of silently discarding authored content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must contain non-whitespace content")
    return value


NonEmptyText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=_MAX_TEXT),
    AfterValidator(_reject_blank),
]
"""Free scientific text that must carry actual content."""

ShortText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=_MAX_SHORT),
    AfterValidator(_reject_blank),
]
"""A short human label or summary that must carry actual content."""

Token = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s]+$")]
"""A single whitespace-free token, for example an opaque implementation label."""


def _reject_unexpected_text(value: str) -> str:
    if any(character.isprintable() is False for character in value):
        raise ValueError("must not contain control characters")
    return value


PrintableToken = Annotated[Token, AfterValidator(_reject_unexpected_text)]
"""A token that additionally carries no control characters."""


def keyed_by(attribute: str) -> AfterValidator:
    """Collection metadata for a set of definitions keyed by one of their members.

    A duplicate key is rejected because it makes the meaning of the collection
    ambiguous. The remaining entries are stored in canonical key order so that two
    equal definitions serialise identically regardless of authoring order.
    """

    def validate(values: tuple[Any, ...]) -> tuple[Any, ...]:
        seen: dict[str, Any] = {}
        for value in values:
            key = str(getattr(value, attribute))
            if key in seen:
                raise ValueError(f"duplicate {attribute} {key!r}")
            seen[key] = value
        return tuple(seen[key] for key in sorted(seen))

    return AfterValidator(validate)


def unique_items() -> AfterValidator:
    """Collection metadata for a set of plain values.

    Duplicates are rejected, and the canonical ascending order is imposed so that
    two equal definitions serialise identically.
    """

    def validate(values: tuple[Any, ...]) -> tuple[Any, ...]:
        seen: set[Any] = set()
        for value in values:
            if value in seen:
                raise ValueError(f"duplicate entry {value!r}")
            seen.add(value)
        return tuple(sorted(seen))

    return AfterValidator(validate)
