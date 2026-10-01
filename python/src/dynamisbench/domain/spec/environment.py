"""Execution environment identity and its declared requirements.

ADR-009 makes the execution environment scientific evidence and ADR-018 keeps it
separate from the application runtime, so the exact environment needed to
reproduce a run is an independently identified definition rather than an
observation collected at run time. Run-time provenance capture arrives with the
evidence modules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from dynamisbench.domain.spec.base import DomainModel, NonEmptyText, ShortText, keyed_by
from dynamisbench.domain.spec.identifiers import (
    EnvironmentId,
    Name,
    Version,
    VersionSpecifier,
)


class ComponentKind(StrEnum):
    """The kind of environment component a requirement constrains.

    ``NUMERICAL_SETTING`` exists because thread counts, solver-related switches,
    and similar settings are reproducibility-relevant configuration rather than
    installed software.
    """

    RUNTIME = "runtime"
    ENGINE = "engine"
    LIBRARY = "library"
    TOOLCHAIN = "toolchain"
    PLATFORM = "platform"
    NUMERICAL_SETTING = "numerical_setting"


class EnvironmentRequirement(DomainModel):
    """One declared constraint on a single component of an environment.

    One requirement per component: a second constraint on the same component
    cannot be resolved into a single intent, so it is rejected rather than merged.
    """

    component: Name
    kind: ComponentKind
    specifier: VersionSpecifier
    purpose: ShortText | None = None


class EnvironmentDefinition(DomainModel):
    """The exact scientific execution environment a realization is run in.

    The environment is never a nested version of the application runtime or of a
    realization. It is its own independently identified concept, and the same
    realization executed in a different environment is a different execution
    (ADR-002, ADR-018).
    """

    environment_id: EnvironmentId
    version: Version
    label: ShortText
    description: NonEmptyText
    requirements: Annotated[
        tuple[EnvironmentRequirement, ...], keyed_by("component"), Field(min_length=1)
    ]
    notes: tuple[ShortText, ...] = ()
