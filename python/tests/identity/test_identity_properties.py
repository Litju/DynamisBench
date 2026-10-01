"""Property and determinism gates for canonical identity (ADR-006).

The property everything else depends on is:

    two definitions with the same meaning have the same digest, and two definitions
    with different meaning have different digests.

These tests attack it from both sides.

**Authoring irrelevance.** Whitespace, property order, YAML versus JSON, and the
authoring order of a collection the domain declared order-insensitive must all be
invisible. ``test_yaml_source_text_never_reach_identity`` is the sharpest of these: it
re-authors a whole definition as YAML, with comments, different indentation, narrow line
wrapping and reversed property order, and requires the same digest.

**Semantic sensitivity.** Any change to authoritative meaning must change the digest, and
the generated text reaches past labels into descriptions, claim ceilings and research
questions. Negative zero is excluded from the generated floats precisely because that
one pair of inputs is *documented as one meaning* rather than being an oversight.

**Ordering.** Order-insensitive keyed collections stay identical under re-authoring in any
order, while semantically ordered sequences - a rotation order, a set of notes, a
command line, a rung of the credibility ladder - stay sensitive.

**Determinism.** Canonicalisation is repeated in-process and re-run in independent
interpreter processes under deliberately different hash seeds and locales. If any part of
identity depended on dict iteration order, the interpreter's per-process hash
randomisation would show up here and the Windows/Linux parity gate would be meaningless.

**Assets and digest typing.** Raw-byte identity depends on content alone; the two digest
types are not interchangeable; and nothing a definition says can change an asset's digest.

The public-boundary properties - no simulator import, and no environment, clock,
randomness or filesystem in a semantic digest - are gated structurally in
``test_public_boundary.py``.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from hypothesis import assume, given
from hypothesis import strategies as st

import dynamisbench.domain.spec as spec
from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.benchmark import BenchmarkRelease, CredibilityLevel
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.quantities import AxisConvention, RotationSense
from dynamisbench.domain.spec.realizations import AssetReference
from dynamisbench.domain.spec.sut import SUTInterface, SUTInterfaceKind
from dynamisbench.identity import (
    AssetDigest,
    SemanticDigest,
    asset_sha256,
    asset_sha256_of_file,
    canonical_semantic_bytes,
    semantic_sha256,
)

from ..domain.factories import (
    benchmark_release,
    capability_requirement,
    environment_definition,
    quantity_assignment,
    quantity_definition,
    realization_definition,
    scenario_definition,
    study_definition,
    sut_definition,
)
from .test_golden_corpus import FIXTURES, _index

DEFINITIONS = (
    quantity_definition,
    scenario_definition,
    realization_definition,
    sut_definition,
    environment_definition,
    study_definition,
    benchmark_release,
)

DEFINITION_IDS = [build.__name__ for build in DEFINITIONS]

KEYED_COLLECTIONS = ("quantities", "scenarios", "metrics", "references")

UNCHANGED = "unchanged baseline authority text"
"""A value the generated text is required to differ from, so the comparison is a real
change of meaning rather than a no-op."""

MEANINGFUL_CHANGES = (
    (quantity_definition, "quantity.label", "label"),
    (quantity_definition, "quantity.description", "description"),
    (benchmark_release, "benchmark.label", "label"),
    (benchmark_release, "benchmark.claim-ceiling", "claim_ceiling"),
    (realization_definition, "realization.label", "label"),
    (sut_definition, "sut.description", "description"),
    (environment_definition, "environment.label", "label"),
    (study_definition, "study.research-question", "research_question"),
    (scenario_definition, "scenario.label", "label"),
)

SENSITIVITY_IDS = [field for _, field, _ in MEANINGFUL_CHANGES]

ORDERED_SEQUENCES = (
    (quantity_definition, "quantity.notes"),
    (benchmark_release, "benchmark.notes"),
    (study_definition, "study.notes"),
)

ORDERED_SEQUENCE_IDS = [field for _, field in ORDERED_SEQUENCES]

MEANINGFUL_TEXT = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x2FF, exclude_categories=("Cs",)),
    min_size=1,
    max_size=120,
).filter(lambda text: bool(text.strip()) and text.strip() == text)

MEANINGFUL_FLOATS = st.floats(allow_nan=False, allow_infinity=False, allow_subnormal=False).filter(
    lambda value: not (value == 0.0 and math.copysign(1.0, value) < 0.0)
)

_CHILD_SCRIPT = "\n".join(
    [
        "import json",
        "import sys",
        "from pathlib import Path",
        "import dynamisbench.domain.spec as spec",
        "from dynamisbench.identity import canonical_semantic_bytes, semantic_sha256",
        "root = Path(sys.argv[1])",
        "cases = json.loads((root / 'identity' / 'golden.json').read_text(",
        "    encoding='utf-8'))['cases']",
        "rows = []",
        "for case in cases:",
        "    document = json.loads((root / case['input']).read_text(encoding='utf-8'))",
        "    model = getattr(spec, case['definition'])",
        "    definition = model.model_validate(document)",
        "    rows.append([",
        "        case['name'],",
        "        semantic_sha256(definition).hex,",
        "        canonical_semantic_bytes(definition).hex(),",
        "    ])",
        "sys.stdout.write(json.dumps(rows))",
    ]
)


def _reversed_keys(value: Any) -> Any:
    """The same document with every object's properties in reverse authoring order."""
    if isinstance(value, dict):
        return {key: _reversed_keys(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [_reversed_keys(item) for item in value]
    return value


def _child_identities(hash_seed: str, locale: str = "C") -> list[list[str]]:
    """Canonicalise the whole golden corpus in a fresh interpreter."""
    environment = {**os.environ, "PYTHONHASHSEED": hash_seed, "LC_ALL": locale, "LANG": locale}
    result = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT, str(FIXTURES)],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
    )
    return json.loads(result.stdout)


