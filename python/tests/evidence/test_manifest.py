"""The manifest, the evidence digest, and the checksum file.

Everything a sealed bundle's identity is made of, tested as a set of properties rather than
as a snapshot of one example:

* **The manifest is a complete and unambiguous description.** Every payload file appears
  exactly once, in canonical path order, and a file set that could mean two things — an
  empty one, a duplicated path — is refused.
* **Canonical bytes are canonical bytes.** The same manifest always produces the same bytes,
  whatever order the files were listed in, and the bytes never contain an absolute path.
* **The seal does not reference itself.** A manifest cannot enumerate itself, cannot
  enumerate the checksum file, and above all cannot embed its own evidence digest — the last
  is a *structural* guarantee, so it is tested as a validation failure rather than as a
  convention.
* **The evidence digest is the manifest's, and only the manifest's.** It changes if any
  payload digest, the run id, or the outcome changes, and it does not change if the bundle
  is moved.
* **The checksum file covers payload plus manifest and excludes itself**, is byte-stable,
  and refuses every ambiguity that would make it mean two things to another reader —
  including one a standard ``sha256sum`` implementation would misread.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamisbench.evidence import CHECKSUMS_FILE_NAME, ArtifactRole, RunOutcome
from dynamisbench.evidence.manifest import (
    CHECKSUM_SEPARATOR,
    MANIFEST_SCHEMA_VERSION,
    ChecksumEntry,
    EvidenceDigest,
    Manifest,
    ManifestEntry,
    canonical_manifest_bytes,
    coverage_discrepancies,
    evidence_digest_of_canonical_manifest_bytes,
    manifest_payload_paths,
    parse_checksums,
    parse_manifest,
    render_checksums,
)
from dynamisbench.identity import AssetDigest

RUN = "run-1"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def entry(path: str, payload: bytes = b"x", role: ArtifactRole | None = None) -> ManifestEntry:
    return ManifestEntry(
        relative_path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        role=role,
    )


def manifest(*files: ManifestEntry, outcome: RunOutcome = RunOutcome.SUCCEEDED) -> Manifest:
    return Manifest(run_id=RUN, outcome=outcome, files=files or (entry("run.json", b"{}"),))


# --- the manifest as a typed structure ---------------------------------------------------------


def test_a_manifest_records_the_version_run_outcome_and_files() -> None:
    value = manifest(entry("run.json", b"{}", ArtifactRole.RUN_METADATA))
    assert value.schema_version == MANIFEST_SCHEMA_VERSION
    assert value.run_id == RUN
    assert value.outcome is RunOutcome.SUCCEEDED
    assert value.files[0].role is ArtifactRole.RUN_METADATA


def test_the_role_is_optional() -> None:
    """Sealing must work before any of the v0 bundle members exist."""
    assert manifest(entry("run.json", b"{}")).files[0].role is None


def test_a_manifest_with_no_files_is_refused() -> None:
    """A bundle with no payload would be sealing an empty claim."""
    with pytest.raises(ValueError, match="at least one payload artifact"):
        Manifest(run_id=RUN, outcome=RunOutcome.SUCCEEDED, files=())


def test_a_duplicated_payload_path_is_refused() -> None:
    with pytest.raises(ValueError, match="more than once"):
        manifest(entry("run.json", b"{}"), entry("run.json", b"{}"))


def test_the_files_are_ordered_by_path_not_by_the_order_they_were_supplied() -> None:
    shuffled = manifest(
        entry("z/last.parquet"),
        entry("a/first.parquet"),
        entry("m/middle.parquet"),
    )
    assert manifest_payload_paths(shuffled) == (
        "a/first.parquet",
        "m/middle.parquet",
        "z/last.parquet",
    )


def test_ordering_is_by_path_bytes_so_it_does_not_depend_on_the_filesystem() -> None:
    """A case-differing pair is the case where a locale or a case-insensitive sort differs."""
    value = manifest(entry("B.json"), entry("a.json"), entry("C.json"))
    assert manifest_payload_paths(value) == ("B.json", "C.json", "a.json")


def test_a_negative_size_is_refused() -> None:
    with pytest.raises(ValueError):
        ManifestEntry(relative_path="run.json", sha256=EMPTY_SHA, size_bytes=-1)


def test_a_boolean_is_not_accepted_as_a_size() -> None:
    """``True`` is an ``int`` in Python; a manifest must not be able to say a file is one byte."""
    with pytest.raises(ValueError):
        ManifestEntry(relative_path="run.json", sha256=EMPTY_SHA, size_bytes=True)  # pyright: ignore[reportArgumentType]


def test_a_malformed_digest_is_refused() -> None:
    with pytest.raises(ValueError):
        ManifestEntry(relative_path="run.json", sha256="NOTHEX", size_bytes=0)


def test_an_unknown_schema_version_is_refused() -> None:
    """Half-understood integrity metadata is worse than none."""
    with pytest.raises(ValueError):
        Manifest.model_validate(
            {"schema_version": 2, "run_id": RUN, "outcome": "succeeded", "files": []}
        )


# --- the non-self-referential seal --------------------------------------------------------------


def test_a_manifest_may_not_declare_itself() -> None:
    with pytest.raises(ValueError, match="written by the seal"):
        entry("manifest.json")


def test_a_manifest_may_not_declare_the_checksum_file() -> None:
    with pytest.raises(ValueError, match="written by the seal"):
        entry("checksums.sha256")


def test_a_manifest_may_not_carry_its_own_evidence_digest() -> None:
    """The recursion is impossible because the model refuses unknown fields."""
    from dynamisbench.evidence import BundleIntegrityError

    value = manifest().model_dump(mode="json")
    value["evidence_digest"] = {"algorithm": "sha256", "hex": EMPTY_SHA}
    with pytest.raises(BundleIntegrityError, match="evidence_digest"):
        parse_manifest(json.dumps(value).encode("utf-8"))


def test_the_evidence_digest_is_the_digest_of_the_canonical_manifest_bytes() -> None:
    value = manifest()
    canonical = canonical_manifest_bytes(value)
    assert (
        evidence_digest_of_canonical_manifest_bytes(canonical).hex
        == hashlib.sha256(canonical).hexdigest()
    )


def test_the_evidence_digest_is_a_third_identity_type_not_a_semantic_or_asset_one() -> None:
    """They answer different questions, so substituting one for another is a type error."""
    from dynamisbench.identity import AssetDigest as IdentityAsset
    from dynamisbench.identity import SemanticDigest

    digest = evidence_digest_of_canonical_manifest_bytes(b"{}")
    assert isinstance(digest, EvidenceDigest)
    assert not isinstance(digest, SemanticDigest)
    assert not isinstance(digest, IdentityAsset)


def test_the_evidence_digest_records_its_algorithm_explicitly() -> None:
    digest = evidence_digest_of_canonical_manifest_bytes(b"{}")
    assert digest.algorithm == "sha256"
    assert json.loads(canonical_manifest_bytes(manifest()))["schema_version"] == 1


# --- canonical bytes ---------------------------------------------------------------------------


def test_the_canonical_manifest_bytes_are_deterministic() -> None:
    first = manifest(entry("run.json", b"{}"), entry("native/t.parquet", b"p"))
    second = manifest(entry("native/t.parquet", b"p"), entry("run.json", b"{}"))
    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)


def test_the_canonical_manifest_bytes_are_rfc8785_with_no_pretty_printing() -> None:
    canonical = canonical_manifest_bytes(manifest())
    assert b" " not in canonical.replace(b'"', b"")
    assert not canonical.endswith(b"\n")


def test_the_canonical_manifest_never_contains_an_absolute_path() -> None:
    """The property that makes a workspace relocatable without changing its identity."""
    canonical = canonical_manifest_bytes(
        manifest(entry("run.json", b"{}"), entry("native/t.parquet", b"p"))
    ).decode("utf-8")
    for machine_artifact in (":\\", "/home/", "C:/", "Users\\", "Temp\\"):
        assert machine_artifact not in canonical
    assert '"relative_path":"run.json"' in canonical


def test_the_schema_version_constant_and_the_closed_literal_agree() -> None:
    """The field is spelled ``Literal[1]``; this is what stops the two drifting apart."""
    assert MANIFEST_SCHEMA_VERSION == 1
    assert Manifest.model_fields["schema_version"].default == MANIFEST_SCHEMA_VERSION


def test_parsing_a_canonical_manifest_round_trips_to_the_same_bytes() -> None:
    canonical = canonical_manifest_bytes(manifest(entry("run.json", b"{}")))
    assert canonical_manifest_bytes(parse_manifest(canonical)) == canonical


def test_a_manifest_stored_in_any_other_form_is_readable_but_is_not_canonical() -> None:
    """The verifier reports these as two different findings, so the model check stands alone."""
    value = manifest()
    pretty = json.dumps(value.model_dump(mode="json"), indent=2).encode("utf-8")
    assert parse_manifest(pretty) == value
    assert canonical_manifest_bytes(parse_manifest(pretty)) != pretty


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'{"run_id":"run-1"}',
        b'{"run_id":"run-1","outcome":"exploded","files":[]}',
        b'{"run_id":"run-1","outcome":"succeeded","files":[]}',
        b'{"schema_version":1,"run_id":"../escape","outcome":"succeeded","files":[]}',
        b'{"schema_version":1,"run_id":"run-1","outcome":"succeeded","files":[],"x":1}',
    ],
)
def test_anything_that_is_not_a_manifest_is_refused(raw: bytes) -> None:
    from dynamisbench.evidence import BundleIntegrityError

    with pytest.raises(BundleIntegrityError):
        parse_manifest(raw)


def test_a_manifest_larger_than_the_read_bound_is_refused() -> None:
    from dynamisbench.evidence import BundleIntegrityError
    from dynamisbench.evidence.manifest import MAX_MANIFEST_BYTES

    with pytest.raises(BundleIntegrityError, match="larger than"):
        parse_manifest(b" " * (MAX_MANIFEST_BYTES + 1))


# --- the checksum file -------------------------------------------------------------------------


def test_the_checksum_file_covers_every_payload_file_and_the_manifest() -> None:
    value = manifest(entry("run.json", b"{}"), entry("native/t.parquet", b"p"))
    canonical = canonical_manifest_bytes(value)
    entries = parse_checksums(render_checksums(value, canonical))
    assert {item.relative_path for item in entries} == {
        "run.json",
        "native/t.parquet",
        "manifest.json",
    }


def test_the_checksum_file_excludes_itself() -> None:
    """The one exclusion that makes the coverage rule non-circular."""
    value = manifest(entry("run.json", b"{}"))
    raw = render_checksums(value, canonical_manifest_bytes(value))
    assert b"checksums.sha256" not in raw


def test_the_checksum_file_is_byte_stable() -> None:
    value = manifest(entry("run.json", b"{}"), entry("native/t.parquet", b"p"))
    canonical = canonical_manifest_bytes(value)
    assert render_checksums(value, canonical) == render_checksums(value, canonical)


def test_the_checksum_file_does_not_depend_on_the_order_files_were_declared() -> None:
    first = manifest(entry("z.parquet", b"z"), entry("a.parquet", b"a"))
    second = manifest(entry("a.parquet", b"a"), entry("z.parquet", b"z"))
    assert render_checksums(first, canonical_manifest_bytes(first)) == render_checksums(
        second, canonical_manifest_bytes(second)
    )


def test_the_checksum_file_is_sorted_by_path_and_uses_the_gnu_separator() -> None:
    value = manifest(entry("z.parquet", b"z"), entry("a.parquet", b"a"))
    raw = render_checksums(value, canonical_manifest_bytes(value)).decode("utf-8")
    paths = [line[len(EMPTY_SHA) + 2 :] for line in raw.splitlines()]
    assert paths == sorted(paths)
    for line in raw.splitlines():
        assert f"{EMPTY_SHA}{CHECKSUM_SEPARATOR}" in line or line[len(EMPTY_SHA) + 2 :]


def test_the_checksum_file_is_readable_by_the_standard_gnu_format() -> None:
    """One line, exactly the shape ``sha256sum -c`` expects, so the bundle is checkable
    without this package installed."""
    value = manifest(entry("run.json", b"{}"))
    raw = render_checksums(value, canonical_manifest_bytes(value)).decode("utf-8")
    assert all(len(line) > 66 and line[64:66] == CHECKSUM_SEPARATOR for line in raw.splitlines())
    assert raw.endswith("\n")


def test_rendering_refuses_manifest_bytes_that_are_not_this_manifests_canonical_form() -> None:
    """Otherwise the evidence digest and the checksum file would describe two bundles."""
    value = manifest(entry("run.json", b"{}"))
    with pytest.raises(Exception, match="different manifest bytes"):
        render_checksums(value, b'{"run_id":"other"}')


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("\n", "blank"),
        ("a" * 64 + "  run.json", "no trailing newline"),
        (EMPTY_SHA + " run.json\n", "one space instead of two"),
        (EMPTY_SHA + "   run.json\n", "three spaces, so the path would start with a space"),
        (EMPTY_SHA + "  run.json\r\n", "CRLF"),
        (EMPTY_SHA.upper() + "  run.json\n", "upper-case hex"),
        (EMPTY_SHA[:-1] + "  run.json\n", "63 hex characters"),
        (EMPTY_SHA + "  ../escape.json\n", "traversal"),
        (EMPTY_SHA + "  /abs.json\n", "absolute"),
        (EMPTY_SHA + "  with space.json\n", "whitespace in a checksum line"),
        (EMPTY_SHA + "  \n", "no file named"),
        (f"{EMPTY_SHA}  run.json\n{EMPTY_SHA}  run.json\n", "listed twice"),
        (f"{EMPTY_SHA}  z.json\n{EMPTY_SHA}  a.json\n", "not sorted"),
        (f"{EMPTY_SHA}  {CHECKSUMS_FILE_NAME}\n", "the checksum file may not cover itself"),
    ],
)
def test_a_checksum_file_that_could_mean_two_things_is_refused(raw: str, reason: str) -> None:
    from dynamisbench.evidence import BundleIntegrityError

    with pytest.raises(BundleIntegrityError):
        parse_checksums(raw.encode("utf-8"))
    assert reason


def test_a_checksum_entry_carries_an_asset_digest_not_a_string() -> None:
    value = manifest(entry("run.json", b"{}"))
    entries = parse_checksums(render_checksums(value, canonical_manifest_bytes(value)))
    assert all(isinstance(item.digest, AssetDigest) for item in entries)
    declared = value.files[0].sha256
    assert next(item for item in entries if item.relative_path == "run.json").digest == AssetDigest(
        hex=declared
    )


def test_coverage_comparison_reports_both_directions() -> None:
    """A file with no digest record and a claim about an undeclared file are different bugs."""
    uncovered, undeclared = coverage_discrepancies(
        ["a.json", "b.json"], ["a.json", "checksums.sha256"]
    )
    assert uncovered == ("b.json",)
    assert undeclared == ("checksums.sha256",)
    assert coverage_discrepancies(["a.json"], ["a.json"]) == ((), ())


def test_a_checksum_entry_is_a_value_comparison_against_a_recomputed_digest() -> None:
    """The comparison RES-229's design note asked for: typed values, not string exercises."""
    payload = b"PAR1"
    value = manifest(entry("native/t.parquet", payload))
    entry_parsed = ChecksumEntry(
        relative_path="native/t.parquet",
        digest=AssetDigest(hex=hashlib.sha256(payload).hexdigest()),
    )
    assert entry_parsed.digest == AssetDigest(hex=value.files[0].sha256)


def test_reading_a_seal_file_that_does_not_exist_is_an_integrity_failure(tmp_path: Path) -> None:
    from dynamisbench.evidence import BundleIntegrityError
    from dynamisbench.evidence.manifest import read_seal_file

    with pytest.raises(BundleIntegrityError, match="could not be read"):
        read_seal_file(tmp_path / "absent.json", max_bytes=10, what="manifest.json")
