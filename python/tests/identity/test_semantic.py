"""The semantic boundary: meaning in, canonical bytes and a digest out.

What is proved here:

* a validated domain object's canonical bytes are exactly the canonical bytes of its
  own JSON-mode dump, so the identity layer adds meaning to a definition and never
  quietly rearranges one;
* unsupported Python values, non-string property names, and non-finite numbers fail
  closed rather than being approximated;
* **negative zero is normalised to positive zero by an explicit rule of this layer**,
  checked across four different domain classes and readable in the layer's own output
  before canonicalisation, rather than being an accident of the serialiser;
* SemVer build metadata stays part of identity, so ``1.2.3+abc`` and ``1.2.3+def`` are
  two artifacts;
* identity is taken over the *semantic* unit representation, not the authored spelling,
  so ``mm``, ``1e-3*m`` and ``0.001*m`` are one unit with one digest;
* the human identity of a definition travels alongside its digest and is never replaced
  by it.

Property tests over the same boundary - authoring irrelevance, semantic sensitivity,
collection ordering, and cross-process determinism - live in
``test_identity_properties.py``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from typing import Any

import pytest

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.metrics import AggregationMethod, MetricAggregation
from dynamisbench.domain.spec.quantities import (
    AxisConvention,
    CanonicalUnit,
    PhysicalDimension,
    RotationSense,
)
from dynamisbench.domain.spec.references import ReferenceOrigin, VerificationCategory
from dynamisbench.domain.spec.studies import PointValue
from dynamisbench.identity import (
    NEGATIVE_ZERO_IS_NORMALISED,
    CanonicalizationError,
    SemanticDigest,
    canonical_bytes,
    canonical_semantic_bytes,
    semantic_representation,
    semantic_sha256,
)

from ..domain.factories import (
    benchmark_release,
    controlled_factor,
    environment_definition,
    event,
    metric_definition,
    quantity_assignment,
    quantity_definition,
    realization_definition,
    reference_definition,
    scenario_definition,
    study_definition,
    sut_definition,
    uncertainty_factor,
)

DEFINITIONS = (
    quantity_definition,
    metric_definition,
    scenario_definition,
    reference_definition,
    realization_definition,
    sut_definition,
    environment_definition,
    study_definition,
    benchmark_release,
)

DEFINITION_IDS = [build.__name__ for build in DEFINITIONS]

HUMAN_IDENTITIES = (
    (benchmark_release, "benchmark_id", "db.lcmj20-alt"),
    (quantity_definition, "quantity_id", "q.foot.vertical_force-alt"),
    (scenario_definition, "scenario_id", "sc.loaded-cmj-alt"),
    (sut_definition, "sut_id", "sut.baseline-0-alt"),
    (realization_definition, "realization_id", "rl.mujoco.loaded-cmj-alt"),
    (environment_definition, "environment_id", "env.mujoco.x86-64-alt"),
    (study_definition, "study_id", "study.contact-stiffness-sensitivity-alt"),
)

HUMAN_IDENTITY_IDS = [build.__name__ for build, _, _ in HUMAN_IDENTITIES]

EQUIVALENT_UNITS = (
    ("mm", "1e-3*m"),
    ("1e-3*m", "0.001*m"),
    ("mm", "0.001*m"),
    ("kN", "1000*N"),
    ("ms", "0.001*s"),
    ("kg*m^2/s^3", "W"),
    ("m/s", "m*s^-1"),
)

EQUIVALENT_UNIT_IDS = [f"{first}={second}" for first, second in EQUIVALENT_UNITS]


class _UnitHolder(DomainModel):
    """A minimal validated definition, so that unit identity is exercised through the
    same semantic boundary a real quantity takes rather than around it."""

    unit: CanonicalUnit


def _rejects(value: Any) -> None:
    with pytest.raises(CanonicalizationError):
        semantic_representation(value)


def _flip_zero_signs(value: Any) -> tuple[Any, int]:
    """Return ``value`` with every floating-point zero rewritten as ``-0.0``."""
    if isinstance(value, dict):
        flipped = [_flip_zero_signs(item) for item in value.values()]
        return dict(zip(value, (item for item, _ in flipped), strict=True)), sum(
            count for _, count in flipped
        )
    if isinstance(value, list):
        flipped_items = [_flip_zero_signs(item) for item in value]
        return [item for item, _ in flipped_items], sum(count for _, count in flipped_items)
    if isinstance(value, float) and value == 0.0:
        return -0.0, 1
    return value, 0


def _numbers(value: Any) -> Iterator[float]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from _numbers(item)
    elif isinstance(value, float):
        yield value


def _sign_of(value: Any) -> float:
    """Read the sign of a normalised number.

    ``semantic_representation`` is typed as returning any JSON value, because that is
    what it can return; the assertions below are about numbers specifically, so the
    narrowing happens here rather than by weakening the public type.
    """
    assert isinstance(value, float)
    return math.copysign(1.0, value)


# --------------------------------------------------------------------------
# the boundary itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_canonical_bytes_are_the_canonical_bytes_of_the_declared_json_dump(build: Any) -> None:
    """The validated object *is* the semantic representation. If identity were computed
    over anything else, this equality would fail."""
    definition = build()
    assert canonical_semantic_bytes(definition) == canonical_bytes(
        definition.model_dump(mode="json")
    )


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_the_semantic_representation_preserves_every_sequence_in_authored_order(
    build: Any,
) -> None:
    """The identity layer never reorders a sequence. Whether ordering carries meaning
    is a domain decision, taken at validation time, and must not be smuggled in here."""
    assert semantic_representation(build()) == build().model_dump(mode="json")


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_semantic_sha256_is_the_sha256_of_the_canonical_bytes(build: Any) -> None:
    definition = build()
    digest = semantic_sha256(definition)
    assert isinstance(digest, SemanticDigest)
    assert digest.hex == hashlib.sha256(canonical_semantic_bytes(definition)).hexdigest()
    assert digest.model_dump() == {"algorithm": "sha256", "hex": digest.hex}


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_a_definition_reloaded_from_its_own_json_keeps_its_identity(build: Any) -> None:
    """Digest, serialise, validate, digest again must be a fixed point, or the same
    authority could be addressed by two identities depending on how it was loaded."""
    definition = build()
    reloaded = type(definition).model_validate_json(definition.model_dump_json())
    assert semantic_sha256(reloaded) == semantic_sha256(definition)


def test_a_definition_and_its_own_json_representation_have_one_identity() -> None:
    release = benchmark_release()
    assert semantic_sha256(release) == semantic_sha256(release.model_dump(mode="json"))


def test_a_nested_domain_object_is_flattened_into_its_own_meaning() -> None:
    quantity = quantity_definition()
    assert semantic_representation({"inner": quantity}) == {
        "inner": quantity.model_dump(mode="json")
    }


@pytest.mark.parametrize(
    "value", [b"bytes", {1, 2}, object(), complex(1, 2)], ids=["bytes", "set", "object", "complex"]
)
def test_a_value_with_no_semantic_representation_fails_closed(value: Any) -> None:
    _rejects(value)


@pytest.mark.parametrize(
    "key", [1, 2.5, b"k", ("a", "b"), None], ids=["int", "float", "bytes", "tuple", "none"]
)
def test_a_property_name_that_is_not_a_string_fails_closed(key: Any) -> None:
    _rejects({key: "value"})


@pytest.mark.parametrize(
    "value", [math.nan, math.inf, -math.inf], ids=["nan", "infinity", "negative-infinity"]
)
def test_a_non_finite_number_fails_closed_before_canonicalisation(value: float) -> None:
    _rejects(value)
    _rejects({"nested": [{"deep": value}]})


def test_no_two_meanings_in_the_corpus_share_a_digest() -> None:
    digests = [semantic_sha256(build()) for build in DEFINITIONS]
    assert len(set(digests)) == len(digests)


def test_a_shared_digest_is_always_shared_meaning() -> None:
    """The property that matters about a content digest: a shared digest never stands
    for two different definitions."""
    by_digest: dict[SemanticDigest, DomainModel] = {}
    for build in DEFINITIONS:
        original = build()
        round_tripped = type(original).model_validate_json(original.model_dump_json())
        for definition in (original, build(), round_tripped):
            assert by_digest.setdefault(semantic_sha256(definition), definition) == definition


# --------------------------------------------------------------------------
# negative zero: the one number rule this layer owns
# --------------------------------------------------------------------------


def test_the_negative_zero_rule_is_declared_rather_than_inherited() -> None:
    assert NEGATIVE_ZERO_IS_NORMALISED is True


def test_the_semantic_layer_normalises_negative_zero_before_canonicalisation() -> None:
    """RFC 8785 also collapses ``-0`` onto ``0``, so a test of the canonical bytes alone
    cannot show who decided it. ``math.copysign`` reads this layer's own output and
    shows that the normalisation happened here, on its own predicate."""
    assert _sign_of(semantic_representation(-0.0)) == 1.0
    assert _sign_of(semantic_representation(0.0)) == 1.0
    assert _sign_of(semantic_representation({"values": [-0.0]}["values"][0])) == 1.0


NEGATIVE_ZERO_PAIRS = (
    pytest.param(
        quantity_assignment(value=-0.0),
        quantity_assignment(value=0.0),
        id="initial-condition",
    ),
    pytest.param(
        MetricAggregation(method=AggregationMethod.MEAN, window_start_s=-0.0, window_end_s=1.0),
        MetricAggregation(method=AggregationMethod.MEAN, window_start_s=0.0, window_end_s=1.0),
        id="metric-window-start",
    ),
    pytest.param(PointValue(value=-0.0), PointValue(value=0.0), id="controlled-factor"),
    pytest.param(
        event("takeoff", expected_time_s=-0.0, tolerance_s=0.005),
        event("takeoff", expected_time_s=0.0, tolerance_s=0.005),
        id="event-expected-time",
    ),
)


@pytest.mark.parametrize(("negative", "positive"), NEGATIVE_ZERO_PAIRS)
def test_two_authorings_that_differ_only_in_the_sign_of_zero_are_one_meaning(
    negative: DomainModel, positive: DomainModel
) -> None:
    assert semantic_sha256(negative) == semantic_sha256(positive)
    assert not _carries_negative_zero(semantic_representation(negative))


def test_negative_zero_is_reachable_authority_and_is_normalised_across_a_whole_release() -> None:
    """RES-228 validates that domain numbers are finite and says nothing about the sign
    of zero, so ``-0.0`` is a legal authoring input. Flipping every zero in a full
    release to ``-0.0`` therefore has to leave the identity untouched."""
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    flipped_payload, flipped = _flip_zero_signs(payload)
    assert flipped > 0, "the release under test contains no floating-point zero to flip"
    negative_release = BenchmarkRelease.model_validate(flipped_payload)
    assert semantic_sha256(negative_release) == semantic_sha256(release)
    assert not _carries_negative_zero(semantic_representation(negative_release))


def _carries_negative_zero(value: Any) -> bool:
    """Whether any number in the representation is a negative zero."""
    return any(number == 0.0 and math.copysign(1.0, number) < 0.0 for number in _numbers(value))


@pytest.mark.parametrize(
    ("negative", "positive"),
    [(-1.5, 1.5), (-5e-324, 5e-324), (-1e-300, 1e-300)],
    ids=["ordinary", "smallest-subnormal", "tiny"],
)
def test_a_negative_value_that_is_not_zero_keeps_its_sign(negative: float, positive: float) -> None:
    """The rule is about zero, not about the minus sign."""
    assert semantic_representation(negative) == negative
    assert _sign_of(semantic_representation(negative)) == -1.0
    assert semantic_sha256(quantity_assignment(value=negative)) != semantic_sha256(
        quantity_assignment(value=positive)
    )


def test_the_smallest_representable_magnitude_is_not_collapsed_onto_zero() -> None:
    smallest = 5e-324
    assert semantic_representation(smallest) == smallest
    assert semantic_sha256(quantity_assignment(value=smallest)) != semantic_sha256(
        quantity_assignment(value=0.0)
    )


# --------------------------------------------------------------------------
# SemVer build metadata is part of identity
# --------------------------------------------------------------------------


def test_two_versions_differing_only_in_build_metadata_are_two_artifacts() -> None:
    """RES-228 retains build metadata as part of identity because they are different
    artifacts. Nothing here may quietly restore SemVer *precedence* semantics, under
    which ``1.2.3+abc`` and ``1.2.3+def`` would be one version."""
    first = quantity_definition(version="1.2.3+abc")
    second = quantity_definition(version="1.2.3+def")
    plain = quantity_definition(version="1.2.3")
    assert semantic_sha256(first) != semantic_sha256(second)
    assert semantic_sha256(first) != semantic_sha256(plain)
    assert b"1.2.3+abc" in canonical_semantic_bytes(first)
    assert b"1.2.3+def" in canonical_semantic_bytes(second)


def test_an_identical_version_gives_an_identical_identity() -> None:
    assert semantic_sha256(quantity_definition(version="1.2.3+abc")) == semantic_sha256(
        quantity_definition(version="1.2.3+abc")
    )


# --------------------------------------------------------------------------
# identity is over the semantic unit, not the authored spelling
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("first", "second"), EQUIVALENT_UNITS, ids=EQUIVALENT_UNIT_IDS)
def test_equivalent_authorings_of_one_unit_have_one_identity(first: str, second: str) -> None:
    left = _UnitHolder(unit=CanonicalUnit(expression=first))
    right = _UnitHolder(unit=CanonicalUnit(expression=second))
    assert left.unit.expression == right.unit.expression
    assert canonical_semantic_bytes(left) == canonical_semantic_bytes(right)


@pytest.mark.parametrize(
    ("expression", "other"),
    [("mm", "m"), ("kN", "N"), ("ms", "s")],
    ids=["mm-m", "kN-N", "ms-s"],
)
def test_a_different_unit_is_a_different_meaning(expression: str, other: str) -> None:
    assert semantic_sha256(_UnitHolder(unit=CanonicalUnit(expression=expression))) != (
        semantic_sha256(_UnitHolder(unit=CanonicalUnit(expression=other)))
    )


def test_the_canonical_bytes_carry_the_canonical_unit_spelling_not_the_authored_one() -> None:
    quantity = quantity_definition(
        dimension=PhysicalDimension(length=1), unit=CanonicalUnit(expression="1e-3*m")
    )
    assert b'"expression":"0.001*m"' in canonical_semantic_bytes(quantity)
    assert b"1e-3" not in canonical_semantic_bytes(quantity)


def test_a_derived_unit_property_does_not_leak_a_second_spelling_into_the_identity() -> None:
    """``CanonicalUnit.scale`` is a property rather than a field, so it cannot drift
    into the identity and give one unit two representations."""
    millimetres = _UnitHolder(unit=CanonicalUnit(expression="mm"))
    assert millimetres.unit.scale != 1
    assert semantic_sha256(millimetres) == semantic_sha256(
        _UnitHolder(unit=CanonicalUnit(expression="0.001*m"))
    )


# --------------------------------------------------------------------------
# the human identity is carried, not replaced
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("build", "field", "value"), HUMAN_IDENTITIES, ids=HUMAN_IDENTITY_IDS)
def test_renaming_the_human_identifier_changes_the_identity(
    build: Any, field: str, value: str
) -> None:
    original = build()
    renamed = build(**{field: value})
    assert getattr(renamed, field) == value
    assert getattr(renamed, field) != getattr(original, field)
    assert semantic_sha256(renamed) != semantic_sha256(original)


def test_a_definition_carries_its_human_identity_inside_its_canonical_meaning() -> None:
    """An authoritative reference can state ``id`` and ``semantic_digest`` together
    without the hash becoming the name."""
    release = benchmark_release()
    canonical = canonical_semantic_bytes(release)
    assert b'"benchmark_id":"db.lcmj20"' in canonical
    assert b'"version":"1.0.0"' in canonical
    digest = semantic_sha256(release)
    assert digest.hex not in canonical.decode("utf-8")


def test_a_digest_records_its_algorithm_and_is_never_a_bare_string() -> None:
    digest = semantic_sha256(quantity_definition())
    assert isinstance(digest, SemanticDigest)
    assert digest.model_dump(mode="json") == {"algorithm": "sha256", "hex": digest.hex}


# --------------------------------------------------------------------------
# the rest of the model travels unchanged
# --------------------------------------------------------------------------


def test_an_omitted_optional_field_is_carried_as_an_explicit_null() -> None:
    """``axis_convention=None`` and an absent ``axis_convention`` are one meaning, and
    the canonical form states that explicitly rather than relying on absence."""
    assert b'"axis_convention":null' in canonical_semantic_bytes(
        quantity_definition(axis_convention=None)
    )


def test_a_rotation_sense_is_order_significant() -> None:
    def convention(sense: RotationSense) -> AxisConvention:
        return AxisConvention(order=("x", "y", "z"), sense=sense)

    assert semantic_sha256(
        quantity_definition(axis_convention=convention(RotationSense.INTRINSIC))
    ) != semantic_sha256(quantity_definition(axis_convention=convention(RotationSense.EXTRINSIC)))


def test_a_reference_origin_and_citation_travel_in_the_identity() -> None:
    experimental = reference_definition(
        origin=ReferenceOrigin.EXPERIMENTAL, category=VerificationCategory.MODEL_VALIDATION
    )
    published = reference_definition(
        origin=ReferenceOrigin.PUBLISHED,
        category=VerificationCategory.MODEL_VALIDATION,
        citation="doi:10.0000/example",
    )
    assert semantic_sha256(experimental) != semantic_sha256(published)


def test_a_varied_factor_and_a_controlled_factor_are_different_meanings() -> None:
    assert semantic_sha256(uncertainty_factor()) != semantic_sha256(controlled_factor())


def test_a_deeper_release_digests_to_something_inspectable() -> None:
    """A real nested definition, so the boundary is exercised on the shape that will
    actually be hashed in M5, and the result stays human-inspectable."""
    release = benchmark_release()
    canonical = canonical_semantic_bytes(release)
    assert canonical.startswith(b'{"applicability_domain":[]')
    assert canonical.endswith(b"}")
    assert b"\n" not in canonical
    assert json.loads(canonical.decode("utf-8")) == release.model_dump(mode="json")
