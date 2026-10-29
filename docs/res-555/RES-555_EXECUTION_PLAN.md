# RES-555 — Execution Plan

**Status:** Proposed plan for review. Not authorized implementation. Not a commit schedule.
**Baseline:** `2a3ef6016e904de5b218e657f15793dd230250bb`, tree
`51e4b366d0cce3cddfba56e6e0fc1720e0fec421`.
**Companion artifacts:** `RES-555_AUTHORITY_AUDIT.md`,
`RES-555_TRUST_BOUNDARY_DESIGN.md`, `RES-555_AUTHORITY_DECISION_PACKET.md`.

> This plan assumes the owner approves the hard decisions in the packet. Until then only
> documentation, test scaffolding, and non-authoritative prototypes are permitted. No
> slice may merge before its authority precondition is met.

---

## 1. Decomposition decision

RES-555 combines four trust boundaries:

```text
A. materialization        content identity, store, canonical definitions, atomicity
B. containment            worker input view, launch/read verification, TOCTOU
C. native evidence        channel, schema, supervisor validation, seal integration
D. integrated execution   real MuJoCo on materialized inputs, both platforms
```

They have different authority decisions, different failure modes, and different review
audiences. Implementing them in one patch would make a security boundary, a scientific
schema, a protocol change, and a real-engine qualification reviewable only as a whole.

**Recommendation:** four child issues (or four independently reviewed commit series under
RES-555) with the dependency graph below. Each slice must be independently testable and
independently rejectable. Do not create the child issues until the owner approves the
decomposition and the hard decisions; issue creation is delivery governance, not an
implementation shortcut.

If the owner prefers a single issue, the same four commits must remain separate and each
must have its own qualification record. A single patch is rejected.

---

## 2. Dependency graph

```text
D1/D2/D9 (materialization authority)
        │
        ▼
DB-3.3A  Content-addressed authority materialization
        │
        ├──────────────┐
        ▼              ▼
D3 (containment)   D4/D5/D6/D7/D8 (native authority)
        │              │
        ▼              ▼
DB-3.3B  Worker-input containment and immutability
        │              │
        └──────┬───────┘
               ▼
DB-3.3C  Native output and evidence extraction
               │
               ▼
DB-3.3D  Integrated real-MuJoCo qualification
               │
               ▼
Post-merge main qualification + independent acceptance
```

`DB-3.3B` can be developed in parallel with `DB-3.3C` only after `DB-3.3A` publishes the
manifest contract and `D3`/`D4` are approved. They share the v2 protocol; the protocol
schema must be reviewed once, before either slice freezes it.

---

## 3. Proposed file boundaries

These are expected boundaries, not permission to create all files. Each slice may use
fewer files if the contract stays reviewable.

### DB-3.3A — materialization

```text
python/src/dynamisbench/materialization/__init__.py
python/src/dynamisbench/materialization/schema.py          InputManifest, DefinitionInput, AssetInput
python/src/dynamisbench/materialization/manifest.py        canonical bytes, InputManifestDigest
python/src/dynamisbench/materialization/store.py           atomic publication, verification
python/src/dynamisbench/materialization/materialize.py     authority selection and orchestration
python/src/dynamisbench/materialization/bounds.py          count/size/path bounds
python/src/dynamisbench/materialization/errors.py          bounded refusals
python/tests/materialization/                              unit, property, concurrency, adversarial
python/tests/fixtures/materialization/                     small canonical definitions/assets
```

Do **not** modify `domain/spec`, `planning/runspec.py`, `execution/contracts.py`, or the
worker in this slice. If a domain change is needed, it is a separate reviewed commit and a
D2 decision.

### DB-3.3B — containment

```text
python/src/dynamisbench/execution/inputs.py                per-run input view, launch/post-run verify
python/src/dynamisbench/execution/contracts_v2.py          WorkerRequestV2/WorkerResponseV2
python/src/dynamisbench/execution/preflight.py             materialization admission (additive)
python/src/dynamisbench/execution/supervisor.py            input copy, launch probe, post-run verify
python/src/dynamisbench/execution/_fs_identity.py          platform probes and handle identity
python/src/dynamisbench/adapters/mujoco/worker_v2.py       v2 entry point, read-time verification
python/src/dynamisbench/adapters/mujoco/inputs.py          verified model/asset loader
python/tests/execution/inputs/                             path, link, race, mutation tests
python/tests/execution/mujoco/test_materialized_inputs.py  real worker read verification
```

