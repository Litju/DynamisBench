"""Materialize the exact five definitions and declared assets of one ``RunSpec``.

DB-3.3A is deliberately narrow. It copies canonical definition bytes and
declared realization assets into a content-addressed cache and derives one
canonical :class:`InputManifest`. It does not build a worker input view, does not
extend the worker protocol, does not read native output, and does not touch sealed
evidence.

Authority selection is exact. The caller supplies five already-validated
definitions; each identifier, version and recomputed semantic digest must equal the
RunSpec's resolved reference, the scenario must be the one embedded in the selected
benchmark release, and the realization must name that same benchmark. A mismatch is
refused before a manifest exists. Identifier equality alone never admits bytes.

Source assets are copied from a verified, no-follow open, hashed **as copied**, and
published by :class:`~dynamisbench.materialization.store.MaterializationStore`.
Subprocess and bridge SUTs are refused: their executable/library closure is not
enumerated by ``RealizationDefinition.assets``, so DB-3.3A cannot claim it
materialized what a subprocess would run.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final

from pydantic import TypeAdapter, ValidationError

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition
from dynamisbench.domain.spec.sut import SUTDefinition, SUTInterfaceKind
from dynamisbench.identity import SemanticDigest, canonical_semantic_bytes, semantic_sha256
from dynamisbench.materialization.errors import (
    MaterializationError,
    MaterializationRefusalCode,
)
from dynamisbench.materialization.manifest import (
    InputManifestDigest,
    canonical_input_manifest_bytes,
    input_manifest_digest,
)
from dynamisbench.materialization.schema import (
    MAX_ASSETS,
    MAX_BYTES_PER_ASSET,
    MAX_DEFINITION_BYTES,
    MAX_PATH_SEGMENTS,
    MAX_TOTAL_ASSET_BYTES,
    AssetInput,
    AssetOwner,
    DefinitionInput,
    DefinitionKind,
    ExecutionInputRefs,
    InputManifest,
    ManifestLimits,
    MaterializedAssetPath,
)
from dynamisbench.materialization.store import MaterializationStore
from dynamisbench.planning import RunSpec
from dynamisbench.workspace import PathScopeError, PersistenceClass, Workspace
from dynamisbench.workspace.paths import resolve_within, validate_logical_reference

_OPEN_BINARY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_BINARY", 0)
_ASSET_PATH_ADAPTER: Final = TypeAdapter(MaterializedAssetPath)


def _validate_asset_declarations(realization: RealizationDefinition) -> None:
    """Refuse an impossible asset set before reading or publishing any bytes."""
    if len(realization.assets) > MAX_ASSETS:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"the realization declares more than {MAX_ASSETS} assets",
        )
    asset_ids: set[str] = set()
    paths: set[str] = set()
    for asset in realization.assets:
        if asset.asset_id in asset_ids:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_SET_UNEXPECTED,
                f"asset {asset.asset_id!r} is declared twice",
            )
        asset_ids.add(asset.asset_id)
        try:
            _ASSET_PATH_ADAPTER.validate_python(asset.path)
        except ValidationError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_PATH_REFUSED,
                f"asset {asset.asset_id!r} has a non-portable materialized path",
            ) from error
        folded = asset.path.casefold()
        if folded in paths:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_SET_UNEXPECTED,
                f"asset path {asset.path!r} is duplicated or differs only by case",
            )
        paths.add(folded)
        if asset.sha256 is None:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_SET_INCOMPLETE,
                f"asset {asset.asset_id!r} declares no SHA-256 content identity",
            )


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        if path.is_junction():
            return True
    except (AttributeError, OSError):
        pass
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _require_match(
    kind: str,
    *,
    identifier: object,
    version: object,
    digest: SemanticDigest,
    expected_identifier: object,
    expected_version: object,
    expected_digest: SemanticDigest,
) -> None:
    if (
        str(identifier) != str(expected_identifier)
        or version != expected_version
        or digest != expected_digest
    ):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH,
            f"the supplied {kind} definition is not the one the RunSpec resolved",
        )


def _definition_record(
    store: MaterializationStore,
    *,
    kind: DefinitionKind,
    identifier: object,
    version: object,
    definition: DomainModel,
) -> DefinitionInput:
    canonical = canonical_semantic_bytes(definition)
    digest = semantic_sha256(definition)
    key = store.publish_bytes(
        canonical,
        expected_sha256=digest.hex,
        max_bytes=MAX_DEFINITION_BYTES,
        kind="object",
        mismatch_code=MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH,
    )
    return DefinitionInput(
        kind=kind,
        identifier=str(identifier),
        version=str(version),
        semantic_digest=digest,
        size_bytes=len(canonical),
        object=key,
    )


def _open_source(path: Path, *, max_bytes: int) -> BinaryIO:
    """Open a regular, non-linked source file and return a binary handle.

    The final name and every parent component are inspected before opening. POSIX
    adds ``O_NOFOLLOW``; the opened handle is compared with the pre-open stat so a
    replacement between inspection and open is refused. Windows has no portable
    no-follow open, so the residual is explicit: the handle check catches a different
    file, but a same-user replacement that preserves the file identity is outside the
    A1 detection claim.
    """
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_SET_INCOMPLETE,
            "a declared realization asset is missing from the source root",
        ) from error
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_SET_INCOMPLETE,
            "a declared realization asset could not be inspected",
        ) from error
    if _is_link(path):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LINK_REFUSED,
            "a declared realization asset is a link, not a regular file",
        )
    if not stat.S_ISREG(before.st_mode):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_SET_INCOMPLETE,
            "a declared realization asset is not a regular file",
        )
    if before.st_nlink != 1:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LINK_REFUSED,
            "a declared realization asset is hard-linked; only a single-link source is trusted",
        )
    if before.st_size > max_bytes:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"a declared realization asset is larger than the {max_bytes}-byte limit",
        )

    flags = _OPEN_BINARY_FLAGS | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_SOURCE_CHANGED,
            "a declared realization asset could not be opened without following a link",
        ) from error
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or after.st_size != before.st_size
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_SOURCE_CHANGED,
                "a declared realization asset changed between inspection and open",
            )
        if after.st_size > max_bytes:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
                f"a declared realization asset is larger than the {max_bytes}-byte limit",
            )
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _source_path(workspace: Workspace, logical_path: str) -> Path:
    try:
        segments = validate_logical_reference(
            logical_path, persistence_class=PersistenceClass.SOURCE_AUTHORITY
        )
    except PathScopeError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_PATH_REFUSED,
            "an asset path is not a portable workspace-relative reference",
        ) from error
    if len(segments) > MAX_PATH_SEGMENTS:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"an asset path has more than {MAX_PATH_SEGMENTS} segments",
        )
    current = workspace.source_root
    for segment in segments[:-1]:
        current = current / segment
        if _is_link(current):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LINK_REFUSED,
                "an asset path contains a link or reparse point",
            )
        if not current.is_dir():
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_SET_INCOMPLETE,
                "an asset path contains a component that is not a directory",
            )
    unresolved = workspace.source_root.joinpath(*segments)
    if _is_link(unresolved):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LINK_REFUSED,
            "a declared realization asset is a link, not a regular file",
        )
    try:
        resolve_within(
            workspace.source_root,
            logical_path,
            authorized_roots=(workspace.source_root,),
            persistence_class=PersistenceClass.SOURCE_AUTHORITY,
        )
    except PathScopeError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_PATH_REFUSED,
            "an asset path leaves the source root",
        ) from error
    return unresolved


@dataclass(frozen=True, slots=True)
class MaterializedInputs:
    """The result of one successful DB-3.3A materialization."""

    manifest: InputManifest
    manifest_digest: InputManifestDigest
    manifest_locator: str


def materialize_inputs(
    workspace: Workspace,
    run_spec: RunSpec,
    *,
    benchmark: BenchmarkRelease,
    scenario: ScenarioDefinition,
    realization: RealizationDefinition,
    system_under_test: SUTDefinition,
    environment: EnvironmentDefinition,
    store: MaterializationStore | None = None,
) -> MaterializedInputs:
    """Materialize exactly the five definitions and declared realization assets.

    :raises MaterializationError: for an authority mismatch, an unsupported SUT
        interface, a missing/oversized/linked asset, a digest mismatch, a store
        corruption, or a manifest that cannot satisfy the schema.
    """
    if system_under_test.interface.kind is not SUTInterfaceKind.IN_PROCESS:
        raise MaterializationError(
            MaterializationRefusalCode.SUT_EXECUTABLE_CLOSURE_UNSUPPORTED,
            "DB-3.3A materializes only in-process SUTs; a subprocess or bridge SUT has no "
            "enumerated executable closure",
        )
    _validate_asset_declarations(realization)

    benchmark_digest = semantic_sha256(benchmark)
    scenario_digest = semantic_sha256(scenario)
    realization_digest = semantic_sha256(realization)
    sut_digest = semantic_sha256(system_under_test)
    environment_digest = semantic_sha256(environment)

    _require_match(
        "benchmark",
        identifier=benchmark.benchmark_id,
        version=benchmark.version,
        digest=benchmark_digest,
        expected_identifier=run_spec.benchmark.identifier,
        expected_version=run_spec.benchmark.version,
        expected_digest=run_spec.benchmark.semantic_digest,
    )
    _require_match(
        "scenario",
        identifier=scenario.scenario_id,
        version=scenario.version,
        digest=scenario_digest,
        expected_identifier=run_spec.scenario.identifier,
        expected_version=run_spec.scenario.version,
        expected_digest=run_spec.scenario.semantic_digest,
    )
    _require_match(
        "realization",
        identifier=realization.realization_id,
        version=realization.version,
        digest=realization_digest,
        expected_identifier=run_spec.realization.identifier,
        expected_version=run_spec.realization.version,
        expected_digest=run_spec.realization.semantic_digest,
    )
    _require_match(
        "system under test",
        identifier=system_under_test.sut_id,
        version=system_under_test.version,
        digest=sut_digest,
        expected_identifier=run_spec.system_under_test.identifier,
        expected_version=run_spec.system_under_test.version,
        expected_digest=run_spec.system_under_test.semantic_digest,
    )
    _require_match(
        "environment",
        identifier=environment.environment_id,
        version=environment.version,
        digest=environment_digest,
        expected_identifier=run_spec.environment.identifier,
        expected_version=run_spec.environment.version,
        expected_digest=run_spec.environment.semantic_digest,
    )

    if (
        realization.benchmark.identifier != run_spec.benchmark.identifier
        or realization.benchmark.version != run_spec.benchmark.version
    ):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH,
            "the realization is not bound to the RunSpec's benchmark release",
        )

    embedded = [
        candidate
        for candidate in benchmark.scenarios
        if candidate.scenario_id == scenario.scenario_id and candidate.version == scenario.version
    ]
    if len(embedded) != 1 or semantic_sha256(embedded[0]) != scenario_digest:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_DEFINITION_MISMATCH,
            "the supplied scenario is not the one embedded in the benchmark release",
        )

    execution_refs = ExecutionInputRefs(
        benchmark=run_spec.benchmark,
        scenario=run_spec.scenario,
        realization=run_spec.realization,
        system_under_test=run_spec.system_under_test,
        environment=run_spec.environment,
    )
    materialization_store = store if store is not None else MaterializationStore(workspace)
    materialization_store.ensure_layout()

    definitions = (
        _definition_record(
            materialization_store,
            kind=DefinitionKind.BENCHMARK,
            identifier=benchmark.benchmark_id,
            version=benchmark.version,
            definition=benchmark,
        ),
        _definition_record(
            materialization_store,
            kind=DefinitionKind.SCENARIO,
            identifier=scenario.scenario_id,
            version=scenario.version,
            definition=scenario,
        ),
        _definition_record(
            materialization_store,
            kind=DefinitionKind.REALIZATION,
            identifier=realization.realization_id,
            version=realization.version,
            definition=realization,
        ),
        _definition_record(
            materialization_store,
            kind=DefinitionKind.SYSTEM_UNDER_TEST,
            identifier=system_under_test.sut_id,
            version=system_under_test.version,
            definition=system_under_test,
        ),
        _definition_record(
            materialization_store,
            kind=DefinitionKind.ENVIRONMENT,
            identifier=environment.environment_id,
            version=environment.version,
            definition=environment,
        ),
    )

    assets: list[AssetInput] = []
    total_asset_bytes = 0
    for asset in realization.assets:
        assert asset.sha256 is not None  # validated before any publication
        source = _source_path(workspace, asset.path)
        with _open_source(source, max_bytes=MAX_BYTES_PER_ASSET) as handle:
            key, size = materialization_store.publish_stream(
                handle,
                expected_sha256=asset.sha256,
                max_bytes=MAX_BYTES_PER_ASSET,
                mismatch_code=MaterializationRefusalCode.INPUT_SOURCE_CHANGED,
            )
        total_asset_bytes += size
        if total_asset_bytes > MAX_TOTAL_ASSET_BYTES:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
                f"the materialized assets exceed the {MAX_TOTAL_ASSET_BYTES}-byte total limit",
            )
        assets.append(
            AssetInput(
                owner=AssetOwner(
                    kind=DefinitionKind.REALIZATION,
                    identifier=str(realization.realization_id),
                    version=realization.version,
                    semantic_digest=realization_digest,
                ),
                asset_id=asset.asset_id,
                logical_path=asset.path,
                declared_sha256=asset.sha256,
                observed_sha256=key.removeprefix("sha256/"),
                size_bytes=size,
                object=key,
            )
        )

    try:
        manifest = InputManifest(
            execution_refs=execution_refs,
            definitions=definitions,
            assets=tuple(assets),
            limits=ManifestLimits(),
        )
    except ValidationError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_SET_UNEXPECTED,
            f"the materialized input set is not a valid canonical manifest: {error}",
        ) from error

    canonical = canonical_input_manifest_bytes(manifest)
    if len(canonical) > manifest.limits.max_manifest_bytes:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            "the canonical input manifest exceeds the declared manifest-byte limit",
        )
    digest, locator = materialization_store.publish_manifest(manifest)
    materialization_store.verify_manifest(manifest)
    if input_manifest_digest(manifest) != digest:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
            "the published manifest digest changed during materialization",
        )
    return MaterializedInputs(
        manifest=manifest,
        manifest_digest=digest,
        manifest_locator=locator,
    )


__all__ = [
    "MaterializedInputs",
    "materialize_inputs",
]
