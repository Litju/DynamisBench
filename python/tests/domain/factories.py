"""Valid-object builders shared by the DB-1.2 domain qualification.

The corpus under ``fixtures/domain`` is the authority-facing view: JSON documents
that must validate or must fail closed. These builders produce the valid Python
objects the corpus is compared against, so a fixture and its builder cannot drift
apart in field coverage without the corpus failing.

YAML is only an authoring representation (RES-228). The validated domain object is
the semantic representation these builders construct.
"""

from __future__ import annotations

from typing import Any

from dynamisbench.domain.spec.capability import (
    Capability,
    CapabilityDeclaration,
    CapabilityRequirement,
    EngineBinding,
)
from dynamisbench.domain.spec.environment import (
    ComponentKind,
    EnvironmentDefinition,
    EnvironmentRequirement,
)
from dynamisbench.domain.spec.identifiers import Comparator, VersionClause, VersionSpecifier

EXACT = Comparator.EXACT
AT_LEAST = Comparator.GREATER_THAN_OR_EQUAL


def specifier(*clauses: tuple[Comparator, str]) -> VersionSpecifier:
    """Build a conjunctive version specifier from comparator/version pairs."""
    return VersionSpecifier(
        clauses=tuple(
            VersionClause(comparator=comparator, version=version) for comparator, version in clauses
        )
    )


def capability_requirement(
    capability: Capability, *, essential: bool = True
) -> CapabilityRequirement:
    return CapabilityRequirement(
        capability=capability,
        essential=essential,
        rationale=f"{capability.value} is required by this definition",
    )


def capability_declaration(capability: Capability) -> CapabilityDeclaration:
    return CapabilityDeclaration(
        capability=capability,
        summary=f"realization provides {capability.value}",
    )


def engine_binding(engine: str = "mujoco", version: str = "3.3.0") -> EngineBinding:
    return EngineBinding(engine=engine, specifier=specifier((EXACT, version)))


def environment_requirement(
    component: str,
    kind: ComponentKind,
    version: str,
) -> EnvironmentRequirement:
    return EnvironmentRequirement(
        component=component,
        kind=kind,
        specifier=specifier((AT_LEAST, version)),
    )


def environment_definition(**overrides: Any) -> EnvironmentDefinition:
    """A minimal valid execution environment."""
    values: dict[str, Any] = {
        "environment_id": "env.mujoco.x86-64",
        "version": "1.0.0",
        "label": "MuJoCo 3.3.0 on CPython 3.12",
        "description": "Exact scientific execution environment for the MuJoCo realization.",
        "requirements": (
            environment_requirement("mujoco", ComponentKind.ENGINE, "3.3.0"),
            environment_requirement("python", ComponentKind.RUNTIME, "3.12"),
            environment_requirement("windows", ComponentKind.PLATFORM, "11"),
        ),
    }
    values.update(overrides)
    return EnvironmentDefinition(**values)
