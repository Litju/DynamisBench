"""Systems under test.

A system under test is the thing a benchmark judges: a controller, a model, a
numerical method, an optimizer, or a complete system (Architecture section 4). It is
its own independently identified definition, not a version of a benchmark or of a
realization.

An external SUT defaults to a versioned process and file contract and must be
identifiable: a SUT that cannot be reduced to a resolved commit or a build digest is
not something a later run can be attributed to (ADR-007, Evidence and Provenance).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import model_validator

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    Token,
    keyed_by,
)
from dynamisbench.domain.spec.capability import CapabilityRequirement
from dynamisbench.domain.spec.identifiers import Sha256Hex, SUTId, Version


class SUTKind(StrEnum):
    """What kind of thing is under test.

    The members are the categories the architecture names for a system under test,
    in its own words.
    """

    CONTROLLER = "controller"
    MODEL = "model"
    NUMERICAL_METHOD = "numerical_method"
    OPTIMIZER = "optimizer"
    COMPLETE_SYSTEM = "complete_system"


class SUTInterfaceKind(StrEnum):
    """How DynamisBench invokes a system under test."""

    IN_PROCESS = "in_process"
    SUBPROCESS = "subprocess"
    BRIDGE = "bridge"


class SUTProvenance(DomainModel):
    """Where the system under test came from, and what identifies what will run.

    A repository and a ref are not enough: they are names for something that has to
    be resolved. At least a resolved commit or a build digest must be present.
    """

    repository: Token | None = None
    ref: Token | None = None
    resolved_commit: Token | None = None
    build_digest: Sha256Hex | None = None

    @model_validator(mode="after")
    def _what_will_run_is_identifiable(self) -> Self:
        if self.resolved_commit is None and self.build_digest is None:
            raise ValueError("a system under test must carry a resolved commit or a build digest")
        return self


class SUTInterface(DomainModel):
    """The invocation contract of a system under test.

    A subprocess SUT is launched by a worker from the execution environment, so it
    must declare its command. An in-process or bridged SUT is instantiated by a
    realization instead, so declaring a command there would describe something the
    platform never runs.
    """

    kind: SUTInterfaceKind
    command: tuple[Token, ...] | None = None

    @model_validator(mode="after")
    def _command_matches_the_interface(self) -> Self:
        if self.kind is SUTInterfaceKind.SUBPROCESS:
            if not self.command:
                raise ValueError("a subprocess system under test must declare its command")
        elif self.command is not None:
            raise ValueError(
                f"a {self.kind.value} system under test is launched by a realization "
                "and must not declare a command"
            )
        return self


class SUTDefinition(DomainModel):
    """The definition of a system under test."""

    sut_id: SUTId
    version: Version
    label: ShortText
    description: NonEmptyText
    kind: SUTKind
    interface: SUTInterface
    provenance: SUTProvenance
    required_capabilities: Annotated[tuple[CapabilityRequirement, ...], keyed_by("capability")] = ()
    notes: tuple[ShortText, ...] = ()