Keep `contracts.py` v1 unchanged. A v2 module avoids accidental v1 schema drift and makes
the version boundary reviewable.

### DB-3.3C — native evidence

```text
python/src/dynamisbench/evidence/native.py                 native descriptor/schema models
python/src/dynamisbench/execution/native.py                supervisor verification and publication
python/src/dynamisbench/evidence/staging.py                allow verified native payload and inputs
python/src/dynamisbench/evidence/sealed.py                 verify native payload rules
python/src/dynamisbench/adapters/mujoco/native.py          reference adapter native writer
python/tests/execution/native/                             valid, partial, malformed, substituted
python/tests/evidence/test_native_sealing.py               success/failure seal policy
```

### DB-3.3D — integrated qualification

```text
python/tests/execution/mujoco/test_integrated_materialized_run.py
python/tools/res555_qualification.py                       exact-head materialized/native receipt
python/tools/res555_receipt_compare.py                     cross-platform comparison
.github/workflows/quality.yml                              two additional platform jobs + comparison
python/tests/test_workflow_authority.py                    expected job/artifact table
docs/res-555/qualification/                                durable qualification records, if accepted
```

Do not put qualification claims in `assessment.json`; RES-555 does not authorize
assessment.

---

## 4. Slice DB-3.3A — Content-addressed authority materialization

### Scope

Materialize the five definitions and every declared asset into a content-addressed store;
publish a canonical `InputManifest`; handle bounds, duplicates, collisions, atomicity,
concurrency, and verification. No worker, protocol, native evidence, or UI change.

### Preconditions

* D1, D2, D9 approved; ADR-026 accepted.
* A decision on whether `AssetReference.sha256` becomes required for materialized
  executions; recommended yes, enforced at materialization and preflight.
* A decision on the store root's persistence class; recommended `CACHE`.

### Exact deliverables

1. `InputManifest` v1 schema and canonical serializer.
2. `InputManifestDigest` type or documented `SemanticDigest` reuse.
3. Definition canonicalization for all five kinds.
4. Asset enumeration, declared-digest requirement, copy-then-hash snapshot, bounds.
5. Content-addressed store with atomic publication, duplicate reuse, collision/inconsistent
   object refusal, and post-publication verification.
6. Materialization orchestration that rejects a mismatched/duplicate/missing definition.
7. A verification function that re-enumerates the manifest and re-hashes every object.
8. Tests: schema, determinism, relocation invariance, duplicate content, collision,
   concurrent publication, source mutation during copy, oversized asset, missing asset,
   extra file, path escape, link/hardlink source, power-loss simulation.
9. A short design note in the code docstring explaining why no absolute path enters the
   manifest or fingerprint.

### Positive tests

* Same inputs in two different workspace roots produce the same manifest digest.
* Same asset bytes at two logical paths produce one store object and two manifest entries.
* Re-running materialization reuses verified objects without rewriting them.
* A manifest read back from disk validates and matches its digest.
* A sealed bundle with `inputs/` remains self-contained after cache deletion (if 3.3A
  includes the embed step; otherwise 3.3C owns the embed and 3.3A tests the store only).

### Adversarial tests

* Change one byte of each definition -> semantic digest changes; manifest changes.
* Change one byte of an asset without changing the declaration -> materialization refuses.
* Change the declaration and the bytes -> realization digest and RunSpec change; a new
  execution is required.
* `..`, absolute, UNC, device, ADS, reserved name, trailing dot/space -> refused.
* Symlink/junction/reparse/hardlink source -> refused or copied-and-verified per policy.
* Two concurrent materializations of the same content -> one object, both verify.
* Existing object with same digest but wrong size/bytes -> refused, not overwritten.
* Oversized asset, too many assets, manifest too large -> refused.
* Source replaced during copy -> digest mismatch; no manifest.
* Partial temp file after simulated interruption -> not enumerated; next run ignores it.

### Required CI

* Ruff, format, both Pyright modes, full pytest on Windows and Linux.
* A materialization job on both platforms (additional; D11 role).
* Existing eight ADR-025 gates remain mandatory.

### Acceptance criteria

* Canonical manifest digest is reproducible across roots and platforms.
* Every asset byte is verified against its declaration.
* No absolute path appears in the manifest.
* Duplicate/collision/concurrency cases fail closed or reuse correctly.
* No worker/protocol/domain change is included.
* Independent architecture/security review signs the store and manifest contract.

