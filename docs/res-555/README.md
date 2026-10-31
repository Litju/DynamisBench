# RES-555 — Design Review Package

**Status:** Revision 2 (RES-561 design repair), draft for independent architecture, scientific,
and security review. **Not authority. Not an ADR. Not implementation authorization.**
**Revision date:** 2026-10-31.
**Code baseline audited:** protected `main` `2a3ef6016e904de5b218e657f15793dd230250bb`,
tree `51e4b366d0cce3cddfba56e6e0fc1720e0fec421`.
**Protected main at repair time:** `4e5aff1636ec6e7a45b730847a997054d72eb25b` (PR #23), which
changes only `apps/workbench/`; no Python, worker, evidence, `RunSpec`, ADR or CI change.

This directory contains the RES-555 Phase A design package for:

> DB-3.3 — Content-addressed model/definition materialization, worker input immutability,
> and native evidence extraction.

The repository is not the architecture authority. The living authority is the Linear
project **DynamisBench — Human Movement Simulation VVUQ & Benchmarking**. These documents
cite that authority and propose bounded changes; they do not replace it. See
`CONTRIBUTING.md`.

## Revision 2 — RES-561 repair

Revision 2 corrects the design defects recorded in RES-561. It is documentation only. It
adds no production code, no ADR amendment, no accepted protocol, and no owner approval.
The design verdict is still `BLOCKED_AUTHORITY` for implementation.

| RES-561 finding | Correction in this revision |
|---|---|
| SEC-01 check-then-`os.replace` is not no-overwrite CAS | Store publication now uses create-if-absent primitives (`os.link` on POSIX, non-replacing rename on Windows), never `os.replace`; visibility, durability and crash recovery are separated; concurrent publishers cannot replace a winner. |
| SEC-02 compressed bytes do not bound decoded Parquet | The native verifier now bounds footer/metadata, row groups, rows, columns, dimensions, uncompressed bytes, decoded batch bytes, decompression ratio, CPU and RSS, and decodes only in a resource-limited validator process. |
| SEC-04 SUT executable closure is absent | Materialized v1 explicitly refuses `SUBPROCESS`/`BRIDGE` SUTs. A versioned SUT executable closure is proposed as D13 and cannot be claimed before approval. |
| SEC-05 A1 is detection, not same-user immutability | A1 is restated as **content-verified snapshot / mutation detection**. Option A under D3 is an owner amendment to RES-555's literal wording, not a way to satisfy it. A2 is split into A2-write and A2-read and requires a proven separate access boundary. |
| SEC-06 process cwd does not deny staging writes | The design now says a same-user worker can write staging by absolute path; `cwd` is not containment. Supervisor publication uses exclusive create and exact expected inventory; no OS-enforced write claim is made. |
| SEC-07 A2 requires a proven separate boundary | A2 is unavailable unless a separate principal/sandbox and an inside-worker denial probe are recorded. Job Objects and restricted tokens are not filesystem boundaries. |
| SEC-08 native scratch verify/copy race and worker binary ownership | Native bytes are copied first and the **copy** is validated and sealed; scratch bytes are never validated then copied. Worker program/interpreter identity is an operational detection record, not a sealed runtime snapshot. |
| Identity: platform-specific environment | Full `RunSpec` fingerprints and `InputManifest` digests differ when environment semantic digests differ. Cross-platform comparison uses shared scientific content, not full fingerprints. |
| Paths: 256 vs 1024 | `WorkspaceRelativePath` is 256 characters. 1024 is the workspace logical-reference bound and is not reused for authority or native payload paths. |
| D1–D13 hard/soft and ADR proposals | The decision packet marks each decision's authority class and blocking level, keeps ADR-026/027 as proposals, and separates scientific inputs from runtime/library dependencies. |
| D3 literal immutability conflict | D3 now states that option A changes the acceptance wording only with owner approval; otherwise DB-3.3B is blocked. No silent downgrade. |

Detailed finding-to-decision closure and executable counterexamples are in
`RES-555_TRUST_BOUNDARY_DESIGN.md` §11. The first proposed Laboratory execution API
boundary is in `RES-555_EXECUTION_PLAN.md` §14.

## Baseline

| Fact | Value |
|---|---|
| Code baseline audited | `2a3ef6016e904de5b218e657f15793dd230250bb` |
| Audited tree | `51e4b366d0cce3cddfba56e6e0fc1720e0fec421` |
| Baseline qualification | workflow `quality`, run `40808263238`, nine successful jobs |
| Protected main after PR #23 | `4e5aff1636ec6e7a45b730847a997054d72eb25b` (apps/workbench only) |
| Post-merge qualification | run `41166834210`, nine successful jobs |
| Design branch base | `origin/main` at the audited commit; not rebased |
| RES-555 Linear state at revision 2 | `Todo` |
| RES-561 Linear state at revision 2 | design repair submitted for review |

## Documents

| Document | Purpose |
|---|---|
| [`RES-555_AUTHORITY_AUDIT.md`](RES-555_AUTHORITY_AUDIT.md) | Authority register, authority-to-implementation matrix, confirmed gaps, prohibited interpretations, inspection limits, RES-561 addendum |
| [`RES-555_TRUST_BOUNDARY_DESIGN.md`](RES-555_TRUST_BOUNDARY_DESIGN.md) | Identity model, materialization architecture, Windows/Linux threat model and protection matrix, TOCTOU closure, native evidence design, state machine, protocol compatibility, finding closure matrix |
| [`RES-555_AUTHORITY_DECISION_PACKET.md`](RES-555_AUTHORITY_DECISION_PACKET.md) | Decisions D1–D13 that require owner approval, each marked hard/soft, with alternatives, consequences, recommendations, amendments, and independent work |
| [`RES-555_EXECUTION_PLAN.md`](RES-555_EXECUTION_PLAN.md) | Four implementation slices, dependency graph, file boundaries, qualification matrix, CI plan, review/merge/post-merge sequence, rollback, first execution API boundary |

## Verdict requested

The design findings are closed **as design corrections**, not as accepted authority.
Implementation is still **blocked on authority** for the hard decisions in the packet:

* materialization manifest/store authority (D1);
* fingerprint and platform/environment identity treatment (D2);
* immutability/containment claim and its literal-acceptance conflict (D3);
* native evidence channel (D4);
* native artifact schema (D5);
* native verification vs scientific assessment (D6);
* sealed-bundle self-containment and retention (D9);
* subprocess SUT executable closure, if any subprocess SUT is ever claimed (D13).

The audit's conclusion remains `BLOCKED_AUTHORITY` for implementation, not because the
design is missing, but because the accepted authority does not authorize the native channel,
does not define the materialization manifest/store, and does not authorize a same-user
immutability claim. Revision 2 makes those limits explicit instead of designing around them.

## Non-claims

Nothing in this package claims:

* implementation of materialization or native evidence;
* a change to `RunSpec`, the v1 worker protocol, or any accepted ADR;
* canonical normalization, assessment, or a scientific VVUQ PASS;
* that A1 detection is same-user immutability or OS-enforced containment;
* that runtime/library bytes are content-addressed scientific inputs;
* OpenSim, generic model loading, controller optimization, inverse dynamics, or a loaded
  CMJ realization;
* a release, production UI run command, or remote scheduling;
* that a repository document is authority.

## Review instruction

Review the authority audit first, then the trust-boundary design, then the decision
packet, then the execution plan. Do not approve an implementation slice until its hard
decisions are recorded in Linear and the corresponding ADR/spec amendment is accepted.
Review the exact revised head; doc-only green CI is not implementation qualification.