def _validated(name: str) -> Any:
    case = next(entry for entry in _index()["cases"] if entry["name"] == name)
    document = json.loads((FIXTURES / case["input"]).read_text(encoding="utf-8"))
    return getattr(spec, case["definition"]).model_validate(document)


# --------------------------------------------------------------------------
# authoring irrelevance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
@pytest.mark.parametrize("indent", [None, 2, 4, "\t"], ids=["compact", "two", "four", "tab"])
def test_json_whitespace_and_property_order_never_reach_identity(build: Any, indent: Any) -> None:
    definition = build()
    text = json.dumps(definition.model_dump(mode="json"), indent=indent)
    reloaded = type(definition).model_validate(json.loads(text))
    assert semantic_sha256(reloaded) == semantic_sha256(definition)


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_property_order_never_reaches_identity(build: Any) -> None:
    definition = build()
    reordered = type(definition).model_validate(_reversed_keys(definition.model_dump(mode="json")))
    assert semantic_sha256(reordered) == semantic_sha256(definition)


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_yaml_source_text_never_reach_identity(build: Any) -> None:
    """The sharpest form of authoring irrelevance: a re-authored YAML document, with
    comments, different indentation, narrow line wrapping and reversed property order, is
    the same authority and must have the same digest."""
    definition = build()
    document = yaml.safe_dump(
        _reversed_keys(definition.model_dump(mode="json")),
        sort_keys=False,
        default_flow_style=False,
        indent=4,
        width=60,
        allow_unicode=True,
    )
    source = "\n".join(
        [
            "# DB-1.3 authoring-irrelevance fixture.",
            "# Comments, indentation, key order and line wrapping are not authority.",
            "---",
            document,
        ]
    )
    reloaded = type(definition).model_validate(yaml.safe_load(source))
    assert semantic_sha256(reloaded) == semantic_sha256(definition)


# --------------------------------------------------------------------------
# semantic sensitivity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("build", "field", "keyword"), MEANINGFUL_CHANGES, ids=SENSITIVITY_IDS)
@given(text=MEANINGFUL_TEXT)
def test_changing_authoritative_text_changes_the_digest(
    build: Any, field: str, keyword: str, text: str
) -> None:
    assume(text != UNCHANGED)
    changed = build(**{keyword: text})
    original = build(**{keyword: UNCHANGED})
    assert semantic_sha256(changed) != semantic_sha256(original), (
        f"{field} changed but the semantic digest did not"
    )