### Out of scope

Worker input view, protocol v2, native evidence, seal integration, real MuJoCo execution,
UI, GC daemon, packaging, OpenSim, generic model loading.

### Rejection / rollback

If D1/D2/D9 are not approved, do not merge. If a slice is merged and a later review finds
a manifest-schema defect, revert the slice commit(s); do not rewrite sealed evidence. A
schema change is a new manifest version, not an in-place edit.

---

## 5. Slice DB-3.3B — Worker-input containment and immutability

### Scope

Create the per-run input view; copy and verify the manifest objects; bind the input
manifest to the v2 request; re-verify at launch; make the worker read and hash the exact
bytes it loads; add post-run verification; add platform probes and honest containment
mode. No native evidence publication yet.

### Preconditions

* DB-3.3A accepted.
* D3 approved (verified-content vs os-enforced).
* D4 protocol shape reviewed (v2 request may be introduced here; native output field can be
  absent until 3.3C, or reserved).
* D10 approved (launch identity probe / residual).

### Exact deliverables

1. `WorkerRequestV2`/`WorkerResponseV2` with `input_manifest_digest`, `containment_mode`,
   and a reserved native-output descriptor (3.3C fills it).
2. Per-run `inputs/` view under the supervisor scratch; relative path convention.
3. Supervisor launch verification: manifest, every input file, worker `--identity` probe,
   environment/adapter/capability/run-id checks.
4. Worker read-time verification: relative path, `fstat`, no link/hardlink, size/digest,
   read bytes, parse from bytes.
5. Post-run input re-hash and `INPUT_CHANGED_DURING_EXECUTION` refusal.
6. Platform capability probe: `verified-content` baseline; optional `os-enforced` probe
   that records available/denied and never claims more than it proves.
7. Tests: path attacks, link/junction/reparse, hardlink, case/Unicode, cross-volume if
   available, source mutation, launch mutation, read-time mutation, worker outside-root
   attempt, timeout/cancel, descendant cleanup, v1/v2 refusal.

### Positive tests

* A real worker loads the materialized model from `inputs/` and completes.
* The same input manifest works on Windows and Linux with the same fingerprint.
* A relaunch with the same manifest reuses the store but creates a new run input view.
* The worker's read-time hash equals the supervisor's manifest digest.
* `containment_mode` is recorded truthfully.

### Adversarial tests

* Replace an input after staging, before launch -> refused before process.
* Replace an input after launch, before worker read -> worker `FAILED`.
* Replace an input after worker read, before post-run -> `FAILED`; no successful seal.
* Add an extra file to `inputs/` -> file-set mismatch.
* Delete an input -> missing; refused.
* Symlink/junction/reparse in `inputs/` -> refused.
* Hardlink in `inputs/` -> refused.
* Absolute path/includes in MJCF -> refused.
* Worker attempts `../` or an absolute path -> adapter refusal; if `os-enforced`, OS denial
  recorded; if `verified-content`, the record says logical only.
* v1 request to v2 worker and v2 request to v1 supervisor -> protocol refusal.
* Source tree mutated between preflight and launch -> identity probe refuses.

### Required CI

* Both platforms, full Python suite, Ruff/Pyright, existing eight gates.
* A containment job on both platforms (additional; D11 role).
* Windows junction and Linux symlink tests must fail closed, not skip silently. If a
  mechanism is unavailable, the job must record the limitation and refuse the claim.

### Acceptance criteria

* No absolute path reaches the worker request.
* The worker loads only verified bytes from `inputs/`.
* Every mutation/substitution case is refused before successful sealing.
* The containment claim matches the probed mode; no unqualified "immutable" claim.
* Existing RES-549/550 behavior regresses nowhere.
* Independent security review signs the threat model and residual risks.

### Out of scope

Native artifact schema/publication (3.3C), OS sandbox implementation (unless D3 chooses B),
generic MJCF multi-file resolver, packaging, UI.

### Rejection / rollback

If D3 chooses `os-enforced` and provisioning is unavailable, stop; do not silently downgrade
to `verified-content`. If v2 is rejected, do not bolt fields onto v1; return to the
decision packet. Revert the slice if it cannot keep the v1 path intact.

---

## 6. Slice DB-3.3C — Native output and evidence extraction

### Scope

