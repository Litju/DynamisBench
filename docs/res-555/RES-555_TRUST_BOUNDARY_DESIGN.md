# RES-555 — Trust Boundary Design

**Status:** Proposed design for independent architecture, scientific, and security review.
Not accepted authority. Not an implementation. Not an ADR.
**Baseline:** protected `main` `2a3ef6016e904de5b218e657f15793dd230250bb`,
tree `51e4b366d0cce3cddfba56e6e0fc1720e0fec421`.
**Companion artifacts:** `RES-555_AUTHORITY_AUDIT.md`,
`RES-555_AUTHORITY_DECISION_PACKET.md`, `RES-555_EXECUTION_PLAN.md`.

> This document proposes a substrate. It deliberately does not implement it, does not
> modify the accepted `RunSpec` or worker protocol, and does not authorize a native
> evidence format. Every schema below is a **candidate** until the corresponding decision
> in the decision packet is approved and the authority is amended.

---

## 0. The claim this design is allowed to make

The design separates four guarantees that are often conflated:

| Guarantee | Question | What can establish it |
|---|---|---|
| **Content identity** | Are these the exact bytes/meaning we think? | SHA-256 over canonical meaning or raw bytes |
| **Execution binding** | Is this execution the one the admitted RunSpec describes? | Resolved refs, fingerprint, manifest digest, admission record |
| **Input integrity during execution** | Did the input bytes stay the admitted bytes? | Verified snapshot, launch re-hash, read-time hash, post-run re-hash |
| **Containment / immutability** | Can a worker read or write outside its authorized set? | An OS trust boundary, not a path convention |

The design can establish the first three with ordinary same-user Python and filesystem
operations. It **cannot** establish the fourth without a separate OS identity, sandbox, or
read-only mapping. The accepted authority already says this:

* A1 §13: the local bearer is not a claim of security against a fully compromised
  same-user operating-system session.
* The accepted evidence implementation (`evidence/sealed.py`, `evidence/__init__.py`):
  Windows read-only bits, ACLs, and WDAC are not the source of scientific immutability; a
  permission bit is not a scientific claim. A3: a self-contained seal with no external
  expected digest proves internal consistency, not tamper-resistance.
* `evidence/sealed.py`: verification proves self-consistency; only an externally trusted
  expected digest proves expected output; neither is tamper-proof.

Therefore the design has two modes, and every record must say which one applied:

```text
CONTAINMENT_MODE = verified-content
    Same OS user. Inputs are copied, content-addressed, re-hashed at launch, at worker
    read, and after execution. Modification is detected; containment is not enforced.

CONTAINMENT_MODE = os-enforced
    A separate worker identity, sandbox, or read-only mapping is provisioned and probed.
    Reads/writes outside the authorized input view are denied by the OS, not merely
    detected. This mode is not available in the accepted baseline and is not claimed.
```

`verified-content` is the only mode this design can honestly propose for DB-3.3B without a
new platform prerequisite. Approving it means accepting detection, not immutability. If
the owner requires the word "immutable" in the acceptance claim, the design must stop at
decision D3 and the OS-enforced mode must be authorized and provisioned first.

---

## 1. Design goals and invariants

### 1.1 Goals

1. Select the exact five validated definitions named by the RunSpec and no others.
2. Materialize their canonical meaning and every declared asset byte into a deterministic,
   content-addressed store.
3. Publish atomically; deduplicate identical content; refuse inconsistent or colliding
   objects.
4. Bind the materialized set to the admitted RunSpec without adding machine paths to
   scientific identity.
5. Give the worker a per-run, relative, verified input view, and make the worker verify
   the bytes it actually loads.
6. Detect source mutation, replacement, replay, missing/extra files, and partial writes.
7. Produce a bounded native artifact through a supervisor-owned publication path, and
   never let a failed or incomplete worker turn it into successful sealed evidence.
8. Preserve the distinction between process completion, native production, native
   verification, sealing, normalization, assessment, and VVUQ acceptance.

### 1.2 Invariants

| ID | Invariant |
|---|---|
| I-1 | A worker may execute only after the supervisor has published and verified an input manifest whose digest matches the admitted execution binding. |
| I-2 | A worker may load model bytes only from the per-run input view, after hashing those exact bytes against the manifest. A path that was not verified is never opened for physics. |
| I-3 | A change to any materialized definition or asset byte either changes the appropriate content identity and prevents execution, or is detected and refused before successful sealing. |
| I-4 | Two runs with identical scientific inputs have the same `ExecutionFingerprint`, regardless of workspace root, store root, temporary directory, drive, host, or user. |
| I-5 | A materialization manifest may bind logical references to store objects; it may not contain an absolute path or a host-specific identifier. |
| I-6 | A successful seal requires a complete native verification record, an unchanged input set, a valid worker response, and a verified terminal process observation. None of those facts implies scientific validity. |
| I-7 | A failed, cancelled, timed-out, partial, substituted, or unverified native output is never sealed as `SUCCEEDED`. |
| I-8 | No new lifecycle enum value is inferred from a native artifact. Native production/verification/sealing are derived records, not new `RunLifecycleState` or `RunOutcome` values. |

---

## 2. Identity model and digest relationships

### 2.1 Existing identity types (unchanged)

| Type | Question | Owner | Input | Canonical form | Lifecycle |
|---|---|---|---|---|---|
| `SemanticDigest` | What does this validated definition mean? | `identity` / domain | Validated Pydantic model | RFC 8785 canonical JSON of the model's JSON-mode meaning; SHA-256 | Stable for the life of the definition; never rewritten |
| `AssetDigest` | What are these exact bytes? | `identity` | Raw byte stream | Raw bytes; SHA-256 | Stable; moving or renaming does not change it |
| `ExecutionFingerprint` | What execution was requested? | `planning` | Resolved `RunSpec` | RFC 8785 canonical JSON of the `RunSpec`; SHA-256 | Stable for the life of the RunSpec; replicate index excluded |
| `EvidenceDigest` | What did the run produce and seal? | `evidence` | Canonical `manifest.json` bytes | RFC 8785 canonical manifest JSON; SHA-256 | Created at seal; never rewritten |
| `WorkerAdapterIdentity.implementation_digest` | Which adapter implementation will run? | adapter / execution | Canonical adapter identity payload | RFC 8785 canonical JSON; SHA-256 | Recomputed at worker start; bound to request |
| `EnvironmentDefinition` semantic digest | Which scientific environment? | domain / planning | Validated environment definition | RFC 8785 canonical JSON; SHA-256 | Stable for the definition |

These types are not interchangeable, and this design does not collapse them. In
particular:

* A `SemanticDigest` is never used where an `AssetDigest` is required.
* An `ExecutionFingerprint` is never compared with an `EvidenceDigest` to decide whether
  two runs agree.
* A worker's self-reported digest is never accepted as independent proof of the bytes it
  read.

### 2.2 Proposed identity types (candidate, not implemented)

| Type | Question | Owner | Trust boundary | Version | Required fields | Digest calculation | Lifecycle |
|---|---|---|---|---|---|---|---|
| `InputManifestDigest` | Which exact definition-and-asset set was materialized for this execution? | `execution` / materialization | Supervisor, derived from RunSpec + definitions | `dynamisbench.execution-input-manifest/1` | `schema_version`, `execution_refs`, `definitions`, `assets`, `limits` | SHA-256 of RFC 8785 canonical `InputManifest` bytes | Derived; reproducible from the RunSpec and its definitions; recorded in admission; not embedded in `ExecutionFingerprint` under the recommended option |
| `NativeArtifactDigest` | Which exact native artifact bytes did the worker produce? | evidence / adapter | Supervisor verifies; worker produces | `dynamisbench.native.mujoco-state/1` | Descriptor fields + file digests | SHA-256 of the descriptor's canonical bytes; per-file raw-byte SHA-256 | Created per run; verified before publication; sealed in `native/` |
| `NativeVerificationDigest` | Which supervisor verification record applies to the native artifact? | supervisor | Supervisor only | `dynamisbench.native.verification/1` | Bindings, checks, verdict | SHA-256 of canonical verification bytes | Created after native validation; sealed with the bundle |

`InputManifestDigest` is deliberately **not** an `EvidenceDigest` (it describes inputs,
not outputs) and **not** a `SemanticDigest` of a single definition (it describes a set).
If the owner prefers not to add a type, it can be a `SemanticDigest` of the manifest model
with an explicit schema tag; that is a naming decision, not a semantic one. The decision
packet records it.

### 2.3 Relationship diagram

```text
BenchmarkRelease ──canonical──► SemanticDigest ─┐
ScenarioDefinition ─canonical─► SemanticDigest ─┤
RealizationDefinition ─canonical► SemanticDigest├──► RunSpec ──canonical──► ExecutionFingerprint
SUTDefinition ─────canonical──► SemanticDigest ─┤
EnvironmentDefinition ─canonical► SemanticDigest┘
                                                          │
Realization.assets[] ──raw bytes──► AssetDigest ──────────┤
                                                          ▼
                                              InputManifest ──canonical──► InputManifestDigest
                                                          │
                                                          ▼
                                              AdmissionBinding (run-specific)
                                                          │
                                                          ▼
                                              WorkerRequest v2 (RunSpec + fingerprint +
                                              environment + adapter + input manifest digest)
                                                          │
                                                          ▼
                                              WorkerResponse v2 + native output
                                                          │
                                                          ▼
                                              native/ + native/verification.json
                                                          │
                                                          ▼
                                              sealed manifest.json ──canonical──► EvidenceDigest
```

### 2.4 The fingerprint rule

The mandatory invariant is:

> Two runs with identical scientific inputs retain the same `ExecutionFingerprint`
> regardless of where the inputs were materialized.

The recommended design keeps `ExecutionFingerprint` **unchanged**:

* `RunSpec` 0.1.0 already carries a semantic digest for the benchmark, scenario,
  realization, SUT, and environment.
* `RealizationDefinition.assets[]` carries a declared SHA-256 for every executable asset,
  and preflight refuses an asset without one.
