# RES-555 — Authority Audit

**Status:** Design-review artifact. Not architecture authority. Not an ADR. Not an implementation record.
**Issue:** RES-555 — DB-3.3, M3 third engineering gate.
**Audit date:** 2026-10-29.
**Repository:** `Litju/DynamisBench`.
**Accepted protected main audited:** `2a3ef6016e904de5b218e657f15793dd230250bb`.
**Accepted tree audited:** `51e4b366d0cce3cddfba56e6e0fc1720e0fec421`.
**Design branch base:** `origin/main` at the same commit and tree.

> This document inventories authority and implementation coverage. It does not create
> authority, amend an ADR, authorize implementation, or convert a repository document into
> a substitute for the Linear authority. `CONTRIBUTING.md` forbids a competing local
> architecture document; this is a bounded review artifact that cites the Linear authority
> and stops at the approval boundary.

---

## 1. Baseline verification

| Fact | Observed value | Method |
|---|---|---|
| Protected `main` commit | `2a3ef6016e904de5b218e657f15793dd230250bb` | `git rev-parse origin/main` |
| Protected `main` tree | `51e4b366d0cce3cddfba56e6e0fc1720e0fec421` | `git rev-parse origin/main^{tree}` |
| Merge subject | `Merge pull request #20 … RES-550 …` | `git log -1 origin/main` |
| Protected-main workflow | `quality`, run `40808263238`, event `push`, conclusion `success` | `gh run view 40808263238` |
| Successful jobs in that run | 9: eight ADR-025 gates plus `mujoco-receipt-comparison` | run job list |
| PR #20 head | `136acab5f9473fa72a55a3bdfe5aadf384af0cf2` | `gh pr view 20` |
| PR #20 merge commit | `2a3ef6016e904de5b218e657f15793dd230250bb` | `gh pr view 20` |
| PR #20 reviews recorded on GitHub | none (`reviews: []`) | `gh pr view 20` |
| RES-550 Linear completion | `2026-10-29T02:45:42.007Z` | `get_issue RES-550` |
| RES-550 post-merge acceptance comment | `2026-10-29T02:53:10.298Z` | Linear comments |
| PR #20 merge time | `2026-10-29T02:45:39Z` | `gh pr view 20` |
| Protected-main ruleset | `DynamisBench main qualification` (id `24680388`), active | `gh api …/rulesets` |
| Ruleset required checks | the eight ADR-025 names | ruleset detail |
| Ruleset approvals | `required_approving_review_count: 0`, no code-owner review | ruleset detail |
| Ruleset merge methods | merge commit only | ruleset detail |
| Ruleset bypass | one user actor, `bypass_mode: pull_request` | ruleset detail |
| Current RES-555 Linear state | `Todo`; no started/completed timestamp | `get_issue RES-555` |

The accepted baseline has **not** advanced. The working tree used for this audit is the
accepted tree, not the RES-550 PR head. The design branch is cut from `origin/main`.

The RES-550 issue was marked Done three seconds after its merge and before the
post-merge protected-main workflow completed. The workflow later succeeded. This is a
process observation, not a claim that RES-550's implementation is defective. It is
recorded because RES-555 must not repeat it.

---

## 2. Authority register

Linear workspace: **ML-Alignerr-Autonomous researcher-CMJ task**
(`https://linear.app/alignerr-cmj`).
Project: **DynamisBench — Human Movement Simulation VVUQ & Benchmarking**.

| ID | Authority | Version / state | Linear document or issue |
|---|---|---|---|
| A1 | DynamisBench Architecture & System Design | v0.7, living baseline | `fd014461-9325-4892-a101-74eec3aadc71` |
| A2 | Engine, SUT & Execution Contracts | v0.1, living baseline | `955ac41d-6689-4189-af8d-61406631d1b6` |
| A3 | Evidence & Provenance Model | v0.3, living baseline | `41e12d5f-0cdc-4412-99f8-3988e10a17c3` |
| A4 | VVUQ Workflow & Scientific Lifecycle | v0.2, living baseline | `6b4bffa9-7488-4238-ae53-b1d3a4cf2517` |
| A5 | Locked Tech Stack & Product Runtime | v0.1, living baseline | `529fa746-ebce-493c-99d0-af6a97fb88cf` |
| A6 | Architecture Decision Register | ADR-001 … ADR-025, accepted, revisable | `66568a0d-cef7-440d-91a1-8f5f0a19619a` |
| A7 | Roadmap, Issue Decomposition & Delivery Governance | active | `94da450d-9ec2-423f-b40f-08013226fc20` |
| A8 | RES-549 acceptance record | Done `2026-10-27T23:17:42Z` | `RES-549` |
| A9 | RES-550 acceptance record | Done `2026-10-29T02:45:42Z` | `RES-550` |
| A10 | RES-555 requirements | Todo; issue requirements only | `RES-555` |
| A11 | RES-548 operator journeys | Todo; parallel UX authority | `RES-548` |

