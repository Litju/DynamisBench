"""Deterministic compilation of validated authority into exact execution intent.

Planning is a compiler, not a scheduler. It turns one validated
:class:`~dynamisbench.domain.spec.studies.StudyDefinition` plus the validated definitions
it references into an ordered, deterministic set of planned executions, each carrying one
:class:`RunSpec` and the :class:`ExecutionFingerprint` of that spec's meaning.

This gate establishes the two identity-bearing types and the factor vocabulary they are
built from.

:class:`RunSpec`
    Only the exact authority and runtime inputs that can change one run's scientific or
    runtime result. It is built from resolved content identities rather than from names,
    because a name can be re-pointed at different content and a run must not discover
    that at execution time.

:class:`ExecutionFingerprint`
    SHA-256 over the RFC 8785 canonical bytes of a RunSpec's meaning — a *fourth* digest
    alongside the semantic, asset and evidence digests, answering "what was this run asked
    to do" where the others answer "what did this mean", "what were these bytes" and "what
    was produced".

What the fingerprint deliberately does not contain is the point of the type: replicate
index, plan ordinal, factor-case name, a future run id, the study's research question or
analysis plan, timestamps, the host, the user, and the workspace path. Two replicates of
one configuration at one seed therefore share a fingerprint, because they request the same
execution — and later differing evidence digests under one fingerprint are exactly the
nondeterminism evidence the architecture asks for.

:class:`FactorCase`
    One explicit, exact assignment of a study's varied factors. Controlled factors resolve
    from the study itself and may not be restated. RES-232 samples nothing, so a varied
    factor's value must arrive in a case; future Sobol / QMC / SALib sampling produces
    cases of exactly this shape rather than changing RunSpec semantics.
"""

from dynamisbench.planning.authority import (
    PlanningContext,
    ResolvedAuthority,
    ResolvedBenchmarkRef,
    ResolvedEnvironmentRef,
    ResolvedQuantityRef,
    ResolvedRealizationRef,
    ResolvedRef,
    ResolvedScenarioRef,
    ResolvedStudyRef,
    ResolvedSUTRef,
)
from dynamisbench.planning.compatibility import (
    UNASSESSED_APPLICABILITY,
    ApplicabilityAssessment,
    ApplicabilityDeclaration,
    ApplicabilityState,
    CapabilityCompatibility,
    CapabilityDemand,
    CapabilityProvision,
    CapabilityRequirementSource,
    EffectiveCapabilityRequirement,
    assess_capabilities,
)
from dynamisbench.planning.errors import (
    AuthorityResolutionError,
    FactorResolutionError,
    IncompatibleCapabilityError,
    PlanningError,
)
from dynamisbench.planning.factors import FactorAssignment, FactorCase, FactorValue
from dynamisbench.planning.runspec import (
    RUN_SPEC_SCHEMA_VERSION,
    ExecutionFingerprint,
    RunSpec,
    canonical_run_spec_bytes,
    execution_fingerprint_of_canonical_bytes,
    run_spec_fingerprint,
)

__all__ = [
    "RUN_SPEC_SCHEMA_VERSION",
    "UNASSESSED_APPLICABILITY",
    "ApplicabilityAssessment",
    "ApplicabilityDeclaration",
    "ApplicabilityState",
    "AuthorityResolutionError",
    "CapabilityCompatibility",
    "CapabilityDemand",
    "CapabilityProvision",
    "CapabilityRequirementSource",
    "EffectiveCapabilityRequirement",
    "ExecutionFingerprint",
    "FactorAssignment",
    "FactorCase",
    "FactorResolutionError",
    "FactorValue",
    "IncompatibleCapabilityError",
    "PlanningContext",
    "PlanningError",
    "ResolvedAuthority",
    "ResolvedBenchmarkRef",
    "ResolvedEnvironmentRef",
    "ResolvedQuantityRef",
    "ResolvedRealizationRef",
    "ResolvedRef",
    "ResolvedSUTRef",
    "ResolvedScenarioRef",
    "ResolvedStudyRef",
    "RunSpec",
    "assess_capabilities",
    "canonical_run_spec_bytes",
    "execution_fingerprint_of_canonical_bytes",
    "run_spec_fingerprint",
]