* Therefore the RunSpec already binds the asset **digests** through the realization
  semantic digest, provided every asset is declared and every declared digest is verified
  against the bytes actually materialized.
* The `InputManifest` is a deterministic function of those same references and digests. It
  adds no new scientific meaning; it makes the binding inspectable and gives the worker a
  manifest to verify.
* A run-specific `AdmissionBinding` records `run_id`, `ExecutionFingerprint`, and
  `InputManifestDigest`. The run id and admission record are operational, not scientific,
  and never enter the fingerprint.

If the owner instead requires an independent input-set identity inside the fingerprint,
the alternative is `RunSpec` 0.2.0 with an `inputs` field and a migration. That is
decision D2. It would invalidate all existing fingerprints for new runs and must be an
explicit schema change, not a silent addition.

### 2.5 What must never enter the fingerprint or manifest

```text
absolute path, drive letter, UNC prefix, device namespace
workspace root, evidence root, cache root, store root
temporary directory, per-run scratch directory
host name, user name, SID, process id
wall-clock timestamp, file mtime, access time
filesystem inode number, volume serial, mount point
worker pid, supervisor pid, job object id
```

A workspace-relative authority path may appear in a definition and therefore in its
semantic digest. That is existing meaning, not a machine location. A store-relative object
key (`sha256/<hex>`) may appear in the manifest's operational mapping, but the manifest is
not part of the RunSpec under the recommended option.

---

## 3. Materialization architecture

### 3.1 Authority selection

For one `RunSpec`, materialization receives exactly:

1. `BenchmarkRelease` whose identifier, version, and semantic digest equal
   `run_spec.benchmark`.
2. `ScenarioDefinition` whose identifier, version, and semantic digest equal
   `run_spec.scenario`, and which is present in that benchmark release's `scenarios`.
3. `RealizationDefinition` whose identifier, version, and semantic digest equal
   `run_spec.realization`.
4. `SUTDefinition` whose identifier, version, and semantic digest equal
   `run_spec.system_under_test`.
5. `EnvironmentDefinition` whose identifier, version, and semantic digest equal
   `run_spec.environment`.

The materializer recomputes each digest from the supplied definition. It does not trust a
caller-supplied digest. It refuses:

* zero or multiple matches;
* a digest mismatch;
* a scenario not embedded in the selected benchmark;
* a realization bound to a different benchmark;
* a SUT or environment whose content changed after planning;
* any unresolved or `latest` reference.

This closes the preflight gap G3 for materialized executions: all five definitions are
re-hashed at materialization, and the resulting manifest binds them.

### 3.2 Canonical definition bytes

Each definition is serialized with the existing semantic boundary:

```text
validated Pydantic definition
    -> semantic_representation
    -> canonical_semantic_bytes (RFC 8785)
    -> SHA-256 = SemanticDigest
    -> stored as canonical UTF-8 JSON bytes
```

The stored bytes are exactly `canonical_semantic_bytes(definition)`. There is no second
serializer, no YAML, no pretty-printing, and no per-run metadata. The store object key is
the semantic digest hex. The manifest records the semantic digest and byte size; a reader
can recompute both.

A definition is stored once per semantic digest. Two authorings that validate to the same
meaning share one object, even if their YAML differed.

### 3.3 Asset enumeration and bounds

Assets are enumerated from `RealizationDefinition.assets[]`. In the accepted reference
case there is one model asset. For a general realization:

| Bound | Proposed value | Rationale |
|---|---|---|
| Maximum assets per realization | 64 | A scientific realization is a small set of model/data files; 64 is generous and bounded |
| Maximum bytes per asset | 256 MiB | Large enough for a mesh/model bundle, small enough to bound copy time and disk |
| Maximum total asset bytes per execution | 1 GiB | Prevents one run from filling the evidence/cache volume |
| Maximum path length | existing `WorkspaceRelativePath` max 1024 | Reuses the accepted path language |
| Maximum path segments | 32 | Bounds nesting and directory traversal work |
| Maximum definition bytes | existing `MAX_AUTHORING_DOCUMENT_BYTES` 8 MiB | Reuses the accepted authoring bound |
| Maximum manifest bytes | 8 MiB | Hundreds of entries at most |
| Maximum native artifact bytes | proposed 64 MiB for the reference case; per-adapter bound | The 2 s, 1 kHz pendulum is ~48 KiB; 64 MiB is three orders of magnitude of headroom |
| Maximum native samples | proposed 1,000,000 | Bounds row count and memory |
| Maximum native descriptor bytes | 1 MiB | Metadata only |

Every bound is checked against bytes actually read, not only against a `stat`, so a file
that grows during the read is still refused.

Asset path rules:

* The path is a `WorkspaceRelativePath`, already relative, `/`-separated, no `.`/`..`,
  no drive, no UNC, no device namespace, no `:`, no trailing dot/space, no reserved name.
* The resolved source path must be inside the source root.
* The source entry must be a regular file, not a symlink, junction, reparse point, socket,
  FIFO, or device. A hard-linked source file is accepted only if the bytes are copied and
  the copy is verified; the copy has one link. If the owner wants source hardlinks refused
  outright, that is a stricter policy and is compatible with this design.
* The asset's declared `sha256` is required. `None` is refused before copying.
* The asset is copied to a new temporary file. The **copy** is hashed and compared to the
  declared digest. The source is never hashed and then reopened as the authoritative
  object; the copy is the snapshot.

### 3.4 Association of asset digests with owning definitions

Each asset entry records both:

```text
owner:
  kind: realization
  identifier: rl.mujoco.reference-pendulum
  version: 1.0.0
  semantic_digest: { algorithm: sha256, hex: ... }
asset_id: reference-model
logical_path: models/reference/pendulum.xml
declared_sha256: <64 hex>
observed_sha256: <64 hex>   # must equal declared
size_bytes: <int>
object: sha256/<64 hex>     # store-relative, not a machine path
```

The `owner.semantic_digest` is the digest of the definition that declared the asset. This
makes the association explicit and prevents an asset from being reattached to a different
realization without changing the manifest.

If two definitions declare the same asset bytes under different logical paths, both
entries point to one store object. That is duplicate content, not duplicate meaning.

### 3.5 Atomic publication

The store is content-addressed and append-only in normal operation:

```text
<store-root>/
  objects/sha256/<64 hex>        # immutable object bytes
  manifests/<64 hex>.json        # canonical InputManifest bytes
  tmp/                           # private, never authoritative
```

Publication of one object:

1. Create a temporary file in `tmp/` with an exclusive, unpredictable name.
2. Write the complete bytes.
3. Flush the file. On POSIX, `fsync` the file; on Windows, `FlushFileBuffers`.
4. Hash the temporary file from its open handle; compare to the expected digest and size.
5. If the final object path already exists, verify its size and digest.
   * Same content: discard the temporary and reuse the object.
   * Different content or corrupt object: refuse; do not overwrite; mark the object
     unhealthy and preserve it for diagnosis.
6. Otherwise `os.replace(temp, objects/sha256/<hex>)` on the same volume. This is the
   atomic publication point.
7. On POSIX, `fsync` the parent directory. On Windows, directory fsync is not available
   through the standard library; document the weaker durability boundary and rely on the
   post-publication verification.

A reader never sees a partially written object: it sees either no object or a complete
object. A power loss can leave a temporary file, never a partially published final name.
Temporary files are cleaned by an explicit maintenance action, not by a run that is trying
to seal evidence.

### 3.6 Duplicate content and collisions

| Case | Behavior |
|---|---|
| Same digest, same bytes, object exists | Reuse; no copy; manifest records one object |
| Same digest, object missing | Publish from the verified temporary |
| Same digest, existing object has different size | Refuse; inconsistent object; do not overwrite |
| Same digest, existing object has different bytes | Refuse; collision or corruption; quarantine/report; never overwrite |
| Different digest, same logical path | Both objects may exist; the manifest decides which one the execution uses |
| Two concurrent publishers of the same digest | Both write private temporaries; one wins the replace; both verify the resulting object; both may proceed |
| Two concurrent publishers of the same logical path with different bytes | They are different executions or a source mutation; each manifest records its own digest; admission decides which is admitted; the other is refused |

SHA-256 collision resistance is assumed. The design does not pretend to detect a true
collision; it detects inconsistent existing objects, which is the practical failure mode.

### 3.7 Materialization manifest (candidate schema)

```yaml
schema_version: dynamisbench.execution-input-manifest/1
execution_refs:
  benchmark:        { identifier, version, semantic_digest }
  scenario:         { identifier, version, semantic_digest }
  realization:      { identifier, version, semantic_digest }
  system_under_test:{ identifier, version, semantic_digest }
  environment:      { identifier, version, semantic_digest }
definitions:
  - kind: benchmark | scenario | realization | system_under_test | environment
    identifier: <string>
    version: <string>
    semantic_digest: { algorithm: sha256, hex: <64> }
    size_bytes: <int>
    object: sha256/<64>
assets:
  - owner: { kind, identifier, version, semantic_digest }
    asset_id: <Name>
    logical_path: <workspace-relative path>
    declared_sha256: <64>
    observed_sha256: <64>
    size_bytes: <int>
    media_type: <bounded token, optional>
    object: sha256/<64>
limits:
  max_assets: <int>
  max_bytes_per_asset: <int>
  max_total_bytes: <int>
  max_native_bytes: <int>
  max_native_samples: <int>
```

Properties:

* No `run_id`, timestamp, host, user, root, absolute path, store path, or pid.
* Arrays are in canonical order: definitions by `(kind, identifier, version)`, assets by
  `(owner.kind, owner.identifier, owner.version, asset_id)`.
* The manifest is serialized with `canonical_semantic_bytes` and hashed with SHA-256.
* `InputManifestDigest` is the SHA-256 of those canonical bytes.
* The manifest is stored as `manifests/<digest>.json`; it is not embedded in the RunSpec
  under the recommended option.

### 3.8 Admission binding (candidate schema)

