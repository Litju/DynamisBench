"""Validated scientific and execution specifications.

See :mod:`dynamisbench.domain` for the owned definitions and their separation
requirements (ADR-002). DB-1.2 (RES-228) introduces the Pydantic v2 domain model:
the validated semantic representation. YAML and JSON are authoring
representations only, and no engine-native type is reachable from this package
(ADR-001).
"""

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    Token,
    keyed_by,
    unique_items,
)
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
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    BenchmarkRef,
    Comparator,
    EnvironmentId,
    EnvironmentRef,
    FactorId,
    Identifier,
    MetricId,
    MetricRef,
    Name,
    QuantityId,
    QuantityRef,
    RealizationId,
    RealizationRef,
    ReferenceId,
    ReferenceRef,
    ScenarioId,
    ScenarioRef,
    Sha256Hex,
    StudyId,
    StudyRef,
    SUTId,
    SUTRef,
    Version,
    VersionClause,
    VersionedRef,
    VersionSpecifier,
    WorkspaceRelativePath,
)

__all__ = [
    "BenchmarkId",
    "BenchmarkRef",
    "Capability",
    "CapabilityDeclaration",
    "CapabilityRequirement",
    "Comparator",
    "ComponentKind",
    "DomainModel",
    "EngineBinding",
    "EnvironmentDefinition",
    "EnvironmentId",
    "EnvironmentRef",
    "EnvironmentRequirement",
    "FactorId",
    "Identifier",
    "MetricId",
    "MetricRef",
    "Name",
    "NonEmptyText",
    "QuantityId",
    "QuantityRef",
    "RealizationId",
    "RealizationRef",
    "ReferenceId",
    "ReferenceRef",
    "ScenarioId",
    "ScenarioRef",
    "Sha256Hex",
    "ShortText",
    "SUTId",
    "SUTRef",
    "StudyId",
    "StudyRef",
    "Token",
    "Version",
    "VersionClause",
    "VersionedRef",
    "VersionSpecifier",
    "WorkspaceRelativePath",
    "keyed_by",
    "unique_items",
]
