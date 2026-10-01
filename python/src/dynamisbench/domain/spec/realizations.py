"""Benchmark realizations.

A realization is the executable implementation of a benchmark in one engine and model
stack. It is a separate independently identified definition from the benchmark it
realises, from a system under test, and from an execution environment; two
realizations of one benchmark are not presumed numerically equivalent, and their
discrepancies are measured rather than assumed away.

This module also holds the realization-specific half of the quantity interoperability
boundary. A canonical quantity carries the engine-independent semantics frozen into
the benchmark release; the extraction mapping and the normalization transform that
turn an engine's own output into that quantity are engine-specific by definition and
therefore belong here. The mapping names a realization-local label. It never carries
an engine object, an engine vector layout, or any native state (ADR-001).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    Token,
    keyed_by,
)
from dynamisbench.domain.spec.capability import CapabilityDeclaration, EngineBinding
from dynamisbench.domain.spec.identifiers import (
    BenchmarkRef,
    Name,
    QuantityId,
    RealizationId,
    Sha256Hex,
    Version,
    WorkspaceRelativePath,
)


class AssetReference(DomainModel):
    """A model or data asset a realization depends on, by workspace-relative path."""

    asset_id: Name
    path: WorkspaceRelativePath
    description: ShortText
    sha256: Sha256Hex | None = None


class ConfigurationEntry(DomainModel):
    """One engine configuration setting, as a realization-private label and value.

    Engine configuration cannot be universalised, so it stays an opaque label and
    value. It is keyed and canonically ordered, so it still contributes a stable
    meaning to a realization's identity.
    """

    name: Name
    value: Token


class NormalizationTransform(DomainModel):
    """A named, versioned mapping from an engine's output to a canonical quantity."""

    name: Name
    version: Version


class RealizationQuantityMapping(DomainModel):
    """How one canonical quantity is extracted from this realization.

    ``source`` is the realization-local name of the engine-native quantity the value
    comes from, for example a model sensor name or an analyser output name. It is a
    name, never an object: no ``qpos``, no ``State``, no engine vector layout can be
    expressed here, and an unknown field is rejected rather than stored.
    """

    quantity: QuantityId
    source: Token
    transform: NormalizationTransform | None = None
    notes: tuple[ShortText, ...] = ()


class RealizationDefinition(DomainModel):
    """One executable implementation of one benchmark release in one engine."""

    realization_id: RealizationId
    version: Version
    label: ShortText
    description: NonEmptyText
    benchmark: BenchmarkRef
    engine: EngineBinding
    capabilities: Annotated[
        tuple[CapabilityDeclaration, ...], keyed_by("capability"), Field(min_length=1)
    ]
    quantity_mappings: Annotated[
        tuple[RealizationQuantityMapping, ...], keyed_by("quantity"), Field(min_length=1)
    ]
    engine_configuration: Annotated[tuple[ConfigurationEntry, ...], keyed_by("name")] = ()
    assets: Annotated[tuple[AssetReference, ...], keyed_by("asset_id")] = ()
    known_discrepancies: tuple[NonEmptyText, ...] = ()
    notes: tuple[ShortText, ...] = ()