The run-specific record is written only after preflight and before worker launch:

```yaml
schema_version: dynamisbench.admission-binding/1
run_id: <RunId>
execution_fingerprint: { algorithm: sha256, hex: <64> }
input_manifest_digest: { algorithm: sha256, hex: <64> }
request_digest: { algorithm: sha256, hex: <64> }
preflight_digest: { algorithm: sha256, hex: <64> }
environment_manifest_digest: { algorithm: sha256, hex: <64> }
worker_program:
  identity: <bounded program identity or path-free label>
  argument_count: <int>
containment_mode: verified-content | os-enforced
materialization_store: cache/inputs   # logical class, not an absolute path
input_manifest_object: manifests/<64>.json
```

This record is operational. It is persisted in the staging bundle as `preflight.json` (or
`inputs.json`) and is hashed as payload at seal time. It is not part of the RunSpec and
does not change the fingerprint. It may contain the run id and the logical store class; it
must not contain an absolute path.

### 3.9 Retention, GC, and sealed evidence

Recommended policy:

* The materialization store is classified as `CACHE` (mutable, disposable). It is a
  performance and deduplication layer, not scientific authority.
* At seal time, the exact definitions and assets used by the run are copied into the
  sealed bundle under `inputs/`:

```text
runs/<run-id>/
  inputs/
    manifest.json
    definitions/<kind>/<identifier>/<version>.json
    assets/<asset_id>/<basename>
  native/
  diagnostics.json
  logs/
  manifest.json
  checksums.sha256
```

* `inputs/manifest.json` is the canonical `InputManifest`. The copied definition and asset
  bytes are verified against it during sealing.
* The sealed bundle remains self-contained. Deleting the cache does not destroy evidence.
* Cache GC may delete objects not referenced by any active staging bundle after a
  retention window. It must never delete a sealed bundle's `inputs/`.
* Because sealed bundles are self-contained, there is no cross-bundle reference counting
  problem. The cost is duplicate bytes per run; for the current reference case this is
  trivial, and for larger models it is a deliberate scientific-integrity cost.

Alternative (not recommended for v1): keep the store authoritative and have sealed
evidence reference it. That requires a new persistence class, reference-aware GC, and a
rule that sealed evidence is not self-contained. It is decision D9.

### 3.10 Concurrency

* Two runs materializing the same content share objects; publication is atomic and
  verified after the race.
* Each run has a unique `run_id`; staging creation uses an exclusive create and refuses an
  existing directory or sealed run.
* The store has no shared mutable index. Manifests are immutable once published.
* A per-digest in-process lock may reduce duplicate work, but correctness does not depend
  on it; `os.replace` and post-publication verification are the cross-process mechanism.
* A GC process must not delete an object between a manifest read and the run's copy. The
  run copies objects into its own staging before launch; if an object disappears, the run
  refuses rather than launching with a missing input. A generation/lease file is an
  optional optimization, not a correctness requirement.
* No lock service, database, or scheduler is introduced.

### 3.11 Refusal behavior

Materialization fails closed. Proposed new refusal codes (not implemented; additions are a
visible v2 protocol change):

```text
INPUT_MANIFEST_MISMATCH
INPUT_DEFINITION_MISMATCH
INPUT_OBJECT_MISSING
INPUT_OBJECT_CORRUPT
INPUT_LIMIT_EXCEEDED
INPUT_LINK_REFUSED
INPUT_SOURCE_CHANGED
INPUT_SET_INCOMPLETE
INPUT_SET_UNEXPECTED
```

Existing codes remain where they fit (`FORBIDDEN_PATH`, `UNSTAGED_ASSET`,
`ASSET_DIGEST_MISMATCH`, `DUPLICATE_EXECUTION`). A refusal carries the existing bounded
`Refusal` shape: code + supervisor-authored message, no absolute path, no rejected value.

### 3.12 Backward compatibility

* Existing sealed bundles remain valid and verifiable. They do not contain `inputs/`; the
  verifier must not require it for historical bundles.
* Existing `RunSpec` 0.1.0 bytes and fingerprints remain valid historical identities.
* New materialized executions use `InputManifest` and, if approved, protocol v2. They do
  not silently reinterpret v1.
* A v2 supervisor must refuse a v1 worker and vice versa; a v1 supervisor must not accept a
  v2 request.
* A manifest schema change is a new schema version, not an optional field.
* The sealed manifest schema remains version 1 unless a native verification field is
  added; the recommended design keeps native verification as a payload file, so the
  sealed manifest schema does not change.

### 3.13 Schema contract summary

| Schema | Owner / trust boundary | Version | Required fields | Digest | Canonical serialization | Bounds | Lifecycle | Validation / refusal | Backward compatibility |
|---|---|---|---|---|---|---|---|---|---|
| `InputManifest` | `execution` / supervisor; materializer writes, preflight/admission reads | `dynamisbench.execution-input-manifest/1` | `schema_version`, `execution_refs`, `definitions`, `assets`, `limits` | `InputManifestDigest` = SHA-256 of canonical bytes | RFC 8785 via `canonical_semantic_bytes` | 5 definitions; ≤64 assets; ≤1 GiB total; ≤8 MiB manifest | Derived per admitted execution; immutable once published | Refuse unknown/missing fields, duplicate keys, duplicate paths, digest/size mismatch, disallowed paths, over-bound content | New schema version for any semantic change; v1 readers refuse v2 |
| `AdmissionBinding` | `execution` / supervisor; written to staging, read by supervisor/evidence | `dynamisbench.admission-binding/1` | `run_id`, `execution_fingerprint`, `input_manifest_digest`, `request_digest`, `preflight_digest`, `environment_manifest_digest`, `worker_program`, `containment_mode`, `materialization_store`, `input_manifest_object` | SHA-256 of canonical bytes (recorded as payload digest at seal) | RFC 8785 via `canonical_semantic_bytes` | ≤1 MiB | Created after preflight, before launch; immutable for the run | Refuse if any binding differs from the recomputed admission tuple; no absolute paths | New schema version for field changes; v1 readers refuse v2 |
| `NativeDescriptor` | adapter / worker produces; supervisor verifies; evidence seals | `dynamisbench.native.mujoco-state/1` | `schema_id`, `producer`, `binding`, `simulation`, `time`, `state`, `files`, `limits`, `claim` | `NativeArtifactDigest` = SHA-256 of canonical descriptor bytes; per-file `AssetDigest` | RFC 8785 via `canonical_semantic_bytes` | ≤1 MiB descriptor; ≤64 MiB artifact; ≤1,000,000 samples; ≤8 files | Created per run in worker scratch; verified; copied to staging; sealed | Refuse unknown/missing fields, non-canonical bytes, binding mismatch, file-set mismatch, link/hardlink, digest/size mismatch, non-finite/non-monotonic values, over-bound | New schema id/version per adapter/engine; a different engine must not reuse the MuJoCo schema |
| `NativeVerification` | supervisor only; evidence seals | `dynamisbench.native.verification/1` | `schema_id`, `run_id`, `execution_fingerprint`, `input_manifest_digest`, `descriptor_sha256`, `checks`, `verdict`, `verifier` | SHA-256 of canonical bytes (payload digest at seal) | RFC 8785 via `canonical_semantic_bytes` | ≤1 MiB; ≤64 checks | Created after native verification; never rewritten after seal | Refuse a `SUCCEEDED` seal unless every check passed and the verdict is `verified`; refuse a `verified` verdict with any failed check | New schema version for check-set changes; historical records remain valid |

`NativeVerification.verdict` is `verified` or `refused`. It is not a scientific verdict and
does not imply numerical correctness. `checks` is a bounded list of
`{name, passed, observed, limit}` records, with no absolute paths and no raw artifact
content.

---

## 4. Worker-input containment and immutability

### 4.1 The trust transition

```text
Mutable source authority
    │  read source; copy to private temporary
    ▼
Verified content-addressed snapshot
    │  hash the copy; compare declared digest; publish atomically
    ▼
Authoritative input manifest
    │  canonical bytes; InputManifestDigest; admission binding
    ▼
Per-run input view
    │  copy/link only the manifest objects into the run's private input root
    ▼
Worker-readable execution inputs
    │  relative paths only; hash at open; parse from verified bytes
    ▼
Native engine
```

The last moment mutable source content is trusted is **the start of the copy**. The copy,
not the source, becomes authoritative when its hash matches the declared digest and it is
published. From that point, source-root changes cannot affect the admitted execution; they
can only cause a future materialization to produce a different manifest or to be refused.

### 4.2 Per-run input view

The supervisor creates the existing per-run scratch directory and adds:

```text
<scratch>/
  inputs/
    manifest.json
    definitions/...
    assets/...
  native-out/          # worker writes here; supervisor publishes from here
```

The worker receives:

* cwd = `<scratch>`;
* no absolute path in the request;
* a relative convention: `inputs/manifest.json`, `inputs/assets/...`;
* no `PATH`, `PYTHONPATH`, or loader variables (existing environment rules);
* `-I` isolated Python mode (existing worker command may be extended with v2 arguments,
  but no shell).

The worker resolves only relative paths under `inputs/`. It must reject:

* absolute paths, drive letters, UNC, device namespaces;
* `.`/`..` segments, empty segments, backslashes used as separators;
* symlinks, junctions, reparse points, hard-linked files;
* files not listed in `inputs/manifest.json`;
* files whose size or digest differs from the manifest;
* model includes that resolve outside `inputs/` (MJCF `file=`/`meshdir=`/`texturedir=`
  traversal).

For the reference case the model is self-contained XML, so the worker reads the XML bytes
from `inputs/assets/reference-model/...`, hashes them, and calls
`mujoco.MjModel.from_xml_string(xml)`. It never calls `from_xml_path` on an unverified
path. For future multi-file MJCF, the adapter must implement a verified asset resolver that
maps every include to a manifest object and rejects anything else; that is future work.

### 4.3 Integrity checks at each boundary

