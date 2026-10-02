"""``RunSpec`` and ``ExecutionFingerprint``: the execution identity boundary.

``RunSpec`` is the exact set of inputs that can change one run's scientific or
runtime result, and nothing else. It is therefore built from resolved content
identities (:class:`~dynamisbench.planning.authority.ResolvedRef`) rather than from
names, because a name can be re-pointed at different content and a run must not be
able to discover that at execution time.

The identity of those inputs is a *fourth* digest, distinct from the three that
already exist (Architecture section 7, Evidence & Provenance Model, "Identity"):

* :class:`~dynamisbench.identity.SemanticDigest` — the meaning of one definition;
* :class:`~dynamisbench.identity.AssetDigest` — the bytes of one asset;
* :class:`~dynamisbench.evidence.manifest.EvidenceDigest` — what a run produced;
* :class:`ExecutionFingerprint` — what a run was *asked to do*.

They answer different questions, so they are different types. A fingerprint may never
be compared against an evidence digest to decide whether two runs agree, and it may
never be stored where a semantic digest is expected: the whole value of keeping them
apart is that "we asked for the same thing" and "we got the same thing" stay
separately checkable.

What the fingerprint deliberately does not contain is the point of the type:

    replicate index, plan ordinal, factor-case name, a future run id, the study's
    research question or analysis plan, timestamps, the host, the user, and the
    workspace path.

One consequence is a requirement rather than an accident. Two replicates of one
configuration at one seed *must* share an execution fingerprint, because the execution
they request is identical. Their evidence digests may then differ, and that
difference is nondeterminism evidence worth keeping. Hiding it by folding the
replicate index into the fingerprint would destroy the only signal that can expose it.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict

from dynamisbench.domain.spec.base import DomainModel, keyed_by, unique_items
from dynamisbench.domain.spec.identifiers import Name, Sha256Hex
from dynamisbench.identity import DigestAlgorithm, canonical_semantic_bytes
from dynamisbench.planning.authority import (
    ResolvedBenchmarkRef,
    ResolvedEnvironmentRef,
    ResolvedRealizationRef,
    ResolvedScenarioRef,
    ResolvedSUTRef,
)
from dynamisbench.planning.factors import FactorAssignment

RUN_SPEC_SCHEMA_VERSION: Literal["0.1.0"] = "0.1.0"
"""The schema version of ``RunSpec``.

Recorded inside the fingerprinted meaning on purpose: a RunSpec whose *fields* are
unchanged but whose interpretation is not is a different execution, and the two must
not be able to share a fingerprint. Adding a field will change the fingerprint too,
because canonicalisation sorts properties and the new property is a new member of the
object; this version is what covers the case where a field is unchanged and its
meaning is not.
"""


class RunSpec(DomainModel):
    """The exact execution-defining authority and runtime inputs of one run.

    Every independently versioned authority is present *and* content-bound:

    * ``benchmark`` — the frozen release, whose scenarios, quantities and canonical
      units govern this run;
    * ``scenario`` — the one case of that release being evaluated, bound to its own
      digest as well as to the release's, so the execution trace names both the
      artifact and the case inside it;
    * ``realization`` — the executable implementation, whose mappings and transforms are
      pinned by its digest rather than copied here;
    * ``system_under_test`` — the object under test;
    * ``environment`` — the exact scientific execution environment (ADR-009, ADR-018);
    * ``factors`` — the exact active factor assignments, with canonical units;
    * ``seed`` — the declared seed;
    * ``outcomes`` — the requested outputs, which decide what is extracted at all.

    ``outcomes`` is included because the requested output set changes what a run
    computes and computes. Planning does not constrain it further: the domain declares
    outcomes as study-level names, not as benchmark quantities, so validating them
    against the release's quantity authority would be inventing a rule the authority
    does not state.

    What is absent is as load-bearing as what is present. ``replicates``,
    ``research_question``, ``analysis_plan``, the study description and label, any
    timestamp, host name or workspace path are not here. Planning verified that none
    of them is reachable from this model, which is what lets a plan be compiled on a
    developer's machine and executed on another and still be the same execution.
    """

    schema_version: Literal["0.1.0"] = RUN_SPEC_SCHEMA_VERSION
    benchmark: ResolvedBenchmarkRef
    scenario: ResolvedScenarioRef
    realization: ResolvedRealizationRef
    system_under_test: ResolvedSUTRef
    environment: ResolvedEnvironmentRef
    factors: Annotated[tuple[FactorAssignment, ...], keyed_by("factor_id")] = ()
    seed: int
    outcomes: Annotated[tuple[Name, ...], unique_items()] = ()


class ExecutionFingerprint(BaseModel):
    """The SHA-256 of the canonical meaning of one ``RunSpec``.

    A cryptographic identity, never a name, and never a substitute for the RunSpec it
    identifies: a worker still needs to know *which* realization, environment and
    factors it was given, and the fingerprint is not a substitute for knowing.

    It is a separate type from :class:`~dynamisbench.identity.SemanticDigest`,
    :class:`~dynamisbench.identity.AssetDigest` and
    :class:`~dynamisbench.evidence.manifest.EvidenceDigest` because it answers a
    fourth question. ``algorithm`` reuses the existing digest vocabulary rather than
    introducing a cryptography abstraction, exactly as RES-229 and RES-231 did: SHA-256
    is the only algorithm, recorded so that a future change is a visible schema change
    and two fingerprints can never be compared without saying which produced them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal[DigestAlgorithm.SHA256] = DigestAlgorithm.SHA256
    hex: Sha256Hex


def canonical_run_spec_bytes(spec: RunSpec) -> bytes:
    """The RFC 8785 canonical bytes a fingerprint is taken over.

    There is no second serializer and no bespoke RunSpec encoding. The bytes are the
    existing semantic boundary applied to a validated domain object, which is why
    property order, whitespace and the authoring order of an order-insensitive
    collection cannot reach a fingerprint (ADR-006).
    """

    return canonical_semantic_bytes(spec)


def execution_fingerprint_of_canonical_bytes(canonical: bytes) -> ExecutionFingerprint:
    """Fingerprint an already-canonical ``RunSpec`` byte string.

    The argument is named for what it must be — the output of
    :func:`canonical_run_spec_bytes` — because a hash over bytes that were not
    canonical would depend on the serialiser rather than on the execution, and would
    therefore be a different value for the same execution. The hash comes from the
    standard library and the algorithm name from the existing identity vocabulary, so
    this adds no cryptography abstraction of its own.
    """

    return ExecutionFingerprint(hex=hashlib.sha256(canonical).hexdigest())


def run_spec_fingerprint(spec: RunSpec) -> ExecutionFingerprint:
    """The execution fingerprint of ``spec``.

    Total, pure, and a function of the RunSpec alone. Nothing about where the plan was
    compiled, in what order its inputs were supplied, under which Python hash seed, or
    for which replicate can reach it, which is the whole reason the replicate-index
    requirement below is met by construction rather than by a filter:

        same RunSpec, same seed, different replicate index
            -> the same ExecutionFingerprint
    """

    return execution_fingerprint_of_canonical_bytes(canonical_run_spec_bytes(spec))
