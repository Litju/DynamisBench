"""DB-3.3A content-addressed materialization of execution inputs.

This package implements ADR-026's DB-3.3A slice only:

* canonical, versioned :class:`InputManifest` and :class:`InputManifestDigest`;
* materialization of the five resolved definitions and declared realization assets;
* exact digest and bounded logical-path verification;
* create-if-absent, no-overwrite CAS publication on Windows and Linux;
* concurrency, collision, corruption and interrupted-write refusal;
* cache reuse and deterministic manifest generation;
* refusal of unsupported subprocess/bridge SUT closures.

It does **not** implement a worker input view, worker protocol v2, native artifacts,
generic model loading, a simulation API, assessment or scientific acceptance. Those
remain later gates.
"""

from dynamisbench.materialization.errors import (
    MAX_REFUSAL_MESSAGE_LENGTH,
    MaterializationError,
    MaterializationRefusalCode,
)
from dynamisbench.materialization.manifest import (
    InputManifestDigest,
    canonical_input_manifest_bytes,
    input_manifest_digest,
    parse_input_manifest,
)
from dynamisbench.materialization.materialize import (
    MaterializedInputs,
    materialize_inputs,
)
from dynamisbench.materialization.schema import (
    INPUT_MANIFEST_SCHEMA_VERSION,
    MAX_ASSETS,
    MAX_BYTES_PER_ASSET,
    MAX_DEFINITION_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PATH_SEGMENTS,
    MAX_TOTAL_ASSET_BYTES,
    AssetInput,
    AssetOwner,
    DefinitionInput,
    DefinitionKind,
    ExecutionInputRefs,
    InputManifest,
    ManifestLimits,
    StoreObjectKey,
)
from dynamisbench.materialization.store import MaterializationStore

__all__ = [
    "INPUT_MANIFEST_SCHEMA_VERSION",
    "MAX_ASSETS",
    "MAX_BYTES_PER_ASSET",
    "MAX_DEFINITION_BYTES",
    "MAX_MANIFEST_BYTES",
    "MAX_PATH_SEGMENTS",
    "MAX_REFUSAL_MESSAGE_LENGTH",
    "MAX_TOTAL_ASSET_BYTES",
    "AssetInput",
    "AssetOwner",
    "DefinitionInput",
    "DefinitionKind",
    "ExecutionInputRefs",
    "InputManifest",
    "InputManifestDigest",
    "ManifestLimits",
    "MaterializationError",
    "MaterializationRefusalCode",
    "MaterializationStore",
    "MaterializedInputs",
    "StoreObjectKey",
    "canonical_input_manifest_bytes",
    "input_manifest_digest",
    "materialize_inputs",
    "parse_input_manifest",
]
