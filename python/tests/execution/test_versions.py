"""Independent qualification of the execution-time engine-version evaluator.

The evaluator has to be right without a simulator: it is the admission decision that stops
an incompatible engine from being launched. These tests therefore exercise the semantics
directly, including the one comparator the accepted authority does not define.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dynamisbench.domain.spec.identifiers import Comparator, VersionClause, VersionSpecifier
from dynamisbench.execution.versions import (
    InvalidVersionError,
    UnsatisfiableSpecifierError,
    UnsupportedComparatorError,
    compare_precedence,
    parse_semver,
    satisfies,
    specifier_is_satisfiable,
)


def _specifier(*clauses: tuple[Comparator, str]) -> VersionSpecifier:
    return VersionSpecifier(
        clauses=tuple(
            VersionClause(comparator=comparator, version=version) for comparator, version in clauses
        )
    )


def _numeric() -> st.SearchStrategy[int]:
    return st.integers(min_value=0, max_value=30)


def _prerelease_identifier() -> st.SearchStrategy[str]:
    alphanumeric = st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
        min_size=1,
        max_size=6,
    ).filter(lambda value: not value.isdigit())
    return st.one_of(_numeric().map(str), alphanumeric)


def _build_identifier() -> st.SearchStrategy[str]:
    return st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
        min_size=1,
        max_size=6,
    )


@st.composite
def _semantic_versions(draw: st.DrawFn, *, with_build: bool = True) -> str:
    text = f"{draw(_numeric())}.{draw(_numeric())}.{draw(_numeric())}"
    prerelease = draw(st.lists(_prerelease_identifier(), max_size=3))
    if prerelease:
        text += "-" + ".".join(prerelease)
    if with_build:
        build = draw(st.lists(_build_identifier(), max_size=3))
        if build:
            text += "+" + ".".join(build)
    return text


def test_semver_precedence_example_sequence_is_ordered() -> None:
    sequence = (
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    )
    parsed = tuple(parse_semver(version) for version in sequence)
    for earlier, later in zip(parsed, parsed[1:], strict=False):
        assert compare_precedence(earlier, later) < 0
        assert compare_precedence(later, earlier) > 0


def test_exact_comparison_is_artifact_identity_not_precedence() -> None:
    with_build = _specifier((Comparator.EXACT, "1.0.0+build.1"))
    without_build = _specifier((Comparator.EXACT, "1.0.0"))

    assert satisfies("1.0.0+build.1", with_build)
    assert not satisfies("1.0.0", with_build)
    assert satisfies("1.0.0", without_build)
    assert not satisfies("1.0.0+build.1", without_build)


def test_ordered_comparison_ignores_build_metadata() -> None:
    lower = _specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0+build.1"))
    upper = _specifier((Comparator.LESS_THAN_OR_EQUAL, "1.0.0+build.1"))

    assert satisfies("1.0.0+build.2", lower)
    assert satisfies("1.0.0+build.2", upper)
    assert satisfies("1.0.0", lower)
    assert satisfies("1.0.0", upper)


def test_not_equal_is_the_negation_of_artifact_identity() -> None:
    assert satisfies("1.0.0+build.2", _specifier((Comparator.NOT_EQUAL, "1.0.0+build.1")))
    assert not satisfies("1.0.0+build.1", _specifier((Comparator.NOT_EQUAL, "1.0.0+build.1")))


@pytest.mark.parametrize(
    ("comparator", "satisfied", "not_satisfied"),
    (
        (Comparator.LESS_THAN, "0.9.9", "1.0.0"),
        (Comparator.LESS_THAN_OR_EQUAL, "1.0.0", "1.0.1"),
        (Comparator.GREATER_THAN, "1.0.1", "1.0.0"),
        (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0", "0.9.9"),
    ),
)
def test_each_ordered_comparator_has_both_truth_values(
    comparator: Comparator, satisfied: str, not_satisfied: str
) -> None:
    specifier = _specifier((comparator, "1.0.0"))
    assert satisfies(satisfied, specifier)
    assert not satisfies(not_satisfied, specifier)


def test_prerelease_precedence_is_semver_and_not_a_package_manager_range() -> None:
    at_least_release = _specifier((Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"))

    assert not satisfies("1.0.0-alpha", at_least_release)
    assert satisfies("1.0.0", at_least_release)
    assert satisfies("1.1.0-beta", at_least_release)


def test_compatible_is_refused_as_unresolvable_authority() -> None:
    specifier = _specifier((Comparator.COMPATIBLE, "1.0.0"))

    with pytest.raises(UnsupportedComparatorError, match="compatible"):
        satisfies("1.0.0", specifier)
    with pytest.raises(UnsupportedComparatorError, match="compatible"):
        specifier_is_satisfiable(specifier)


@pytest.mark.parametrize("version", ("1.0", "1.0.0.0", "01.0.0", "1.0.0-", "not-a-version"))
def test_malformed_clause_versions_are_refused(version: str) -> None:
    with pytest.raises(InvalidVersionError, match="Semantic Versioning"):
        satisfies("1.0.0", _specifier((Comparator.LESS_THAN, version)))


def test_malformed_candidate_versions_are_refused() -> None:
    with pytest.raises(InvalidVersionError, match="Semantic Versioning"):
        satisfies("1.0", _specifier((Comparator.EXACT, "1.0.0")))


def test_contradictory_ordered_constraints_are_unsatisfiable() -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN_OR_EQUAL, "2.0.0"),
        (Comparator.LESS_THAN, "2.0.0"),
    )
    assert not specifier_is_satisfiable(specifier)
    with pytest.raises(UnsatisfiableSpecifierError, match="contradictory"):
        satisfies("2.0.0", specifier)


def test_exact_and_not_equal_of_one_artifact_is_unsatisfiable() -> None:
    specifier = _specifier(
        (Comparator.EXACT, "1.0.0"),
        (Comparator.NOT_EQUAL, "1.0.0"),
    )
    assert not specifier_is_satisfiable(specifier)


def test_equal_inclusive_bounds_are_satisfiable() -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"),
        (Comparator.LESS_THAN_OR_EQUAL, "1.0.0"),
    )
    assert specifier_is_satisfiable(specifier)
    assert satisfies("1.0.0", specifier)


def test_a_prerelease_lies_between_two_distinct_releases() -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN, "1.0.0"),
        (Comparator.LESS_THAN, "1.0.1"),
    )
    assert specifier_is_satisfiable(specifier)
    assert satisfies("1.0.1-alpha", specifier)


def test_a_build_variant_remains_distinct_at_the_same_precedence() -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"),
        (Comparator.LESS_THAN_OR_EQUAL, "1.0.0"),
        (Comparator.NOT_EQUAL, "1.0.0"),
    )
    assert specifier_is_satisfiable(specifier)
    assert satisfies("1.0.0+build.1", specifier)


@given(_semantic_versions())
@settings(max_examples=100, deadline=None)
def test_precedence_is_reflexive(version: str) -> None:
    assert compare_precedence(parse_semver(version), parse_semver(version)) == 0


@given(_semantic_versions(), _semantic_versions())
@settings(max_examples=100, deadline=None)
def test_precedence_is_antisymmetric(left: str, right: str) -> None:
    forward = compare_precedence(parse_semver(left), parse_semver(right))
    backward = compare_precedence(parse_semver(right), parse_semver(left))
    assert forward == -backward


@given(_semantic_versions(), _semantic_versions(), _semantic_versions())
@settings(max_examples=60, deadline=None, suppress_health_check=(HealthCheck.too_slow,))
def test_precedence_is_transitive(left: str, middle: str, right: str) -> None:
    left_middle = compare_precedence(parse_semver(left), parse_semver(middle))
    middle_right = compare_precedence(parse_semver(middle), parse_semver(right))
    if left_middle <= 0 and middle_right <= 0:
        assert compare_precedence(parse_semver(left), parse_semver(right)) <= 0


@given(_semantic_versions(with_build=False))
@settings(max_examples=100, deadline=None)
def test_adding_build_metadata_does_not_change_precedence(version: str) -> None:
    with_build = f"{version}+build.7"
    assert compare_precedence(parse_semver(version), parse_semver(with_build)) == 0
    assert satisfies(with_build, _specifier((Comparator.GREATER_THAN_OR_EQUAL, version)))
    assert satisfies(with_build, _specifier((Comparator.LESS_THAN_OR_EQUAL, version)))


@given(_semantic_versions(), _semantic_versions())
@settings(max_examples=100, deadline=None)
def test_ordered_clauses_agree_with_the_precedence_function(left: str, right: str) -> None:
    comparison = compare_precedence(parse_semver(left), parse_semver(right))
    assert satisfies(left, _specifier((Comparator.LESS_THAN, right))) == (comparison < 0)
    assert satisfies(left, _specifier((Comparator.LESS_THAN_OR_EQUAL, right))) == (comparison <= 0)
    assert satisfies(left, _specifier((Comparator.GREATER_THAN, right))) == (comparison > 0)
    assert satisfies(left, _specifier((Comparator.GREATER_THAN_OR_EQUAL, right))) == (
        comparison >= 0
    )


@given(_semantic_versions())
@settings(max_examples=100, deadline=None)
def test_exact_and_not_equal_are_exact_artifact_identities(version: str) -> None:
    assert satisfies(version, _specifier((Comparator.EXACT, version)))
    assert not satisfies(version, _specifier((Comparator.NOT_EQUAL, version)))
