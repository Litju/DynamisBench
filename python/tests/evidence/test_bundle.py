"""The naming language, outcome vocabulary, and no-links rule a sealed bundle obeys.

These are the rules everything else in the package inherits, so they are tested as *rules*
rather than as incidental behaviour: each is stated here with the reason it exists, and a
test that stops firing is a defect this gate should catch.

Three groups:

* **The run id.** Lower-case, single segment, the project identifier convention, and never
  a Windows device name. Two spellings that collide on a case-insensitive filesystem are
  not one vocabulary.
* **The bundle path.** Relative, already normalized, ``/``-separated, no whitespace, no
  traversal, no drive, and never a name the seal writes. The traversal and device-name
  halves are *not* re-tested as this package's own logic — they are the RES-230 gate being
  reused, and what matters here is that a rejection still happens through this module.
* **Links and reparse points.** A symlink, a junction, and any other reparse point are
  refused; a hard link deliberately is not. The junction case matters most on the primary
  platform, because ``is_symlink()`` reports a junction as an ordinary directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynamisbench.evidence import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    RESERVED_BUNDLE_FILE_NAMES,
    SEAL_FILE_NAMES,
    ArtifactRole,
    BundleNamingError,
    RunOutcome,
    is_link_or_reparse_point,
    parse_bundle_relative_path,
    parse_run_id,
)
from tests.evidence.links import FileLinkFactory
from tests.workspace.links import UNAVAILABLE, DirectoryLinkFactory, require_directory_link

WINDOWS_DEVICE_NAMES = ("con", "nul", "aux", "prn", "com1", "lpt1", "con.json", "nul.txt")
"""Names the identifier convention happily admits and Windows will not store as files."""


# --- run id ---------------------------------------------------------------------------------

VALID_RUN_IDS = ("run-1", "db-lcmj20.r001.s00001", "a", "a1_b2-c3", "0")


@pytest.mark.parametrize("value", VALID_RUN_IDS)
def test_an_ordinary_run_id_is_accepted(value: str) -> None:
    assert parse_run_id(value) == value


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("Run-1", "upper case collides with run-1 on a case-insensitive filesystem"),
        ("", "a name is required"),
        ("run/1", "a run id is one directory segment, not a path"),
        ("run\\1", "a backslash is a separator on Windows and a name character on POSIX"),
        ("run 1", "whitespace makes a run id ambiguous on a command line"),
        ("run-1-", "a trailing separator is not a segment"),
        ("-run-1", "a leading separator is not a segment"),
        ("..", "traversal is never an identifier"),
        ("run:1", "a colon addresses an alternate data stream on NTFS"),
        ("run\x00", "a NUL is not a name"),
        ("a" * 97, "a run id is bounded so it is always a usable path segment"),
    ],
)
def test_a_malformed_run_id_is_refused(value: str, reason: str) -> None:
    with pytest.raises(BundleNamingError):
        parse_run_id(value)
    assert reason  # the reason is the point of the case, not an afterthought


@pytest.mark.parametrize("value", WINDOWS_DEVICE_NAMES)
def test_a_run_id_is_never_a_reserved_device_name(value: str) -> None:
    """The identifier convention admits ``con``; the platform name gate must not."""
    with pytest.raises(BundleNamingError):
        parse_run_id(value)


@pytest.mark.parametrize("value", sorted(RESERVED_BUNDLE_FILE_NAMES))
def test_a_run_id_is_never_a_name_the_seal_reserves(value: str) -> None:
    """``.staging/manifest.json`` would be a bundle named like the file that identifies it."""
    assert value not in VALID_RUN_IDS
    with pytest.raises(BundleNamingError):
        parse_run_id(value)


def test_a_run_id_naming_error_is_also_a_value_error() -> None:
    """So a deserialising boundary that catches ``ValueError`` still catches this."""
    assert issubclass(BundleNamingError, ValueError)


# --- bundle-relative path --------------------------------------------------------------------

VALID_BUNDLE_PATHS = (
    "run.json",
    "native/table.parquet",
    "canonical/vgrf.parquet",
    "logs/solver-1.log",
    "a/b/c/d.bin",
    "report.1.0.0+build.json",
    "COM10.txt",
    "auxiliary.txt",
)
"""Portably spelled names, including two that only *look* like Windows device names.

