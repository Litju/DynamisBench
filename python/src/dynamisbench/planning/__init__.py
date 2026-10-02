"""Deterministic compilation of validated authority into exact execution intent.

Planning is a compiler, not a scheduler. It turns one validated
:class:`~dynamisbench.domain.spec.studies.StudyDefinition` plus the validated definitions
it references into a :class:`StudyPlan`: an ordered, deterministic set of
:class:`PlannedRun` instances, each carrying one :class:`RunSpec` and the
:class:`ExecutionFingerprint` of that spec's meaning.

Four concepts are kept distinct on purpose, because collapsing any two of them makes some
later question unanswerable:

``StudyPlan``
    The expansion of one study, identified by the study's semantic identity. It carries
    the study's research prose as a *digest* and nowhere else.

``PlannedRun``
    One planned instance. Its ordinal, factor-case identity and replicate index distinguish
    planned instances of the same execution and are never execution-defining.

``RunSpec``
    Only the exact authority and runtime inputs that can change a run's scientific or
    runtime result: resolved benchmark, scenario, realization, system under test,
    environment, active factor assignments, seed, and requested outcomes.

``ExecutionFingerprint``
    SHA-256 over the RFC 8785 canonical bytes of a RunSpec's meaning — a fourth digest
    alongside the semantic, asset and evidence digests, answering "what was this run
    asked to do" where the others answer "what did this mean", "what were these bytes"
    and "what was produced".

Three properties follow and are why the package is shaped this way.

**Replicates share a fingerprint.** Two replicates of one configuration at one seed
request the same execution, so they have the same fingerprint; later, differing evidence
digests under one fingerprint are nondeterminism evidence. Both planned runs are kept.
Nothing is deduplicated because their fingerprints match.

**The expansion is the authority.** Every compatible benchmark/realization pair, times
every scenario of that release, times every referenced system under test, times every
referenced environment, times every factor case, times every declared seed, times every
replicate index. The study model has no scenario subset, so a referenced benchmark
contributes every scenario and no selector is invented.

**The planner is pure.** It creates no directory, touches no ``.staging`` or ``runs/``,
writes no evidence, reads no arbitrary file, inspects no installed package, spawns no
process, installs no environment, samples no distribution, reads no clock, and reaches
no network or hidden state. It is a function of its arguments, and
``tests/planning/test_public_boundary.py`` proves the boundaries structurally rather
than by reading the code.

Continuous and discrete UQ sampling is deliberately not here. A study with varied factors
is expanded from :class:`FactorCase` inputs the caller supplies; future Sobol / QMC /
SALib sampling produces those same inputs rather than changing RunSpec semantics (VVUQ
Workflow, Factors). Actually installed-runtime satisfaction and engine/toolchain preflight
belong to execution, not here.
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
from dynamisbench.planning.plan import (
    BASELINE_CASE_ID,
    PlannedRun,
    QuantityCoverage,
    RealizationBinding,
    StudyPlan,
    plan_study,
)
from dynamisbench.planning.runspec import (
    RUN_SPEC_SCHEMA_VERSION,
    ExecutionFingerprint,
    RunSpec,
    canonical_run_spec_bytes,
    execution_fingerprint_of_canonical_bytes,
    run_spec_fingerprint,
)

__all__ = [
    "BASELINE_CASE_ID",
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
    "PlannedRun",
    "PlanningContext",
    "PlanningError",
    "QuantityCoverage",
    "RealizationBinding",
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
    "StudyPlan",
    "assess_capabilities",
    "canonical_run_spec_bytes",
    "execution_fingerprint_of_canonical_bytes",
    "plan_study",
    "run_spec_fingerprint",
]