Repository sources inspected:

```text
python/src/dynamisbench/domain/          validated definitions and closed vocabularies
python/src/dynamisbench/planning/        resolution, StudyPlan, RunSpec, fingerprint
python/src/dynamisbench/identity/        RFC 8785 canonical bytes, semantic and asset digests
python/src/dynamisbench/workspace/       roots, persistence classes, path gate, source reading
python/src/dynamisbench/execution/       worker protocol, preflight, supervisor, process tree
python/src/dynamisbench/evidence/        staging, manifest, checksum file, verification, seal
python/src/dynamisbench/adapters/mujoco/ real reference adapter, model, identity, diagnostics
python/tests/execution/                   protocol, preflight, supervisor, real MuJoCo
python/tests/workspace/                   path containment, discovery, relocation identity
python/tests/evidence/                    finalization and verification
.github/workflows/quality.yml             ADR-025 eight-gate matrix
python/tests/test_workflow_authority.py   enforced CI authority
CONTRIBUTING.md                           repository discipline and authority-first rule
```

### 2.1 Authority class of RES-555

RES-555 is an **issue requirement**, not an accepted architecture, ADR, or scientific
authority. It can request that a design close a gap; it cannot by itself amend ADR-006,
ADR-008, ADR-009, ADR-017, ADR-018, ADR-021, ADR-023, or ADR-025. Where RES-555 and an
accepted decision differ, the accepted decision wins until the owner explicitly amends
it.

This distinction matters for the native-evidence and immutability requirements, both of
which touch accepted contracts rather than merely extending an implementation.

---

## 3. Status vocabulary used here

| Status | Meaning |
|---|---|
| **DEFINED** | Accepted authority explicitly specifies the behavior. |
| **IMPLEMENTED** | Repository code enforces the behavior. |
| **QUALIFIED** | Tests or durable evidence establish the behavior under declared conditions. |
| **PARTIAL** | Some of the behavior is defined, implemented, or qualified, but not the whole contract. |
| **UNRESOLVED** | The behavior needs an authoritative decision before implementation can safely choose a meaning. |
| **PROHIBITED** | Accepted authority forbids the change, or the change would silently redefine accepted semantics. |

A row may be DEFINED and IMPLEMENTED without being QUALIFIED, or IMPLEMENTED without being
DEFINED where the code is ahead of authority. The matrix records each separately.

---

## 4. Authority-to-implementation matrix

### 4.1 Scientific definitions and identity

| ID | Accepted requirement | Authority | DEFINED | IMPLEMENTED | QUALIFIED | Implementation / tests | Gap |
|---|---|---|---|---|---|---|---|
| R-01 | Validated benchmark, scenario, realization, SUT, environment, study, factor definitions; immutable after validation | A1 §3, §4; ADR-002 | Yes | Yes | Yes | `domain/spec/*`; `tests/domain/test_definitions.py`, `test_serialization.py`, invalid fixtures | None for the existing domain surface |
| R-02 | Semantic identity is SHA-256 of RFC 8785 canonical validated meaning; no path, clock, host, or authoring syntax | A1 §7; A3 Identity; ADR-006 | Yes | Yes | Yes | `identity/canonical.py`, `semantic.py`; `tests/identity/*`, RFC 8785 vectors, golden corpus | None |
| R-03 | Asset identity is raw-byte SHA-256; moving an asset does not change its identity | A3 Identity; ADR-006 | Yes | Yes | Yes | `identity/digests.py`; `tests/identity/test_digests.py`, `tests/workspace/test_identity_invariance.py` | Asset digest has no size bound at the identity layer; callers must bound |
| R-04 | Every execution reference resolves to exactly one definition and exact semantic digest; no `latest`, no fallback | A1 §3; A4 Resolution | Yes | Yes | Yes | `planning/authority.py`; `tests/planning/test_resolution.py`, `test_determinism.py` | None |
| R-05 | `RunSpec` contains only execution-defining inputs; fingerprint excludes replicate index, plan ordinal, run id, timestamps, host, workspace path | A1 §3, §7; ADR-006 | Yes | Yes | Yes | `planning/runspec.py`; `tests/planning/test_runspec.py`, `tests/workspace/test_identity_invariance.py` | The fingerprint does not yet bind a materialized input set; see R-17 |
| R-06 | `ExecutionFingerprint` is a distinct type and is not interchangeable with semantic, asset, or evidence digests | A1 §7 | Yes | Yes | Yes | `planning/runspec.py`; `tests/planning/test_runspec.py` | None |
| R-07 | Static `AssetReference` may carry a declared SHA-256, but the domain does not require it | A1 §4 realization; `realizations.py` | PARTIAL | PARTIAL | PARTIAL | `AssetReference.sha256` is `Sha256Hex` or `None`; preflight refuses `None` at execution | A materialized execution needs an explicit rule that every executable asset is content-addressed; see D2 |

