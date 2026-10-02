"""``StudyPlan``, ``PlannedRun``, and the compiler that produces them.

Planning is a compiler from validated authority to exact execution intent:

    StudyDefinition + resolved authority + explicit factor cases
        -> StudyPlan
        -> PlannedRun[]
        -> RunSpec
        -> ExecutionFingerprint

It performs no execution. Nothing here starts a worker, installs an environment,
creates a run directory, writes evidence, samples a distribution, reads the clock, or
knows that a filesystem exists. Run identity belongs to the execution lifecycle, so no
run id is invented and no staging bundle is created: a planned run is a request, and
the identity of the thing that answers it is a later question.

**Expansion is the authority.** The plan is the deterministic Cartesian product of

    every compatible benchmark/realization pair
      x every scenario of that benchmark release
      x every referenced system under test
      x every referenced environment
      x every factor case
      x every declared seed
      x every replicate index 0..replicates-1

A referenced benchmark contributes *all* of its scenarios. The study model has no
scenario subset, so a scenario filter, a default scenario or a first-scenario rule
would be an invented selector with no authority behind it. A future need for scenario
selection is a domain-model amendment, not a planning parameter.

**Order is canonical.** Runs are sorted by one documented key built only from
authoritative logical values — benchmark, realization, scenario, system under test,
environment, factor case, seed, replicate index — and each ordinal is assigned after
sorting. Nothing about the caller's input order, the platform, or the clock reaches
the order.

**Replicates are distinct instances with identical configuration.** Repeating a
configuration ``n`` times produces ``n`` planned runs that intentionally share one
execution fingerprint, because they request the same execution. That is not a
duplication to be cleaned up: later, differing evidence digests under one fingerprint
are exactly the nondeterminism evidence the architecture asks for, and a planner that
folded the replicate index into the fingerprint would have destroyed the signal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Self

from pydantic import Field, model_validator

from dynamisbench.domain.spec.base import DomainModel, keyed_by, unique_items
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    EnvironmentId,
    FactorId,
    Name,
    QuantityId,
    RealizationId,
    ScenarioId,
    SUTId,
)
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition
from dynamisbench.domain.spec.studies import (
    FactorTargetKind,
    StudyDefinition,
    UncertaintyFactorDefinition,
)
from dynamisbench.domain.spec.sut import SUTDefinition
from dynamisbench.identity import semantic_sha256
from dynamisbench.planning.authority import (
    PlanningContext,
    ResolvedAuthority,
    ResolvedBenchmarkRef,
    ResolvedEnvironmentRef,
    ResolvedRealizationRef,
    ResolvedStudyRef,
    ResolvedSUTRef,
)
from dynamisbench.planning.compatibility import (
    UNASSESSED_APPLICABILITY,
    ApplicabilityAssessment,
    ApplicabilityDeclaration,
    CapabilityCompatibility,
    assess_capabilities,
)
from dynamisbench.planning.errors import AuthorityResolutionError, FactorResolutionError
from dynamisbench.planning.factors import (
    FactorAssignment,
    FactorCase,
    FactorSet,
    active_factors,
    assignment,
    case_values,
    check_support,
    controlled_factors,
    controlled_value,
    varied_factors,
)
from dynamisbench.planning.runspec import ExecutionFingerprint, RunSpec, run_spec_fingerprint

BASELINE_CASE_ID: Name = "baseline"
"""The case identifier a study with no varied factors is given.

``baseline`` rather than ``default``: there is no default scenario, no default
factorisation and no default authority anywhere in this package, and a name implying
one would be the same mistake wearing a different word.
"""

type _Binding = tuple[
    ResolvedAuthority[BenchmarkRelease, BenchmarkId],
    ResolvedAuthority[RealizationDefinition, RealizationId],
]
"""A resolved realization together with the benchmark release it declares."""

type _PlanSortKey = tuple[str, str, str, str, str, str, str, str, str, str, str, int, int]
"""The canonical plan order: eleven identifiers/versions, then seed, then replicate.

