"""Versioned schema for the exact execution-input set of one materialized run.

This is ADR-026's ``dynamisbench.execution-input-manifest/1``. The manifest describes
the five resolved scientific definitions and every declared realization asset that
were materialized for an execution. It is a *derived, inspectable binding*, not a
replacement for semantic or asset identity and not part of ``RunSpec`` 0.1.0.

The model is deliberately strict:

* exactly five definitions, one per authority kind;
* definition semantic digests and asset observed digests must be the digest each
  store object is keyed by;
* every asset owner must be the realization, and its identity must equal the
  realization reference in ``execution_refs``;
* declared and observed asset digests must agree;
* paths are the domain's 256-character ``WorkspaceRelativePath`` and the manifest
  additionally bounds segment count;
* arrays are sorted into one canonical order and duplicate logical paths (including
  case-only aliases) are refused.

A manifest that cannot satisfy these invariants is not a weaker manifest; it is not
an input identity at all.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.identifiers import Sha256Hex, Version, WorkspaceRelativePath
from dynamisbench.identity import SemanticDigest
from dynamisbench.planning import (
    ResolvedBenchmarkRef,
    ResolvedEnvironmentRef,
    ResolvedRealizationRef,
    ResolvedScenarioRef,
    ResolvedSUTRef,
)
from dynamisbench.workspace import PathScopeError, PersistenceClass
from dynamisbench.workspace.paths import validate_logical_reference

INPUT_MANIFEST_SCHEMA_VERSION: Final = "dynamisbench.execution-input-manifest/1"

MAX_ASSETS: Final = 64
MAX_BYTES_PER_ASSET: Final = 256 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES: Final = 1024 * 1024 * 1024
MAX_DEFINITION_BYTES: Final = 8 * 1024 * 1024
MAX_MANIFEST_BYTES: Final = 8 * 1024 * 1024
MAX_PATH_SEGMENTS: Final = 32
MAX_IDENTIFIER_LENGTH: Final = 128

StoreObjectKey = Annotated[
    str,
    StringConstraints(pattern=r"^sha256/[0-9a-f]{64}$"),
]
"""A store-relative object key. It is never an absolute path or a store root."""


def _validated_materialized_path(value: str) -> str:
    """Apply the workspace path gate in addition to the domain path bound.

    ``WorkspaceRelativePath`` already enforces 256 characters, ``/`` separators and
    no whitespace. This second gate refuses Windows device names, alternate-data-stream
    spellings, illegal characters, trailing dots/spaces and traversal forms, so a
    manifest path and a producer path cannot be two different languages.
    """
    try:
        segments = validate_logical_reference(
            value, persistence_class=PersistenceClass.SOURCE_AUTHORITY
        )
    except PathScopeError as error:
        raise ValueError(f"not a portable materialized asset path: {error}") from error
    if len(segments) > MAX_PATH_SEGMENTS:
        raise ValueError(f"a materialized asset path may have at most {MAX_PATH_SEGMENTS} segments")
    return value


MaterializedAssetPath = Annotated[
    WorkspaceRelativePath, AfterValidator(_validated_materialized_path)
]
"""A materialized asset path: the domain path bound plus the workspace lexical gate."""


class DefinitionKind(StrEnum):
    """The five authority kinds a materialized execution must bind."""

    BENCHMARK = "benchmark"
    SCENARIO = "scenario"
    REALIZATION = "realization"
    SYSTEM_UNDER_TEST = "system_under_test"
    ENVIRONMENT = "environment"


class DefinitionInput(DomainModel):
    """One canonical definition object in the materialized input set."""

    kind: DefinitionKind
    identifier: Annotated[str, StringConstraints(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)]
    version: Version
    semantic_digest: SemanticDigest
    size_bytes: Annotated[int, Field(ge=0, le=MAX_DEFINITION_BYTES)]
    object: StoreObjectKey


class AssetOwner(DomainModel):
    """The definition that declared an asset."""

    kind: DefinitionKind
    identifier: Annotated[str, StringConstraints(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)]
    version: Version
    semantic_digest: SemanticDigest


class AssetInput(DomainModel):
    """One declared realization asset, bound to its exact bytes and store object."""

    owner: AssetOwner
    asset_id: Annotated[str, StringConstraints(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)]
    logical_path: MaterializedAssetPath
    declared_sha256: Sha256Hex
    observed_sha256: Sha256Hex
    size_bytes: Annotated[int, Field(ge=0, le=MAX_BYTES_PER_ASSET)]
    object: StoreObjectKey


class ManifestLimits(DomainModel):
    """The policy bounds the manifest was produced under.

    These are recorded so a reader can see the bounds, but they are not caller
    choices: a manifest that claims a different policy is refused. Changing a bound
    is a new manifest schema version, not a per-file option.
    """

    max_assets: int = MAX_ASSETS
    max_bytes_per_asset: int = MAX_BYTES_PER_ASSET
    max_total_bytes: int = MAX_TOTAL_ASSET_BYTES
    max_definition_bytes: int = MAX_DEFINITION_BYTES
    max_manifest_bytes: int = MAX_MANIFEST_BYTES
    max_path_segments: int = MAX_PATH_SEGMENTS

    @model_validator(mode="after")
    def _limits_are_the_declared_policy(self) -> Self:
        observed = (
            self.max_assets,
            self.max_bytes_per_asset,
            self.max_total_bytes,
            self.max_definition_bytes,
            self.max_manifest_bytes,
            self.max_path_segments,
        )
        expected = (
            MAX_ASSETS,
            MAX_BYTES_PER_ASSET,
            MAX_TOTAL_ASSET_BYTES,
            MAX_DEFINITION_BYTES,
            MAX_MANIFEST_BYTES,
            MAX_PATH_SEGMENTS,
        )
        if observed != expected:
            raise ValueError(
                "manifest limits must equal the declared DB-3.3A policy; "
                "a different policy is a new manifest version"
            )
        return self


class ExecutionInputRefs(DomainModel):
    """The five resolved references copied from the RunSpec."""

    benchmark: ResolvedBenchmarkRef
    scenario: ResolvedScenarioRef
    realization: ResolvedRealizationRef
    system_under_test: ResolvedSUTRef
    environment: ResolvedEnvironmentRef


def _definition_sort_key(item: DefinitionInput) -> tuple[str, str, str]:
    return (item.kind.value, item.identifier, item.version)


def _asset_sort_key(item: AssetInput) -> tuple[str, str, str, str]:
    return (
        item.owner.kind.value,
        item.owner.identifier,
        item.owner.version,
        item.asset_id,
    )


def _canonical_definitions(
    values: tuple[DefinitionInput, ...],
) -> tuple[DefinitionInput, ...]:
    """Sort definitions and refuse duplicate kinds before the model is built."""
    kinds = [item.kind for item in values]
    if len(set(kinds)) != len(kinds):
        raise ValueError("an input manifest must contain each definition kind at most once")
    return tuple(sorted(values, key=_definition_sort_key))


def _canonical_assets(values: tuple[AssetInput, ...]) -> tuple[AssetInput, ...]:
    """Sort assets and refuse duplicate ids or case-only logical-path aliases.

    Case folding is deliberate on both platforms: a manifest that is valid on
    Windows must not become ambiguous when the same bytes are read on Linux, and a
    case-only pair would name two entries for one NTFS file.
    """
    keys: set[tuple[str, str, str, str]] = set()
    paths: set[str] = set()
    for item in values:
        key = _asset_sort_key(item)
        if key in keys:
            raise ValueError(f"asset {item.asset_id!r} is declared twice for one owning definition")
        keys.add(key)
        folded = item.logical_path.casefold()
        if folded in paths:
            raise ValueError(
                f"asset logical path {item.logical_path!r} is duplicated or differs only by case"
            )
        paths.add(folded)
    return tuple(sorted(values, key=_asset_sort_key))


class InputManifest(DomainModel):
    """One canonical, self-consistent materialized input set."""

    schema_version: Literal["dynamisbench.execution-input-manifest/1"] = (
        INPUT_MANIFEST_SCHEMA_VERSION
    )
    execution_refs: ExecutionInputRefs
    definitions: Annotated[
        tuple[DefinitionInput, ...],
        Field(min_length=5, max_length=5),
        AfterValidator(_canonical_definitions),
    ]
    assets: Annotated[
        tuple[AssetInput, ...],
        Field(max_length=MAX_ASSETS),
        AfterValidator(_canonical_assets),
    ] = ()
    limits: ManifestLimits = Field(default_factory=ManifestLimits)

    @model_validator(mode="after")
    def _the_input_set_is_exactly_the_declared_authority(self) -> Self:
        expected_refs = {
            DefinitionKind.BENCHMARK: self.execution_refs.benchmark,
            DefinitionKind.SCENARIO: self.execution_refs.scenario,
            DefinitionKind.REALIZATION: self.execution_refs.realization,
            DefinitionKind.SYSTEM_UNDER_TEST: self.execution_refs.system_under_test,
            DefinitionKind.ENVIRONMENT: self.execution_refs.environment,
        }

        seen_kinds: set[DefinitionKind] = set()
        for definition in self.definitions:
            if definition.kind in seen_kinds:
                raise ValueError(f"definition kind {definition.kind.value!r} appears twice")
            seen_kinds.add(definition.kind)
            ref = expected_refs[definition.kind]
            if (
                definition.identifier != str(ref.identifier)
                or definition.version != ref.version
                or definition.semantic_digest != ref.semantic_digest
            ):
                raise ValueError(
                    f"the {definition.kind.value} definition is not the one the RunSpec resolved"
                )
            expected_object = f"sha256/{definition.semantic_digest.hex}"
            if definition.object != expected_object:
                raise ValueError(
                    f"the {definition.kind.value} object key is not its semantic digest"
                )

        if seen_kinds != set(DefinitionKind):
            raise ValueError("an input manifest must contain exactly the five authority kinds")

        total_asset_bytes = 0
        for asset in self.assets:
            if asset.owner.kind is not DefinitionKind.REALIZATION:
                raise ValueError("DB-3.3A materializes only realization-declared assets")
            realization = self.execution_refs.realization
            if (
                asset.owner.identifier != str(realization.identifier)
                or asset.owner.version != realization.version
                or asset.owner.semantic_digest != realization.semantic_digest
            ):
                raise ValueError("an asset owner is not the RunSpec's realization")
            if asset.declared_sha256 != asset.observed_sha256:
                raise ValueError("an asset's observed bytes do not match its declaration")
            expected_object = f"sha256/{asset.observed_sha256}"
            if asset.object != expected_object:
                raise ValueError("an asset object key is not its observed digest")
            segments = asset.logical_path.split("/")
            if len(segments) > self.limits.max_path_segments:
                raise ValueError(
                    f"asset logical path has {len(segments)} segments; the limit is "
                    f"{self.limits.max_path_segments}"
                )
            total_asset_bytes += asset.size_bytes

        if total_asset_bytes > self.limits.max_total_bytes:
            raise ValueError("the input set exceeds the declared total asset-byte limit")
        return self


__all__ = [
    "INPUT_MANIFEST_SCHEMA_VERSION",
    "MAX_ASSETS",
    "MAX_BYTES_PER_ASSET",
    "MAX_DEFINITION_BYTES",
    "MAX_MANIFEST_BYTES",
    "MAX_PATH_SEGMENTS",
    "MAX_TOTAL_ASSET_BYTES",
    "AssetInput",
    "AssetOwner",
    "DefinitionInput",
    "DefinitionKind",
    "ExecutionInputRefs",
    "InputManifest",
    "ManifestLimits",
    "MaterializedAssetPath",
    "StoreObjectKey",
]