| Boundary | Check | Actor | Failure |
|---|---|---|---|
| Materialization copy | Copy bytes; hash copy; compare declared digest and size | Supervisor | Refuse; no manifest |
| Store publication | Existing object size/digest; atomic replace; post-publish verify | Supervisor | Refuse; no admission |
| Admission binding | Recompute manifest from RunSpec + definitions; compare digest; compare request | Supervisor | Refuse; no staging |
| Staging input copy | Copy from store; hash each copy; compare manifest | Supervisor | Refuse; no worker |
| Immediately before launch | Re-hash `inputs/manifest.json` and every input file; compare admission; run worker `--identity` probe and compare implementation digest | Supervisor | Refuse; no process |
| Worker open | Open relative path; `fstat`; read all bytes; hash; compare manifest; parse from bytes | Worker | `FAILED` response; no physics |
| Worker before first physics step | Verify model structure and solver settings against the reviewed reference (existing `_verify_model`) | Worker | `FAILED` response |
| After worker exit | Re-hash every input file; compare admission; verify native output | Supervisor | `FAILED`; no successful seal |
| Seal | Hash every input/native payload; manifest/checksum verify | Evidence | Refuse promotion |

### 4.4 Can a malicious worker modify its own inputs?

Under `verified-content` (same OS user): **yes, it can**. The design detects:

* a change visible at the post-run re-hash;
* a change that alters the bytes the worker loads, because the worker hashes before
  loading;
* a substitution of a file that is not listed, because the file set is checked.

It does **not** detect a worker that modifies an input, uses the modified bytes, and
restores the original before the post-run check. It also cannot prevent a worker from
reading files outside `inputs/`. Those are OS-boundary problems, not file-hash problems.

Under `os-enforced` (separate identity/sandbox/read-only mapping): a worker cannot write
the input view, and reads outside the view are denied. That mode is not available in the
accepted baseline and is not claimed.

### 4.5 What "immutable" may mean in the acceptance record

The acceptance record must use one of these phrases, never an unqualified "immutable":

* **Content-verified input snapshot** — the exact bytes were verified at materialization,
  launch, worker read, and post-run; mutation is detected; same-user containment is not
  enforced.
* **OS-enforced read-only input view** — the worker cannot write the input view and cannot
  read outside it; requires the provisioned OS boundary and a probe record.

If RES-555's acceptance criterion requires the second, the first cannot satisfy it. That
is decision D3.

---

## 5. Windows/Linux threat model

### 5.1 Threat actors and assumptions

| Actor | Capability | In scope? |
|---|---|---|
| Accidental user/process | Edits, moves, truncates, or replaces a source file; runs two jobs at once | Yes |
| Defective adapter | Reads the wrong path, ignores a digest, writes a partial artifact | Yes |
| Malformed scientific asset | Huge, deeply nested, invalid XML, includes, device names | Yes |
| Untrusted MJCF document | Parser input; may contain includes, absolute paths, entities | Yes |
| Same-user malicious worker | Can read/write anything the user can; can lie in IPC | **Detection only** under `verified-content`; OS-enforced only under `os-enforced` |
| Different-user attacker | Cannot write the user's files unless ACLs allow it | Out of scope for this gate; OS permissions apply |
| Administrator/root | Can do anything | Out of scope; not a security boundary |
| Network attacker | No network channel in the worker | Out of scope; no network introduced |

### 5.2 Attack classes and platform behavior

| # | Attack class | Windows behavior | Linux behavior | Defensive primitive | Privilege | Availability | Residual race | Verification test | Supported claim |
|---|---|---|---|---|---|---|---|---|---|
| T1 | Absolute path, drive, UNC, device namespace in a logical reference | `C:\`, `\\server\share`, `\\?\`, `\\.\` are absolute/device forms | `/`, `//`, `\` are absolute or separator tricks | `WorkspaceRelativePath` + `validate_logical_reference`; reject drive, root, UNC/device prefix, `:` | None | Python stdlib, both platforms | None at the lexical gate | Parametrized path tests on both OS | Request-path containment |
| T2 | `..`, `.`, empty segment, separator ambiguity | Backslash and slash are separators; `.. ` normalizes | `/` only; backslash is a name character | Split on both separators; reject `.`/`..`/empty; reject trailing dot/space; canonical `/` | None | stdlib | None at the lexical gate | `test_paths.py`, property tests | Request-path containment |
| T3 | Symlink/junction/reparse escape | `Path.resolve` follows; `is_junction` detects junctions; `FILE_ATTRIBUTE_REPARSE_POINT` detects others | `Path.resolve` follows; `O_NOFOLLOW`/`openat2` can refuse | Resolve both location and result; `is_relative_to`; reject any link in the input view; `lstat` per component | None / `openat2` unprivileged | `pathlib` both; `openat2` Linux ≥5.6 | Parent directory can be swapped between resolve and open | Junction/symlink tests on both OS | No link escape at checked names; read via handle under `os-enforced` |
| T4 | Hardlink alias | `st_nlink > 1`; `GetFileInformationByHandle` | `st_nlink > 1`; `fstat` | Sealed bundle rejects hardlinks; input copies are new files; worker input view rejects hardlinked files | None | stdlib | A hardlink created after the check | `test_verification.py` hardlink test; input-view test | Self-contained evidence; no known alias |
| T5 | ADS / reserved names / trailing dot-space | `:` is ADS; `CON`, `NUL`, `COM1`; trailing dot/space stripped | `:` and reserved names are ordinary names | `validate_logical_reference` rejects `:`, device names, trailing dot/space; canonical names only | None | stdlib | None at lexical gate | `test_paths.py` | Portable naming |
| T6 | Case alias | NTFS case-insensitive, case-preserving | ext4 case-sensitive | Run IDs lower-case; manifest names reject case-insensitive duplicates; `keyed_by` exact; containment uses platform case rules | None | stdlib | A case-only duplicate created after validation | Case-collision test on Windows and Linux | No case alias in one manifest |
| T7 | Unicode normalization / lookalike | NTFS stores UTF-16; no normalization; lookalikes possible | UTF-8 bytes; no normalization | Require NFC for manifest names; reject names that change under NFC/NFD; reject case-fold duplicates; consider confusable check | None | Python `unicodedata` | A lookalike that is canonically distinct remains distinct; not a security boundary | Unicode collision tests | Canonical spelling; no normalization alias |
| T8 | Cross-volume / mount point | Junction/mount point; volume serial | `st_dev`; bind mount | Resolve and verify the opened object's volume/device equals the input root's; reject a different volume | None | `st_dev` both; volume serial via Win32 | Mount point added after check | Cross-volume test with a junction/symlink to another temp volume if available | Input root stays on one volume |
| T9 | Rename/replacement race | `CreateFileW` share mode; file ID | `openat2`/`O_NOFOLLOW`; `fstat` | Open first, then verify identity; read from the handle; compare file ID/size/digest | None | Python `open`; stronger with Win32/`openat2` | Parent rename before open; handle identity still points to a real object | Race test with a thread replacing the path | Read bytes are from the verified object |
| T10 | Change between hash and open | Same-user can replace | Same-user can replace | Hash the same handle used to read/parse; never hash a path then reopen it | None | stdlib | Same-user can replace before open; hash catches wrong bytes | Corrupt-between-hash-and-open test | Content binding at read |
| T11 | Replacement after materialization | Same-user can replace | Same-user can replace | Launch re-hash; worker read hash; post-run re-hash; seal hash | None | stdlib | Replace-and-restore before post-run check is not detected | Mutation-before-launch and mutation-after-run tests | Mutation detection, not immutability |
| T12 | Worker reads outside root | Same-user can open any readable path | Same-user can open any readable path | Request carries no absolute path; adapter rejects absolute/includes; `os-enforced` sandbox if available | None; sandbox needs provisioning | No portable unprivileged read sandbox | Same-user can ignore the convention | Instrumented worker attempts; OS sandbox test if provisioned | Logical containment; OS containment only in `os-enforced` |
| T13 | Malformed/oversized/nested asset | Parser may allocate; XML entities | Same | Count/size/depth bounds; regular file only; no archives; parse in worker; engine pinned | None | stdlib + MuJoCo | A parser vulnerability remains a parser vulnerability | Oversized, deeply nested, invalid XML, include traversal tests | Bounded input; no parser safety claim |
| T14 | Concurrent workspace mutation | Two processes write | Two processes write | Unique run id; exclusive staging; atomic store publish; post-publication verify; no shared mutable index | None | stdlib | GC can race; use lease/generation or no automatic GC | Concurrent publication and duplicate-run tests | No corruption under concurrent publication |
| T15 | Failed worker partial artifacts | Worker writes scratch | Worker writes scratch | Worker writes only `native-out/`; supervisor requires a complete manifest and exact file set; partial output refused | None | stdlib | Worker can write arbitrary scratch; supervisor validates after exit | Crash after partial write; missing manifest; extra file; truncated file | Partial output never sealed as success |
| T16 | Compromised adapter | Can forge response/artifacts | Same | Implementation digest, pinned source, engine version, process tree; external expected digest if available | None | Existing | Compromised worker can forge a consistent bundle | Adversarial worker substitution tests | Integrity/consistency, not authenticity |

### 5.3 Platform protection matrix

The following table is the **claim matrix**. It distinguishes what the design can require
from what the current baseline can prove.