Every element has a fixed type at its position, so the lexicographic comparison Python
performs never has to compare unlike values, and the key is a total order over
authoritative logical values alone.
"""


class QuantityCoverage(DomainModel):
    """Which canonical quantities of a benchmark a realization does and does not map.

    The current authority does not state that a realization must map *every* quantity,
    and it must not be assumed to: that would turn this planner into the inventor of a
    coverage requirement the domain never declared. What the authority does state is
    that a mapping names a quantity the benchmark declares, and that is checked. The
    gap between the two is *reported* here rather than silently accepted, so a study
    that will not be able to observe a quantity it asked for can see that from the plan
    instead of from a failed run.
    """

    mapped: Annotated[tuple[QuantityId, ...], unique_items()] = ()
    unmapped: Annotated[tuple[QuantityId, ...], unique_items()] = ()


class RealizationBinding(DomainModel):
    """A realization resolved against the benchmark release it declares.

    The pairing is recorded rather than left for the reader to infer. A realization is a
    candidate only for ``RealizationDefinition.benchmark``, so a study referencing two
    benchmarks and two realizations yields two pairs and not four, and this is where
    the plan states which is which.
    """

    realization: ResolvedRealizationRef
    benchmark: ResolvedBenchmarkRef
    quantity_coverage: QuantityCoverage


class PlannedRun(DomainModel):
    """One planned execution instance: plan metadata around one RunSpec.

    Everything on this type that is *not* on the RunSpec is plan-instance metadata:
    which factor case produced it, which replicate it is, where it sits in canonical
    order, and the compatibility and applicability assessments that explain why it is
    allowed to exist. None of it is execution-defining, and none of it can reach the
    execution fingerprint, which is exactly why these fields live here and not there.
    """

    ordinal: Annotated[int, Field(ge=0)]
    factor_case: Name
    replicate_index: Annotated[int, Field(ge=0)]
    spec: RunSpec
    fingerprint: ExecutionFingerprint
    capabilities: CapabilityCompatibility
    applicability: ApplicabilityAssessment


class StudyPlan(DomainModel):
    """The deterministic expansion of exactly one validated ``StudyDefinition``.

    The study is identified by its resolved reference — identifier, version and
    semantic digest — and not by its prose. The research question, the analysis plan,
    the label and the description stay here as a *digest* and nowhere else: they are
    what the plan is for, but they cannot change what any single run executes, and
    carrying them into a RunSpec would make two runs of one configuration differ
    because someone reworded a paragraph.

    ``runs`` is in canonical order and ``ordinal`` is the position in that order. Both
    are validated here rather than assumed, because a plan whose stated order and
    actual order disagree is a plan nobody can reason about.
    """

    study: ResolvedStudyRef
    benchmarks: Annotated[tuple[ResolvedBenchmarkRef, ...], keyed_by("identifier")]
    bindings: Annotated[tuple[RealizationBinding, ...], keyed_by("realization")]
    systems_under_test: Annotated[tuple[ResolvedSUTRef, ...], keyed_by("identifier")]
    environments: Annotated[tuple[ResolvedEnvironmentRef, ...], keyed_by("identifier")]
    factor_cases: Annotated[tuple[FactorCase, ...], keyed_by("case_id")]
    runs: Annotated[tuple[PlannedRun, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _runs_agree_with_their_own_ordinals_and_fingerprints(self) -> Self:
        for position, run in enumerate(self.runs):
            if run.ordinal != position:
                raise ValueError(
                    f"the planned run at position {position} declares ordinal "
                    f"{run.ordinal}; an ordinal is the position in canonical order"
                )
            if run.fingerprint != run_spec_fingerprint(run.spec):
                raise ValueError(
                    f"the planned run at position {position} carries a fingerprint that is "
                    "not the SHA-256 of its own RunSpec; a plan may not assert an execution "
                    "identity it did not compute"
                )
        return self


@dataclass(frozen=True)
class _Candidate:
    """The authorities one candidate execution is built from.

    Held as a value rather than threaded through seven parameters, because the factor
    logic has to ask "is this factor's target one of my four authorities?" and answering
    that from one object is the only way to keep the four kinds from being confused.
    """

    context: PlanningContext
    benchmark: ResolvedAuthority[BenchmarkRelease, BenchmarkId]
    scenario: ResolvedAuthority[ScenarioDefinition, ScenarioId]
    realization: ResolvedAuthority[RealizationDefinition, RealizationId]
    system_under_test: ResolvedAuthority[SUTDefinition, SUTId]
    environment: ResolvedAuthority[EnvironmentDefinition, EnvironmentId]

    def active_identifier(self, kind: FactorTargetKind) -> str:
        """The one nominal identifier of this candidate a factor of this kind may target."""
        match kind:
            case FactorTargetKind.BENCHMARK_QUANTITY:
                return str(self.benchmark.reference.identifier)
            case FactorTargetKind.REALIZATION:
                return str(self.realization.reference.identifier)
            case FactorTargetKind.SUT:
                return str(self.system_under_test.reference.identifier)
            case FactorTargetKind.ENVIRONMENT:
                return str(self.environment.reference.identifier)


def _resolve_factor_targets(
    study: StudyDefinition,
    benchmarks: tuple[ResolvedAuthority[BenchmarkRelease, BenchmarkId], ...],
    realizations: tuple[ResolvedAuthority[RealizationDefinition, RealizationId], ...],
    systems_under_test: tuple[ResolvedAuthority[SUTDefinition, SUTId], ...],
    environments: tuple[ResolvedAuthority[EnvironmentDefinition, EnvironmentId], ...],
) -> dict[FactorTargetKind, frozenset[str]]:
    """Resolve every factor target against the study's referenced authority, or refuse.

    The returned map is what "referenced" means for factor targeting: the nominal
    identifiers a factor of each kind may legitimately name. A target naming anything
    else is dangling authority — it would vary an object the study never consumes, and
    the value would silently apply to nothing.

    A target is matched on its nominal identifier, not on a version.
    ``FactorTarget`` is deliberately a name plus a parameter rather than a versioned
    reference: the target says *which object* a factor varies, and the exact version of
    that object is already pinned by the candidate's resolved references.
    """

    referenced: dict[FactorTargetKind, frozenset[str]] = {
        FactorTargetKind.BENCHMARK_QUANTITY: frozenset(
            item.reference.identifier for item in benchmarks
        ),
        FactorTargetKind.REALIZATION: frozenset(item.reference.identifier for item in realizations),
        FactorTargetKind.SUT: frozenset(item.reference.identifier for item in systems_under_test),
        FactorTargetKind.ENVIRONMENT: frozenset(item.reference.identifier for item in environments),
    }
    for factor in study.factors:
        if factor.target.identifier not in referenced[factor.target.kind]:
            raise AuthorityResolutionError(
                f"factor {factor.factor_id!r} targets {factor.target.kind.value} "
                f"{factor.target.identifier!r}, which study {study.study_id!r} does not "
                "reference; a factor may only vary authority the study consumes"
            )
    return referenced


def _resolve_factor_cases(
    study: StudyDefinition, factor_cases: tuple[FactorCase, ...] | None
) -> tuple[FactorCase, ...]:
    """Return the exact factor cases this study is expanded with, in canonical order.

    A study with varied factors gets the caller's cases and must get all of them: there
    is no way to invent a value for a distribution without sampling it, and sampling is
    not this issue's work. A study with none gets exactly one synthesized baseline case,
    because a case with no values is still a case and the product's cardinality must
    have exactly one factor-case factor either way.
    """

    varied = varied_factors(study.factors)
    required = tuple(factor.factor_id for factor in varied)
    if not required:
        if factor_cases:
            raise FactorResolutionError(
                f"study {study.study_id!r} varies no factor, so it is expanded with one "
                f"baseline case; {len(factor_cases)} factor case(s) were supplied and there "
                "is nothing for them to assign"
            )
        return (FactorCase(case_id=BASELINE_CASE_ID),)

    if not factor_cases:
        raise FactorResolutionError(
            f"study {study.study_id!r} varies factor(s) {[str(item) for item in required]} "
            "and no factor cases were supplied; planning does not sample a distribution, so "
            "every varied factor needs an exact value"
        )

    controlled = {factor.factor_id for factor in controlled_factors(study.factors)}
    declared = {factor.factor_id for factor in study.factors}
    for case in factor_cases:
        assigned = set(case_values(case))
        overriding = sorted(str(item) for item in assigned & controlled)
        if overriding:
            raise FactorResolutionError(
                f"factor case {case.case_id!r} assigns controlled factor(s) {overriding}; a "
                "controlled factor's value is already declared by the study and a case may "
                "not override it"
            )
        unknown = sorted(str(item) for item in assigned - declared)
        if unknown:
            raise FactorResolutionError(
                f"factor case {case.case_id!r} assigns factor(s) {unknown}, which study "
                f"{study.study_id!r} does not declare"
            )
        missing = [str(item) for item in required if item not in assigned]
        if missing:
            raise FactorResolutionError(
                f"factor case {case.case_id!r} does not assign varied factor(s) {missing}; a "
                "case must assign every varied factor exactly once"
            )
        values = case_values(case)
        for factor in varied:
            check_support(factor, values[factor.factor_id])
    return tuple(sorted(factor_cases, key=lambda case: str(case.case_id)))


def _bind_realizations(
    study: StudyDefinition,
    realizations: tuple[ResolvedAuthority[RealizationDefinition, RealizationId], ...],
    benchmarks: tuple[ResolvedAuthority[BenchmarkRelease, BenchmarkId], ...],
) -> tuple[_Binding, ...]:
    """Pair every referenced realization with the benchmark it declares, or refuse.

    A realization bound to a benchmark the study does not reference would produce
    candidate executions against authority the study never named, so that is refused.
    An *unrelated* pair is not a pairing this function constructs, and it is not an
    error either: a study may reference several benchmarks and several realizations and
    the mismatched combinations simply are not candidates.
    """

    by_reference = {
        (str(benchmark.reference.identifier), str(benchmark.reference.version)): benchmark
        for benchmark in benchmarks
    }
    pairs: list[_Binding] = []
    for realization in realizations:
        declared = realization.definition.benchmark
        benchmark = by_reference.get((str(declared.identifier), str(declared.version)))
        if benchmark is None:
            raise AuthorityResolutionError(
                f"realization {realization.reference.identifier!r} version "
                f"{realization.reference.version} declares benchmark "
                f"{declared.identifier!r} version {declared.version}, which study "
                f"{study.study_id!r} does not reference; a realization is a candidate only "
                "for a benchmark the study consumes"
            )
        pairs.append((benchmark, realization))
    return tuple(pairs)


def _quantity_coverage(
    benchmark: BenchmarkRelease, realization: RealizationDefinition
) -> QuantityCoverage:
    """Check a realization's mappings against its benchmark, then report the coverage."""

    declared = {quantity.quantity_id for quantity in benchmark.quantities}
    mapped: set[QuantityId] = set()
    for mapping in realization.quantity_mappings:
        if mapping.quantity not in declared:
            raise AuthorityResolutionError(
                f"realization {realization.realization_id!r} version {realization.version} "
                f"maps {mapping.quantity!r}, which benchmark {benchmark.benchmark_id!r} "
                f"version {benchmark.version} does not declare as a canonical quantity"
            )
        mapped.add(mapping.quantity)
    return QuantityCoverage(
        mapped=tuple(sorted(mapped, key=str)),
        unmapped=tuple(sorted(declared - mapped, key=str)),
    )