``COM10.txt`` and ``auxiliary.txt`` are here on purpose: the reserved-device rule covers
``com1``-``com9`` and ``lpt1``-``lpt9`` with any extension, so ``com6.txt`` is a device and
these two are ordinary files. A gate that rejected them would be refusing portable names.
"""


@pytest.mark.parametrize("value", VALID_BUNDLE_PATHS)
def test_an_ordinary_bundle_path_is_accepted(value: str) -> None:
    assert parse_bundle_relative_path(value) == value


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("/run.json", "a manifest path is relative to its bundle, never absolute"),
        ("C:/run.json", "a drive letter is machine state, not scientific data"),
        ("//server/share/run.json", "a UNC prefix is machine state"),
        ("../outside.json", "traversal would let a manifest name a file outside the bundle"),
        ("native/../../outside.json", "traversal is refused wherever it appears"),
        ("native/./table.parquet", "a '.' segment is not the normalized form"),
        ("native//table.parquet", "an empty segment is not a name"),
        ("native/table.parquet/", "a trailing separator is not the normalized form"),
        ("native\\table.parquet", "one canonical spelling, so the manifest has one form"),
        ("logs/a b.log", "whitespace makes a checksum line ambiguous to any reader"),
        ("logs/a\tb.log", "a control character is not a name"),
        ("logs/a:b.log", "a colon addresses an alternate data stream on NTFS"),
        ("", "a path is required"),
        ("a" * 1025, "a path is bounded so it is expressible without a platform escape"),
    ],
)
def test_a_malformed_bundle_path_is_refused(value: str, reason: str) -> None:
    with pytest.raises(BundleNamingError):
        parse_bundle_relative_path(value)
    assert reason


@pytest.mark.parametrize("value", (MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME))
def test_a_manifest_path_may_not_name_the_seals_own_metadata(value: str) -> None:
    """Self-reference is exactly what the v0 seal is designed to avoid."""
    with pytest.raises(BundleNamingError):
        parse_bundle_relative_path(value)


def test_an_absolute_path_can_never_reach_the_manifest_language(tmp_path: Path) -> None:
    """The property that matters downstream: no absolute path is a legal manifest path.

    Checked against a real absolute path rather than a hand-written one, so a change to
    the validator cannot accidentally depend on this test's idea of an absolute path.
    """
    for candidate in (tmp_path / "run.json", Path.cwd() / "x.json", Path("C:/x.json")):
        with pytest.raises(BundleNamingError):
            parse_bundle_relative_path(candidate.as_posix())


def test_the_reserved_names_cover_the_two_seal_files_and_their_temporaries() -> None:
    assert SEAL_FILE_NAMES == frozenset({MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME})
    assert RESERVED_BUNDLE_FILE_NAMES > SEAL_FILE_NAMES
    assert all(
        name.startswith(("manifest.json", "checksums.sha256"))
        for name in RESERVED_BUNDLE_FILE_NAMES
    )


@given(
    segments=st.lists(
        st.from_regex(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", fullmatch=True),
        min_size=1,
        max_size=4,
    )
)
def test_any_generated_safe_path_round_trips_unchanged(segments: list[str]) -> None:
    """A path made only of portable name characters survives the language unchanged.

    The interesting half is the round trip: the language is not merely a filter, it is a
    fixed point, so a path that passed can be written into a manifest, read back, and be
    the same string.
    """
    value = "/".join(segments)
    assert parse_bundle_relative_path(value) == value


# --- outcome and role vocabularies ------------------------------------------------------------


def test_the_outcome_vocabulary_is_exactly_success_and_failure() -> None:
    """Two values on purpose: a reason for failure is payload, not seal metadata.

    Asserted as a closed set so that adding a third value — cancelled, timed out,
    non-converged — has to be a deliberate change to a sealed meaning rather than a
    convenience for whoever wires up the next simulator.
    """
    assert {outcome.value for outcome in RunOutcome} == {"succeeded", "failed"}


def test_a_failed_run_is_a_distinct_outcome_from_a_successful_one() -> None:
    assert RunOutcome.FAILED is not RunOutcome.SUCCEEDED
    assert RunOutcome("failed") is RunOutcome.FAILED


def test_every_artifact_role_names_a_member_the_evidence_model_already_declares() -> None:
    """No role may describe an evidence kind that current authority does not declare."""
    assert {role.value for role in ArtifactRole} == {
        "run_metadata",
        "run_spec",
        "preflight",
        "environment",
        "provenance",
        "diagnostics",
        "assessment",
        "native_evidence",
        "canonical_evidence",
        "log",
    }


# --- links and reparse points -----------------------------------------------------------------


def test_a_plain_file_is_not_a_link(tmp_path: Path) -> None:
    target = tmp_path / "run.json"
    target.write_bytes(b"{}")
    assert not is_link_or_reparse_point(target)


def test_a_plain_directory_is_not_a_link(tmp_path: Path) -> None:
    directory = tmp_path / "native"
    directory.mkdir()
    assert not is_link_or_reparse_point(directory)


def test_a_file_link_is_detected(tmp_path: Path, file_link_maker: FileLinkFactory) -> None:
    """A payload artifact that is a link is a link, whichever way the host spells one.

    The skip below is deliberate and named rather than hidden: on Windows a file symbolic
    link needs Developer Mode or elevation, and a junction can only point at a directory,
    so a host without that privilege can construct a reparse point but not a linked file.
    The limitation is recorded here, reported by ``pytest -ra``, and stated in the
    qualification evidence; the junction test above and the inventory tests in
    ``test_staging.py`` prove the same rejection through the shared predicate.
    """
    target = tmp_path / "run.json"
    target.write_bytes(b"{}")
    link = tmp_path / "linked.json"
    mechanism = file_link_maker(link, target)
    if mechanism == UNAVAILABLE:
        pytest.skip(
            "this host forbids file symbolic links (Windows requires Developer Mode or "
            "elevation), so the is_symlink branch of the link predicate is unproved here; "
            "the junction case above proves the shared rejection on this host"
        )
    assert is_link_or_reparse_point(link), f"a {mechanism} was not recognised as a link"


def test_a_directory_junction_is_detected_even_though_is_symlink_disagrees(
    tmp_path: Path, link_maker: DirectoryLinkFactory
) -> None:
    """The junction case is the one that matters on the authoritative platform.

    ``Path.is_symlink()`` reports a Windows junction as an ordinary directory, so a
    symlink-only check would let a bundle escape without noticing. The predicate is
    asserted for whatever the host builds, and the disagreement itself is asserted in the
    junction case so a future change cannot make the test vacuously true.
    """
    target = tmp_path / "outside"
    target.mkdir()
    (target / "leak.json").write_bytes(b"{}")
    link = tmp_path / "linked"
    mechanism = require_directory_link(
        link_maker(link, target), "junction rejection is unproved on this host"
    )
    assert is_link_or_reparse_point(link), f"a {mechanism} was not recognised as a link"
    if mechanism == "junction":
        assert not link.is_symlink(), (
            "a junction must disagree with is_symlink for this to prove anything"
        )


def test_a_hard_link_is_not_treated_as_an_escape(tmp_path: Path) -> None:
    """A hard link is a second name for bytes already inside the bundle, not a redirect.

    Both names hash to the same digest, so refusing one would cost portability nothing and
    would reject a legitimate artifact arrangement on filesystems that produce them.
    """
    target = tmp_path / "run.json"
    target.write_bytes(b"{}")
    hard = tmp_path / "run-copy.json"
    try:
        os.link(target, hard)
    except (OSError, NotImplementedError):
        pytest.fail("this host does not permit hard links, so the hard-link rule is unproved")
    assert not is_link_or_reparse_point(hard)


def test_a_missing_path_is_not_reported_as_a_link(tmp_path: Path) -> None:
    """The predicate describes a path that exists; absence is a different question."""
    assert not is_link_or_reparse_point(tmp_path / "absent.json")
