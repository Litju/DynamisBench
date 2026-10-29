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


_BOUNDARY_VERSIONS = (
    "0.0.0-0",
    "0.0.0-0.0",
    "0.0.0-0+build.1",
    "0.0.0",
    "0.0.0+build.1",
    "0.0.1-0",
    "0.0.1",
    "1.0.0-alpha",
    "1.0.0-alpha.0",
    "1.0.0-alpha.0.0",
    "1.0.0",
    "1.0.0+build.1",
    "1.0.1-0",
    "1.0.0-184467440737095516160",
)
"""Precedence boundaries, including the global minimum and its immediate successors."""


def _successor_text(version: str) -> str:
    """The least precedence value above ``version``, written as a valid version string."""
    parsed = parse_semver(version)
    if parsed.prerelease:
        identifiers = (*parsed.prerelease, "0")
        return f"{parsed.major}.{parsed.minor}.{parsed.patch}-{'.'.join(identifiers)}"
    return f"{parsed.major}.{parsed.minor}.{parsed.patch + 1}-0"


def _with_build(version: str, tag: int) -> str:
    """A distinct build-metadata spelling at the same precedence as ``version``."""
    return f"{version}.witness{tag}" if "+" in version else f"{version}+witness{tag}"


def _witness_pool(clauses: tuple[tuple[Comparator, str], ...]) -> list[str]:
    versions = {"0.0.0-0"}
    for _comparator, version in clauses:
        versions.add(version)
        versions.add(_successor_text(version))
    return [
        witness
        for version in versions
        for witness in (version, *(_with_build(version, tag) for tag in range(4)))
    ]


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


def test_adjacent_prerelease_endpoints_are_unsatisfiable() -> None:
    """SemVer precedence is not dense: nothing lies between ``alpha`` and ``alpha.0``."""
    specifier = _specifier(
        (Comparator.GREATER_THAN, "1.0.0-alpha"),
        (Comparator.LESS_THAN, "1.0.0-alpha.0"),
    )
    assert not specifier_is_satisfiable(specifier)
    with pytest.raises(UnsatisfiableSpecifierError, match="contradictory"):
        satisfies("1.0.0-alpha.0", specifier)


@pytest.mark.parametrize(
    ("lower", "upper", "satisfiable"),
    (
        # Both inclusive: the lower endpoint is a witness.
        (Comparator.GREATER_THAN_OR_EQUAL, Comparator.LESS_THAN_OR_EQUAL, True),
        # Lower exclusive, upper inclusive: the upper endpoint is a witness.
        (Comparator.GREATER_THAN, Comparator.LESS_THAN_OR_EQUAL, True),
        # Lower inclusive, upper exclusive: the lower endpoint is a witness.
        (Comparator.GREATER_THAN_OR_EQUAL, Comparator.LESS_THAN, True),
        # Both exclusive: no value exists between adjacent endpoints.
        (Comparator.GREATER_THAN, Comparator.LESS_THAN, False),
    ),
)
def test_adjacent_bound_inclusivity_is_decided_exactly(
    lower: Comparator, upper: Comparator, satisfiable: bool
) -> None:
    specifier = _specifier((lower, "1.0.0-alpha"), (upper, "1.0.0-alpha.0"))
    assert specifier_is_satisfiable(specifier) is satisfiable


@pytest.mark.parametrize("endpoint", ("0", "alpha", "alpha.beta", "alpha.zzz"))
def test_every_prerelease_has_an_immediate_successor(endpoint: str) -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN, f"1.0.0-{endpoint}"),
        (Comparator.LESS_THAN, f"1.0.0-{endpoint}.0"),
    )
    assert not specifier_is_satisfiable(specifier)