def _applicability_by_benchmark(
    study: StudyDefinition,
    benchmarks: tuple[ResolvedAuthority[BenchmarkRelease, BenchmarkId], ...],
    declarations: tuple[ApplicabilityDeclaration, ...],
) -> dict[str, ApplicabilityAssessment]:
    """Index the caller's applicability assessments by benchmark, or refuse a dangling one."""

    if not declarations:
        return {}
    referenced = {str(item.reference.identifier) for item in benchmarks}
    supplied = {str(declaration.benchmark): declaration.assessment for declaration in declarations}
    dangling = sorted(set(supplied) - referenced)
    if dangling:
        raise AuthorityResolutionError(
            f"an applicability declaration names benchmark {dangling}, which study "
            f"{study.study_id!r} does not reference"
        )
    return supplied


def _value_of(factor: UncertaintyFactorDefinition, values: Mapping[FactorId, float]) -> float:
    """The exact value of a factor in one candidate: the case's, or the study's own."""
    if factor.factor_id in values:
        return values[factor.factor_id]
    return controlled_value(factor)


def _active_assignments(
    candidate: _Candidate,
    factors: FactorSet,
    values: Mapping[FactorId, float],
) -> tuple[FactorAssignment, ...]:
    """The factor assignments that are active for this candidate, in canonical order.

    A factor is active only when its declared target is one of this candidate's
    authorities. An inactive factor is not recorded as an assignment with no effect; it
    is absent, because a RunSpec that listed it would claim the run had been told
    something about an object it is not running.

    A controlled factor's value comes from the study, never from the case, so a case
    cannot supply it — that refusal happens earlier, when the cases are resolved. The
    ``values.get`` fallback here is the automatic resolution, not a second way in.
    """

    active = active_factors(
        factors,
        {kind: frozenset({candidate.active_identifier(kind)}) for kind in FactorTargetKind},
    )
    return tuple(
        assignment(
            factor,
            _value_of(factor, values),
            quantity=factor.quantity,
            unit=candidate.context.quantity_of(
                candidate.benchmark.definition, factor.quantity
            ).definition.unit,
        )
        for factor in active
    )


