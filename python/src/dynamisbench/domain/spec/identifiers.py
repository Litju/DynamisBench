"""Identifier, version, and reference vocabulary.

ADR-002 makes benchmark releases, realizations, systems under test, studies, and
execution environments independently identified and versioned concepts. Each of
those identities is a distinct nominal type here: a realization identifier cannot
be supplied where a benchmark identifier is required, at type-check time and at
validation time, so the five concepts can never collapse into one another.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final

from pydantic import AfterValidator, Field, StringConstraints
from pydantic_core import core_schema

from dynamisbench.domain.spec.base import DomainModel, Token, keyed_by

IDENTIFIER_PATTERN: Final = r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$"
"""Dot, dash, or underscore separated alphanumeric segments.

The convention exists so that every identifier is a single unambiguous word: no
empty segment, no leading or trailing separator, no whitespace, no case ambiguity,
and safe to use verbatim as a Git path segment and as a stable artifact key.
"""

IDENTIFIER_MAX_LENGTH: Final = 96
VERSION_MAX_LENGTH: Final = 64
PATH_MAX_LENGTH: Final = 256

SEMVER_PATTERN: Final = (
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$"
)
"""Semantic Versioning 2.0.0.

Build metadata is retained rather than discarded, because two versions that differ
only in build metadata are different artifacts and must not collapse into one
identity (ADR-006). Nothing in DB-1.2 depends on Semantic Versioning precedence.
"""


class Identifier(str):
    """A validated object identifier.

    Validation happens on the parsed string and the value is then rebuilt as the
    requesting nominal type. A value that is already a *different* identifier type
    is rejected rather than silently reinterpreted, so one identity can never be
    substituted for another.
    """

    __slots__ = ()

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: object, handler: object
    ) -> core_schema.CoreSchema:
        expected = cls.__name__

        def reject_foreign(value: object) -> object:
            if isinstance(value, str) and type(value) is not str and not isinstance(value, cls):
                raise ValueError(f"expected {expected}, got {type(value).__name__}")
            return value

        def build(value: str) -> Identifier:
            return cls(value)

        def serialize(value: Identifier) -> str:
            return str(value)

        return core_schema.no_info_after_validator_function(
            build,
            core_schema.no_info_before_validator_function(
                reject_foreign,
                core_schema.str_schema(
                    pattern=IDENTIFIER_PATTERN, max_length=IDENTIFIER_MAX_LENGTH
                ),
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize, return_schema=core_schema.str_schema()
            ),
        )


class BenchmarkId(Identifier):
    """Identity of a benchmark family and release line (ADR-002)."""


class RealizationId(Identifier):
    """Identity of an executable implementation of a benchmark (ADR-002)."""


class SUTId(Identifier):
    """Identity of an object under test (ADR-002)."""


class StudyId(Identifier):
    """Identity of a research study (ADR-002)."""


class EnvironmentId(Identifier):
    """Identity of an exact scientific execution environment (ADR-002)."""


class QuantityId(Identifier):
    """Identity of a canonical physical quantity."""


class ScenarioId(Identifier):
    """Identity of a scenario."""


class MetricId(Identifier):
    """Identity of a metric."""


class ReferenceId(Identifier):
    """Identity of a reference case."""


class FactorId(Identifier):
    """Identity of an uncertainty factor."""


Version = Annotated[str, StringConstraints(pattern=SEMVER_PATTERN, max_length=VERSION_MAX_LENGTH)]
"""A Semantic Versioning 2.0.0 version of exactly one independent definition."""

Name = Annotated[
    str, StringConstraints(pattern=IDENTIFIER_PATTERN, max_length=IDENTIFIER_MAX_LENGTH)
]
"""An open-vocabulary name that follows the identifier convention.

Used for names whose *concept* carries no identity that must stay distinct — engine
names, environment components, frame names, anatomical segments. A concept whose
identity must not be interchangeable with another concept uses a nominal
:class:`Identifier` subclass instead.
"""

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A lowercase hex SHA-256 content digest.

This is the recorded reference form only; computing digests is RES-229/ADR-006 work.
"""


class Comparator(StrEnum):
    """Comparison semantics of a single version constraint clause."""

    EXACT = "exact"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    COMPATIBLE = "compatible"


class VersionClause(DomainModel):
    """One comparison of a component version against a required version."""

    comparator: Comparator
    version: Token


class VersionSpecifier(DomainModel):
    """A conjunction of version constraints on one component.

    Repeating a comparator is rejected: ``>=3,>=4`` states no single satisfiable
    intent, so it is malformed authority rather than a stricter constraint.
    """

    clauses: Annotated[tuple[VersionClause, ...], keyed_by("comparator"), Field(min_length=1)]


class VersionedRef[IdentifierT: Identifier](DomainModel):
    """A pointer from one independent domain object to another.

    The identifier type parameter keeps benchmark, realization, SUT, study, and
    environment references distinct both in the type system and at validation
    time, so a reference can never be silently reinterpreted as another concept
    (ADR-002).
    """

    identifier: IdentifierT
    version: Version


BenchmarkRef = VersionedRef[BenchmarkId]
RealizationRef = VersionedRef[RealizationId]
SUTRef = VersionedRef[SUTId]
StudyRef = VersionedRef[StudyId]
EnvironmentRef = VersionedRef[EnvironmentId]
QuantityRef = VersionedRef[QuantityId]
ScenarioRef = VersionedRef[ScenarioId]
MetricRef = VersionedRef[MetricId]
ReferenceRef = VersionedRef[ReferenceId]


def _validate_relative_path(value: str) -> str:
    if "\\" in value:
        raise ValueError("must use '/' separators, not '\\'")
    if value.startswith("/"):
        raise ValueError("must be relative, not absolute")
    if len(value) > 1 and value[1] == ":":
        raise ValueError("must not carry a drive letter")
    if any(character.isspace() or not character.isprintable() for character in value):
        raise ValueError("must not contain whitespace or control characters")
    for segment in value.split("/"):
        if segment in {"", ".", ".."}:
            raise ValueError(f"must not contain empty, '.' or '..' segments: {value!r}")
    return value


WorkspaceRelativePath = Annotated[
    str,
    StringConstraints(min_length=1, max_length=PATH_MAX_LENGTH),
    AfterValidator(_validate_relative_path),
]
"""A workspace-relative authority path.

Absolute paths, drive letters, backslashes, whitespace, and empty/``.``/``..``
segments are rejected so authority stays inside its repository and stays portable
between Windows and Linux.
"""
