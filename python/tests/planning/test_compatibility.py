"""Capability merging, compatibility verdicts, and the applicability hook.

Two claims are pinned.

**The union is a union.** A candidate's effective requirements are the study's, the
active scenario's and the system under test's, merged per capability with essential-OR.
If a scenario cannot run without a capability, the candidate cannot run without it,
however indifferent the study that contains that scenario is.

**Applicability is explicit and starts unassessed.** A benchmark release states its
applicability domain in prose. This planner will not pretend to have decided whether a
run is inside it, so the default state says so, and asserting any other state requires
saying on what basis.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.capability import Capability
from dynamisbench.planning import (
    UNASSESSED_APPLICABILITY,
    ApplicabilityAssessment,
    ApplicabilityDeclaration,
    ApplicabilityState,
    CapabilityRequirementSource,
    IncompatibleCapabilityError,
    assess_capabilities,
)
from dynamisbench.planning.compatibility import CapabilityCompatibility
from tests.domain import factories as domain
from tests.planning import factories as planning


def assess(**overrides):
    values = {
        "study": planning.study(),
        "scenario": domain.scenario_definition("sc.loaded-cmj"),
        "system_under_test": domain.sut_definition(),
        "realization": domain.realization_definition(),
    }
    values.update(overrides)
    return assess_capabilities(**values)


def advertises(*capabilities: Capability):
    return tuple(domain.capability_declaration(capability) for capability in capabilities)


def forward_dynamics_study(**overrides):
    """A study that needs only what a forward-dynamics realization advertises."""
    values = {
        "required_capabilities": (domain.capability_requirement(Capability.FORWARD_DYNAMICS),)
    }
    values.update(overrides)
    return planning.study(**values)


def test_requirements_come_from_the_study_the_scenario_and_the_system_under_test() -> None:
    compatibility = assess(
        study=forward_dynamics_study(),
        scenario=domain.scenario_definition(
            "sc.loaded-cmj",
            required_capabilities=(domain.capability_requirement(Capability.STATE_SNAPSHOT),),
        ),
        system_under_test=domain.sut_definition(
            required_capabilities=(domain.capability_requirement(Capability.ANALYSIS),)
        ),
        realization=domain.realization_definition(
            capabilities=advertises(
                Capability.FORWARD_DYNAMICS,
                Capability.STATE_SNAPSHOT,
                Capability.ANALYSIS,
            )
        ),
    )

    assert {item.capability for item in compatibility.requirements} == {
        Capability.FORWARD_DYNAMICS,
        Capability.STATE_SNAPSHOT,
        Capability.ANALYSIS,
    }
    sources = {
        requirement.capability: {demand.source for demand in requirement.demands}
        for requirement in compatibility.requirements
    }
    assert sources[Capability.FORWARD_DYNAMICS] == {CapabilityRequirementSource.STUDY}
    assert sources[Capability.STATE_SNAPSHOT] == {CapabilityRequirementSource.SCENARIO}
    assert sources[Capability.ANALYSIS] == {CapabilityRequirementSource.SYSTEM_UNDER_TEST}


def test_the_same_capability_from_three_sources_merges_with_essential_or_semantics() -> None:
    """Essential is the OR of the declaring flags, never the last one or the strictest-looking."""
    compatibility = assess(
        study=planning.study(
            required_capabilities=(
                domain.capability_requirement(Capability.FORWARD_DYNAMICS, essential=False),
            )
        ),
        scenario=domain.scenario_definition(
            "sc.loaded-cmj",
            required_capabilities=(
                domain.capability_requirement(Capability.FORWARD_DYNAMICS, essential=True),
            ),
        ),
        system_under_test=domain.sut_definition(
            required_capabilities=(
                domain.capability_requirement(Capability.FORWARD_DYNAMICS, essential=False),
            )
        ),
    )

    merged = next(
        item
        for item in compatibility.requirements
        if item.capability is Capability.FORWARD_DYNAMICS
    )
    assert merged.essential is True
    assert {demand.source for demand in merged.demands} == {
        CapabilityRequirementSource.STUDY,
        CapabilityRequirementSource.SCENARIO,
        CapabilityRequirementSource.SYSTEM_UNDER_TEST,
    }


def test_every_demand_keeps_the_rationale_of_the_authority_that_declared_it() -> None:
    compatibility = assess(
        study=planning.study(
            required_capabilities=(domain.capability_requirement(Capability.FORWARD_DYNAMICS),)
        ),
        scenario=domain.scenario_definition(
            "sc.loaded-cmj",
            required_capabilities=(domain.capability_requirement(Capability.FORWARD_DYNAMICS),),
        ),
    )

    merged = next(
        item
        for item in compatibility.requirements
        if item.capability is Capability.FORWARD_DYNAMICS
    )
    rationales = {demand.source: demand.rationale for demand in merged.demands}
    assert set(rationales) == {
        CapabilityRequirementSource.STUDY,
        CapabilityRequirementSource.SCENARIO,
    }
    assert all(rationale for rationale in rationales.values())


def test_a_missing_essential_capability_fails_before_a_run_spec_exists() -> None:
    realization = domain.realization_definition(
        capabilities=planning.forward_dynamics_only(),
    )

    with pytest.raises(IncompatibleCapabilityError) as failure:
        assess(realization=realization)

    assert "state_snapshot" in str(failure.value)


def test_a_missing_optional_capability_is_recorded_and_the_assessment_still_returns() -> None:
    compatibility = assess(
        study=planning.study(
            required_capabilities=(
                domain.capability_requirement(Capability.FORWARD_DYNAMICS),
                domain.capability_requirement(Capability.STATE_SNAPSHOT, essential=False),
            )
        ),
        scenario=domain.scenario_definition("sc.loaded-cmj", required_capabilities=()),
        realization=domain.realization_definition(capabilities=planning.forward_dynamics_only()),
    )

    assert compatibility.unmet_essential == ()
    assert compatibility.unmet_optional == (Capability.STATE_SNAPSHOT,)
    assert compatibility.satisfied is True


def test_the_refusal_names_the_realization_the_scenario_and_the_study() -> None:
    """A candidate that cannot run is refused, not silently dropped: the message has to
    identify it, or a study could lose its only realization without anyone noticing."""
    with pytest.raises(IncompatibleCapabilityError) as failure:
        assess(
            realization=domain.realization_definition(
                capabilities=advertises(Capability.FORWARD_DYNAMICS)
            )
        )

    message = str(failure.value)
    assert "rl.mujoco.loaded-cmj" in message
    assert "sc.loaded-cmj" in message
    assert "study.contact-stiffness-sensitivity" in message
    assert "state_snapshot" in message


def test_declared_limitations_are_carried_through_and_never_interpreted() -> None:
    """Limitations are explanatory authority. This planner reads them; it does not judge them."""
    realization = domain.realization_definition(
        capabilities=(
            domain.CapabilityDeclaration(
                capability=Capability.FORWARD_DYNAMICS,
                summary="forward dynamics with the published integrator",
                limitations=(
                    "does not cover implicit contact stabilisation",
                    "does not support external force callbacks",
                ),
            ),
        )
    )

    compatibility = assess(
        study=forward_dynamics_study(),
        scenario=domain.scenario_definition("sc.loaded-cmj", required_capabilities=()),
        realization=realization,
    )

    provision = compatibility.provisions[0]
    assert provision.limitations == (
        "does not cover implicit contact stabilisation",
        "does not support external force callbacks",
    )
    assert compatibility.unmet_essential == ()
    assert compatibility.satisfied is True


def test_an_unadvertised_capability_is_absent_even_when_a_study_prefers_it() -> None:
    """An advertisement is the whole claim; a preference for an absent capability is recorded."""
    compatibility = assess(
        study=forward_dynamics_study(
            required_capabilities=(
                domain.capability_requirement(Capability.FORWARD_DYNAMICS),
                domain.capability_requirement(Capability.INVERSE_DYNAMICS, essential=False),
            )
        ),
        scenario=domain.scenario_definition("sc.loaded-cmj", required_capabilities=()),
        realization=domain.realization_definition(
            capabilities=advertises(Capability.FORWARD_DYNAMICS)
        ),
    )

    assert compatibility.unmet_optional == (Capability.INVERSE_DYNAMICS,)


def test_the_provisions_recorded_are_the_realizations_own_advertisements() -> None:
    realization = domain.realization_definition()

    compatibility = assess(realization=realization)

    assert {item.capability for item in compatibility.provisions} == {
        declaration.capability for declaration in realization.capabilities
    }


def test_the_assessment_is_a_frozen_validated_value() -> None:
    """A compatibility verdict that could be edited after the fact would be no verdict."""
    assert CapabilityCompatibility.model_config.get("frozen") is True
    assert CapabilityCompatibility.model_config.get("extra") == "forbid"


def test_the_pure_planner_produces_an_unassessed_applicability() -> None:
    """No credibility it has not established, on every run."""
    assert UNASSESSED_APPLICABILITY.state is ApplicabilityState.UNASSESSED
    assert UNASSESSED_APPLICABILITY.rationale is None
    assert UNASSESSED_APPLICABILITY.asserted is False


@pytest.mark.parametrize(
    "state",
    [ApplicabilityState.WITHIN_DECLARED_DOMAIN, ApplicabilityState.OUTSIDE_DECLARED_DOMAIN],
)
def test_asserting_an_applicability_state_requires_stating_why(state) -> None:
    with pytest.raises(ValueError, match="must state a rationale"):
        ApplicabilityAssessment(state=state)


def test_an_assessed_applicability_is_representable_and_keeps_its_rationale() -> None:
    assessment = ApplicabilityAssessment(
        state=ApplicabilityState.OUTSIDE_DECLARED_DOMAIN,
        rationale="The loaded subject exceeds the release's stated mass range.",
    )

    assert assessment.asserted is True
    assert assessment.state is ApplicabilityState.OUTSIDE_DECLARED_DOMAIN


def test_a_rationale_without_a_state_is_refused() -> None:
    with pytest.raises(ValueError, match="state the assessment it justifies"):
        ApplicabilityAssessment(
            state=ApplicabilityState.UNASSESSED, rationale="Because it seems right."
        )


def test_the_applicability_hook_is_a_supplied_declaration_not_a_planner_inference() -> None:
    declaration = ApplicabilityDeclaration(
        benchmark=domain.benchmark_ref().identifier,
        assessment=ApplicabilityAssessment(
            state=ApplicabilityState.WITHIN_DECLARED_DOMAIN,
            rationale="Validated against the release's own admissibility checks.",
        ),
    )

    assert declaration.assessment.asserted is True


def test_the_assessment_records_no_requirement_when_there_are_none() -> None:
    compatibility = CapabilityCompatibility(
        requirements=(),
        provisions=(),
    )

    assert compatibility.satisfied is True
    assert compatibility.unmet_optional == ()