def _run_sort_key(run: PlannedRun) -> _PlanSortKey:
    """The one canonical plan order documented in the module docstring."""

    spec = run.spec
    return (
        str(spec.benchmark.identifier),
        str(spec.benchmark.version),
        str(spec.realization.identifier),
        str(spec.realization.version),
        str(spec.scenario.identifier),
        str(spec.scenario.version),
        str(spec.system_under_test.identifier),
        str(spec.system_under_test.version),
        str(spec.environment.identifier),
        str(spec.environment.version),
        str(run.factor_case),
        spec.seed,
        run.replicate_index,
    )


def _expand(
    *,
    study: StudyDefinition,
    context: PlanningContext,
    bindings: tuple[_Binding, ...],
    systems_under_test: tuple[ResolvedAuthority[SUTDefinition, SUTId], ...],
    environments: tuple[ResolvedAuthority[EnvironmentDefinition, EnvironmentId], ...],
    cases: tuple[FactorCase, ...],
    applicability: dict[str, ApplicabilityAssessment],
) -> tuple[PlannedRun, ...]:
    """Expand the authority's Cartesian product into canonically ordered planned runs.

    Capability assessment happens here, before any RunSpec for that candidate is
    built, so a refusal names the candidate it refuses while that candidate is still
    identifiable.
    """

    ordered: list[tuple[_PlanSortKey, PlannedRun]] = []
    for benchmark, realization in bindings:
        for scenario in benchmark.definition.scenarios:
            resolved_scenario = context.scenario_of(benchmark.definition, scenario.scenario_id)
            for system_under_test in systems_under_test:
                compatibility = assess_capabilities(
                    study=study,
                    scenario=scenario,
                    system_under_test=system_under_test.definition,
                    realization=realization.definition,
                )
                for environment in environments:
                    candidate = _Candidate(
                        context=context,
                        benchmark=benchmark,
                        scenario=resolved_scenario,
                        realization=realization,
                        system_under_test=system_under_test,
                        environment=environment,
                    )
                    assessment = applicability.get(
                        str(benchmark.reference.identifier), UNASSESSED_APPLICABILITY
                    )
                    for case in cases:
                        assignments = _active_assignments(
                            candidate, study.factors, case_values(case)
                        )
                        for seed in study.seeds:
                            for replicate_index in range(study.replicates):
                                spec = RunSpec(
                                    benchmark=candidate.benchmark.reference,
                                    scenario=candidate.scenario.reference,
                                    realization=candidate.realization.reference,
                                    system_under_test=candidate.system_under_test.reference,
                                    environment=candidate.environment.reference,
                                    factors=assignments,
                                    seed=seed,
                                    outcomes=study.outcomes,
                                )
                                run = PlannedRun(
                                    ordinal=0,
                                    factor_case=case.case_id,
                                    replicate_index=replicate_index,
                                    spec=spec,
                                    fingerprint=run_spec_fingerprint(spec),
                                    capabilities=compatibility,
                                    applicability=assessment,
                                )
                                ordered.append((_run_sort_key(run), run))
    ordered.sort(key=lambda entry: entry[0])
    return tuple(
        PlannedRun(
            ordinal=position,
            factor_case=run.factor_case,
            replicate_index=run.replicate_index,
            spec=run.spec,
            fingerprint=run.fingerprint,
            capabilities=run.capabilities,
            applicability=run.applicability,
        )
        for position, (_, run) in enumerate(ordered)
    )