@pytest.mark.parametrize(
    ("clauses", "satisfiable", "witness"),
    (
        # Semantic Versioning has a global minimum precedence, 0.0.0-0. A range that ends
        # at or below it is empty even though it declares no lower bound.
        (((Comparator.LESS_THAN, "0.0.0-0"),), False, None),
        (((Comparator.LESS_THAN_OR_EQUAL, "0.0.0-0"),), True, "0.0.0-0"),
        (((Comparator.GREATER_THAN, "0.0.0-0"),), True, "0.0.0-0.0"),
        (((Comparator.GREATER_THAN_OR_EQUAL, "0.0.0-0"),), True, "0.0.0-0"),
        # Build metadata does not move the endpoint in precedence, so it cannot rescue a
        # range that excludes the minimum, and cannot make an inclusive minimum empty.
        (((Comparator.LESS_THAN, "0.0.0-0+build.1"),), False, None),
        (((Comparator.LESS_THAN_OR_EQUAL, "0.0.0-0+build.1"),), True, "0.0.0-0"),
        # Adjacent prerelease endpoints remain empty/open as before.
        (
            (
                (Comparator.GREATER_THAN, "1.0.0-alpha"),
                (Comparator.LESS_THAN, "1.0.0-alpha.0"),
            ),
            False,
            None,
        ),
        (
            (
                (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0-alpha"),
                (Comparator.LESS_THAN_OR_EQUAL, "1.0.0-alpha.0"),
            ),
            True,
            "1.0.0-alpha",
        ),
    ),
)
def test_global_minimum_and_adjacent_bounds_are_decided_exactly(
    clauses: tuple[tuple[Comparator, str], ...],
    satisfiable: bool,
    witness: str | None,
) -> None:
    specifier = _specifier(*clauses)

    assert specifier_is_satisfiable(specifier) is satisfiable
    if witness is not None:
        assert satisfies(witness, specifier)
    else:
        with pytest.raises(UnsatisfiableSpecifierError, match="contradictory"):
            satisfies("0.0.0-0", specifier)


def test_minimum_precedence_bounds_every_valid_version() -> None:
    minimum = parse_semver("0.0.0-0")
    for version in _BOUNDARY_VERSIONS:
        assert compare_precedence(minimum, parse_semver(version)) <= 0


@pytest.mark.parametrize(
    ("clauses", "satisfiable", "witness"),
    (
        # A not-equal clause cannot empty an interval that still contains a build-metadata
        # spelling of an accepted precedence, even at the global minimum.
        (
            (
                (Comparator.LESS_THAN, "0.0.0-0"),
                (Comparator.NOT_EQUAL, "0.0.0-0"),
            ),
            False,
            None,
        ),
        (
            (
                (Comparator.LESS_THAN_OR_EQUAL, "0.0.0-0"),
                (Comparator.NOT_EQUAL, "0.0.0-0"),
            ),
            True,
            "0.0.0-0+build.1",
        ),
        (
            (
                (Comparator.GREATER_THAN_OR_EQUAL, "0.0.0-0"),
                (Comparator.LESS_THAN_OR_EQUAL, "0.0.0-0"),
                (Comparator.NOT_EQUAL, "0.0.0-0"),
            ),
            True,
            "0.0.0-0+build.1",
        ),
        (
            (
                (Comparator.LESS_THAN, "0.0.0-0+build.1"),
                (Comparator.NOT_EQUAL, "0.0.0-0+build.1"),
            ),
            False,
            None,
        ),
        (
            (
                (Comparator.LESS_THAN_OR_EQUAL, "0.0.0-0+build.1"),
                (Comparator.NOT_EQUAL, "0.0.0-0+build.1"),
            ),
            True,
            "0.0.0-0+build.2",
        ),
    ),
)
def test_minimum_boundary_with_not_equal_and_build_metadata(
    clauses: tuple[tuple[Comparator, str], ...],
    satisfiable: bool,
    witness: str | None,
) -> None:
    specifier = _specifier(*clauses)

    assert specifier_is_satisfiable(specifier) is satisfiable
    if witness is not None:
        assert satisfies(witness, specifier)


def test_minimum_boundary_with_large_numeric_prerelease_identifiers() -> None:
    large = 10**80

    adjacent = _specifier(
        (Comparator.GREATER_THAN, f"0.0.0-{large}"),
        (Comparator.LESS_THAN, f"0.0.0-{large}.0"),
    )
    assert not specifier_is_satisfiable(adjacent)

    unbounded = _specifier((Comparator.GREATER_THAN, f"0.0.0-{large}"))
    assert specifier_is_satisfiable(unbounded)
    assert satisfies(f"0.0.0-{large}.0", unbounded)

    narrow = _specifier(
        (Comparator.GREATER_THAN, f"0.0.0-{large - 1}"),
        (Comparator.LESS_THAN, f"0.0.0-{large}"),
    )
    assert specifier_is_satisfiable(narrow)
    assert satisfies(f"0.0.0-{large - 1}.0", narrow)


def test_minimum_release_is_adjacent_to_the_next_prerelease() -> None:
    adjacent = _specifier(
        (Comparator.GREATER_THAN, "0.0.0"),
        (Comparator.LESS_THAN, "0.0.1-0"),
    )
    assert not specifier_is_satisfiable(adjacent)

    inclusive = _specifier(
        (Comparator.GREATER_THAN_OR_EQUAL, "0.0.0"),
        (Comparator.LESS_THAN, "0.0.1-0"),
    )
    assert specifier_is_satisfiable(inclusive)
    assert satisfies("0.0.0", inclusive)


@pytest.mark.parametrize(
    ("lower", "upper", "witness"),
    (
        ("1.0.0-alpha", "1.0.0-alpha.0.0", "1.0.0-alpha.0"),
        ("1.0.0-0", "1.0.0-0.0.0", "1.0.0-0.0"),
        ("1.0.0-alpha.0", "1.0.0-alpha.0.1", "1.0.0-alpha.0.0"),
        ("1.0.0-0.9", "1.0.0-0.10", "1.0.0-0.9.0"),
        ("1.0.0-1", "1.0.0-2", "1.0.0-1.0"),
    ),
)
def test_a_valid_narrow_open_interval_is_not_falsely_refused(
    lower: str, upper: str, witness: str
) -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN, lower),
        (Comparator.LESS_THAN, upper),
    )
    assert specifier_is_satisfiable(specifier)
    assert satisfies(witness, specifier)