### 4.2 Planning, admission, and process execution

| ID | Accepted requirement | Authority | DEFINED | IMPLEMENTED | QUALIFIED | Implementation / tests | Gap |
|---|---|---|---|---|---|---|---|
| R-08 | Planning is deterministic, pure, side-effect-free, and resolves definitions before a RunSpec exists | A1 §3; A4 Planning; ADR-004 | Yes | Yes | Yes | `planning/plan.py`; `tests/planning/*` | None |
| R-09 | Preflight is read-only, re-derives the fingerprint, re-checks realization/environment identity, capabilities, asset digests, worker program, and duplicate run id | A8; A1 §3 `execution` | Yes | Yes | Yes | `execution/preflight.py`; `tests/execution/test_preflight.py`, `tests/execution/mujoco/test_adversarial_runtime.py` | It does not receive or independently verify benchmark/scenario/SUT definitions; it does not materialize; see G3 |
| R-10 | Worker request carries the exact `RunSpec`, fingerprint, environment, adapter identity, capability sets, and one logical `staging_locator`; no absolute path, host, user, pid, or timestamp | A8; `execution/contracts.py` | Yes | Yes | Yes | `contracts.py`; `tests/execution/test_contracts.py` | No input-manifest field; `staging_locator` is evidence staging only |
| R-11 | Worker protocol v1 is one request, one response, one exit; stdout is one bounded JSON object; stderr is bounded diagnostics; cancellation and timeout are supervisor decisions | A8; `contracts.py` | Yes | Yes | Yes | `contracts.py`, `supervisor.py`; `tests/execution/test_supervisor.py` | No native scientific artifact channel |
| R-12 | Fixed executable vector, no shell, rebuilt minimal environment, absolute program, bounded timeout/log, no PATH or loader-sensitive variables | A8; A1 §8; ADR-017, ADR-018 | Yes | Yes | Yes | `execution/environment.py`; `tests/execution/test_contracts.py`, `test_supervisor.py` | Same OS user as supervisor; no OS sandbox |
| R-13 | Worker runs in an isolated subprocess; process tree is owned, terminated, reaped, and verified empty on every path | A8; ADR-017 | Yes | Yes | Yes | `execution/_process_tree.py`, `supervisor.py`; descendant/timeout/cancel tests | Process isolation, not filesystem isolation |
| R-14 | A run is `COMPLETED` only when the worker returns a valid response for this request and exits zero; completion is not a scientific claim | A8; `contracts.py` | Yes | Yes | Yes | `RunLifecycleState`, `ExecutionResult`; `tests/execution/test_supervisor.py` | The lifecycle vocabulary is closed; native verification is not a state |
| R-15 | Failed, cancelled, timed-out, or abnormal runs cannot be sealed as successful evidence | A8; ADR-008 | Yes | Yes | Yes | `SupervisedExecution.finalize`; `tests/execution/test_supervisor.py`, `tests/evidence/test_finalization.py` | Native artifacts do not yet exist; the success rule will need extension for them |

### 4.3 Evidence and sealing