| Threat | Defensive primitive | Required privilege | Availability | Residual race | Verification test | Supported security claim |
|---|---|---|---|---|---|---|
| Path traversal / absolute / UNC / device | Lexical reference gate | None | Python stdlib, both | None at gate | Parametrized paths | Request-path containment |
| Symlink/junction escape | Resolve + containment; reject links in input view | None | Python stdlib, both | Parent swap | Junction/symlink tests | No escape through a checked name |
| Hardlink alias | `st_nlink`; new copies | None | Python stdlib, both | Post-check link | Hardlink tests | No known alias in sealed bundle |
| Case/Unicode alias | Lower-case IDs; NFC; case-fold duplicate rejection | None | Python stdlib, both | Lookalikes remain | Collision tests | Canonical manifest names |
| Cross-volume | `st_dev` / volume serial | None | Python + Win32 | Mount after check | Cross-volume test | Input root on one volume |
| Hash/open race | Hash the open handle, parse from bytes | None | Python stdlib, both | Same-user replace before open | Race test | Read bytes match digest |
| Replace after materialization | Launch/read/post-run re-hash | None | Python stdlib, both | Replace-and-restore | Mutation tests | Mutation detection |
| Worker write to inputs | Read-only mapping / ACL / separate identity | Admin/root or sandbox provisioning | **Not in baseline**; Linux userns/mount, Windows AppContainer/restricted token | Same-user owner can change ACL | Provisioned probe | OS-enforced immutability **only if provisioned** |
| Worker read outside root | AppContainer/mount namespace/Landlock | Provisioning | **Not in baseline**; Linux Landlock ≥5.13/userns; Windows AppContainer | Kernel/API gaps | Provisioned probe | OS-enforced read containment **only if provisioned** |
| Worker process escape | Job Object / session-process group | None | Windows Job Object; POSIX `killpg` | `setsid`/job breakaway | Descendant cleanup tests | Owned process tree only |
| Partial native output | Supervisor-owned publication; exact file set | None | Python stdlib, both | Worker can forge a complete set | Partial/crash tests | Partial output refused |
| Forged native artifact | Binding + verification; external expected digest | None / future signature | Existing | Compromised worker can forge | Substitution tests | Consistency, not authenticity |
| Source replacement during copy | Copy-then-hash | None | Python stdlib, both | Source can change mid-copy; digest mismatch | Concurrent mutation test | Snapshot matches declared digest |
| Package/editable source change | Implementation identity; launch `--identity` probe | None | Python stdlib, both | Code already imported before hash | Identity mismatch test | Bounded residual; not a sealed snapshot |

### 5.4 What is not claimed

* No claim that `chmod`, `FILE_ATTRIBUTE_READONLY`, an ACL, a private cwd, a stripped
  environment, or path normalization makes an input immutable.
* No claim that a same-user worker cannot read outside its input root.
* No claim that a compromised worker cannot forge a self-consistent native artifact.
* No claim that a Windows Job Object restricts file access.
* No claim that GitHub-hosted runner privilege (administrator/sudo) represents an ordinary
  product user.
* No claim that a Linux user namespace, Landlock, or `openat2` is available until the target
  job probes it.

### 5.5 Assurance levels

| Level | Name | What it establishes | What it does not establish | Current status |
|---|---|---|---|---|
| A0 | Operational integrity | The app can detect ordinary corruption, stale files, duplicate run ids, and partial writes | Adversarial substitution or same-user immutability | Accepted baseline |
| A1 | Content-verified inputs | The exact bytes were verified at materialization, launch, worker read, and post-run; mutation/substitution is detected; the worker loads only manifest-listed bytes | A same-user worker cannot modify/read outside; a compromised worker cannot forge | Proposed for DB-3.3B (`verified-content`) |
| A2 | OS-enforced containment | A separate identity/sandbox/read-only mapping denies worker writes to inputs and reads outside the input view | Authenticity of a compromised worker's output; scientific validity | Not implemented; requires D3 option B |
| A3 | Cryptographic provenance | An external expected digest/signature binds the output to a trusted producer | Scientific validity | Future; not in RES-555 |

Every acceptance record must name the level. A1 is not A2. A sealed artifact is not A3.

### 5.6 Candidate OS-enforced mode (not authorized, not implemented)

This subsection exists so decision D3 option B is reviewable. It is **not** a claim that
these mechanisms are available on the supported targets. Each must be probed in the target
job and recorded.

| Mechanism | Platform | Required privilege | Availability to verify | Residual | Claim if it passes |
|---|---|---|---|---|---|
| Dedicated standard user for the worker; supervisor-owned input root ACL denies write to that user | Windows | Administrator to create the account and set ACLs | `CreateProcessWithLogonW` / `CreateProcessAsUser`; account provisioning | Supervisor/owner can still change ACLs; account lifecycle; desktop product prerequisite | Worker cannot write inputs under its own identity; process runs as a different principal |
| AppContainer with a capability SID limited to the input root | Windows | Administrator to create the profile; `CreateAppContainerProfile` | Win32 API; not Python stdlib; would need a reviewed native/Rust helper | AppContainer compatibility with Python/MuJoCo; filesystem virtualization; profile cleanup | Worker reads only brokered paths; writes denied outside its container |
| Restricted token / job object | Windows | None for a restricted token; job object already used | `CreateRestrictedToken`; job object does not restrict file reads | File ACLs still govern access; a restricted token is not a filesystem sandbox by itself | Process-tree containment only; not a read/write claim |
| User namespace + mount namespace with read-only bind mount of `inputs/` | Linux | Unprivileged user namespaces if enabled; otherwise root/CAP_SYS_ADMIN | `unshare` with `CLONE_NEWUSER` and `CLONE_NEWNS`; `mount` with `MS_BIND` and `MS_RDONLY`; `pivot_root`; probe needed | Ubuntu AppArmor restrictions; kernel config; nested containers | Worker sees a read-only input view and no host paths |
| Landlock ruleset restricting read/write to the input view | Linux | Unprivileged | Landlock ABI ≥1, kernel ≥5.13; `landlock_create_ruleset`/`add_rule`/`restrict_self` via ctypes | ABI feature gaps; path-beneath rules; no Windows equivalent | Worker FS access restricted to the ruleset; deny outside |
| `openat2` with `RESOLVE_BENEATH`, `RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_MAGICLINKS` | Linux | Unprivileged | Kernel ≥5.6; syscall via ctypes | Parent rename before open; fd identity still needed | No symlink/beneath escape on the opened path |
| `NtCreateFile` with `OBJECT_ATTRIBUTES.RootDirectory` and `FILE_OPEN_REPARSE_POINT` | Windows | Unprivileged (ntdll) | Not exposed by Python stdlib; ctypes/native helper; security review required | Handle inheritance/lifetime; ntdll ABI stability | Handle-relative open below a verified root handle |
| Read-only filesystem / `chattr +i` | Linux | `chattr +i` needs CAP_LINUX_IMMUTABLE; read-only mount needs mount privilege | Varies | Owner/root can change; not portable | Only if provisioned and probed; not a default claim |

A candidate `os-enforced` design would use:

* Windows: a dedicated worker principal plus a supervisor-owned input root whose ACL denies
  write to that principal; open files with `CreateFileW` (`FILE_SHARE_READ`,
  `FILE_FLAG_OPEN_REPARSE_POINT` where applicable), verify `GetFinalPathNameByHandleW` and
  `FILE_ID_INFO`, and optionally AppContainer for read restriction. This requires
  provisioning and a reviewed native helper; it is not a Python-stdlib-only change.
* Linux: `unshare(CLONE_NEWUSER|CLONE_NEWNS)`, bind-mount `inputs/` read-only, `pivot_root`,
  then `openat2` + `fstat` inside the namespace; or Landlock for read/write restriction if
  the kernel ABI is available. This can be unprivileged only when user namespaces are
  enabled; otherwise it requires root/provisioning.

If the probe fails, `containment_mode: os-enforced` must not be recorded, and no claim may
depend on it. The implementation must fall back to `verified-content` **only if the owner
has approved that fallback**; it must not silently downgrade a security claim.

---

## 6. Source-asset TOCTOU closure strategy

### 6.1 The exact trust transition

| Moment | State | Trusted actor | Evidence |
|---|---|---|---|
| M0 | Source authority is mutable and version-controlled | Repository / owner | Git commit, source file |
| M1 | Materializer opens a source asset and copies it to a private temporary | Supervisor | Temporary file; source path is not yet authoritative |
| M2 | The **copy** is hashed and compared to the declared digest | Supervisor | `observed_sha256 == declared_sha256` |
| M3 | The object is atomically published under its digest | Supervisor | `objects/sha256/<hex>` complete and verified |
| M4 | The canonical input manifest is published | Supervisor | `manifests/<digest>.json` |
| M5 | The admission binding is written | Supervisor | `preflight.json` / `inputs.json` in staging |
| M6 | The per-run input view is copied and verified | Supervisor | `inputs/` complete |
| M7 | The worker opens, hashes, and loads the bytes | Worker | Read-time verification in the worker |
| M8 | The worker exits; the supervisor re-hashes the input view | Supervisor | Post-run verification record |
| M9 | The seal hashes the payload and promotes the bundle | Evidence | `manifest.json`, `checksums.sha256` |

The mutable source is trusted **only until M1**. After M2, the copy is the authority. After
M3/M4, the store and manifest are the authority. After M6, the per-run view is the
authority. The source root is never read again for that execution.

### 6.2 Concurrent source replacement

The materializer does not `stat` then open then trust the path. It:

1. Opens the source and copies bytes to a new temporary.
2. Closes the source.
3. Hashes the temporary.
4. Compares to the declared digest and size.
5. If the source changed during the copy, the temporary digest will differ from the
   declared digest; the materialization is refused. There is no retry inside the same
   admission. The operator may start a new admission, which will read the new source and
   either produce a new manifest or fail again.
6. If the source is replaced after the copy but before publication, the temporary is
   unaffected. The published object is the copied bytes.
7. If the source is replaced after publication, the admitted execution is unaffected; the
   store object is immutable. A future execution will materialize the new bytes and get a
   different manifest, or be refused if the declaration did not change.

### 6.3 Incomplete copies and power loss

* A temporary file is never authoritative and is never enumerated by the manifest.
* A power loss during the copy leaves a temporary; the store has no final object for that
  digest unless a previous publication exists.
* A power loss during `os.replace` leaves either the old object (if any) or the new object;
  the final name is never a partial file on a local filesystem.
* A power loss after publication but before the manifest leaves an unreferenced object.
  It is harmless; GC may collect it later.
* A power loss after manifest publication but before admission leaves an unreferenced
  manifest. It is harmless; it is not evidence.