@given(first=MEANINGFUL_FLOATS, second=MEANINGFUL_FLOATS)
def test_changing_a_number_changes_the_digest(first: float, second: float) -> None:
    assume(first != second)
    assert semantic_sha256(quantity_assignment(value=first)) != semantic_sha256(
        quantity_assignment(value=second)
    )


def test_changing_a_capability_set_changes_the_identity() -> None:
    forward_only = study_definition(
        required_capabilities=(capability_requirement(Capability.FORWARD_DYNAMICS),)
    )
    forward_and_snapshot = study_definition(
        required_capabilities=(
            capability_requirement(Capability.FORWARD_DYNAMICS),
            capability_requirement(Capability.STATE_SNAPSHOT),
        )
    )
    assert semantic_sha256(forward_only) != semantic_sha256(forward_and_snapshot)


def test_changing_a_rotation_sense_changes_the_identity() -> None:
    def convention(sense: RotationSense) -> AxisConvention:
        return AxisConvention(order=("x", "y", "z"), sense=sense)

    assert semantic_sha256(
        quantity_definition(axis_convention=convention(RotationSense.INTRINSIC))
    ) != semantic_sha256(quantity_definition(axis_convention=convention(RotationSense.EXTRINSIC)))


def test_a_further_rung_of_the_credibility_ladder_changes_the_identity() -> None:
    without_unit_problem = benchmark_release(
        credibility_hierarchy=(
            CredibilityLevel.BENCHMARK_REFERENCE_CASE,
            CredibilityLevel.COMPLETE_SYSTEM,
        )
    )
    with_unit_problem = benchmark_release(
        credibility_hierarchy=(
            CredibilityLevel.UNIT_PROBLEM,
            CredibilityLevel.BENCHMARK_REFERENCE_CASE,
            CredibilityLevel.COMPLETE_SYSTEM,
        )
    )
    assert semantic_sha256(without_unit_problem) != semantic_sha256(with_unit_problem)


# --------------------------------------------------------------------------
# ordering
# --------------------------------------------------------------------------


@pytest.mark.parametrize("collection", KEYED_COLLECTIONS)
def test_a_keyed_collection_is_insensitive_to_authoring_order(collection: str) -> None:
    """RES-228 stores a keyed collection in canonical key order and rejects duplicate
    keys, so two authorings of one set are already identical before identity is computed.
    The identity layer relies on that decision rather than re-deriving it."""
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    payload[collection] = list(reversed(payload[collection]))
    reordered = BenchmarkRelease.model_validate(payload)
    assert (
        reordered.model_dump(mode="json")[collection]
        == (release.model_dump(mode="json")[collection])
    )
    assert semantic_sha256(reordered) == semantic_sha256(release)


@pytest.mark.parametrize("collection", KEYED_COLLECTIONS)
def test_two_versions_of_a_keyed_collection_member_are_different_meanings(collection: str) -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    members = [dict(member) for member in payload[collection]]
    members[-1]["version"] = "2.0.0"
    payload[collection] = members
    assert semantic_sha256(BenchmarkRelease.model_validate(payload)) != semantic_sha256(release)


@pytest.mark.parametrize(("build", "field"), ORDERED_SEQUENCES, ids=ORDERED_SEQUENCE_IDS)
def test_a_semantically_ordered_sequence_stays_order_sensitive(build: Any, field: str) -> None:
    first = build(notes=("first-item", "second-item"))
    second = build(notes=("second-item", "first-item"))
    assert semantic_sha256(first) != semantic_sha256(second)


def test_a_rotation_axis_order_stays_order_sensitive() -> None:
    def convention(*order: str) -> AxisConvention:
        return AxisConvention(order=order, sense=RotationSense.INTRINSIC)

    assert semantic_sha256(
        quantity_definition(axis_convention=convention("x", "y", "z"))
    ) != semantic_sha256(quantity_definition(axis_convention=convention("z", "y", "x")))


def test_a_command_sequence_stays_order_sensitive() -> None:
    def interface(*command: str) -> SUTInterface:
        return SUTInterface(kind=SUTInterfaceKind.SUBPROCESS, command=command)

    assert semantic_sha256(
        sut_definition(interface=interface("python", "-m", "controller"))
    ) != semantic_sha256(sut_definition(interface=interface("-m", "python", "controller")))


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


