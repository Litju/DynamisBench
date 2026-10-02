"""Capability compatibility and the applicability hook.

ADR-003 makes capability contracts the compatibility question: a realization
advertises what it can provide, and a study, a scenario and a system under test
declare what they need. Planning is where those two sides meet, and it is the only
place where a mismatch can be caught before a worker is started.

Two decisions are made here explicitly, because both are ways planning could easily
overclaim:

**The union is a union, not an intersection.** A candidate's effective requirements
are the deterministic union of the study's, the active scenario's and the system under
test's requirements for one capability. A capability that any one of them marks
essential is essential for the candidate, so ``essential`` is the OR of the declaring
flags. Weakening it — "the study says optional, so it is optional" — would let a
scenario that cannot run at all be planned because the study that contains it was
indifferent.

**Declared limitations are not interpreted.** A realization records what its
advertisement does not cover, in prose. Planning carries that prose through unchanged
and does not try to read it, because deciding whether a sentence about a limitation
forbids the study would be a natural-language judgement dressed up as a compatibility
check. The limitations travel so a reader can see them; the verdict is taken from the
advertisement, which is typed.

The same restraint governs the applicability assessment. A benchmark release's
applicability domain is free text, and this planner will not pretend to have decided
whether a run falls inside it. What it provides instead is an explicit, validated
assessment that is *unassessed* until something with authority to judge says
otherwise.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import model_validator

from dynamisbench.domain.spec.base import (
    DomainModel,
    NonEmptyText,
    ShortText,
    keyed_by,
    unique_items,
)
from dynamisbench.domain.spec.capability import Capability, CapabilityRequirement
from dynamisbench.domain.spec.identifiers import BenchmarkId
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition
from dynamisbench.domain.spec.studies import StudyDefinition
from dynamisbench.domain.spec.sut import SUTDefinition
from dynamisbench.planning.errors import IncompatibleCapabilityError


class CapabilityRequirementSource(StrEnum):
    """Which independently versioned authority declared a requirement.

    The three sources are kept apart because they are three different obligations. A
    study's requirement is a property of the research question, a scenario's is a
    property of the frozen benchmark release, and a system under test's is a property
    of the object under test. Merging them loses which one a reader has to go and
    change in order to relax a candidate.
    """

    STUDY = "study"
    SCENARIO = "scenario"
    SYSTEM_UNDER_TEST = "sut"


class CapabilityDemand(DomainModel):
    """One declared requirement, together with the authority that declared it."""

    source: CapabilityRequirementSource
    rationale: ShortText
    essential: bool


class EffectiveCapabilityRequirement(DomainModel):
    """One capability's merged requirement for a single candidate execution.

    ``demands`` is keyed by source, which is correct rather than convenient: a study, a
    scenario and a system under test can each declare a capability at most once, so
    there is at most one demand per source and a second one would be authority that
    means nothing.
    """

    capability: Capability
    essential: bool
    demands: Annotated[tuple[CapabilityDemand, ...], keyed_by("source")]


class CapabilityProvision(DomainModel):
    """What a realization advertises for one capability, with its stated limits.

    ``limitations`` is copied through as declared. It is explanatory authority, and the
    module docstring is explicit that nothing here infers from it.
    """

    capability: Capability
    summary: ShortText
    limitations: tuple[ShortText, ...] = ()


class CapabilityCompatibility(DomainModel):
    """Whether one candidate's effective requirements are met by its realization.

    ``unmet_optional`` is the reason this is recorded rather than merely raised on: a
    missing non-essential requirement is a scientific decision the study already made
    when it marked the capability optional, and it must stay visible on the plan rather
    than disappear because planning was willing to proceed.
    """

    requirements: Annotated[tuple[EffectiveCapabilityRequirement, ...], keyed_by("capability")]
    provisions: Annotated[tuple[CapabilityProvision, ...], keyed_by("capability")]
    unmet_essential: Annotated[tuple[Capability, ...], unique_items()] = ()
    unmet_optional: Annotated[tuple[Capability, ...], unique_items()] = ()

    @property
    def satisfied(self) -> bool:
        """Whether every essential requirement of this candidate is provided."""
        return not self.unmet_essential


def _merged_requirements(
    declarations: tuple[tuple[CapabilityRequirementSource, tuple[CapabilityRequirement, ...]], ...],
) -> tuple[EffectiveCapabilityRequirement, ...]:
    """Merge requirements from several sources with essential-OR semantics.

    ``keyed_by`` on each source's own collection already gave one requirement per
    capability per source, so merging is a group-by-capability over at most three
    demands. The merged result is keyed by capability, which both fixes the order and
    refuses a capability claimed twice by one source.
    """

    merged: dict[Capability, list[CapabilityDemand]] = {}
    essential: dict[Capability, bool] = {}
    for source, requirements in declarations:
        for requirement in requirements:
            merged.setdefault(requirement.capability, []).append(
                CapabilityDemand(
                    source=source,
                    rationale=requirement.rationale,
                    essential=requirement.essential,
                )
            )
            essential[requirement.capability] = (
                essential.get(requirement.capability, False) or requirement.essential
            )
    return tuple(
        EffectiveCapabilityRequirement(
            capability=capability,
            essential=essential[capability],
            demands=tuple(sorted(demands, key=lambda demand: demand.source.value)),
        )
        for capability, demands in sorted(merged.items(), key=lambda item: item[0].value)
    )


def assess_capabilities(
    *,
    study: StudyDefinition,
    scenario: ScenarioDefinition,
    system_under_test: SUTDefinition,
    realization: RealizationDefinition,
) -> CapabilityCompatibility:
    """Assess one candidate execution, or refuse it.

    :raises IncompatibleCapabilityError: if the realization advertises no capability
        for an essential requirement. The error is raised rather than the candidate
        being dropped: dropping it would produce a smaller plan that still looks
        complete, and a study that silently loses its only realization has not been
        planned, it has been quietly rewritten.
    """

    requirements = _merged_requirements(
        (
            (CapabilityRequirementSource.STUDY, study.required_capabilities),
            (CapabilityRequirementSource.SCENARIO, scenario.required_capabilities),
            (
                CapabilityRequirementSource.SYSTEM_UNDER_TEST,
                system_under_test.required_capabilities,
            ),
        )
    )
    provisions = tuple(
        CapabilityProvision(
            capability=declaration.capability,
            summary=declaration.summary,
            limitations=declaration.limitations,
        )
        for declaration in realization.capabilities
    )
    provided = frozenset(declaration.capability for declaration in realization.capabilities)
    missing = tuple(
        requirement.capability
        for requirement in requirements
        if requirement.capability not in provided
    )
    essential = {requirement.capability: requirement.essential for requirement in requirements}
    compatibility = CapabilityCompatibility(
        requirements=requirements,
        provisions=provisions,
        unmet_essential=tuple(capability for capability in missing if essential[capability]),
        unmet_optional=tuple(capability for capability in missing if not essential[capability]),
    )
    if compatibility.unmet_essential:
        plural = "y" if len(compatibility.unmet_essential) == 1 else "ies"
        raise IncompatibleCapabilityError(
            f"realization {realization.realization_id!r} version {realization.version} does "
            f"not provide the essential capabilit{plural} "
            f"{[item.value for item in compatibility.unmet_essential]}, which scenario "
            f"{scenario.scenario_id!r} and study {study.study_id!r} require; planning "
            "refuses to produce a RunSpec for a configuration that cannot execute"
        )
    return compatibility


class ApplicabilityState(StrEnum):
    """Where a planned run stands relative to a benchmark's declared applicability.

    ``UNASSESSED`` is the state a pure planner produces and the only honest default:
    the release's applicability domain is prose, and no amount of reading it
    constitutes an assessment. The other two states are reachable only by supplying an
    :class:`ApplicabilityAssessment` explicitly.
    """

    UNASSESSED = "unassessed"
    WITHIN_DECLARED_DOMAIN = "within_declared_domain"
    OUTSIDE_DECLARED_DOMAIN = "outside_declared_domain"


class ApplicabilityAssessment(DomainModel):
    """An explicit statement about a run's standing in the declared domain.

    ``rationale`` is required whenever a state is asserted and forbidden while
    unassessed, so an assertion cannot be a bare flag: either someone says on what
    basis a run is inside the domain, or the plan says nothing. An outside-domain run
    is not prohibited — it is *distinguishable*, so a later claim cannot inherit
    in-domain credibility without an assessment saying so (VVUQ Workflow, Claim
    discipline).
    """

    state: ApplicabilityState = ApplicabilityState.UNASSESSED
    rationale: NonEmptyText | None = None

    @model_validator(mode="after")
    def _an_asserted_state_is_justified(self) -> Self:
        asserted = self.state is not ApplicabilityState.UNASSESSED
        justified = self.rationale is not None
        if asserted and not justified:
            raise ValueError(
                f"an applicability state of {self.state.value!r} must state a rationale; "
                "an assessment with no stated basis is the unassessed state"
            )
        if justified and not asserted:
            raise ValueError(
                "an applicability rationale was supplied for a run whose state is "
                "unassessed; state the assessment it justifies"
            )
        return self

    @property
    def asserted(self) -> bool:
        """Whether someone with authority to judge has made a statement."""
        return self.state is not ApplicabilityState.UNASSESSED


UNASSESSED_APPLICABILITY = ApplicabilityAssessment()
"""The assessment a pure planner produces for every planned run."""


class ApplicabilityDeclaration(DomainModel):
    """An applicability assessment a caller states for one referenced benchmark.

    This is the hook, and it is deliberately weak. Planning does not *decide*
    applicability — it cannot — so a caller who has a benchmark-specific criterion, a
    validated domain membership check, or a human judgement supplies the assessment and
    planning carries it onto every run of that benchmark. A declaration naming a
    benchmark the study does not reference is dangling authority and is refused.
    """

    benchmark: BenchmarkId
    assessment: ApplicabilityAssessment = UNASSESSED_APPLICABILITY