* A power loss during the seal is handled by the existing staging→seal transaction: the
  staging bundle remains, `runs/<run-id>` is absent, and recovery classifies the staging
  directory. Native publication must use the same atomic discipline.

### 6.4 Relationship between source digest and materialized bytes

The manifest records both `declared_sha256` (from the definition) and `observed_sha256`
(from the copy). They must be equal. The store object key is the observed digest. The
definition's semantic digest includes the declared digest and the logical path, so a
change to either changes the realization identity. The materialized bytes are therefore
bound twice: by the definition's semantic digest and by the manifest's observed digest.

If the owner chooses to keep `AssetReference.sha256` optional, a materialized execution
must refuse an asset without a declared digest. This is already the preflight behavior;
the design makes it a materialization precondition and a domain requirement for the
materialized path.

### 6.5 Integrity checks at worker launch and before model loading

**At launch (supervisor):**

* Recompute the `InputManifest` from the RunSpec and the exact definitions; compare to the
  admitted digest.
* Re-hash `inputs/manifest.json` and every input file; compare to the manifest.
* Re-hash the worker program and run the worker's `--identity` command; compare the
  implementation digest to the request adapter identity.
* Re-check the environment definition, adapter engine/version, capability set, timeout,
  and log bound.
* Re-check that the run id has no staging or sealed directory.
* If any check fails: no process is started; the run is `REFUSED`; no successful seal.

**Immediately before model loading (worker):**

* Read `inputs/manifest.json`; validate schema and canonicality.
* Verify the requested run id, execution fingerprint, input manifest digest, adapter
  identity, engine version, and model SHA-256 against the manifest and request.
* For each file the adapter will open: relative path under `inputs/`; `lstat` regular file;
  no link/reparse/hardlink; size and SHA-256 match the manifest.
* Read the model bytes into memory; hash those exact bytes; parse from the bytes, not from
  the path.
* Verify the model structure and solver settings against the reviewed reference (existing
  `_verify_model`).
* If any check fails: a protocol-valid `FAILED` response; no physics step; no native
  artifact.

### 6.6 If content changes during execution

The worker has already loaded verified bytes into memory, so a later change to the file
does not change the in-memory model. But the claim "the execution used the admitted input
set for its whole duration" is no longer provable. The supervisor therefore:

* re-hashes the input view after the worker exits;
* if any input changed, records `INPUT_CHANGED_DURING_EXECUTION`;
* refuses `SUCCEEDED` and seals `FAILED` (or leaves the staging bundle for diagnosis);
* never promotes a native artifact from that run as successful evidence.

A change that occurs and is restored before the post-run check is not detected under
`verified-content`. Only an OS-enforced read-only view closes that.

### 6.7 Can a malicious worker modify its own inputs?

Yes, under the same OS user. The design's answer is explicit:

* **Detection:** read-time hash, post-run hash, file-set check, admission record comparison.
* **Prevention:** only `os-enforced` with a separate identity/sandbox/read-only mapping.
* **Authenticity:** even `os-enforced` does not make a compromised worker's *output*
  authentic; an external expected digest or future attestation is required.

### 6.8 Conditions for input snapshot reuse

A materialized input set may be reused when:

* the `InputManifestDigest` is identical;
* every object in the manifest verifies (size + digest);
* the definitions' semantic digests match the RunSpec;
* the store object is not marked corrupt;
* the target execution's containment mode is recorded;
* the run id is new (never reuse a staging directory or sealed run id).

The store object may be shared by many runs. The per-run input view is never reused.

---

## 7. Native simulator evidence architecture

### 7.1 Authorization status

| Source | What it says | Consequence |
|---|---|---|
| A3 Evidence & Provenance | Native evidence is a first-class layer; run bundle layout includes `native/`; sealing requires complete files, schemas, manifest, checksums, atomic promotion | A native artifact is conceptually authorized |
| A2 Engine, SUT & Execution | Worker responsibilities include "emit native evidence" | A worker-side native output is conceptually expected |
| A8 RES-549 | Worker protocol v1: one request, one response, one exit; stdout one bounded JSON object; stderr diagnostics; no ambient control channel | v1 does **not** authorize a native artifact channel |
| A9 RES-550 | Adapter diagnostic on stderr is not native evidence; a later gate may promote a reviewed subset | RES-555 is that later gate, but it must define the contract |
| `evidence/bundle.py` | `ArtifactRole.NATIVE_EVIDENCE` exists; role is a hint, not a schema | The sealed manifest can label a native file, but cannot validate its contents |

Conclusion: the **layer** is authorized, the **channel and schema** are not. A versioned
extension is required. This is decision D4/D5.

### 7.2 Options compared

| Option | Isolation | Throughput | Size bound | Compatibility | Windows/Linux | Provenance | Verdict |
|---|---|---|---|---|---|---|---|
| A. Worker writes directly into `staging/native/` | Weak: worker writes evidence root | Good | Hard to bound during write | No protocol change, but violates staging ownership and worker isolation | Same-user writes | Worker-controlled | Reject |
| B. Supervisor-owned scratch, worker writes `native-out/`, supervisor validates and publishes into `staging/native/` | Good: worker cannot write evidence root; supervisor is sole publisher | Good for bounded artifacts | Post-hoc byte/sample bounds; optional size watchdog | v2 descriptor; no absolute path in request | Works on both with stdlib | Supervisor records what it published | **Recommend** |
| C. Dedicated IPC stream (pipe/fd) captured by supervisor | Strongest: supervisor writes every byte | Good for streaming | Byte-counted during transfer | New transport; Windows handle inheritance complexity | Feasible but more surface | Supervisor writes exactly the bytes | Future option |
| D. Extend response or stderr | No: response is bounded metadata; stderr is diagnostics | Poor for trajectories | 1 MiB response / 256 KiB stderr | Breaks v1 semantics | Existing | Ambiguous | Prohibited |

Option B is the smallest interface that keeps the worker out of the evidence root and
gives the supervisor a single publication point. It does not make a compromised worker
honest; it makes partial, missing, extra, malformed, or oversized output fail closed.

### 7.3 Recommended channel (candidate)

```text
Worker process
  cwd = <supervisor-owned scratch>
  reads  inputs/...
  writes native-out/
    descriptor.json          # must be written last, atomically
    state.parquet            # or another adapter-declared artifact

Supervisor after exit
  verifies native-out/ descriptor, file set, digests, sizes, schema, bindings
  copies verified bytes into staging/native/
  writes staging/native/verification.json (supervisor-authored)
  never copies an unverified file
```

Why this shape:

* No absolute path enters the worker request. The worker already has a supervisor-owned
  cwd; the relative convention is fixed by the protocol version.
* The worker cannot write `staging/native/`; it can only write its scratch directory.
* A crash before `descriptor.json` leaves no publishable native output.
* A partial `state.parquet` fails its declared size/digest.
* An extra file fails the exact file-set check.
* A link/hardlink fails the `walk_bundle`-style check.
* The supervisor can delete the scratch after publication; the verified copy is in staging.

Option C is a future hardening if the owner wants byte-level capture without trusting the
worker's file writes. It should not be mixed into the same implementation slice.

### 7.4 Candidate native artifact: `dynamisbench.native.mujoco-state/1`

This is a candidate for the accepted reference pendulum, not a normative format.

`descriptor.json` (canonical JSON, no unknown fields):

```yaml
schema_id: dynamisbench.native.mujoco-state/1
producer:
  adapter_id: dynamisbench.mujoco.reference
  adapter_version: 0.1.0
  implementation_digest: <64 hex>
  engine: mujoco
  engine_version: 3.17.0
  python_version: 3.12.13
  platform: windows-x86-64 | linux-x86-64
binding:
  run_id: <RunId>
  execution_fingerprint: <64 hex>
  input_manifest_digest: <64 hex>
  model_sha256: <64 hex>
  realization_semantic_digest: <64 hex>
  environment_semantic_digest: <64 hex>
simulation:
  integrator: RK4
  solver: Newton
  timestep_s: 0.001
  duration_s: 2.0
  steps: 2000
  nq: 1
  nv: 1
  nu: 0
  gravity_m_s2: 9.80665
  seed: 0
  randomness_policy: no stochastic process
time:
  basis: simulation_time_since_reset
  unit: s
  sample_count: 2001
  first_time_s: 0.0
  last_time_s: 2.0
  monotonic: true
state:
  layout: qpos[0]=hinge angle (rad); qvel[0]=hinge angular velocity (rad/s)
  position_unit: rad
  velocity_unit: rad/s
  frame: hinge axis +y; angle measured from downward vertical
  sign: right-hand rule about +y
files:
  - path: state.parquet
    sha256: <64 hex>
    size_bytes: <int>
    media_type: application/vnd.apache.parquet
    role: native_state_samples
limits:
  max_bytes: 67108864
  max_samples: 1000000
claim: native MuJoCo state only; not canonical; not assessed; not a scientific validation
```

`state.parquet` (candidate schema):

| Column | Type | Unit / meaning |
|---|---|---|
| `time_s` | `double` | MuJoCo simulation time since reset |
| `qpos` | fixed-size list `double[nq]` | Native generalized coordinates |
| `qvel` | fixed-size list `double[nv]` | Native generalized velocities |
| `qacc` (optional v1.1) | fixed-size list `double[nv]` | Native accelerations, if the adapter declares them |
| `ctrl` (optional) | fixed-size list `double[nu]` | Applied controls, if any |

Parquet key-value metadata repeats the schema id, adapter identity, run id, execution
fingerprint, input manifest digest, model SHA-256, units, and time basis. The descriptor is
the authority; the Parquet metadata is a redundant reader aid and must agree.

For the reference case, `nq = nv = 1`, `nu = 0`, 2001 rows, ~48 KiB uncompressed. That is
well inside any reasonable bound and is enough to demonstrate real native output without
inventing a generic trajectory format.

### 7.5 Producer identity and binding

The descriptor must reproduce:

