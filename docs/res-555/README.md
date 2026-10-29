# RES-555 — Design Review Package

**Status:** Draft for independent architecture, scientific, and security review.
**Not authority. Not an ADR. Not implementation authorization.**

This directory contains the RES-555 Phase A design package for:

> DB-3.3 — Content-addressed model/definition materialization, worker input immutability,
> and native evidence extraction.

The repository is not the architecture authority. The living authority is the Linear
project **DynamisBench — Human Movement Simulation VVUQ & Benchmarking**. These documents
cite that authority and propose bounded changes; they do not replace it. See
`CONTRIBUTING.md`.

## Baseline

| Fact | Value |
|---|---|
| Accepted protected `main` | `2a3ef6016e904de5b218e657f15793dd230250bb` |
| Accepted tree | `51e4b366d0cce3cddfba56e6e0fc1720e0fec421` |
| Protected-main qualification | workflow `quality`, run `40808263238`, nine successful jobs |
| Design branch base | `origin/main` at the accepted commit and tree |
| RES-555 Linear state at audit time | `Todo` |

## Documents

| Document | Purpose |
|---|---|
| [`RES-555_AUTHORITY_AUDIT.md`](RES-555_AUTHORITY_AUDIT.md) | Authority register, authority-to-implementation matrix, confirmed gaps, prohibited interpretations, inspection limits |
| [`RES-555_TRUST_BOUNDARY_DESIGN.md`](RES-555_TRUST_BOUNDARY_DESIGN.md) | Identity model, materialization architecture, Windows/Linux threat model and protection matrix, TOCTOU closure, native evidence design, state machine, protocol compatibility |
| [`RES-555_AUTHORITY_DECISION_PACKET.md`](RES-555_AUTHORITY_DECISION_PACKET.md) | Twelve decisions that require owner approval, with alternatives, consequences, recommendations, amendments, and independent work |
| [`RES-555_EXECUTION_PLAN.md`](RES-555_EXECUTION_PLAN.md) | Four implementation slices, dependency graph, file boundaries, qualification matrix, CI plan, review/merge/post-merge sequence, rollback |

## Verdict requested

The design is complete enough to review, but implementation is **blocked on authority**
for the hard decisions in the packet:

* materialization manifest/store authority (D1);
* fingerprint treatment (D2);
* immutability/containment claim (D3);
* native evidence channel (D4);
* native artifact schema (D5);
* native verification vs scientific assessment (D6);
* sealed-bundle self-containment and retention (D9).

The audit's conclusion is `BLOCKED_AUTHORITY` for implementation, not because the design
is missing, but because the accepted authority does not authorize the native channel or
same-user immutability claim, and does not define the materialization manifest/store.

## Non-claims

Nothing in this package claims:

* implementation of materialization or native evidence;
* a change to `RunSpec`, the v1 worker protocol, or any accepted ADR;
* canonical normalization, assessment, or a scientific VVUQ PASS;
* OpenSim, generic model loading, controller optimization, inverse dynamics, or a loaded
  CMJ realization;
* a release, production UI run command, or remote scheduling;
* that a repository document is authority.

## Review instruction

Review the authority audit first, then the trust-boundary design, then the decision
packet, then the execution plan. Do not approve an implementation slice until its hard
decisions are recorded in Linear and the corresponding ADR/spec amendment is accepted.