Implement the supervisor-owned native scratch/publication channel, the native descriptor
and Parquet sample schema, supervisor validation, `native/verification.json`, and the
staging→seal policy. Use a control worker and the reference adapter's real native output;
do not perform scientific assessment.

### Preconditions

* DB-3.3A and DB-3.3B accepted.
* D4, D5, D6, D7, D8 approved; ADR-027 accepted.
* `pyarrow` is already a `dynamisbench` dependency; confirm the worker environment resolves
  it from the same lockfile and that its version is recorded in the adapter identity.
* A decision on whether native verification is a payload file or a manifest field;
  recommended payload file, manifest schema 1 unchanged.

### Exact deliverables

1. `dynamisbench.native.mujoco-state/1` descriptor model and canonical serializer.
2. Parquet schema/writer/reader with deterministic settings and metadata.
3. Worker native writer: `native-out/descriptor.json` last, atomic; no absolute paths.
4. Supervisor native verifier: file set, links, sizes, digests, schema, bindings, sample
   count/time/finite/dimensions, bounds.
5. `native/verification.json` with per-check records and a verdict.
6. Staging/seal integration: verified native payload only; `SUCCEEDED` requires it;
   `FAILED` may retain `native/partial/` with a refused verdict.
7. Tests: valid, missing descriptor, missing file, extra file, truncated file, wrong
   digest, wrong binding, non-finite, non-monotonic time, wrong sample count, oversized,
   malicious path, link, hardlink, partial write, crash, substitution from another run.
8. A control-worker fixture that produces a valid native artifact without MuJoCo, so the
   supervisor verifier is testable independently of the engine.

### Positive tests

* A valid native artifact is verified, copied into `native/`, sealed, and included in the
  evidence manifest and checksums.
* The native descriptor binds run id, fingerprint, input manifest, model, adapter, engine,
  environment.
* The sealed bundle verifies after native publication.
* The native sample bytes are unchanged from the worker's scratch to the sealed bundle.

### Adversarial tests

* Worker returns `COMPLETED` with no native output -> `FAILED`, no successful seal.
* Worker writes a descriptor for another run/fingerprint/manifest -> refused.
* Worker writes a valid descriptor but a truncated Parquet -> refused.
* Worker writes extra files -> refused.
* Worker writes a symlink/junction/hardlink -> refused.
* Worker writes 65 MiB -> refused without unbounded allocation.
* Worker writes 1,000,001 samples -> refused.
* Worker writes NaN/Inf -> refused.
* Worker writes non-monotonic time -> refused.
* Worker writes a plausible artifact but the input changed -> `FAILED`.
* A failed run's partial native bytes are retained only in `native/partial/` with a
  refused verdict; a `SUCCEEDED` bundle never contains them.

### Required CI

* Both platforms, full Python suite, Ruff/Pyright, existing eight gates.
* A native-evidence job on both platforms using the control worker and the real MuJoCo
  reference (additional; D11 role).
* The numerical reference comparison remains a separate job/verdict; it does not gate the
  native integrity seal under D6 option A.

### Acceptance criteria

* A failed, partial, substituted, or unverified native artifact cannot be sealed as
  `SUCCEEDED`.
* A valid native artifact is sealed with exact provenance and input binding.
* Native integrity and numerical correctness have separate records/verdicts.
* No canonicalization, assessment, or scientific claim is added.
* Independent evidence-authority review signs the schema and seal policy.

### Out of scope

Canonical normalization, assessment.json, plotting, 3D, controller optimization, inverse
dynamics, generic model loading, OpenSim, UI run command, remote compute.

### Rejection / rollback

If D4/D5/D6 are not approved, do not implement. If a native schema defect is found after
merge, introduce a new schema version; never rewrite sealed native artifacts. Revert the
slice if the seal policy cannot be enforced without changing `RunOutcome`.

---

## 7. Slice DB-3.3D — Integrated real-MuJoCo qualification

### Scope

Run the real isolated MuJoCo worker on authorized materialized inputs on Windows x64 and
Linux x64; produce native artifacts; verify them; seal evidence; compare the native
numerical result to the accepted RES-550 pendulum reference; publish exact-head receipts.
No scientific acceptance.

### Preconditions

* DB-3.3A/B/C accepted.
* D10 resolved for the integrated path (launch identity probe; packaged snapshot if
  required).
* D11 acceptance role defined.
* The RES-550 reference constants and tolerances are reused; no new physical acceptance
  criteria are invented.

### Exact deliverables