* `run_id` and `execution_fingerprint` from the request;
* `input_manifest_digest` from the request/v2 binding;
* `model_sha256` from the input manifest and the request's realization;
* `realization_semantic_digest` and `environment_semantic_digest` from the RunSpec;
* adapter identity from the request;
* engine version from the running engine;
* implementation digest from the worker identity.

The supervisor compares these to the request, the admission binding, and the persisted
`diagnostics.json`. It cannot independently recompute adapter implementation identity
without running the worker identity command, which it already does at launch for v2.

### 7.6 Time, units, and coordinate conventions

* **Time basis:** MuJoCo simulation time since reset, in seconds. Not wall-clock, not
  event-relative, not canonical time.
* **Position:** `qpos[0]` is the hinge angle in radians, measured from the downward
  vertical, positive by the right-hand rule about +y.
* **Velocity:** `qvel[0]` is the hinge angular velocity in rad/s.
* **Frame:** right-handed world frame with gravity along -z; hinge axis +y.
* **Precision:** IEEE 754 double; `float64` only for v1.
* **No unit conversion** is performed in native evidence. Canonicalization is a later,
  separate layer.

### 7.7 Bounds, streaming, and atomic staging

| Bound | Value | Enforcement |
|---|---|---|
| Descriptor bytes | 1 MiB | Read with a hard ceiling; refuse larger |
| Native artifact bytes | adapter-declared, default 64 MiB | Sum of file sizes; refuse larger; optional scratch watchdog |
| Native sample count | adapter-declared, default 1,000,000 | Parquet row count; refuse larger |
| Native file count | 8 | Exact file-set check |
| Native file path length | 1024 | Existing bundle path language |
| Native file names | no whitespace, no `:`, no reserved names | Existing `BundleRelativePath` rules |
| Worker stdout | 1 MiB | Existing protocol bound |
| Worker stderr | 256 KiB | Existing environment bound |

Memory behavior:

* The supervisor holds the descriptor (≤1 MiB), one Parquet row group at a time, and one
  copy buffer (≤1 MiB); it never loads the whole trajectory into memory.
* The worker may hold the full trajectory only for the reference-sized artifact; a larger
  adapter must stream rows and must not exceed the declared sample/byte bounds.
* The supervisor's memory bound is a function of the declared bounds, not of worker
  self-report; the worker cannot make the supervisor allocate beyond `max_bytes` because
  the supervisor checks size before reading content and streams the copy.

Streaming vs bounded buffer:

* The worker may stream Parquet rows to disk; it must not hold the full trajectory in
  memory if the adapter declares a large bound.
* For the reference case, the trajectory is small and may be written in one pass.
* The supervisor reads the descriptor first, then validates file sizes before reading
  content; it never reads an unbounded artifact into memory.
* The supervisor's publication copy streams file-by-file with a byte counter.

Atomic staging:

* Worker writes `native-out/descriptor.json.seal-tmp`, then `os.replace` to
  `descriptor.json` last. The descriptor is the commit marker for the worker's output.
* Supervisor verifies the complete set, then copies each file to
  `staging/native/<path>.seal-tmp`, verifies the copy, and `os.replace` into place.
* Supervisor writes `staging/native/verification.json` last, also via a temporary +
  replace.
* If any step fails, no `native/verification.json` exists and the run cannot be sealed as
  `SUCCEEDED`.

### 7.8 Partial-write detection

* Missing descriptor: no native output.
* Descriptor present, declared file missing: refuse.
* Declared file present but truncated: size/digest mismatch.
* Extra file: file-set mismatch.
* Descriptor written before the data file is complete: digest mismatch.
* Worker crash mid-write: no descriptor or a digest mismatch.
* Supervisor crash during copy: staging contains a temporary or an incomplete native
  directory; finalization refuses because the verification record is absent or the
  manifest file set is incomplete.
* Power loss during native copy: temporary remains; staging is not promoted; recovery
  classifies it.

### 7.9 Malformed output refusal

The supervisor refuses:

* non-UTF-8 or non-JSON descriptor;
* unknown schema id or unknown fields;
* non-canonical descriptor bytes (for the stored form);
* missing/extra files;
* path traversal, absolute path, link, junction, reparse point, hardlink, non-regular file;
* digest/size mismatch;
* sample count mismatch;
* non-finite values;
* non-monotonic or non-uniform time;
* `qpos`/`qvel` dimension mismatch;
* initial state not matching the scenario;
* final time not matching the duration;
* solver/integrator/timestep mismatch;
* total bytes/samples over bound;
* binding mismatch (run id, fingerprint, input manifest, model, adapter, engine,
  environment).

Every refusal is a bounded diagnostic. The run may still be sealed as `FAILED` with a
complete failure record; the invalid native output is never sealed as successful evidence.

### 7.10 Independent supervisor-side validation

The supervisor validates structure, binding, bounds, and file integrity. It does **not**
validate numerical correctness. Numerical correctness is a separate qualification
comparison against the accepted pendulum reference and has its own verdict.

Validation sequence:

1. Enumerate `native-out/` with `lstat`; reject links/hardlinks/non-regular files.
2. Read descriptor under 1 MiB; parse with the exact schema; require canonical bytes.
3. Check descriptor bindings against request, admission, `diagnostics.json`, and input
   manifest.
4. Check declared file set equals actual file set.
5. For each file: size bound, digest, regular file, no link.
6. Parse Parquet schema; check row count, column types, finite values, time monotonicity,
   dimensions.
7. Check sample count equals `steps + 1` and first/last times.
8. Write `native/verification.json` with every check and a verdict.
9. Copy only verified files into `staging/native/`.
10. Re-verify the copied set against the verification record.

A failure at any step writes a `refused` verification record (if the run is to be retained
as a failed run) and forbids `SUCCEEDED`.

### 7.11 Successful versus failed sealing policy

| Condition | Seal outcome | Native payload |
|---|---|---|
| Process `COMPLETED`; worker response valid; native descriptor present; all checks pass; inputs unchanged | `SUCCEEDED` | `native/descriptor.json`, `native/state.parquet`, `native/verification.json` |
| Process `COMPLETED`; native output missing | `FAILED` | No successful `native/`; `diagnostics.json`, log |
| Process `COMPLETED`; native output malformed/partial/oversized | `FAILED` | Optional `native/partial/` with `verification.json` verdict `refused`; never `native/` success |
| Process `COMPLETED`; input changed after launch | `FAILED` | No successful `native/`; diagnostics record the input change |
| Process `FAILED`/timeout/cancel/abnormal | `FAILED`/`CANCELED`/`TIMED_OUT` | No successful `native/`; diagnostics/log retained |
| Native structural verification passes but numerical reference comparison fails | `SUCCEEDED` for native evidence integrity; separate numerical verdict `FAIL` | `native/` sealed; qualification receipt records numerical failure |
| Native structural verification fails but numerical values look plausible | `FAILED` | No successful `native/` |

The last two rows are the critical separation: **native evidence integrity and numerical
correctness have separate tests and verdicts.**

### 7.12 Lifecycle distinctions

These are facts, not enum values:

```text
PROCESS_COMPLETED
    The worker exited zero with a valid response for this request.

NATIVE_RESULT_PRODUCED
    The worker wrote a complete native-out/ descriptor and declared files.

NATIVE_ARTIFACT_VERIFIED
    The supervisor validated structure, binding, bounds, and file digests.

NATIVE_EVIDENCE_SEALED
    The verified native files are in a promoted sealed bundle.

CANONICAL_NORMALIZATION_COMPLETED
    A later layer produced canonical quantities. Not in RES-555.

SCIENTIFIC_ASSESSMENT_COMPLETED
    A later layer produced metrics/assessment. Not in RES-555.

VVUQ_CLAIM_ACCEPTED
    A later, authorized scientific process accepted a claim. Not in RES-555.
```

No fact implies the next. A process can complete without native output. A native artifact
can verify structurally and fail numerically. A sealed native artifact is not canonical
evidence. A canonical artifact is not a validated conclusion.

---

## 8. Exact execution and evidence state machine

### 8.1 Conceptual stages

These are design stages, not new production enum values.

