"""Execution-time evaluation of an engine version against a declared specifier.

The domain carries :class:`~dynamisbench.domain.spec.identifiers.VersionSpecifier`, a
conjunction of :class:`~dynamisbench.domain.spec.identifiers.VersionClause` values, but it
deliberately does not evaluate one. This module is the execution-admission evaluator that
closes that gap, and it is deliberately narrow about what the accepted authority supports.

**What is authorized.** ``Version`` is a Semantic Versioning 2.0.0 string. Ordered
comparators therefore use the precedence rules of Semantic Versioning 2.0.0 section 11;
build metadata is ignored for precedence by section 10. Exact and not-equal clauses compare
the complete version string, including build metadata, because ADR-006 says two versions
that differ only in build metadata are different artifacts and must not collapse into one
identity. No normalisation, implicit latest version, or guessed equivalence is applied.

**What is not authorized.** ``Comparator.COMPATIBLE`` names a caret/compatibility range,
but no accepted DynamisBench authority defines what "compatible" means: whether it is a
caret range, a tilde range, same-major, same-minor, or an engine-specific policy; how it
treats ``0.x`` versions; or how it admits or excludes prereleases. This evaluator does not
invent those rules. It refuses a ``COMPATIBLE`` clause as unresolvable, which makes the
dependent admission path fail closed until a future authority decision defines the
semantics. The same refusal applies to a clause whose version token is not a valid
Semantic Versioning 2.0.0 string.

**Prereleases are not special-cased.** Semantic Versioning defines their precedence, so an
ordered clause admits a prerelease exactly when that precedence satisfies the clause. For
example, ``1.1.0-beta`` satisfies ``>=1.0.0`` because it precedes ``1.1.0`` but follows
``1.0.0``. npm-style "ranges exclude prereleases" behaviour is a package-manager policy,
not Semantic Versioning, and is not invented here.

The evaluator is pure and deterministic: no clock, environment, filesystem, network,
randomness, or engine import. That is what lets it be tested independently of a simulator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from dynamisbench.domain.spec.identifiers import (
    SEMVER_PATTERN,
    Comparator,
    VersionSpecifier,
)

__all__ = [
    "InvalidVersionError",
    "SemVer",
    "SpecifierEvaluationError",
    "UnsatisfiableSpecifierError",
    "UnsupportedComparatorError",
    "compare_precedence",
    "parse_semver",
    "satisfies",
    "specifier_is_satisfiable",
]

_SEMVER: Final = re.compile(SEMVER_PATTERN)


class SpecifierEvaluationError(ValueError):
    """A version specifier cannot be evaluated under the accepted semantics."""


class InvalidVersionError(SpecifierEvaluationError):
    """A clause or candidate version is not a Semantic Versioning 2.0.0 version."""


class UnsupportedComparatorError(SpecifierEvaluationError):
    """The comparator has no accepted meaning, so it may not be guessed at."""


class UnsatisfiableSpecifierError(SpecifierEvaluationError):
    """No version can satisfy every clause of the conjunction."""


@dataclass(frozen=True, slots=True)
class SemVer:
    """One parsed Semantic Versioning 2.0.0 version.

    ``raw`` is retained because exact comparison is an artifact-identity comparison, not a
    precedence comparison. The numeric and identifier components are retained separately
    because precedence needs them.
    """

    raw: str
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]
    build: tuple[str, ...]

    @property
    def is_prerelease(self) -> bool:
        """Whether this version carries a prerelease component."""
        return bool(self.prerelease)


def parse_semver(text: str) -> SemVer:
    """Parse exactly one Semantic Versioning 2.0.0 string, or refuse it.

    The domain's own ``Version`` annotation already enforces this shape on version fields.
    Specifier clause versions are ``Token`` values, however, so execution admission must
    re-validate them rather than trust that a token is a version.

    :raises InvalidVersionError: if ``text`` is not a Semantic Versioning 2.0.0 version.
    """
    if _SEMVER.fullmatch(text) is None:
        raise InvalidVersionError(
            f"{text!r} is not a Semantic Versioning 2.0.0 version; a clause version must "
            "be exactly MAJOR.MINOR.PATCH with optional prerelease and build components"
        )
    without_build, separator, build = text.partition("+")
    core, prerelease_separator, prerelease = without_build.partition("-")
    major_text, minor_text, patch_text = core.split(".")
    return SemVer(
        raw=text,
        major=int(major_text),
        minor=int(minor_text),
        patch=int(patch_text),
        prerelease=tuple(prerelease.split(".")) if prerelease_separator else (),
        build=tuple(build.split(".")) if separator else (),
    )


def _compare_identifier(left: str, right: str) -> int:
    """Compare two prerelease identifiers by the Semantic Versioning rule."""
    left_numeric = left.isdigit()
    right_numeric = right.isdigit()
    if left_numeric and right_numeric:
        return (int(left) > int(right)) - (int(left) < int(right))
    if left_numeric != right_numeric:
        # Numeric identifiers always have lower precedence than alphanumeric identifiers.
        return -1 if left_numeric else 1
    return (left > right) - (left < right)


def compare_precedence(left: SemVer, right: SemVer) -> int:
    """Return ``-1``, ``0`` or ``1`` for Semantic Versioning precedence.

    Build metadata is ignored, exactly as Semantic Versioning section 10 requires. The
    result is therefore a precedence comparison and not an artifact-identity comparison;
    use :func:`satisfies` with an exact clause for the latter.
    """
    for left_part, right_part in (
        (left.major, right.major),
        (left.minor, right.minor),
        (left.patch, right.patch),
    ):
        if left_part != right_part:
            return -1 if left_part < right_part else 1
    if not left.prerelease and not right.prerelease:
        return 0
    if not left.prerelease:
        return 1
    if not right.prerelease:
        return -1
    for left_identifier, right_identifier in zip(left.prerelease, right.prerelease, strict=False):
        comparison = _compare_identifier(left_identifier, right_identifier)
        if comparison:
            return comparison
    return (len(left.prerelease) > len(right.prerelease)) - (
        len(left.prerelease) < len(right.prerelease)
    )


def _clause_matches(candidate: SemVer, comparator: Comparator, required: SemVer) -> bool:
    """Evaluate one already-parsed clause against one already-parsed candidate."""
    match comparator:
        case Comparator.EXACT:
            # Artifact identity, not precedence: build metadata is part of the version.
            return candidate.raw == required.raw
        case Comparator.NOT_EQUAL:
            return candidate.raw != required.raw
        case Comparator.LESS_THAN:
            return compare_precedence(candidate, required) < 0
        case Comparator.LESS_THAN_OR_EQUAL:
            return compare_precedence(candidate, required) <= 0
        case Comparator.GREATER_THAN:
            return compare_precedence(candidate, required) > 0
        case Comparator.GREATER_THAN_OR_EQUAL:
            return compare_precedence(candidate, required) >= 0
        case Comparator.COMPATIBLE:
            raise UnsupportedComparatorError(
                "the 'compatible' comparator has no accepted DynamisBench semantics; a "
                "caret/tilde/same-major interpretation would be invented here"
            )
        case _:  # pragma: no cover - the domain enum is closed
            raise UnsupportedComparatorError(f"unknown comparator {comparator!r}")


def _immediate_successor(version: SemVer) -> SemVer:
    """Return the least Semantic Versioning precedence value greater than ``version``.

    Semantic Versioning precedence is *not* dense, which the previous satisfiability check
    incorrectly assumed. For example, there is no version strictly between ``1.0.0-alpha``
    and ``1.0.0-alpha.0``: a version above ``alpha`` must either share the whole identifier
    prefix and add at least one more identifier, whose least value is the numeric ``0``, or
    differ at an earlier identifier and therefore already exceed ``alpha.0``.

    Every precedence value has an immediate successor:

    * a prerelease ``A.B`` is followed by ``A.B.0`` — a longer sequence with the same
      identifiers has higher precedence, and ``0`` is the lowest possible next identifier;
    * a release ``X.Y.Z`` is followed by ``X.Y.(Z+1)-0`` — no prerelease of the same core can
      exceed the release, and ``0`` is the lowest prerelease of the next core.

    Build metadata is irrelevant here because it does not participate in precedence. The
    successor is used only to decide interval emptiness; it is never compared as an artifact
    identity, so its canonical raw spelling does not matter.
    """
    if version.prerelease:
        prerelease = (*version.prerelease, "0")
        return SemVer(
            raw=f"{version.major}.{version.minor}.{version.patch}-{'.'.join(prerelease)}",
            major=version.major,
            minor=version.minor,
            patch=version.patch,
            prerelease=prerelease,
            build=(),
        )
    patch = version.patch + 1
    return SemVer(
        raw=f"{version.major}.{version.minor}.{patch}-0",
        major=version.major,
        minor=version.minor,
        patch=patch,
        prerelease=("0",),
        build=(),
    )


def _ordered_bounds(
    clauses: tuple[tuple[Comparator, SemVer], ...],
) -> tuple[tuple[SemVer, bool] | None, tuple[SemVer, bool] | None]:
    """Return the strongest lower and upper precedence bounds, with inclusivity.

    Equal-precedence bounds are merged conservatively: if either clause excludes the bound,
    the merged bound excludes it.
    """
    lower: tuple[SemVer, bool] | None = None
    upper: tuple[SemVer, bool] | None = None
    for comparator, version in clauses:
        if comparator in (Comparator.GREATER_THAN, Comparator.GREATER_THAN_OR_EQUAL):
            inclusive = comparator is Comparator.GREATER_THAN_OR_EQUAL
            if lower is None:
                lower = (version, inclusive)
            else:
                comparison = compare_precedence(version, lower[0])
                if comparison > 0:
                    lower = (version, inclusive)
                elif comparison == 0:
                    lower = (lower[0], lower[1] and inclusive)
        elif comparator in (Comparator.LESS_THAN, Comparator.LESS_THAN_OR_EQUAL):
            inclusive = comparator is Comparator.LESS_THAN_OR_EQUAL
            if upper is None:
                upper = (version, inclusive)
            else:
                comparison = compare_precedence(version, upper[0])
                if comparison < 0:
                    upper = (version, inclusive)
                elif comparison == 0:
                    upper = (upper[0], upper[1] and inclusive)
    return lower, upper


def _parsed_clauses(specifier: VersionSpecifier) -> tuple[tuple[Comparator, SemVer], ...]:
    """Parse every clause or refuse, so no caller can skip a malformed or unknown clause."""
    parsed: list[tuple[Comparator, SemVer]] = []
    for clause in specifier.clauses:
        if clause.comparator is Comparator.COMPATIBLE:
            raise UnsupportedComparatorError(
                "the 'compatible' comparator has no accepted DynamisBench semantics; a "
                "caret/tilde/same-major interpretation would be invented here"
            )
        parsed.append((clause.comparator, parse_semver(clause.version)))
    return tuple(parsed)


def specifier_is_satisfiable(specifier: VersionSpecifier) -> bool:
    """Whether at least one Semantic Versioning version satisfies all clauses.

    This is an exact decision procedure for the supported comparators, not a conservative
    approximation. Precedence intervals are checked against the immediate-successor rule
    above rather than assuming density, so adjacent prerelease endpoints such as
    ``> 1.0.0-alpha, < 1.0.0-alpha.0`` are correctly refused. A finite not-equal set can
    never empty a nonempty precedence interval because every precedence value has infinitely
    many build-metadata spellings, and build metadata is part of exact/not-equal identity.

    It is used to refuse contradictory authority with a distinct reason before a candidate
    version is compared, rather than reporting an ordinary mismatch for a specifier that can
    never be satisfied.

    :raises UnsupportedComparatorError: for ``COMPATIBLE``.
    :raises InvalidVersionError: for a clause version that is not Semantic Versioning.
    """
    clauses = _parsed_clauses(specifier)
    exact = next(
        (version for comparator, version in clauses if comparator is Comparator.EXACT), None
    )
    if exact is not None:
        return all(_clause_matches(exact, comparator, required) for comparator, required in clauses)

    lower, upper = _ordered_bounds(clauses)
    if lower is None or upper is None:
        # With no two-sided precedence interval, a not-equal clause cannot exhaust the
        # infinite Semantic Versioning vocabulary.
        return True
    comparison = compare_precedence(lower[0], upper[0])
    if comparison > 0:
        return False
    if comparison < 0:
        # An inclusive endpoint is its own witness. Otherwise the open interval is nonempty
        # exactly when the upper endpoint is not the immediate successor of the lower one;
        # SemVer precedence has adjacent values and no version can exist between them.
        if lower[1] or upper[1]:
            return True
        return compare_precedence(_immediate_successor(lower[0]), upper[0]) < 0
    # Equal precedence: only an inclusive bound on both sides leaves a candidate. Build
    # metadata variants remain distinct artifact strings at that precedence, so a finite
    # not-equal clause cannot empty the interval.
    return lower[1] and upper[1]


def satisfies(version: str, specifier: VersionSpecifier) -> bool:
    """Whether ``version`` satisfies every clause of ``specifier``.

    :raises InvalidVersionError: if the candidate or a clause version is not Semantic
        Versioning 2.0.0.
    :raises UnsupportedComparatorError: if a clause uses ``COMPATIBLE``.
    :raises UnsatisfiableSpecifierError: if the specifier itself is contradictory.
    """
    candidate = parse_semver(version)
    clauses = _parsed_clauses(specifier)
    if not specifier_is_satisfiable(specifier):
        raise UnsatisfiableSpecifierError(
            "the version constraints are contradictory; no version can satisfy every clause"
        )
    return all(_clause_matches(candidate, comparator, required) for comparator, required in clauses)