1. An integrated fixture: workspace, materialized definitions/assets, RunSpec, v2 request,
   real worker, native descriptor/Parquet, supervisor verification, sealed bundle.
2. A durable qualification receipt per platform with:
   * exact checkout commit and tree;
   * RunSpec fingerprint and input manifest digest;
   * materialized definition/asset digests;
   * adapter implementation digest, engine version, Python version, platform, dependency
     closure;
   * native descriptor digest and sample count;
   * native integrity verdict;
   * numerical reference verdict with the accepted tolerance;
   * containment mode and probe result;
   * explicit non-claims.
3. A cross-platform comparison receipt that recomputes the authority, fingerprints, input
   manifests, and native validation; it does not trust a receipt's self-declared verdict.
4. Regression tests for RES-549/550 behavior.
5. Documentation of the exact residual source dependency and containment mode.

### Positive tests

* Real MuJoCo loads the materialized model bytes, not the package asset path.
* The native artifact verifies and seals on both platforms.
* The numerical comparison passes within the accepted RES-550 tolerance, or the
  discrepancy is reported without changing the criterion.
* The same inputs across platforms produce the same fingerprint and manifest digest;
  environment digests may differ by platform as accepted.

### Adversarial tests

* Corrupt one materialized model byte -> worker refuses before physics; no native success.
* Substitute an input from another run -> binding refusal.
* Worker writes to `inputs/` -> detection/refusal; OS denial only if `os-enforced`.
* Worker reads outside `inputs/` -> logical refusal; OS denial only if probed.
* Timeout/cancel -> tree cleanup; no native success.
* Invalid/partial native output -> no successful seal.
* Forged success response -> response identity mismatch; no successful seal unless the
  worker also forges a consistent native set (documented residual).
* Duplicate run id -> refused.
* Failure-to-success seal attempt -> refused.

### Required CI

* All eight ADR-025 gates on the exact PR head, first attempt.
* Additional materialization/containment/native jobs on both platforms.
* Cross-platform receipt comparison job.
* Exact-head evidence: the receipt must name the tested commit and, for a PR, the head SHA.
* Post-merge protected-main run on the merge commit.

### Acceptance criteria

* A real isolated MuJoCo run consumes the authorized materialized inputs and produces a
  verified native artifact on both operating systems.
* The sealed bundle contains `inputs/`, `native/`, `diagnostics.json`, and the verification
  record; it verifies.
* Native integrity and numerical correctness are separately reported.
* No scientific VVUQ PASS is claimed.
* Independent scientific, security, and runtime review signs the result.

### Out of scope

Everything in RES-555's non-goals, plus any release, packaging, UI run command, remote
scheduling, or scientific claim.

### Rejection / rollback

If either platform cannot complete the integrated run, the slice is not accepted. Do not
weaken the test to a control worker. Do not replace a real MuJoCo run with a package-asset
load that ignores the materialized input. Revert the integration commit if the materialized
input path can be bypassed.

---

## 8. Qualification matrix

| Test family | Windows x64 | Linux x64 | Required for | Gate |
|---|---|---|---|---|
| Canonical identity / manifest determinism | Yes | Yes | 3.3A | Python + materialization |
| Relocation invariance (no path in manifest/fingerprint) | Yes | Yes | 3.3A | Python + materialization |
| Duplicate content / concurrent publication | Yes | Yes | 3.3A | Materialization |
| Collision / inconsistent object | Yes | Yes | 3.3A | Materialization |
| Source mutation during copy | Yes | Yes | 3.3A | Materialization |
| Path traversal / absolute / UNC / device / ADS | Yes | Yes | 3.3A/B | Materialization + containment |
| Symlink/junction/reparse escape | Junction/symlink | Symlink | 3.3B | Containment |
| Hardlink alias | Yes | Yes | 3.3B | Containment |
| Case/Unicode collision | Yes | Yes | 3.3B | Containment |
| Cross-volume/mount escape | If available | If available | 3.3B | Containment; record limitation |
| Launch-time mutation | Yes | Yes | 3.3B | Containment |
| Worker read-time mutation | Yes | Yes | 3.3B | Containment |
| Worker outside-root read attempt | Yes | Yes | 3.3B | Containment; claim depends on mode |
| Read-only enforcement failure | Yes | Yes | 3.3B | Containment; expected under verified-content |
| Native valid artifact | Yes | Yes | 3.3C | Native |
| Native missing/partial/truncated/extra | Yes | Yes | 3.3C | Native |
| Native malformed/oversized/non-finite | Yes | Yes | 3.3C | Native |
| Native substitution from another run | Yes | Yes | 3.3C | Native |
| Failure-to-success seal refusal | Yes | Yes | 3.3C | Native + evidence |
| Real MuJoCo materialized run | Yes | Yes | 3.3D | Integrated |
| Numerical reference comparison | Yes | Yes | 3.3D | Integrated + comparison |
| RES-549/550 regression | Yes | Yes | 3.3D | Python |
| Eight ADR-025 gates | Yes | Yes | All | Required |
| Exact-head / post-merge main | Yes | Yes | Closure | Governance |