| ID | Accepted requirement | Authority | DEFINED | IMPLEMENTED | QUALIFIED | Implementation / tests | Gap |
|---|---|---|---|---|---|---|---|
| R-16 | Staging is mutable and non-authoritative; promotion to `runs/<run-id>/` is a single atomic rename; sealed evidence is never overwritten | A1 §6; A3 Sealing; ADR-008 | Yes | Yes | Yes | `evidence/staging.py`; `tests/evidence/test_finalization.py` | None for the existing seal |
| R-17 | Manifest enumerates every payload file by normalized relative path, raw-byte SHA-256, and size; manifest is not self-referential; evidence digest is SHA-256 of canonical manifest bytes | A3 Seal coverage; ADR-006, ADR-008 | Yes | Yes | Yes | `evidence/manifest.py`; `tests/evidence/test_manifest.py`, `test_verification.py` | No native artifact schema; no input files are sealed |
| R-18 | Checksums cover payload plus manifest, exclude themselves, are sorted, and are independently verified before promotion | A3 Sealing | Yes | Yes | Yes | `evidence/manifest.py`, `staging.py`, `sealed.py`; finalization/verification tests | None |
| R-19 | Sealed bundles contain regular files and directories only; symlinks, junctions, other reparse points, and hard-linked files are refused | A3 Sealing; `evidence/bundle.py` | Yes | Yes | Yes | `walk_bundle`; `tests/evidence/test_finalization.py`, `test_verification.py` | This is bundle-content policy, not worker-input policy |
| R-20 | A valid seal proves internal consistency; only an externally trusted expected evidence digest proves expected output; neither is called tamper-proof | A3 Identity; `evidence/sealed.py` | Yes | Yes | Yes | `VerificationResult`; `tests/evidence/test_verification.py` | The same honesty boundary must apply to native evidence |

### 4.4 Real MuJoCo capability

| ID | Accepted requirement | Authority | DEFINED | IMPLEMENTED | QUALIFIED | Implementation / tests | Gap |
|---|---|---|---|---|---|---|---|
| R-21 | The first real adapter implements only the declared forward-dynamics capability, with a real MuJoCo forward-dynamics reference run | A9; A2 Capability families | Yes | Yes | Yes | `adapters/mujoco/*`; `tests/execution/mujoco/*`; receipts on Windows/Linux | Fixed reference only; no generic model loading |
| R-22 | Engine/version admission evaluates the realization specifier and the environment ENGINE requirement with accepted SemVer semantics; `compatible` and malformed constraints are refused | A9; `execution/versions.py` | Yes | Yes | Yes | `_engine_version_refusals`; `tests/execution/test_version_admission.py` | None |
| R-23 | The worker proves the request names the compiled reference case and the installed implementation, including semantic digests, model SHA-256, engine version, Python version, platform, and implementation digest | A9; `adapters/mujoco/worker.py` | Yes | Yes | Yes | `_verify_reference_authority`, `_verify_installed_identity`; adversarial authority/runtime tests | The worker proves the package model; it does not consume a materialized source asset |
| R-24 | Real MuJoCo output is a bounded adapter diagnostic on stderr, not `native/`, canonical, assessment, or sealed scientific evidence | A9; `adapters/mujoco/diagnostics.py` | Yes | Yes | Yes | `test_real_execution.py` asserts absence of `native/`, `canonical/`, `assessment.json` | This is the explicit boundary RES-555 must change, with authority |

### 4.5 RES-555 requirements not yet covered by accepted implementation

