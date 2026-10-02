"""The applicability assessment and its hook.

A benchmark states its applicability domain in prose, and this planner will not pretend to
have judged it. Every run therefore starts unassessed, an asserted state must state its
rationale, and an outside-domain run stays distinguishable.
"""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.identifiers import BenchmarkId
from dynamisbench.planning import (
    ApplicabilityAssessment,
    ApplicabilityDeclaration,
    ApplicabilityState,
    AuthorityResolutionError,
)
from tests.planning.compiler import (
    one_run,
)


def test_the_pure_planner_leaves_every_run_unassessed_for_applicability() -> None:
    plan = one_run()

    assert {run.applicability.state for run in plan.runs} == {ApplicabilityState.UNASSESSED}


def test_a_supplied_applicability_assessment_is_carried_onto_its_benchmarks_runs() -> None:
    declaration = ApplicabilityDeclaration(
        benchmark=BenchmarkId("db.lcmj20"),
        assessment=ApplicabilityAssessment(
            state=ApplicabilityState.WITHIN_DECLARED_DOMAIN,
            rationale="Validated against the release's own admissibility checks.",
        ),
    )

    plan = one_run(applicability=(declaration,))

    assert {run.applicability.state for run in plan.runs} == {
        ApplicabilityState.WITHIN_DECLARED_DOMAIN
    }


def test_an_out_of_domain_assessment_is_distinguishable_on_the_plan() -> None:
    declaration = ApplicabilityDeclaration(
        benchmark=BenchmarkId("db.lcmj20"),
        assessment=ApplicabilityAssessment(
            state=ApplicabilityState.OUTSIDE_DECLARED_DOMAIN,
            rationale="The loaded subject exceeds the release's stated mass range.",
        ),
    )

    plan = one_run(applicability=(declaration,))

    assert {run.applicability.state for run in plan.runs} == {
        ApplicabilityState.OUTSIDE_DECLARED_DOMAIN
    }
    assert all(run.applicability.asserted for run in plan.runs)


def test_an_applicability_declaration_for_an_unreferenced_benchmark_is_dangling() -> None:
    declaration = ApplicabilityDeclaration(benchmark=BenchmarkId("db.absent"))

    with pytest.raises(AuthorityResolutionError, match="does not reference"):
        one_run(applicability=(declaration,))


def test_an_applicability_assessment_is_not_fingerprint_bearing() -> None:
    """It is a credibility judgement about the plan, not an input to the execution."""
    plain = one_run()
    assessed = one_run(
        applicability=(
            ApplicabilityDeclaration(
                benchmark=BenchmarkId("db.lcmj20"),
                assessment=ApplicabilityAssessment(
                    state=ApplicabilityState.OUTSIDE_DECLARED_DOMAIN,
                    rationale="The loaded subject exceeds the release's stated mass range.",
                ),
            ),
        )
    )

    assert plain.runs[0].fingerprint == assessed.runs[0].fingerprint
    assert plain.runs[0].spec == assessed.runs[0].spec