### 8.1 Scientific checks

Reuse the accepted RES-550 reference:

* model mass 1.0 kg, COM distance 1.0 m, hinge inertia 0.001 + 1.0 kg·m²;
* standard gravity 9.80665 m/s² along -z;
* initial angle 30° (0.5235987755982988 rad), zero angular velocity;
* timestep 0.001 s, duration 2.0 s, 2000 steps, RK4, Newton, tolerance 1e-12;
* accepted numerical tolerances from `qualification_criteria.py` and the RES-550
  receipts.

Do not invent a new physical acceptance criterion to test materialization. Native evidence
integrity and numerical correctness have separate tests and verdicts.

---

## 9. Integration checkpoints

| Checkpoint | Required evidence | Reviewer | Consequence if failed |
|---|---|---|---|
| C0 — design approval | This packet + D1–D12 decisions | Owner + independent architecture/security | No implementation |
| C1 — 3.3A contract freeze | Manifest schema, store invariants, tests | Architecture + security | 3.3B cannot start |
| C2 — v2 protocol freeze | v2 request/response, v1 refusal tests | Runtime + science | 3.3B/C cannot share a protocol |
| C3 — containment claim | Probe record, mode decision, residual register | Security | 3.3B not accepted |
| C4 — native schema/seal policy | Schema, verification record, failure tests | Evidence authority + science | 3.3C not accepted |
| C5 — integrated run | Real Windows/Linux receipts, 8/8, native/inputs sealed | Independent science/security/runtime | 3.3D not accepted |
| C6 — PR head | Exact-head 8/8 + additional jobs, no unresolved review threads | Independent reviewer | No merge |
| C7 — governed merge | Merge commit only, protected branch | Owner | No post-merge qualification |
| C8 — post-merge main | Protected-main workflow on merge commit | Independent reviewer | Reopen/hold; not Done |

---

## 10. CI plan

### 10.1 Existing gates

The eight ADR-025 gates remain mandatory and unchanged:

```text
platform-identity (windows-x64, linux-x64)
python            (windows-x64, linux-x64)
frontend          (windows-x64, linux-x64)
desktop           (windows-x64, linux-x64)
```

`mujoco-receipt-comparison` remains an additional non-gate unless the owner changes it.

### 10.2 Additional RES-555 jobs

Proposed, subject to D11:

```text
materialization (windows-x64, linux-x64)
    canonical manifest, store, duplicate/collision, path attacks

containment (windows-x64, linux-x64)
    input view, link/junction/reparse, launch/read/post mutation,
    worker outside-root attempt, capability probe

native-evidence (windows-x64, linux-x64)
    control-worker valid/invalid/partial, real MuJoCo native artifact,
    supervisor verification, seal policy

res555-receipt-comparison (linux-x64, needs the two native/materialization receipts)
    recompute authority, fingerprints, manifests, native validation;
    compare cross-platform; do not trust self-declared verdicts
```

Each job publishes exactly one reviewed artifact with an exact name and path. The
`test_workflow_authority.py` expected-artifact table must be updated; otherwise the workflow
gate fails. New jobs must not introduce `self-hosted`, `-latest`, `pull_request_target`,
write permissions, secrets, or `continue-on-error`.

### 10.3 Acceptance role

* For the first delivery, the new jobs are **additional RES-555 checks**, not ADR-025
  gates. The eight remain 8/8.
* The RES-555 PR acceptance requires all additional jobs green on the exact head, first
  attempt.
* After two consecutive clean exact-head runs, the owner may add the stable checks to the
  ruleset as required checks. That is a governance change, not a workflow convenience.
* If a new job is unavailable, the affected claim is blocked; do not silently drop the job
  or call the 8/8 sufficient.

---

## 11. Review and merge sequence