| Stage | Preconditions | Authority checked | Allowed filesystem mutations | Trusted actor | Required durable record | Failure outcome | Cancellation | Idempotence / retry | Successful sealing prohibited when |
|---|---|---|---|---|---|---|---|---|---|
| `AUTHORITY_RESOLVED` | StudyPlan and RunSpec exist; definitions supplied | Ref resolution, semantic digests, capabilities, benchmark/scenario relationship | None | Planner | `StudyPlan`, `RunSpec` (existing) | Planning refusal | N/A | Deterministic; same inputs same plan | N/A |
| `INPUT_MATERIALIZATION_REQUESTED` | RunSpec admitted for materialization; definitions available | RunSpec refs, declared asset digests, bounds | Private store `tmp/` only | Supervisor / materializer | `MaterializationRequest` (operational) | Materialization refusal | Before first publish: no store mutation; after publish: orphan object is harmless | New request may reuse existing objects | N/A |
| `INPUTS_MATERIALIZED_AND_VERIFIED` | All definitions canonicalized; all assets copied/hashed/published; manifest published | Manifest digest; object digests; definition digests | Store objects and manifest | Supervisor | `InputManifest`, `InputManifestDigest`, `MaterializationRecord` | Refusal; no admission | Orphan objects remain; no evidence | Re-running with same inputs reuses objects; verifies existing | N/A |
| `PREFLIGHT_READY` | Manifest verified; environment/adapter/capabilities/program/run id admitted; no duplicate | Existing preflight checks + manifest binding | None (preflight remains read-only) | Supervisor | `PreflightReport` in memory; durable `preflight.json` written later | `REFUSED` | Before staging: no mutation | Re-preflight is deterministic | N/A |
| `WORKER_STARTING` | Ready admission; staging created; input view copied/verified; admission binding written; launch re-check passes | Admission tuple, manifest, input view, worker identity, environment, capabilities, run id | Create `.staging/<run-id>/`; copy inputs; write `preflight.json`; create scratch | Supervisor | `preflight.json`, `inputs/`, scratch | `REFUSED`/`FAILED`; staging may exist and is diagnosable | If cancelled before launch: close staging, no process; seal as `CANCELED` only if a complete failure record exists | Staging creation is exclusive; retry requires a new run id | If admission re-check fails, no process; no success |
| `WORKER_RUNNING` | Process started; request delivered; deadline/cancel armed | Fixed program, rebuilt env, request digest | Worker writes only scratch (`native-out/`, temp) | Supervisor + worker | Lifecycle events (in memory); final `diagnostics.json` | Timeout/cancel/abnormal exit | Supervisor terminates tree; verifies empty | No automatic retry; new run id | If tree not cleaned, `FAILED` |
| `WORKER_TERMINATED` | Process exited/reaped; tree verified empty; stdout/stderr bounded | Exit code, response, tree cleanup | Write `diagnostics.json`, `logs/worker.stderr.txt` | Supervisor | `diagnostics.json`, log | `FAILED`/`CANCELED`/`TIMED_OUT` | Same | Terminal; no retry | If diagnostic missing/malformed, no seal |
| `NATIVE_OUTPUT_VERIFICATION` | Worker terminated; `native-out/` exists; descriptor present | Descriptor schema, bindings, file set, digests, samples, input re-hash | Read scratch; write `native/` and `native/verification.json` | Supervisor | `native/verification.json` | `FAILED`; optional `native/partial/` with refused verdict | If cancelled after termination: no native publication; seal as canceled if record complete | Re-verification is deterministic for the same scratch; scratch is deleted after | If verification fails, no successful native seal |
| `EVIDENCE_FINALIZATION` | Complete terminal record; verified native output (or explicit failed policy); staging closed for payload | Manifest outcome, payload inventory, checksums, exact file set | Write `manifest.json`, `checksums.sha256`; atomic promote | Evidence | `manifest.json`, `checksums.sha256`, `SealResult` | `BundleConflictError`/`BundleIntegrityError`/`BundleOperationError`; staging remains | Finalization is not cancellable once promotion begins; a crash leaves staging | Second finalization refuses; sealed evidence never overwritten | If promotion fails, no sealed evidence |
| `SEALED_SUCCEEDED` | Promotion succeeded; evidence digest computed; all checks passed | Evidence verification | None after promotion | Evidence | `runs/<run-id>/`, evidence digest | N/A | N/A | Immutable | N/A |
| `SEALED_FAILED` | Promotion succeeded for a complete failure record | Evidence verification | None after promotion | Evidence | `runs/<run-id>/`, evidence digest, failure payload | N/A | N/A | Immutable | N/A |
| `REFUSED` | Admission or materialization refused before launch | Refusal code | No staging (or a diagnostic staging only if the policy says so) | Supervisor | `PreflightReport` / refusal record | Terminal | N/A | New run id | Always |
| `ABANDONED_STAGING` | Process died before a complete record; staging exists | Recovery classification | None | Operator/recovery | Recovery report | Not authoritative | N/A | Do not reuse; classify | Always |

### 8.2 Scenario test matrix

| Scenario | Expected behavior | Seal policy |
|---|---|---|
| Worker crashes after writing part of an artifact | No descriptor or digest mismatch; `FAILED`; diagnostics retained | No `SUCCEEDED`; optional `native/partial/` with refused verdict |
| Cancellation during materialization | No admission; private temporaries may remain; no staging | No seal; materialization can be retried |
| Timeout during output extraction | Supervisor stops reading/copying; `FAILED`; tree cleaned | No `SUCCEEDED`; partial native never promoted |
| Power loss during atomic publication | Final object either absent or complete; temporary remains | No admission until verify; no evidence |
| Two runs with identical inputs | Same `ExecutionFingerprint` and `InputManifestDigest`; different run ids; store objects shared | Each run seals independently |
| Duplicate run IDs | Preflight refuses; staging creation refuses; finalization refuses | No second seal |
| Replayed materialization manifest | Digest matches; input view verifies; if run id is new, allowed; if same run id, refused | No replay of a sealed run id |
| Changed input after launch | Post-run re-hash fails; `FAILED` | No `SUCCEEDED` |
| Different native results for the same fingerprint | Both may seal; different `EvidenceDigest`s are nondeterminism evidence, not identity collapse | Both can be valid native evidence; numerical comparison decides |
| Worker returns `COMPLETED` with missing output files | Descriptor/file-set check fails; `FAILED` | No `SUCCEEDED` |
| Forged success response | Response identity checks may pass; native verification/binding must also pass; a compromised worker can still forge a consistent set | Consistency only; external expected digest for authenticity |
| Substituted artifact from another execution | Binding/run id/fingerprint/input manifest mismatch; refused | No `SUCCEEDED` |

### 8.3 Idempotence and retry

* Materialization is idempotent for the same inputs: same manifest digest, same objects.
* Preflight is read-only and deterministic.
* Staging creation is not idempotent: one run id is one execution; retry requires a new
  run id.
* Finalization is not idempotent: a second finalization refuses; sealed evidence is never
  overwritten.
* Native verification is deterministic for the same scratch bytes; the scratch is deleted
  after publication.
* A failed run may be sealed as `FAILED` once; it is not retried under the same run id.

---

## 9. Protocol compatibility

### 9.1 Why v1 is insufficient

`WorkerRequest` v1 is a closed Pydantic model with `extra="forbid"`; it has no input
manifest field. `WorkerResponse` v1 has no native artifact field. `staging_locator` is
validated as `.staging/<run-id>` and is not an input locator. Adding optional fields would
be a silent semantic change and would violate A8's rule that an incompatible change is a
new version.

### 9.2 Recommended v2 shape

```text
WorkerRequest v2:
  schema_version: 2
  protocol_version: 2
  run_id
  run_spec
  execution_fingerprint
  environment
  adapter
  required_capabilities
  supported_capabilities
  staging_locator              # unchanged meaning: evidence staging only
  input_manifest_digest        # new: binds the materialized input set
  containment_mode             # verified-content | os-enforced
  native_output:
    schema_id: dynamisbench.native.mujoco-state/1
    max_bytes: <int>
    max_samples: <int>
    relative_directory: native-out   # fixed relative convention, not an absolute path
```

`WorkerResponse v2` adds:

```text
  native_output:
    present: bool
    descriptor_relative_path: native-out/descriptor.json
    descriptor_sha256: <64> | null
    file_count: <int>
    total_bytes: <int>
```

The response remains one bounded JSON object. The native bytes are not in the response.
The supervisor still reads one response and one exit. The v2 worker may write only to its
scratch `native-out/`; it still may not write staging.

### 9.3 Compatibility rules

* A v2 supervisor refuses a v1 worker and a v2 worker refuses a v1 request.
* A v1 supervisor remains able to read historical v1 evidence; it cannot execute a v2
  request.
* `RunSpec` 0.1.0 remains valid historical identity. If the owner chooses D2 option A, a
  new `RunSpec` 0.2.0 is introduced; the two are not silently interchangeable.
* The sealed manifest schema remains 1 under the recommended design; native verification
  is a payload file, not a new manifest field. If the owner wants native verification in
  the manifest, that is manifest schema 2 and a separate decision.

---

## 10. Refusal taxonomy and residual risks

### 10.1 Proposed refusal additions (not implemented)

```text
# Materialization / input binding
INPUT_MANIFEST_MISMATCH
INPUT_DEFINITION_MISMATCH
INPUT_OBJECT_MISSING
INPUT_OBJECT_CORRUPT
INPUT_LIMIT_EXCEEDED
INPUT_LINK_REFUSED
INPUT_SOURCE_CHANGED
INPUT_SET_INCOMPLETE
INPUT_SET_UNEXPECTED

# Worker input / native output
INPUT_CHANGED_DURING_EXECUTION
NATIVE_OUTPUT_MISSING
NATIVE_OUTPUT_INVALID
NATIVE_OUTPUT_TOO_LARGE
NATIVE_OUTPUT_BINDING_MISMATCH
```

Adding codes is a visible protocol change. Existing codes remain for existing meanings.
The `Refusal` message remains bounded and path-free.

### 10.2 Residual risks

| Risk | Residual | Mitigation | Honest claim |
|---|---|---|---|
| Same-user worker modifies inputs | Undetected if restored before post-run check | Read-time hash; post-run hash; OS-enforced mode future | Mutation detection, not immutability |
| Same-user worker reads outside root | Not prevented | Request has no absolute paths; adapter rejects includes; OS sandbox future | Logical containment, not OS containment |
| Compromised worker forges native output | A consistent forgery is possible | Binding, structural verification, external expected digest future | Consistency, not authenticity |
| Source changes during copy | Digest mismatch; refused | Copy-then-hash; no retry | Snapshot integrity |
| Existing store object corrupt | Refused; no overwrite | Size/digest verify; quarantine/report | No silent reuse |
| GC races with a run | Object disappears; run refuses | Copy before launch; no automatic GC during run | Fail closed |
| Editable worker source changes | Identity check normally refuses; code already imported is not re-hashed | Launch `--identity` probe; future packaged snapshot | Bounded residual |
| Native parser vulnerability | MuJoCo parse may crash | Isolated process; pinned engine; bounds | Process containment, not parser safety |
| Windows directory fsync | Weaker durability | File flush; post-publication verify; recovery | No torn final name; durability caveat |
| Linux namespace/Landlock unavailable | Cannot claim OS enforcement | Probe; refuse the claim; use verified-content | Platform-specific claim only when probed |
| Hosted runner privilege differs from product user | Test may not represent user | Record privilege context; separate product test | Qualification context is explicit |

### 10.3 Non-claims

This design does not claim:

* scientific validity of the pendulum or any human movement;
* canonical normalization;
* assessment or VVUQ acceptance;
* generic MuJoCo model loading;
* OpenSim execution;
* a production UI run command;
* remote scheduling or distributed workers;
* packaging or release readiness;
* that a repository document is authority.

Those remain later gates.