| ID | RES-555 requirement | Authority status | IMPLEMENTED | QUALIFIED | Gap |
|---|---|---|---|---|---|
| R-25 | Materialize the exact benchmark/scenario/realization/SUT/environment definitions and every authorized asset into a deterministic, content-addressed store or layout | **UNRESOLVED** as architecture; RES-555 requirement only | No | No | No store, manifest schema, persistence class, retention rule, or GC rule |
| R-26 | Strict workspace containment at preflight, materialization, launch, and worker-read time | PARTIAL: workspace path gate is DEFINED and QUALIFIED for workspace references | Partial | Partial | No worker input root, no worker-read check, no OS containment |
| R-27 | Immutable worker-readable inputs; read-only to the worker; re-verify hashes at launch and before physics; refuse changed/missing/extra/substituted input | **UNRESOLVED / conflicting**: RES-555 requires it; A1 §13 and the accepted evidence implementation (`evidence/sealed.py`, `evidence/__init__.py`) explicitly disclaim same-user immutability from permission bits/ACLs | No | No | Same-user worker; no sandbox; no read-only mount; no enforceable immutability |
| R-28 | Exact RunSpec-to-asset bindings in one inspectable chain, including adapter, engine/runtime, capabilities, definition content, asset content, environment content | PARTIAL: semantic digests and declared asset SHA-256 exist | Partial | Partial | No manifest; benchmark/scenario/SUT definitions not independently re-bound at preflight; worker does not read the asset |
| R-29 | Native simulator evidence extraction under accepted evidence authority; bounded native outputs with producer/run/model/input/engine provenance; staging→seal transaction that cannot turn failure into success | **UNRESOLVED**: A3 defines a native evidence layer conceptually; A2 says workers emit native evidence; A8 protocol v1 authorizes diagnostics only | No | No | No channel, artifact schema, validation record, or seal policy |
| R-30 | Preserve raw native evidence; no canonicalization, scoring, assessment, or scientific acceptance in this gate | DEFINED as a RES-555 non-goal; consistent with A1 §6 and A3 | No | No | Depends on R-29 |
| R-31 | Operator-visible preflight/refusal, materialization identity, worker input root, terminal status, and evidence locator facts shared with RES-548 | PARTIAL: preflight/refusal and terminal facts exist | Partial | Partial | No materialization identity, input root, or native evidence facts |
| R-32 | Real Windows x64 and Linux x64 hosted qualification, negative security tests, exact-head 8/8, independent review, post-merge main qualification | DEFINED by A7, A6 ADR-025, RES-555 | Partial | Partial | 8/8 exists; no RES-555 security/materialization/native jobs; no post-merge hold |

### 4.6 Governance

| ID | Accepted requirement | Authority | DEFINED | IMPLEMENTED | QUALIFIED | Gap |
|---|---|---|---|---|---|---|
| R-33 | Eight required ADR-025 gates remain mandatory on pinned `windows-2025` and `ubuntu-24.04`; additional jobs do not replace them | A6 ADR-025; A7; `test_workflow_authority.py` | Yes | Yes | Yes (run `40808263238`) | New RES-555 jobs must be declared additional and must not be counted as the eight |
| R-34 | An issue is Done only after all required evidence exists; merge is not acceptance | A7 Issue quality / Milestone closure; RES-549, RES-550, RES-555 | Yes | **No** | No | Ruleset requires zero approvals and permits a bypass actor; RES-550 was marked Done before post-merge CI |
| R-35 | Independent scientific/security/runtime review before acceptance | RES-555; A7 | Yes | **No** | No | PR #20 has no GitHub review object or approval; review may exist elsewhere, but it is not a durable merge gate |

---

## 5. Confirmed gaps

The gaps below are facts about the accepted baseline. They are not yet authority decisions;
the decision packet proposes the smallest decisions that would close them.

### G1 — No materialization model, store, or manifest

There is no `materialization` package, no `PersistenceClass` for execution inputs, no
manifest schema, no canonical definition serialization step for execution, no asset
enumeration bound, and no publication or duplicate-content rule. `AssetReference` names a
workspace-relative path and an optional declared digest; nothing materializes it.

### G2 — The worker has no authorized input location

`WorkerRequest` carries `staging_locator`, and `staging_locator` is validated as the
canonical `.staging/<run-id>` reference. The worker does not resolve it and does not use
it. Preflight hashes source assets, but the worker never receives them. Reinterpreting
`staging_locator` as a model-input locator would be a silent protocol redefinition and is
prohibited.

### G3 — Preflight does not independently bind all five definitions

`PreflightedRun` holds the realization and environment definitions. `admission_refusals`
recomputes their semantic digests. The benchmark, scenario, and SUT definitions are only
present inside the accepted `PlannedRun`/`RunSpec` as resolved references; preflight does
not receive them and cannot re-hash them. For a generic materialized execution, that is a
binding gap.

### G4 — Asset enumeration and bounds are incomplete

`AssetReference.sha256` is optional. `preflight._asset_refusals` refuses a `None` digest at
execution time, which is a good fail-closed check, but the domain does not require the
field. There is no maximum asset count, per-asset size, total size, or nesting bound in
the materialization path because that path does not exist. `asset_sha256_of_file` streams
in 1 MiB chunks but has no size ceiling.