```text
IMPLEMENTED
    │  code + tests + exact-head local/CI evidence
    ▼
INDEPENDENT_REVIEW
    │  architecture/security/science reviewer(s), no author self-approval
    ▼
QUALIFIED_PR_HEAD
    │  all eight ADR-025 gates + additional RES-555 checks, first attempt,
    │  on the exact PR head; no unresolved review threads
    ▼
GOVERNED_MERGE
    │  protected branch, merge commit only, no direct push,
    │  no bypass unless explicitly authorized and recorded
    ▼
POSTMERGE_MAIN_QUALIFICATION
    │  protected-main quality workflow on the merge commit, all gates
    ▼
FINAL_ACCEPTANCE
    │  independent reviewer records the post-merge run and the claim ceiling
    ▼
ISSUE_DONE
```

Merge is not acceptance. A green PR is not acceptance. A sealed artifact is not a
scientific conclusion.

### 11.1 Independent review conditions

* The reviewer is not the author and did not pair on the slice.
* The review covers: authority compliance, threat model, schema, refusal behavior,
  compatibility, tests, residual risks, and claim ceiling.
* The review is recorded as a durable GitHub review or a Linear acceptance comment linked
  from the PR; a verbal approval is not evidence.
* Security review is required for 3.3B and 3.3C. Scientific review is required for 3.3D.
* Architecture review is required for 3.3A and any ADR amendment.

### 11.2 Post-merge hold

* Keep RES-555 in `In Review` after merge.
* Record the merge commit, the protected-main run id/URL, and the exact-head evidence.
* If post-merge main fails: reopen the issue, do not mark Done, and do not rewrite the
  merge history.
* Only after a successful post-merge run and independent acceptance may the issue move to
  Done.

### 11.3 Ruleset observations (not changes)

Current facts: zero required approvals, one bypass actor, merge-only, eight required
checks. Recommended controls, subject to D12 and owner authorization:

* require at least one independent approval;
* dismiss stale approvals on push;
* require approval of the last push;
* remove or narrowly scope the bypass actor;
* add stable RES-555 checks as required after they prove stable.

Do not modify repository automation, rulesets, or account settings without explicit
authorization.

---

## 12. Rollback and rejection behavior

| Failure | Response |
|---|---|
| D1/D2/D9 not approved | Stop 3.3A; keep the design PR unmerged |
| Manifest schema defect after merge | New manifest schema version; do not rewrite existing manifests or sealed evidence |
| Store corruption | Refuse new publication; mark object unhealthy; do not overwrite; operator repair |
| v2 protocol rejected | Do not extend v1; return to D4; keep v1 historical |
| Containment mode not approved | Stop 3.3B; do not downgrade silently |
| Native schema rejected | Stop 3.3C; do not seal a native artifact under a provisional schema |
| Native verification fails | `FAILED`; retain diagnostics; no `SUCCEEDED` |
| Numerical comparison fails | Report the discrepancy; do not change the criterion to pass |
| Exact-head CI fails | Fix forward with a new commit; rerun the full matrix; do not merge a red head |
| Post-merge main fails | Reopen/hold; no Done; diagnose on a new branch |
| Review finds an unapproved authority change | Revert the change; amend the decision packet; restart review |

No rollback may modify, delete, or rewrite a sealed evidence bundle.

---

## 13. Definition of done for RES-555 (proposed, not claimed)

RES-555 may be considered for Done only when:

1. All hard decisions D1–D6, D9 are approved and the corresponding authority is amended.
2. DB-3.3A–D are implemented, independently reviewed, and accepted.
3. The materialized input manifest is reproducible and path-independent.
4. The worker consumes only verified materialized inputs and refuses mutation/substitution.
5. The native artifact is produced, structurally verified, sealed, and bound to the
   execution and input manifest.
6. Failure, cancellation, timeout, partial output, and substitution cannot produce a
   successful native seal.
7. The real MuJoCo integrated run passes on Windows x64 and Linux x64.
8. Native integrity and numerical reference verdicts are separate; no VVUQ PASS is claimed.
9. All eight ADR-025 gates pass on the exact PR head, first attempt; additional RES-555
   checks pass; post-merge protected-main qualification passes on the merge commit.
10. Independent architecture, security, scientific, and runtime review is recorded.
11. The issue is moved to Done only after the post-merge acceptance record exists.

Until then, the correct status is `In Review`, `Blocked`, or `Todo` — never Done.
