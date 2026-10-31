# RES-555 — Authority Decision Packet

**Status:** Approval request, revision 2.2. D1-B, D2-B and D9-A were explicitly approved by
the owner on 2026-10-31 and ADR-026 was accepted. All other decisions remain proposed.
Not an implementation authorization except for DB-3.3A.
**Baseline:** `2a3ef6016e904de5b218e657f15793dd230250bb`, tree
`51e4b366d0cce3cddfba56e6e0fc1720e0fec421`. Protected main at revision 2:
`4e5aff1636ec6e7a45b730847a997054d72eb25b` (PR #23, `apps/workbench/` only).
**Companion artifacts:** `RES-555_AUTHORITY_AUDIT.md`,
`RES-555_TRUST_BOUNDARY_DESIGN.md`, `RES-555_EXECUTION_PLAN.md`.

> The design is complete enough to review, but several contracts cannot be implemented
> without an owner decision. This packet names each one, why code cannot choose its
> meaning, the alternatives, the consequences, and the recommended amendment. Nothing in
> this packet is approved by being written.

---

## 0. How to use this packet

Each decision has:

* **ID and title**;
* **Exact missing or conflicting authority**;
* **Why implementation cannot safely choose**;
* **Alternatives** with security and scientific consequences;
* **Recommendation**;
* **Compatibility implications**;
* **Required ADR/spec amendment**;
* **Work that can proceed independently**;
* **Blocking level** — `HARD` means the named slice cannot be accepted without the
  decision; `SOFT` means the slice can proceed under a documented provisional choice but
  the final claim needs the decision;
* **Authority class** — `OWNER` means the owner must amend or accept authority;
  `CLARIFICATION` means the accepted authority already permits the documented reading and
  the decision records that reading; `PROCESS` means a delivery/governance rule.

Approval means: the owner accepts the recommended option, or chooses another, and records
the amendment in Linear. It does **not** mean the implementation is accepted, the PR may
be merged, or RES-555 may be marked Done. Revision 2 records design corrections; it does
not fill the approval table.

**Scientific inputs versus runtime/library dependencies.** Throughout this packet,
"scientific inputs" means the five definitions and the realization-declared assets whose
semantic/asset digests bind the execution. The Python interpreter, MuJoCo wheel/native
libraries, pyarrow, OS libraries and the editable adapter source are **runtime/library
dependencies**, not content-addressed scientific inputs. They are recorded as operational
provenance with incomplete byte closure. No decision below authorizes calling them sealed
inputs or part of the `InputManifest`.

---

## 1. Decision summary

| ID | Decision | Recommended option | Authority class | Blocking | Blocks |
|---|---|---|---|---|---|
| D1 | Materialization manifest and store authority | New manifest schema; store as `CACHE`; sealed bundle embeds `inputs/` | OWNER | HARD | DB-3.3A |
| D2 | Does the input-set digest enter `ExecutionFingerprint`, and how are platform-specific environments treated? | No input-set field; keep RunSpec 0.1.0; derive manifest from RunSpec + bound definitions; bind at admission; compare shared scientific content across platforms | OWNER + CLARIFICATION | HARD | DB-3.3A/B |
| D3 | What immutability/containment claim is authorized? | `verified-content` detection mode for 3.3B **only if the owner amends the literal wording**; OS-enforced mode is a separate future gate | OWNER | HARD | DB-3.3B |
| D4 | Native evidence channel | Supervisor-owned scratch + copy-then-validate publication; protocol v2 | OWNER | HARD | DB-3.3C |
| D5 | Native artifact schema and decoded bounds | JSON descriptor + Parquet samples, `dynamisbench.native.mujoco-state/1`; bounded decoder | OWNER | HARD | DB-3.3C |
| D6 | Native verification vs scientific assessment | Structural verification gates successful sealing; numerical comparison is separate | OWNER + CLARIFICATION | HARD | DB-3.3C/D |
| D7 | Evidence lifecycle representation | Derived records; no new `RunLifecycleState`/`RunOutcome` values | CLARIFICATION | SOFT | DB-3.3C |
| D8 | Partial/failed native evidence retention | Retain only in a `FAILED` bundle under `native/partial/`; never in `SUCCEEDED` | CLARIFICATION | SOFT | DB-3.3C |
| D9 | Store retention/GC and sealed-bundle self-containment | Embed inputs in sealed bundle; cache is disposable | OWNER | HARD | DB-3.3A |
| D10 | Editable worker source dependency | Bound with launch identity probe for 3.3B; packaged snapshot before final acceptance | OWNER | SOFT | DB-3.3B/D |
| D11 | CI acceptance role of new jobs | Additional RES-555 checks; not renamed as ADR-025 gates; promote after two clean runs | PROCESS | SOFT | DB-3.3A-D |
| D12 | Post-merge acceptance hold and independent review | Require independent approval; hold Done until post-merge main qualification | PROCESS | SOFT | RES-555 closure |
| D13 | Subprocess SUT executable closure | Refuse `SUBPROCESS`/`BRIDGE` in v1; define a versioned closure before any support | OWNER | HARD for subprocess SUT support; not blocking the reference path | Future SUT slice |

**Approved 2026-10-31:** D1 option **B**, D2 option **B**, D9 option **A**. **ADR-026**
was accepted with that approval. Every other row remains proposed; D3/D4/D5/D6/D13 still
block their named later slices.

---

## D1 — Materialization manifest and store authority

**Status:** **APPROVED — option B** by explicit owner decision on 2026-10-31; ADR-026
accepted. Applies to DB-3.3A only.

### Exact missing or conflicting authority

* A1 §11 declares persistence domains (`SOURCE_AUTHORITY`, `SEALED_EVIDENCE`, `STAGING`,
  `DERIVED`, `CACHE`, `TMP`, `USER_STATE`) but no execution-input store or materialization
  manifest.
* A3 §Run bundle declares `run.json`, `run-spec.json`, `preflight.json`,
  `environment.json`, `provenance.json`, `diagnostics.json`, `assessment.json`, `native/`,
  `canonical/`, `logs/`, `manifest.json`, `checksums.sha256` — no `inputs/`.
* A8 RES-549 authorizes a logical `staging_locator`, not an input manifest.
* `workspace/authority.py` declares persistence classes as a closed mapping; adding one is
  a workspace authority change.

### Why implementation cannot safely choose

A manifest schema, store class, and bundle layout are durable scientific interfaces. If an
implementer invents them locally, two runs can disagree about what "the materialized input
set" means, or sealed evidence can lose the bytes it depends on. The repository cannot
create a competing identity/provenance protocol; `CONTRIBUTING.md` forbids it.

### Alternatives

**A. New authoritative `EXECUTION_INPUTS` persistence class.**
The store is immutable scientific authority; sealed bundles reference store objects.
Consequences: strong reuse; no duplication; but sealed evidence is not self-contained, GC
must be reference-aware, and a lost store breaks old evidence. Requires a new
`PersistenceClass`, bundle layout, and migration.

**B. `CACHE` store + self-contained sealed bundle (recommended).**
The store is a disposable, deduplicated cache; every sealed bundle embeds the exact
`inputs/` it used. Consequences: sealed evidence remains self-contained; GC is simple;
cost is duplicate bytes per run. No new persistence class; `CACHE` already exists. Requires
an `inputs/` bundle-layout extension and manifest schema.

**C. Per-run copies only, no store.**
Each run copies directly from source to its staging `inputs/`. Consequences: simplest; no
dedup; source is read once per run; no shared store races. But large models duplicate per
run, and there is no reusable content-addressed substrate. It still needs a manifest
schema and bundle layout.

### Recommendation

**B.** Add `dynamisbench.execution-input-manifest/1`, an `inputs/` sealed-bundle layout, and
classify the store as `CACHE`. Do not add a new `PersistenceClass` in v1. Keep the manifest
out of `RunSpec` under D2's recommended option.

The manifest contains the five definitions and the realization-declared assets only. It
does **not** contain the interpreter, engine wheel/native libraries, pyarrow, OS libraries
or the editable adapter source; those are runtime/library dependencies recorded separately
as operational provenance. Publication uses create-if-absent, never `os.replace` over an
existing final name (trust-boundary design §3.5). A concurrency test and an
inconsistent-existing-object test are part of the contract, not an implementation detail.

### Compatibility implications

* Historical bundles without `inputs/` remain valid; the verifier must not require
  `inputs/` for them.
* New bundles carry `inputs/`; the sealed manifest enumerates those files like any other
  payload, so the evidence digest covers them.
* No change to `Manifest` schema 1 is required if `inputs/manifest.json` is ordinary
  payload. `ArtifactRole` may remain unset for input files, or a later role addition can
  label them; role is optional.
* A cache GC that deletes an object cannot affect a sealed bundle.

### Required amendment

* New **ADR-026 — Content-addressed execution inputs and materialization manifests**
  (proposed).
* A1 §11: add the input cache and `inputs/` layout as a derived/operational class.
* A3 §Run bundle: add `inputs/` and the input manifest to the recommended layout.
* A8/A9: reference the new manifest in the v2 protocol, not in v1.

### Work that can proceed independently

Schema design, canonical definition bytes, asset enumeration and bounds, atomic
publication, duplicate/collision handling, tests, and a store prototype behind a feature
flag. No worker or protocol change.

### Blocking level

**HARD.** DB-3.3A cannot be accepted without D1.

---

## D2 — Does the input-set digest enter `ExecutionFingerprint`?

**Status:** **APPROVED — option B** by explicit owner decision on 2026-10-31; ADR-026
accepted. Applies to DB-3.3A only.

### Exact missing or conflicting authority

* A1 §7 defines `ExecutionFingerprint` as resolved benchmark + realization + scenario +
  SUT + environment + protocol + factors + seed + transformation versions.
* A8/RES-550 and existing sealed evidence depend on `RunSpec` 0.1.0 bytes and
  fingerprints.
* RES-555 requires exact RunSpec-to-asset binding and says not to add paths to the
  existing fingerprint, but does not say whether a materialized input-set digest is part
  of scientific identity.

### Why implementation cannot safely choose

Adding a field to `RunSpec` changes every new fingerprint and invalidates cross-run
comparisons with RES-550 evidence. Not adding it may leave the fingerprint blind to an
input set if the declared asset digests are incomplete. Both are scientific-identity
decisions, not implementation details.

### Alternatives

**A. Add `inputs` (input-manifest digest) to `RunSpec` 0.2.0.**
Consequences: strongest explicit binding; every new run gets a new fingerprint; existing
0.1.0 evidence remains historical but is not directly comparable; requires a schema
version, migration, and new golden vectors. A run-specific manifest must not include
`run_id`, or fingerprints become run-specific.

**B. Keep `RunSpec` 0.1.0; derive the manifest from the RunSpec; bind it at admission
(recommended).**
Consequences: existing fingerprints remain valid; the realization semantic digest already
covers every declared asset digest and logical path; preflight/materialization verify the
actual bytes against those declared digests; the admission record binds the manifest
digest. Requires a rule that every executable asset has a declared SHA-256 (already
enforced at preflight) and a test that the manifest is a deterministic function of the
RunSpec. It does not make the manifest itself part of the fingerprint; it makes it a
redundant, inspectable binding.

**C. Keep the fingerprint unchanged and bind only the request.**
Consequences: least invasive; but two runs with different materialized bytes could share
a fingerprint if the request binding is bypassed. Weaker than B.

### Recommendation

**B.** Keep `RunSpec` 0.1.0. Add a materialization precondition that every executable asset
has a declared digest. Record `InputManifestDigest` in the admission binding and v2 worker
request, not in `ExecutionFingerprint`. Add a property test: same RunSpec + same
definitions/assets -> same manifest digest; changed asset bytes -> materialization refusal
or changed realization digest -> changed fingerprint.

**Platform rule.** Because `RunSpec` includes the environment semantic digest, two
executions with different environment definitions — for example Windows and Linux
platform requirements — legitimately have different full fingerprints and different
`InputManifestDigest`s. The comparison receipt must compare the shared benchmark, scenario,
realization, SUT and asset digests separately. It must never assert that the full
fingerprint or manifest digest is equal across differing environments. An operational
`runtime_selection_digest` is machine-specific and is never part of scientific identity.

### Compatibility implications

* RES-550 fingerprints and sealed evidence remain valid.
* No mass migration.
* If the owner later wants A, it is a separate 0.2.0 schema change with its own
  qualification.
* The manifest must not contain `run_id`, timestamps, or paths, or it would not be a
  function of the RunSpec.

### Required amendment

* A1 §7 clarification: the fingerprint binds declared asset digests through the
  realization semantic digest; the materialization manifest is a derived operational
  binding, not a fifth scientific identity.
* ADR-006 note: an input manifest digest is a derived integrity value, not a replacement
  for semantic/asset identity.

### Work that can proceed independently

Manifest determinism tests, materialization, admission binding, and protocol v2 design. No
RunSpec change under B.

### Blocking level

**HARD.** DB-3.3A/B cannot choose A or B silently.

---

## D3 — What immutability/containment claim is authorized?

### Exact missing or conflicting authority

* RES-555: "Materialized inputs must be read-only to the worker and must not be mutable by
  an unprivileged run"; "Prove every worker-readable input is inside the supervisor-owned
  execution root"; "Refuse … symlinks/junctions/reparse points … on both Windows and
  Linux."
* A1 §13: the local bearer is not security against a fully compromised same-user OS
  session.
* The accepted evidence implementation (`evidence/sealed.py`, `evidence/__init__.py`):
  read-only bits, ACLs, and WDAC are not the source of scientific immutability; a
  permission bit is not a scientific claim.
* A3: a self-contained seal with no external expected digest proves internal consistency,
  not tamper-resistance.
* The current worker runs under the supervisor's OS user. There is no sandbox.

### Why implementation cannot safely choose

The words "read-only", "immutable", and "contained" are acceptance claims. A same-user
worker can write its own inputs, read outside its cwd, and restore a modification before a
post-run hash. Python's `chmod`/read-only attribute does not stop the owner. If the
implementation claims immutability without an OS boundary, it overstates the evidence.

### Alternatives

**A. `verified-content` detection mode (recommended for DB-3.3B).**
Same-user worker; copy, content-address, re-hash at launch, read-time, and post-run;
refuse mutation/substitution; record `containment_mode: verified-content`. Consequences:
honest, implementable on both hosted platforms now; does not satisfy a literal
"immutable/contained" claim; a replace-and-restore attack is undetected.

**B. Require `os-enforced` on both platforms.**
Provision a separate worker identity and/or sandbox: Windows AppContainer/restricted token
or a dedicated standard user; Linux user namespace + read-only bind mount or Landlock.
Consequences: can support a stronger claim; requires admin/root provisioning, a product
prerequisite, new CI probes, and a substantial security review. GitHub-hosted runners run
with admin/sudo, so the test context may not represent an ordinary user. This is a new
platform architecture, not a DB-3.3B patch.

**C. Platform-specific best effort.**
Use `os-enforced` on Linux when available, `verified-content` on Windows. Consequences:
different claims per platform; a Windows result cannot support the same containment claim;
the acceptance record must be platform-specific. It is honest but operationally complex.

### Recommendation

**A for DB-3.3B**, with an explicit `containment_mode` field in the admission and
qualification records, and a separate follow-up issue for **B** if the owner requires a
literal immutability/containment claim. Do not use the word "immutable" unqualified in
RES-555 acceptance. Use "content-verified input snapshot" and "logical containment".

**This is an amendment, not a satisfaction.** Option A detects mutation; it does not make
the input read-only to a same-user worker and does not prevent reads outside the input
root. RES-555's literal text requires the latter. Approving A therefore means the owner
explicitly replaces that acceptance wording for DB-3.3B. If the owner does not approve that
replacement, DB-3.3B is blocked; an implementer may not downgrade the wording by choice.
Under option B, A2-write and A2-read are separate claims. Each requires a proven separate
principal/sandbox and an inside-worker denial probe. A Job Object, process group or
restricted token alone does not establish either.

If the owner requires B for RES-555, stop DB-3.3B at the design boundary and authorize a
new OS-containment gate before implementation. DB-3.3A can still proceed.

### Compatibility implications

* No change to the existing worker protocol for A; v2 adds `containment_mode`.
* Existing RES-549 process-containment claims remain true (process tree only).
* A B decision changes product installation (a worker account/sandbox) and CI; it is not
  compatible with a simple per-user desktop install without provisioning.

### Required amendment

* ADR-026/027: state the supported containment mode and the exact claim.
* A1 §13: add the execution-input boundary and the distinction between process, logical,
  and OS-enforced containment.
* RES-555 acceptance wording: replace "immutable" with the chosen mode, or authorize B.

### Work that can proceed independently

Copy/verify/hash controls, read-time verification, post-run verification, path tests,
capability probes, and the `containment_mode` record. No OS sandbox.

### Blocking level

**HARD.** DB-3.3B's acceptance claim cannot be written without D3.

---

## D4 — Native evidence channel

### Exact missing or conflicting authority

* A3 authorizes a native evidence layer and a `native/` bundle directory.
* A2 says workers emit native evidence.
* A8 RES-549 v1 authorizes one bounded JSON response on stdout and bounded diagnostics on
  stderr; no native artifact channel.
* A9 RES-550 explicitly says the stderr diagnostic is not native evidence and a later gate
  must define the contract.
* `WorkerRequest`/`WorkerResponse` v1 are closed models with `extra="forbid"`.

### Why implementation cannot safely choose

A channel determines who can write evidence, how bytes are bounded, how partial writes are
detected, and what a worker can forge. Writing directly into `staging/` would let the
worker write evidence authority. Sending trajectories through stdout/stderr would violate
the bounded protocol and the diagnostic/native distinction.

### Alternatives

**A. Supervisor-owned scratch + supervisor publication (recommended).**
Worker writes only `native-out/` under its existing supervisor-owned cwd; supervisor copies
and validates the copy, then publishes into `staging/native/`. Consequences: the adapter
does not write the evidence root; partial/extra/missing files fail; no absolute path in the
request; v2 descriptor needed. A same-user worker can still write staging by absolute path,
so the claim is design convention plus detection, not OS denial. A compromised worker can
still forge a consistent set.

**B. Worker writes directly into `staging/native/`.**
Consequences: simple; but the worker gets write access to evidence, and a failed/compromised
worker can plant files. Reject.

**C. Dedicated IPC stream captured by the supervisor.**
Consequences: supervisor writes every byte; strongest containment; requires a new
transport and Windows handle-inheritance work; more review risk. A future hardening, not
v1.

**D. Extend stdout/stderr.**
Consequences: violates the 1 MiB response and 256 KiB log bounds; mixes diagnostics with
evidence; no streaming for trajectories. Reject.

### Recommendation

**A**, with a versioned v2 descriptor and a fixed relative `native-out/` convention. Keep C
as a future option if the owner wants byte-level capture.

### Compatibility implications

* v2 protocol; v1 workers/supervisors refuse each other.
* `staging_locator` keeps its existing meaning.
* No absolute path in the request.
* Native bytes are not in the response; the response only describes the artifact.

### Required amendment

* **ADR-027 — Native simulator evidence channel and sealing** (proposed).
* A2 Worker contract: native output is a v2 channel, not stderr.
* A3: native artifact schema and verification record.
* A8: v2 protocol definition.

### Work that can proceed independently

Artifact schema design, supervisor validator, control-worker tests, failure/partial tests,
and the `native/verification.json` record. No real MuJoCo integration until D5.

### Blocking level

**HARD.** DB-3.3C cannot be accepted without D4.

---

## D5 — Native artifact schema

### Exact missing or conflicting authority

A3 declares native evidence conceptually but defines no schema, units, time basis, sample
structure, byte bounds, or producer fields. `ReferenceDiagnostic` is a bounded
adapter-private diagnostic, not a native artifact. A9 says a later gate may promote a
reviewed subset but does not define it.

### Why implementation cannot safely choose

A native schema becomes a durable scientific artifact. If it silently mixes engine-native
state with canonical quantities, or omits time/unit/frame semantics, later normalization
and assessment cannot distinguish native observation from canonical meaning. If it is
unbounded, a worker can exhaust memory/disk.

### Alternatives

**A. JSON descriptor + Parquet sample table (recommended).**
Descriptor carries schema, producer, binding, simulation/solver identity, time/unit/frame,
file list, and bounds; Parquet carries dense samples. Consequences: matches A1/A5
(Parquet for dense evidence, JSON for metadata); bounded; readable by DuckDB/PyArrow;
native state remains explicit. Requires pyarrow in the worker environment (already a
`dynamisbench` dependency) and deterministic writer settings.

**B. JSON-only samples.**
Consequences: simple for 2001 rows; poor for larger trajectories; JSON float formatting and
size become a risk. Acceptable only for the reference case, not a general native format.

**C. Arrow IPC stream.**
Consequences: efficient; but A1 §10 reserves Arrow IPC for product transport, and the
durable evidence format is Parquet. It would add a second dense format. Not recommended.

### Recommendation

**A**, with `dynamisbench.native.mujoco-state/1`, `time_s`, `qpos`, `qvel`, optional
`qacc`, and the descriptor fields in the trust-boundary design. Keep it explicitly
native: no canonical units, no normalization, no assessment. Bound descriptor at 1 MiB,
artifact at 64 MiB for the reference case, samples at 1,000,000, files at 8.

The bound is not only compressed bytes. D5 also fixes footer/metadata, row-group, row,
column, dimension, uncompressed, decoded-batch, decompression-ratio, CPU and RSS limits, and
requires decoding in a resource-limited validator child (trust-boundary design §7.7). A
sample-count check after an unbounded decode is not an acceptable implementation.

### Compatibility implications

* New native schema; no existing native artifact to migrate.
* Sealed manifest schema 1 unchanged if the native files are ordinary payload.
* `ArtifactRole.NATIVE_EVIDENCE` can label them; role remains a hint.
* Future adapters declare their own schema ids; they do not reuse the MuJoCo schema for a
  different engine.

### Required amendment

* ADR-027: native schema family, versioning, units/time/frame requirements, bounds, and
  refusal behavior.
* A3: native artifact schema and the rule that native is not canonical.

### Work that can proceed independently

Schema model, canonical serialization, Parquet writer/reader, validator, and control
fixtures. No claim that the reference case is scientifically validated.

### Blocking level

**HARD.** DB-3.3C cannot seal a native artifact without D5.

---

## D6 — Native verification versus scientific assessment

### Exact missing or conflicting authority

A3 says native, canonical, and assessment evidence are separate. A4 says software-test
PASS is not model validation. RES-555 says native evidence integrity and numerical
correctness must have separate tests and verdicts, but does not define which one gates
successful sealing.

### Why implementation cannot safely choose

If a numerical comparison gates sealing, a scientifically wrong but structurally valid
native artifact is treated as a sealing failure, conflating evidence integrity with
scientific validity. If numerical comparison is ignored, a sealed native artifact could be
mistaken for a validated result. The lifecycle must make the distinction explicit.

### Alternatives

**A. Structural verification gates sealing; numerical comparison is separate
(recommended).**
Consequences: a native artifact can be sealed as `SUCCEEDED` native evidence while the
numerical reference verdict is `FAIL`; the qualification receipt records both. This is
honest: the seal says "this is what the engine produced and it is intact", not "the engine
is scientifically correct."

**B. Numerical comparison gates sealing.**
Consequences: stronger success criterion; but a failed numerical comparison prevents
retaining a valid native observation, which is bad for diagnosis and for later scientific
assessment. It also makes the seal a scientific verdict, which A3/A4 separate.

**C. Two sealed bundles (native and assessment).**
Consequences: clean separation; more layout/complexity; assessment is out of scope for
RES-555.

### Recommendation

**A.** Sealing requires structural/binding/integrity checks and unchanged inputs.
Numerical comparison is a separate qualification artifact with its own verdict. A sealed
native artifact is not canonical evidence and not a scientific conclusion.

### Compatibility implications

* `RunOutcome.SUCCEEDED` means "native evidence is complete and verified", not "science
  passed". The existing meaning already says completion is not a scientific claim; the
  acceptance record must state the narrowed native meaning.
* No new enum values.
* Qualification receipts must carry both verdicts.

### Required amendment

* ADR-027: sealing policy and the separation of native integrity from numerical validity.
* A4 lifecycle: native evidence capture/verification is distinct from normalization,
  assessment, and VVUQ.

### Work that can proceed independently

Supervisor validator, verification record, negative tests, and separate numerical
qualification tooling.

### Blocking level

**HARD (clarification).** DB-3.3C/D cannot write the acceptance rule without it.

---

## D7 — Evidence lifecycle representation

### Exact missing or conflicting authority

`RunLifecycleState` and `RunOutcome` are closed vocabularies. RES-555 requires distinct
facts: `PROCESS_COMPLETED`, `NATIVE_RESULT_PRODUCED`, `NATIVE_ARTIFACT_VERIFIED`,
`NATIVE_EVIDENCE_SEALED`, `CANONICAL_NORMALIZATION_COMPLETED`,
`SCIENTIFIC_ASSESSMENT_COMPLETED`, `VVUQ_CLAIM_ACCEPTED`. It also says these are logical
distinctions, not authorization to add enum values.

### Why implementation cannot safely choose

Adding values changes a closed protocol and every consumer. Collapsing them into
`COMPLETED` or `SUCCEEDED` would make a native artifact look like a scientific result.

### Alternatives

**A. Derived records, no new enum values (recommended).**
`diagnostics.json` records the process state; `native/verification.json` records native
verification; the sealed manifest outcome records successful/failed sealing. The
conceptual facts are derived from those records. No `RunLifecycleState` or `RunOutcome`
change.

**B. Add native values to `RunLifecycleState`/`RunOutcome`.**
Consequences: explicit, but a protocol/schema change; every consumer must handle the new
values; it risks implying that a lifecycle state is a scientific verdict.

**C. Separate evidence state machine.**
Consequences: cleanest conceptual separation; more new surface; maybe later.

### Recommendation

**A.** Keep the enums closed. Add a supervisor-authored `native/verification.json` and
document the derivation rules. If a future evidence query needs a first-class native
status, introduce it in a separate evidence schema, not in the worker lifecycle.

### Compatibility implications

* No v1 consumer breakage.
* Native facts are readable from payload, not from the lifecycle enum.
* The sealed manifest outcome remains the existing two-value vocabulary.

### Required amendment

* A3: native verification record and derivation rules.
* A1 §6: native evidence is a payload layer, not a new execution state.
* RES-555 acceptance wording: confirm derived facts are sufficient.

### Work that can proceed independently

Verification record schema, derivation table, and tests.

### Blocking level

**SOFT.** DB-3.3C can proceed with A as a provisional design.

---

## D8 — Partial/failed native evidence retention

### Exact missing or conflicting authority

A3 says a failed execution may be sealed as failed evidence if its failure record is
complete; a crashed/abandoned staging directory is not authoritative. It does not say
whether partial native bytes may be retained in a failed bundle or under which path.

### Why implementation cannot safely choose

Retaining partial native bytes under `native/` could be mistaken for successful native
evidence. Discarding them loses diagnostic value. The path and outcome must be explicit.

### Alternatives

**A. Retain only in a `FAILED` bundle under `native/partial/` with a refused verification
record (recommended).**
Consequences: preserves diagnosis; the path and outcome prevent confusion; the sealed
manifest outcome is `FAILED`.

**B. Discard partial native bytes; retain only `diagnostics.json` and logs.**
Consequences: simplest; less diagnostic detail; no risk of confusion.

**C. Retain under `logs/` as opaque bytes.**
Consequences: no native schema claim; but loses structure and provenance.

### Recommendation

**A**, with a strict rule: `native/partial/` is allowed only when the bundle outcome is
`FAILED`, and `native/verification.json` must say `refused` with the reason. A `SUCCEEDED`
bundle may contain only verified `native/` files.

### Compatibility implications

* No manifest schema change; paths are payload.
* The verifier can require that a `SUCCEEDED` bundle has no `native/partial/`.
* A `FAILED` bundle with partial native bytes is evidence of a failed attempt, not a
  native result.

### Required amendment

* ADR-027: partial native retention policy.
* A3: failed-bundle payload rule.

### Work that can proceed independently

Failure-path tests and verification-record schema.

### Blocking level

**SOFT.** DB-3.3C can proceed with A as the documented policy.

---

## D9 — Store retention/GC and sealed-bundle self-containment

**Status:** **APPROVED — option A** by explicit owner decision on 2026-10-31; ADR-026
accepted. Applies to DB-3.3A only.

### Exact missing or conflicting authority

A3 says sealed bundles contain self-contained regular files/directories. A1 §11 separates
authority, derived, cache, and staging but does not classify an input store. RES-555 asks
how retention/GC interact with sealed evidence but does not choose embed-vs-reference.

### Why implementation cannot safely choose

If sealed evidence references a disposable cache, deleting the cache destroys the ability
to reproduce the evidence. If the store is authoritative, GC needs reference counting and
the sealed bundle is not self-contained. This is a scientific-evidence retention decision.

### Alternatives

**A. Embed exact inputs in every sealed bundle; store is `CACHE` (recommended).**
Consequences: self-contained evidence; simple GC; duplicate bytes per run. Compatible with
A3's self-containment rule.

**B. Authoritative store; sealed bundles reference objects.**
Consequences: no duplication; smaller evidence; but requires a new persistence class,
reference-aware GC, and a change to the self-containment claim. Higher risk.

**C. Hybrid: embed small definitions, reference large assets.**
Consequences: balances size; but the evidence is only partially self-contained; needs an
explicit rule for what may be referenced.

### Recommendation

**A.** Embed `inputs/` in the sealed bundle; cache is disposable. This is the only option
that preserves the accepted self-containment rule without a new authority class.

### Compatibility implications

* New `inputs/` payload in new bundles; historical bundles remain valid.
* Cache GC cannot affect sealed evidence.
* Larger bundles; acceptable for the reference case, a deliberate cost for larger models.

### Required amendment

* ADR-026: store class, embedding rule, GC rule.
* A3: `inputs/` layout and self-containment.

### Work that can proceed independently

Store publication, embed-on-seal, GC tests, and a size accounting report.

### Blocking level

**HARD.** DB-3.3A cannot finalize retention semantics without D9.

---

## D10 — Editable worker source dependency

### Exact missing or conflicting authority

RES-555: "Remove the current editable source-tree dependency from the execution path, or
justify and bound any residual source dependency explicitly." A1 §9 and ADR-018 require
separate execution environments but do not define a packaged worker snapshot. The current
`worker-mujoco/pyproject.toml` installs `dynamisbench` editable from `..`.

### Why implementation cannot safely choose

The worker imports code from the mutable checkout. The implementation identity hashes the
installed source files and the request binds that digest, so a changed source tree is
normally refused. But execution is not from a single content-addressed artifact, and there
is no supervisor-side identity probe immediately before launch. Claiming a sealed source
snapshot would be false; ignoring the dependency would leave a known gap.

### Alternatives

**A. Build/install a content-addressed wheel or source snapshot per execution.**
Consequences: true snapshot; requires packaging/build infrastructure, a per-run install or
a pinned environment per adapter version; larger scope, likely M8.

**B. Bound the residual with a launch identity probe (recommended for 3.3B).**
Run `worker --identity` immediately before launch; compare the implementation digest to the
request/manifest; refuse on mismatch; record `source_binding: verified-editable`. The
worker already recomputes identity at start. Consequences: closes the preflight→launch
window; does not create a sealed source snapshot; a same-user attacker who rewrites source
and request/identity together is outside the threat model.

**C. Do nothing; rely on the existing identity check.**
Consequences: weakest; no launch probe; not acceptable for RES-555's stated gap.

### Recommendation

**B for DB-3.3B**, with a recorded residual and an explicit follow-up for **A** before any
claim of a sealed execution environment. If the owner requires A for RES-555, DB-3.3D
cannot be accepted without a packaging gate.

The launch probe covers the adapter source digest. It does not create a sealed interpreter,
wheel or native-library snapshot. Those remain runtime/library dependencies with
version-only provenance; the acceptance record must say so.

### Compatibility implications

* No protocol change; the identity probe is an operational launch step.
* The worker environment remains an editable install; the record says so.
* Future packaging can replace it without changing scientific identity.

### Required amendment

* A1 §9/ADR-018 note: bounded editable-source residual and the launch identity probe.
* RES-555 acceptance wording: state the residual; do not claim a sealed source snapshot.

### Work that can proceed independently

Launch probe, identity comparison, negative test for source mutation, and a
`source_binding` record.

### Blocking level

**SOFT.** DB-3.3B can proceed with B and an explicit residual.

---

## D11 — CI acceptance role of new jobs

### Exact missing or conflicting authority

ADR-025 defines eight required gates. `test_workflow_authority.py` enumerates them and
declares `mujoco-receipt-comparison` an additional non-gate. RES-555 requires additional
security/materialization/native jobs but does not say whether they become required checks
or remain additional.

### Why implementation cannot safely choose

A new job that is not required can fail silently while the PR merges. A new job that is
counted as one of the eight would redefine ADR-025. The acceptance role must be explicit.

### Alternatives

**A. Additional RES-555 checks, not ADR-025 gates (recommended for first delivery).**
Run on both platforms, publish receipts, and require them for RES-555 acceptance via the
PR checklist/ruleset addition after two clean runs. Do not rename the eight.

**B. Add them to the eight.**
Consequences: stronger automatic gate; but changes the accepted ADR-025 matrix and the
meaning of "8/8". Requires an ADR amendment.

**C. Keep them non-gating evidence only.**
Consequences: weakest; a failing security job does not block merge. Not acceptable for a
security gate.

### Recommendation

**A**, then promote the stable jobs to required checks by an explicit ruleset update after
two consecutive clean exact-head runs. The eight remain mandatory and unchanged.

### Compatibility implications

* `test_workflow_authority.py` must be updated for the new job names/artifacts.
* The PR ruleset may require the new checks for RES-555 without calling them ADR-025 gates.
* Existing 8/8 evidence remains valid.

### Required amendment

* Roadmap/ADR-025 interpretation: additional RES-555 checks and their promotion rule.
* `test_workflow_authority.py` expected-artifact table.

### Work that can proceed independently

Workflow job design, receipt schema, and local test commands. No ruleset change until
owner approval.

### Blocking level

**SOFT.** Implementation can proceed; final acceptance needs the role defined.

---

## D12 — Post-merge acceptance hold and independent review

### Exact missing or conflicting authority

A7 says an issue is Done only when all required evidence exists; RES-555 says leave In
Review pending independent acceptance. The ruleset currently requires zero approvals,
allows a bypass actor, and has no post-merge hold. RES-550 was marked Done three seconds
after merge, before post-merge CI. The existing GitHub–Linear automation may close issues
on merge; the exact automation configuration is not in the repository.

### Why implementation cannot safely choose

Changing repository automation, branch protection, or account settings without
authorization is prohibited. But treating merge as acceptance repeats the RES-550 process
weakness.

### Alternatives

**A. Manual post-merge hold (recommended, no settings change).**
Keep RES-555 In Review after merge; add a checklist item: post-merge protected-main run
must succeed on the merge commit, and an independent reviewer must record acceptance,
before Done. Reopen if the post-merge run fails.

**B. Ruleset change: require 1 approval, dismiss stale reviews, require last-push approval,
remove bypass.**
Consequences: stronger durable gate; requires owner/admin authorization; may block
solo-owner workflow. Do not apply without approval.

**C. Linear automation rule to reopen on failed post-merge run.**
Consequences: durable; requires access to the Linear/GitHub automation configuration;
not in the repository; do not change without authorization.

### Recommendation

**A now**, **B as a separate governance change** if the owner wants an enforceable gate.
Record the post-merge run URL and merge commit in the issue before Done. Do not modify
unrelated automation or account settings.

### Compatibility implications

* No code change.
* The acceptance record becomes the authority for Done, not the merge event.
* A failed post-merge run reopens the issue.

### Required amendment

* Roadmap governance note: post-merge acceptance hold.
* RES-555 acceptance checklist.

### Work that can proceed independently

The design PR, review, and qualification can proceed. Only the Done transition is held.

### Blocking level

**SOFT (process).** Does not block implementation; blocks Done.

---

## D13 — Subprocess SUT executable closure

### Exact missing or conflicting authority

* `SUTDefinition` requires a resolved commit or build digest for provenance, but
  `SUTInterface.command` is only a tuple of tokens. It carries no executable path, argv
  closure, interpreter/loader closure, library closure or per-file digest.
* `RealizationDefinition.assets[]` enumerates realization assets, not a subprocess SUT's
  executable or shared libraries.
* RES-555 requires exact materialized inputs for the SUT, but the accepted domain has no
  closure to materialize.
* A1/A2 describe SUT execution conceptually; A8 RES-549 v1 has no subprocess SUT closure.

### Why implementation cannot safely choose

If a worker launches a subprocess SUT whose executable and libraries are not enumerated,
the run can execute different bytes than the SUT definition names. Hashing the command
string or the resolved commit does not bind the executable that actually runs. Claiming a
materialized subprocess SUT without a closure would be a false provenance claim.

### Alternatives

**A. Refuse subprocess and bridge SUTs in materialized v1 (recommended).**
Only `IN_PROCESS` SUTs whose behavior is fully realized by the engine and enumerated assets
are admitted. Consequences: honest and small; the reference pendulum qualifies; generic
subprocess SUT support waits.

**B. Versioned `SUTExecutableClosure`.**
Enumerate every executable, interpreter/loader component, shared library and data file the
SUT runs, with asset IDs, logical paths (≤256), declared/observed SHA-256 and sizes. Bind
the closure to the SUT definition and the input manifest; launch only from the read-only
input view with no PATH fallback. Explicitly exclude and version-bind OS-provided libraries.
Consequences: supports subprocess SUTs; requires a new schema, authority amendment, and
substantial security review.

**C. Best-effort hashing of the command's resolved executable only.**
Consequences: misses libraries, interpreter configuration, plugin loading and later
replacement; not acceptable for a provenance claim.

### Recommendation

**A for DB-3.3 v1.** Refuse `SUBPROCESS` and `BRIDGE` SUTs with
`SUT_EXECUTABLE_CLOSURE_UNSUPPORTED`. Add **B** only as a separately accepted future gate
(D13). Do not treat the Python interpreter, MuJoCo wheel/native libraries, pyarrow, OS
libraries or editable adapter source as scientific assets under this decision.

### Compatibility implications

* No change to `SUTDefinition`, the v1 protocol or the reference path.
* A subprocess SUT is refused before materialization, not failed at launch.
* A future closure is a new schema version and a new authority decision.

### Required amendment

* A2 SUT contract: the admissible SUT interfaces for materialized execution.
* ADR-026/027 or a new SUT-closure ADR: the `SUTExecutableClosure` schema and its exclusion
  rules, if option B is ever chosen.

### Work that can proceed independently

The refusal path, negative tests for `SUBPROCESS`/`BRIDGE`, and the reference `IN_PROCESS`
path. No subprocess SUT implementation.

### Blocking level

**HARD for any subprocess SUT support; not blocking the reference path.** The reference
`IN_PROCESS` model SUT can proceed under D1/D2/D9 once they are approved.

---

## 2. What is not being requested

This packet does **not** request:

* approval to implement DB-3.3B, DB-3.3C or DB-3.3D (DB-3.3A is separately authorized by
  D1-B/D2-B/D9-A and ADR-026);
* approval to modify `RunSpec`, the v1 worker protocol, or any accepted ADR;
* approval to merge the design PR;
* approval to mark RES-555 Done;
* approval to publish a release;
* approval to modify sealed evidence;
* approval to add OpenSim, generic model loading, canonicalization, assessment, or a
  scientific VVUQ claim;
* approval to support a subprocess SUT executable closure (D13);
* approval to change repository automation, rulesets, or account settings.

It requests only the authority decisions needed to make the design implementable and
reviewable.

---

## 3. Approval record (to be completed by the owner)

**D1-B, D2-B and D9-A are approved; all other rows remain blank.** The owner explicitly
approved them on 2026-10-31 and accepted ADR-026. This authorizes DB-3.3A only.

| Decision | Chosen option | Approver | Date | Amendment reference |
|---|---|---|---|---|
| D1 | B | Owner (explicit approval in RES-555) | 2026-10-31 | ADR-026 |
| D2 | B | Owner (explicit approval in RES-555) | 2026-10-31 | ADR-026 |
| D3 | | | | |
| D4 | | | | |
| D5 | | | | |
| D6 | | | | |
| D7 | | | | |
| D8 | | | | |
| D9 | A | Owner (explicit approval in RES-555) | 2026-10-31 | ADR-026 |
| D10 | | | | |
| D11 | | | | |
| D12 | | | | |
| D13 | | | | |

Until the remaining rows are completed and the corresponding Linear authority is amended,
the later implementation slices in `RES-555_EXECUTION_PLAN.md` remain blocked at their
stated boundaries. DB-3.3A proceeds under the approved rows and ADR-026.