### G5 — The source-asset TOCTOU is not closed

RES-549's post-merge acceptance record explicitly lists "source-asset launch/read TOCTOU"
among its remaining limits, and RES-550's acceptance record repeats "Source-asset TOCTOU
and the RES-549 process-containment limitations remain." In code, preflight hashes a source
asset; the supervisor re-hashes it before staging and again before launch. The worker never
reads it. The supervisor's second check occurs after the staging bundle is created and
after a working directory and request bytes are prepared, so the window between the last
check and process start is not tested. More importantly, the source root remains mutable
and the worker's execution is not causally tied to the materialized source bytes.

### G6 — No worker read-time verification

The worker loads the packaged reference model through
`importlib.resources` and verifies `MODEL_SHA256`. That is real content verification, but
it verifies the package asset, not the source asset named by the realization. A generic
materialized model would need to be read, hashed, and parsed from the verified bytes
inside the worker.

### G7 — Same-user worker; no filesystem immutability or containment

The supervisor launches the worker with the supervisor's OS user. The worker environment
is minimal and `-I` is used, but the process can still open any file the user can read and
write any file the user can write. `chmod`, `FILE_ATTRIBUTE_READONLY`, ACLs, a private cwd,
and a stripped environment are not immutability against that worker. A1 §13 explicitly
says the local bearer is not protection against a fully compromised same-user session.
The accepted evidence implementation (`evidence/sealed.py`, `evidence/__init__.py`) says
read-only bits, ACLs, and WDAC are not the source of scientific immutability, and A3 says a
self-contained seal with no external expected digest proves internal consistency rather
than tamper-resistance.

### G8 — Process containment is not filesystem containment

The Windows Job Object and POSIX session/process group own the process tree. They do not
restrict file access. There is no AppContainer, restricted token, mount namespace, user
namespace, Landlock, seccomp, or read-only bind mount in the execution path.

### G9 — No native evidence channel or schema

`ReferenceDiagnostic` is explicitly an adapter diagnostic on stderr. It is not
`NativeEvidence`. The evidence model's `ArtifactRole.NATIVE_EVIDENCE` exists, and the run
bundle layout declares `native/`, but no schema, producer contract, artifact format,
verification record, bounds, or seal rule is implemented. The worker protocol v1 has no
native-output field.

### G10 — Native lifecycle distinctions are not representable

`RunLifecycleState` is a closed enum with `COMPLETED`/`FAILED` etc. `RunOutcome` is
`SUCCEEDED`/`FAILED`. There is no representation of `NATIVE_RESULT_PRODUCED`,
`NATIVE_ARTIFACT_VERIFIED`, `NATIVE_EVIDENCE_SEALED`, `CANONICAL_NORMALIZATION_COMPLETED`,
`SCIENTIFIC_ASSESSMENT_COMPLETED`, or `VVUQ_CLAIM_ACCEPTED`. Adding enum values would be
an authority change; the design must keep these as derived facts or separate records.

### G11 — No input retention or GC policy

Sealed bundles are self-contained and contain only payload the supervisor wrote. There is
no `inputs/` layout, no rule that sealed evidence retains the exact materialized bytes,
and no GC rule for a content-addressed store. A store classified as `CACHE` is disposable;
if sealed evidence referenced it, deletion would break evidence. If the store is
authoritative, retention and GC need an explicit rule.

### G12 — The worker environment is an editable source install

`python/worker-mujoco/pyproject.toml` declares `dynamisbench = { path = "..", editable = true }`.
The worker imports the adapter from the checkout. `build_implementation_identity` hashes
the installed source files and the supervisor binds that digest, so a changed source tree
is normally refused at worker identity verification. But execution is not from a
content-addressed snapshot, and there is no supervisor-side `--identity` probe immediately
before launch. This is the residual source dependency RES-555 requires to remove or bound.
The RES-550 acceptance record also states that runtime dependency verification covers
installed distribution versions, not wheel bytes or the interpreter binary; the lockfile
hash is a repository/CI attestation.

### G13 — Governance can close an issue before qualification

