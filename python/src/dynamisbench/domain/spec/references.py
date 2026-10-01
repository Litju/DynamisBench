"""Reference case definitions.

A reference case is the frozen comparison point for verification, solution
verification, model validation, controller benchmarking, and complete-system
qualification. The VVUQ authority keeps those five activities distinct and keeps
code verification separate from model validation, so the category is part of the
reference's identity rather than a free-text note. A software-test PASS is never
treated as scientific validation, and this model does not provide a way to say so.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from dynamisbench.domain.spec.base import DomainModel, NonEmptyText, ShortText
from dynamisbench.domain.spec.identifiers import ReferenceId, ScenarioId, Version


class VerificationCategory(StrEnum):
    """Which distinct V&V activity a reference case supports."""

    CODE_VERIFICATION = "code_verification"
    SOLUTION_VERIFICATION = "solution_verification"
    MODEL_VALIDATION = "model_validation"
    CONTROLLER_BENCHMARKING = "controller_benchmarking"
    COMPLETE_SYSTEM_QUALIFICATION = "complete_system_qualification"


class ReferenceOrigin(StrEnum):
    """Where a reference case came from."""

    PUBLISHED = "published"
    EXPERIMENTAL = "experimental"
    SYNTHETIC = "synthetic"
    REANALYSIS = "reanalysis"


class ReferenceDefinition(DomainModel):
    """A reference case for one scenario of the owning benchmark release."""

    reference_id: ReferenceId
    version: Version
    label: ShortText
    description: NonEmptyText
    scenario_id: ScenarioId
    category: VerificationCategory
    origin: ReferenceOrigin
    citation: ShortText | None = None
    license: ShortText | None = None
    notes: tuple[ShortText, ...] = ()

    @model_validator(mode="after")
    def _published_reference_is_citable(self) -> Self:
        if self.origin is ReferenceOrigin.PUBLISHED and self.citation is None:
            raise ValueError(
                f"reference {self.reference_id!r} is published and must carry a citation"
            )
        return self