def plan_study(
    study: StudyDefinition,
    context: PlanningContext,
    *,
    factor_cases: tuple[FactorCase, ...] | None = None,
    applicability: tuple[ApplicabilityDeclaration, ...] = (),
) -> StudyPlan:
    """Compile one validated study into a deterministic :class:`StudyPlan`.

    The whole function is a function of its arguments. It reads no clock, no
    environment, no filesystem, no random source and no registry, so two calls with
    equal arguments produce equal plans — equal down to the order of every collection
    and every execution fingerprint.

    :param study: the validated study to expand. Its prose is identified by digest and
        never reaches a RunSpec.
    :param context: the immutable catalog of validated definitions the study's
        references resolve against. Every reference must resolve to exactly one
        definition with the same identifier *and* version.
    :param factor_cases: the exact values for the study's varied factors, one entry per
        factor case. Required when the study varies any factor, and refused when it
        varies none, because then there is nothing for a case to assign.
    :param applicability: explicit applicability assessments, one per referenced
        benchmark. The planner produces no assessment of its own.
    :raises AuthorityResolutionError: a reference did not resolve to exactly one
        definition, a realization is bound to a benchmark the study does not reference,
        a factor target dangles, a realization maps a quantity its benchmark does not
        declare, or an applicability declaration names an unreferenced benchmark.
    :raises IncompatibleCapabilityError: a candidate realization does not provide an
        essential capability.
    :raises FactorResolutionError: the factor cases do not exactly cover the study's
        varied factors, or a value lies outside its declared support.
    """

    benchmarks = tuple(context.resolve_benchmark(item) for item in study.benchmarks)
    realizations = tuple(context.resolve_realization(item) for item in study.realizations)
    systems_under_test = tuple(
        context.resolve_system_under_test(item) for item in study.systems_under_test
    )
    environments = tuple(context.resolve_environment(item) for item in study.environments)

    _resolve_factor_targets(study, benchmarks, realizations, systems_under_test, environments)
    cases = _resolve_factor_cases(study, factor_cases)
    assessments = _applicability_by_benchmark(study, benchmarks, applicability)
    bindings = _bind_realizations(study, realizations, benchmarks)

    return StudyPlan(
        study=ResolvedStudyRef(
            identifier=study.study_id,
            version=study.version,
            semantic_digest=semantic_sha256(study),
        ),
        benchmarks=tuple(item.reference for item in benchmarks),
        bindings=tuple(
            RealizationBinding(
                realization=realization.reference,
                benchmark=benchmark.reference,
                quantity_coverage=_quantity_coverage(benchmark.definition, realization.definition),
            )
            for benchmark, realization in bindings
        ),
        systems_under_test=tuple(item.reference for item in systems_under_test),
        environments=tuple(item.reference for item in environments),
        factor_cases=cases,
        runs=_expand(
            study=study,
            context=context,
            bindings=bindings,
            systems_under_test=systems_under_test,
            environments=environments,
            cases=cases,
            applicability=assessments,
        ),
    )