The ruleset requires zero approvals, allows one user to bypass via pull request, and has
no post-merge acceptance hold. PR #20 has no GitHub review object or approval. Linear
transitioned RES-550 to Done at `2026-10-29T02:45:42Z`, three seconds after the
`02:45:39Z` merge. The
post-merge acceptance comment was added at `02:53:10Z`, after protected-main run
`40808263238` completed. That acceptance record itself states that no human approval was
required by the ruleset and none is claimed. The post-merge run later succeeded, but the
Done transition preceded its evidence.

### G14 — CI has no RES-555 gate

The eight ADR-025 gates and the MuJoCo receipt comparison exist. There is no
materialization, containment, worker-input, native-evidence, or substitution gate. The
`mujoco-receipt-comparison` job is explicitly a non-gate.

---

## 6. Prohibited interpretations and changes

The following are prohibited unless an explicit ADR/spec amendment is accepted first.

1. **Do not put absolute paths, temporary directories, workspace roots, drive letters,
   host names, user names, or mount points into `ExecutionFingerprint`.** A1 §3 and §7 and
   ADR-006 make location operational state, never scientific identity.
2. **Do not reinterpret `staging_locator` as a model-input or asset locator.** It is the
   evidence staging reference of one run id; `contracts.py` validates exactly that form.
3. **Do not add native lifecycle values to `RunLifecycleState` or `RunOutcome` by
   convenience.** The lifecycle vocabulary is closed by `contracts.py`; A1 §6 and A3
   separate evidence layers, not execution states, and neither authorizes new values.
4. **Do not claim filesystem immutability from `chmod`, `FILE_ATTRIBUTE_READONLY`, ACLs, a
   private cwd, a stripped environment, or path normalization.** A1 §13 and the accepted
   evidence implementation reject that inference.
5. **Do not extend worker protocol v1 with optional native fields.** The v1 models are
   `extra="forbid"`, and A8 says an incompatible change is a new protocol version.
6. **Do not silently change `RunSpec` 0.1.0 or `ExecutionFingerprint` semantics.** Existing
   sealed evidence and RES-550 receipts depend on those bytes.
7. **Do not implement generic MuJoCo model loading, OpenSim, canonical normalization,
   assessment, controller optimization, inverse dynamics, or a scientific VVUQ PASS.**
   RES-555's non-goals and A1/A4 keep those as later gates.
8. **Do not edit ADR-001 … ADR-025 as if approval existed.** Propose an amendment, record
   the impact, and wait.
9. **Do not merge the design PR, mark RES-555 Done, publish a release, or modify sealed
   evidence.**
10. **Do not treat a repository design document as authority.** `CONTRIBUTING.md` is
    explicit: Linear is authority; this repository implements it.

---

## 7. Inspection limits

* Linear documents are living authority. The versions read for this audit are the ones
  listed in §2; a later edit is a later baseline.
* No accepted ADR beyond ADR-025 exists at this baseline. Proposed ADR-026/027 in the
  decision packet are proposals only.
* The local host is Windows 11 x64 at medium integrity. Linux primitives were not executed
  on this host. The protection matrix therefore distinguishes **documented API
  availability** from **qualified availability**; every security primitive must be probed
  in the target CI job before any claim depends on it.
* GitHub-hosted Windows runners commonly run with administrator rights; Linux runners have
  passwordless `sudo`. A test that creates a junction, user, or namespace there does not
  by itself prove the same operation is available to an ordinary product user. The
  qualification record must state the privilege context.
* No independent review of this audit has occurred yet. This is a review input, not an
  acceptance record.

---

## 8. Summary

The accepted baseline is strong on **scientific definition identity**, **planning
determinism**, **read-only preflight**, **fixed-vector process supervision**, **staging and
sealing**, and the **real MuJoCo reference run**. It is deliberately weak on exactly the
four boundaries RES-555 names: materialization, worker-input immutability/containment,
RunSpec-to-asset binding for generic execution, and native evidence extraction.

The gaps are not all of one kind:

* G1, G4, G11, G12 are implementation and schema gaps that can be designed within the
  existing architecture once a manifest/store decision is made.
* G2, G3, G5, G6, G9, G10 require an explicit protocol or evidence-schema extension.
* G7, G8, G13 are trust-boundary and governance issues that cannot be closed by code
  alone; they need an owner decision about the supported security claim.

The authority decision packet (`RES-555_AUTHORITY_DECISION_PACKET.md`) records those
decisions. Implementation is blocked until the hard decisions are approved.
