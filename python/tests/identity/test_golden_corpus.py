"""The committed golden canonical-identity corpus.

This corpus is the parity authority for canonical identity. Every Windows/Linux
digest comparison the project will ever make is decided by these committed values: if
the same validated definition canonicalises to different bytes on two machines, or on
two versions of the code, the corpus fails and the difference is visible in a diff.

**Why the whole DB-1.2 valid corpus.** Every case is an existing, committed
``fixtures/domain/valid`` document rather than a synthetic bare-JSON blob or a
duplicated copy of one. That means the identity authority is pinned for every domain
class the project has — quantities including the dimensionless angular case, releases,
scenarios, metrics, references, realizations, systems under test, environments,
studies, factors and the capability vocabulary — and a new domain concept cannot be
added without this corpus covering it. The inputs are referenced, never copied, so an
input and its expected digest cannot drift apart silently.

**What is committed, and why both forms.** Each case records

* ``canonical/<filename>.jcs`` — the exact RFC 8785 canonical bytes, so the bytes
  themselves are inspectable and diffable, not only their hash;
* ``sha256`` — the semantic digest, which is what an authoritative reference cites.

A digest alone would prove nothing to a reader; canonical bytes alone would make every
reviewer re-hash by hand. Both together mean a reader can see what was hashed and check
the hash.

**Why the ``.jcs`` files are byte-stable across platforms.** RFC 8785 escapes every
control character, including both newline characters, so canonical output contains no
raw CR or LF and no text-encoding or line-ending normalisation can touch it. A gate
below asserts that, because the whole parity claim rests on it.

Regenerate deliberately with ``pytest --update-golden`` and read the diff: a changed
digest is a changed scientific identity, not a test artefact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import dynamisbench.domain.spec as spec
from dynamisbench.identity import (
    CanonicalizationError,
    SemanticDigest,
    canonical_bytes,
    canonical_semantic_bytes,
    semantic_sha256,
)

from ..domain.test_corpus import VALID_CORPUS, model_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_ROOT = FIXTURES / "identity"
GOLDEN_INDEX = GOLDEN_ROOT / "golden.json"
CANONICAL_ROOT = GOLDEN_ROOT / "canonical"

INDEX = json.loads(GOLDEN_INDEX.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = INDEX["cases"]
CASE_IDS = [case["name"] for case in CASES]

HEX_DIGITS = frozenset("0123456789abcdef")


def _index() -> dict[str, Any]:
    """The committed index, re-read so that a regeneration is visible immediately."""
    return json.loads(GOLDEN_INDEX.read_text(encoding="utf-8"))


def _definition_of(case: dict[str, Any]) -> Any:
    document = json.loads((FIXTURES / case["input"]).read_text(encoding="utf-8"))
    return getattr(spec, case["definition"]).model_validate(document)


def _write_corpus() -> dict[str, bytes]:
    CANONICAL_ROOT.mkdir(parents=True, exist_ok=True)
    canonical_by_name: dict[str, bytes] = {}
    cases = []
    for case in CASES:
        definition = _definition_of(case)
        canonical = canonical_semantic_bytes(definition)
        canonical_by_name[case["name"]] = canonical
        (GOLDEN_ROOT / case["canonical"]).write_bytes(canonical)
        cases.append({**case, "sha256": semantic_sha256(definition).hex})
    GOLDEN_INDEX.write_text(
        json.dumps({**INDEX, "cases": cases}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return canonical_by_name


@pytest.fixture(scope="module", autouse=True)
def _regenerate_when_requested(request: pytest.FixtureRequest) -> None:
    """Rewrite the corpus before anything reads it, and only when asked.

    Regeneration is opt-in and writes files, so it can never be how a test makes itself
    pass by accident; the result is always a reviewable diff.
    """
    if request.config.getoption("--update-golden"):
        _write_corpus()


def test_the_corpus_covers_every_valid_domain_document() -> None:
    """A new domain concept is not qualified until the identity corpus covers it, in
    the same way the DB-1.2 corpus requires valid and invalid fixtures for each."""
    covered = {Path(case["input"]).name for case in CASES}
    assert covered == {filename for filename, _ in VALID_CORPUS}


def test_every_case_names_a_definition_that_exists_and_matches_its_fixture() -> None:
    for case in CASES:
        filename = Path(case["input"]).name
        assert model_for(filename).__name__ == case["definition"], case["name"]
        assert getattr(spec, case["definition"]).__module__.startswith("dynamisbench.domain.spec")


def test_every_case_is_described_and_points_at_a_committed_canonical_file() -> None:
    for case in CASES:
        assert case["description"].strip(), case["name"]
        assert (GOLDEN_ROOT / case["canonical"]).is_file(), case["name"]
        assert case["canonical"] == f"canonical/{case['name']}.jcs", case["name"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_case_canonicalises_to_its_committed_bytes_and_digest(case: dict[str, Any]) -> None:
    definition = _definition_of(case)
    canonical = canonical_semantic_bytes(definition)
    digest = semantic_sha256(definition)
    committed = (GOLDEN_ROOT / case["canonical"]).read_bytes()
    expected = next(entry for entry in _index()["cases"] if entry["name"] == case["name"])

    assert canonical == committed, (
        f"{case['name']} canonicalises to different bytes than the committed authority"
    )
    assert isinstance(digest, SemanticDigest)
    assert digest.hex == expected["sha256"], f"{case['name']} has a different semantic digest"
    assert set(expected["sha256"]) <= HEX_DIGITS
    assert len(expected["sha256"]) == 64


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_committed_canonical_file_is_the_whole_definition_as_inspectable_json(
    case: dict[str, Any],
) -> None:
    """A reader must be able to open the committed bytes and see the definition without
    running any code: the file parses as JSON, carries the entire meaning, and
    re-canonicalises to itself. The re-canonicalisation is what proves no insignificant
    whitespace or formatting survived, since any of it would survive the round trip as a
    different byte string."""
    committed = (GOLDEN_ROOT / case["canonical"]).read_bytes()
    definition = _definition_of(case)
    text = committed.decode("utf-8")
    assert json.loads(text) == definition.model_dump(mode="json")
    assert canonical_bytes(json.loads(text)) == committed


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_committed_canonical_file_carries_no_byte_a_platform_could_rewrite(
    case: dict[str, Any],
) -> None:
    """Canonical output escapes CR and LF, so no checkout, line-ending policy or text
    encoding can alter it. The Windows/Linux parity claim depends on this."""
    committed = (GOLDEN_ROOT / case["canonical"]).read_bytes()
    assert b"\r" not in committed
    assert b"\n" not in committed
    assert committed == canonical_semantic_bytes(_definition_of(case))


def test_two_cases_never_share_a_digest() -> None:
    digests = [entry["sha256"] for entry in _index()["cases"]]
    assert len(set(digests)) == len(digests)


def test_the_corpus_records_its_own_provenance() -> None:
    index = _index()
    assert index["canonicalisation"] == "RFC 8785 (JSON Canonicalization Scheme)"
    assert index["digest"] == "sha256"
    assert index["authority"].startswith("DB-1.3 (RES-229)")


def test_the_corpus_is_not_trivially_small() -> None:
    assert len(CASES) >= 17


def test_regenerating_the_corpus_twice_changes_nothing(request: pytest.FixtureRequest) -> None:
    """Guards the regeneration switch itself: it must be idempotent, so a regeneration is
    always visible as a diff against committed authority rather than as drift."""
    if not request.config.getoption("--update-golden"):
        pytest.skip("--update-golden was not requested")
    first = _write_corpus()
    assert first == _write_corpus()


def test_no_committed_case_declares_a_value_that_cannot_be_canonicalised() -> None:
    for case in CASES:
        try:
            canonical_semantic_bytes(_definition_of(case))
        except CanonicalizationError as error:  # pragma: no cover - a corpus defect
            pytest.fail(f"{case['name']} in the golden corpus cannot be canonicalised: {error}")