def test_adjacent_release_and_next_prerelease_are_unsatisfiable() -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN, "1.0.0"),
        (Comparator.LESS_THAN, "1.0.1-0"),
    )
    assert not specifier_is_satisfiable(specifier)


def test_large_numeric_prerelease_identifiers_are_compared_exactly() -> None:
    large = 10**80
    adjacent = _specifier(
        (Comparator.GREATER_THAN, f"1.0.0-{large}"),
        (Comparator.LESS_THAN, f"1.0.0-{large}.0"),
    )
    assert not specifier_is_satisfiable(adjacent)

    narrow = _specifier(
        (Comparator.GREATER_THAN, f"1.0.0-{large - 1}"),
        (Comparator.LESS_THAN, f"1.0.0-{large}"),
    )
    assert specifier_is_satisfiable(narrow)
    assert satisfies(f"1.0.0-{large - 1}.0", narrow)


def test_exact_plus_not_equal_uses_artifact_identity_and_build_metadata() -> None:
    contradictory = _specifier(
        (Comparator.EXACT, "1.0.0"),
        (Comparator.NOT_EQUAL, "1.0.0"),
    )
    assert not specifier_is_satisfiable(contradictory)

    build_distinct = _specifier(
        (Comparator.EXACT, "1.0.0+build.1"),
        (Comparator.NOT_EQUAL, "1.0.0+build.2"),
    )
    assert specifier_is_satisfiable(build_distinct)
    assert satisfies("1.0.0+build.1", build_distinct)

    exact_release = _specifier(
        (Comparator.EXACT, "1.0.0+build.1"),
        (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"),
        (Comparator.LESS_THAN_OR_EQUAL, "1.0.0"),
    )
    assert specifier_is_satisfiable(exact_release)

    exact_above = _specifier(
        (Comparator.EXACT, "1.0.0+build.1"),
        (Comparator.GREATER_THAN, "1.0.0"),
    )
    assert not specifier_is_satisfiable(exact_above)


def test_build_metadata_keeps_an_equal_precedence_interval_nonempty() -> None:
    specifier = _specifier(
        (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0+build.1"),
        (Comparator.LESS_THAN_OR_EQUAL, "1.0.0+build.1"),
        (Comparator.NOT_EQUAL, "1.0.0+build.1"),
    )
    assert specifier_is_satisfiable(specifier)
    assert satisfies("1.0.0+build.2", specifier)


def test_inclusive_and_exclusive_precedence_bounds_remain_consistent() -> None:
    inclusive = _specifier(
        (Comparator.GREATER_THAN_OR_EQUAL, "1.0.0"),
        (Comparator.LESS_THAN, "1.0.1-0"),
    )
    assert specifier_is_satisfiable(inclusive)
    assert satisfies("1.0.0", inclusive)

    exclusive = _specifier(
        (Comparator.GREATER_THAN, "1.0.0"),
        (Comparator.LESS_THAN, "1.0.1-0"),
    )
    assert not specifier_is_satisfiable(exclusive)


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
    for comparator, expected in (
        (Comparator.LESS_THAN, comparison < 0),
        (Comparator.LESS_THAN_OR_EQUAL, comparison <= 0),
        (Comparator.GREATER_THAN, comparison > 0),
        (Comparator.GREATER_THAN_OR_EQUAL, comparison >= 0),
    ):
        specifier = _specifier((comparator, right))
        if specifier_is_satisfiable(specifier):
            assert satisfies(left, specifier) == expected
        else:
            # A single clause can still be empty against the global minimum, in which
            # case the candidate is refused as contradictory rather than mismatched.
            assert expected is False


@given(_semantic_versions())
@settings(max_examples=100, deadline=None)
def test_exact_and_not_equal_are_exact_artifact_identities(version: str) -> None:
    assert satisfies(version, _specifier((Comparator.EXACT, version)))
    assert not satisfies(version, _specifier((Comparator.NOT_EQUAL, version)))


_ORDERED_COMPARATORS = (
    Comparator.EXACT,
    Comparator.NOT_EQUAL,
    Comparator.GREATER_THAN,
    Comparator.GREATER_THAN_OR_EQUAL,
    Comparator.LESS_THAN,
    Comparator.LESS_THAN_OR_EQUAL,
)


@given(
    st.lists(
        st.tuples(
            st.sampled_from(_ORDERED_COMPARATORS),
            st.one_of(_semantic_versions(with_build=False), st.sampled_from(_BOUNDARY_VERSIONS)),
        ),
        min_size=1,
        max_size=3,
        unique_by=lambda clause: clause[0],
    )
)
@settings(max_examples=250, deadline=None)
def test_satisfiable_specifiers_admit_a_constructed_witness(
    clauses: list[tuple[Comparator, str]],
) -> None:
    """A satisfiable decision must name a version the ordinary evaluator admits.

    The witness pool is constructed from the clause endpoints, the global minimum, each
    endpoint's immediate successor, and distinct build-metadata spellings. If the decision
    says a range is nonempty, at least one of those candidates must actually satisfy it.
    This is the no-false-refusal direction, exercised over the whole supported comparator
    set; the endpoint table tests cover the false-refusal direction directly.
    """
    specifier = _specifier(*clauses)
    if not specifier_is_satisfiable(specifier):
        return

    witnesses = _witness_pool(tuple(clauses))
    assert any(satisfies(witness, specifier) for witness in witnesses), (
        f"the decision says {clauses} is satisfiable but no constructed witness satisfies it"
    )


@given(st.one_of(_semantic_versions(with_build=False), st.sampled_from(_BOUNDARY_VERSIONS)))
@settings(max_examples=200, deadline=None)
def test_initial_segment_satisfiability_is_bounded_by_the_global_minimum(version: str) -> None:
    minimum = parse_semver("0.0.0-0")
    parsed = parse_semver(version)
    less = _specifier((Comparator.LESS_THAN, version))
    at_most = _specifier((Comparator.LESS_THAN_OR_EQUAL, version))

    assert specifier_is_satisfiable(less) == (compare_precedence(minimum, parsed) < 0)
    assert specifier_is_satisfiable(at_most)
    if specifier_is_satisfiable(less):
        assert satisfies("0.0.0-0", less)
    assert satisfies("0.0.0-0", at_most)


@given(st.one_of(_semantic_versions(with_build=False), st.sampled_from(_BOUNDARY_VERSIONS)))
@settings(max_examples=200, deadline=None)
def test_final_segment_satisfiability_has_no_upper_bound(version: str) -> None:
    greater = _specifier((Comparator.GREATER_THAN, version))
    at_least = _specifier((Comparator.GREATER_THAN_OR_EQUAL, version))

    assert specifier_is_satisfiable(greater)
    assert specifier_is_satisfiable(at_least)
    assert satisfies(_successor_text(version), greater)
    assert satisfies(version, at_least)