@pytest.mark.parametrize("build", DEFINITIONS, ids=DEFINITION_IDS)
def test_repeated_canonicalisation_in_one_process_is_byte_identical(build: Any) -> None:
    definition = build()
    canonical = [canonical_semantic_bytes(definition) for _ in range(10)]
    digests = [semantic_sha256(definition) for _ in range(10)]
    assert all(item == canonical[0] for item in canonical)
    assert all(digest == digests[0] for digest in digests)


def test_independent_processes_produce_byte_identical_canonical_output() -> None:
    """The cross-platform parity claim, made locally: a fresh interpreter with a
    different hash seed and locale must reproduce every committed canonical byte string
    and digest. If dictionary iteration order could reach identity, hash randomisation
    would break this."""
    golden = FIXTURES / "identity"
    expected = [
        [
            case["name"],
            case["sha256"],
            (golden / case["canonical"]).read_bytes().hex(),
        ]
        for case in _index()["cases"]
    ]
    assert _child_identities("0") == expected
    assert _child_identities("524287") == expected
    assert _child_identities("1", locale="C.UTF-8") == expected


def test_this_process_agrees_with_an_independent_one() -> None:
    assert [row[1:] for row in _child_identities("0")] == [
        [semantic_sha256(_validated(name)).hex, canonical_semantic_bytes(_validated(name)).hex()]
        for name, _, _ in _child_identities("0")
    ]


# --------------------------------------------------------------------------
# assets
# --------------------------------------------------------------------------


@given(payload=st.binary(max_size=4096))
def test_identical_bytes_always_give_one_asset_digest(payload: bytes) -> None:
    assert asset_sha256(payload) == asset_sha256(payload)
    assert isinstance(asset_sha256(payload), AssetDigest)


@given(payload=st.binary(min_size=1), offset=st.integers(min_value=0))
def test_one_changed_byte_always_changes_the_asset_digest(payload: bytes, offset: int) -> None:
    position = offset % len(payload)
    mutated = payload[:position] + bytes((payload[position] ^ 0x01,)) + payload[position + 1 :]
    assert mutated != payload
    assert asset_sha256(payload) != asset_sha256(mutated)


def test_moving_an_asset_leaves_its_digest_and_changes_the_realization(tmp_path: Path) -> None:
    """Two identities, two answers: the same bytes are the same artifact, while the
    definition that points at them is a different piece of authority."""
    original = tmp_path / "models" / "subject.xml"
    moved = tmp_path / "cache" / "subject.xml"
    original.parent.mkdir(parents=True)
    moved.parent.mkdir(parents=True)
    payload = b"<mujoco model><worldbody/></mujoco>"
    original.write_bytes(payload)
    moved.write_bytes(payload)
    assert asset_sha256_of_file(original) == asset_sha256_of_file(moved)

    def realization(path: str, digest: AssetDigest) -> Any:
        return realization_definition(
            assets=(
                AssetReference(
                    asset_id="subject-model",
                    path=path,
                    description="Segment geometry and inertia of the modelled subject.",
                    sha256=digest.hex,
                ),
            )
        )

    assert semantic_sha256(
        realization("cache/subject.xml", asset_sha256_of_file(moved))
    ) != semantic_sha256(realization("models/subject.xml", asset_sha256_of_file(original)))


# --------------------------------------------------------------------------
# digest typing
# --------------------------------------------------------------------------


@given(build=st.sampled_from(DEFINITIONS))
def test_a_definition_never_produces_an_asset_digest(build: Any) -> None:
    assert isinstance(semantic_sha256(build()), SemanticDigest)
    assert not isinstance(semantic_sha256(build()), AssetDigest)


def test_the_same_bytes_hashed_as_meaning_and_as_content_are_typed_differently() -> None:
    quantity = quantity_definition()
    raw = canonical_semantic_bytes(quantity)
    assert asset_sha256(raw).hex == semantic_sha256(quantity).hex
    assert type(asset_sha256(raw)) is not type(semantic_sha256(quantity))


def test_equality_of_definitions_is_equality_of_identity() -> None:
    left: DomainModel = quantity_definition()
    right: DomainModel = quantity_definition()
    assert left == right
    assert semantic_sha256(left) == semantic_sha256(right)
