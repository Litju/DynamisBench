"""Properties that must hold for every reference, not for the ones we thought of.

The enumerated attack corpus in ``test_paths.py`` covers the shapes that were anticipated.
This suite covers the ones that were not, by generating references and states and
asserting the two guarantees the workspace owes regardless of input:

* **nothing gets out.** Whatever a caller asks for, the resolver either refuses it or
  returns a path inside the authorised root. There is no third outcome, so no future
  reference shape can be the one that slips through.
* **nothing legitimate gets refused by accident.** Any name that means the same thing on
  both platforms and contains nothing Windows would normalise is accepted, on both
  platforms.

The escaping states are generated too: a junction or symlink inside a workspace, placed at
an arbitrary depth and pointing at an arbitrary directory, must not become a way out. One
session-wide workspace is used for the filesystem properties because constructing
directories 500 times would make the CI profile the slowest thing in the repository.

``HYPOTHESIS_PROFILE=ci`` raises these to 500 examples, which is why the strategies are
biased toward the shapes that break containment — separators, dots, colons, spaces — and
away from long runs of harmless letters.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter

from dynamisbench.domain.spec.identifiers import WorkspaceRelativePath
from dynamisbench.workspace import (
    MAX_LOGICAL_REFERENCE_LENGTH,
    PathScopeError,
    PersistenceClass,
    SourceCategory,
    initialize_workspace,
    validate_logical_reference,
)
from tests.workspace.links import DirectoryLinkFactory

AUTHORED_PATH = TypeAdapter(WorkspaceRelativePath)

RESERVED_STEM = r"(?!CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])"

LEGAL_SEGMENT = st.from_regex(
    rf"\A{RESERVED_STEM}[A-Za-z0-9][A-Za-z0-9 .\-_~]*\Z",
    fullmatch=True,
).filter(lambda segment: not segment.endswith((".", " ")) and segment.strip() == segment)

AUTHORED_SEGMENT = st.from_regex(
    rf"\A{RESERVED_STEM}[A-Za-z0-9][A-Za-z0-9.\-_~]*\Z", fullmatch=True
).filter(lambda segment: not segment.endswith("."))
"""The intersection both vocabularies accept.

``WorkspaceRelativePath`` forbids any whitespace and the resolver permits interior spaces,
so a generated name containing one would not be a legal authored reference and the
consistency property would be asserting something untrue. Windows-ineligible names are
excluded too, since those are the deliberate, separately enumerated divergence below.
"""

AUTHORITY_SAFE_REFERENCE = st.lists(LEGAL_SEGMENT, min_size=1, max_size=4).map("/".join)

SEGMENT_CHARS = st.sampled_from(
    list("/\\")
    + [".", " ", ":", "|", "*", "?", "<", ">", '"', "\x00", "\t", "\n", "a", "Z", "0", "-", "~"]
)

ADVERSARIAL_REFERENCE = st.lists(SEGMENT_CHARS, min_size=1, max_size=14).map("".join)

HOSTILE_PREFIXES = (
    "/",
    "\\",
    "//",
    "\\\\",
    "C:\\",
    "C:/",
    "D:/",
    "\\\\server\\share\\",
    "//server/share/",
    "\\\\?\\C:\\",
    "\\\\.\\PIPE\\",
    "../",
    "..\\",
    "./",
    ".\\",
    "a/../",
    "a\\..\\",
)

HOSTILE_SUFFIXES = ("", "/..", "\\..", "/.", "\\.", "/../", "/a/../..", "\\a\\..\\..")

HOSTILE_MIDDLES = ("a/../../b", "a\\..\\..\\b", "NUL", "nul.txt", "COM1", "run.json:$DATA")


def hostile_references() -> st.SearchStrategy[str]:
    """References assembled from shapes that must never be accepted, whatever follows."""
    bodies = st.one_of(
        st.just(""),
        st.text(SEGMENT_CHARS, max_size=8),
        st.sampled_from(HOSTILE_MIDDLES),
    )
    return st.builds(
        lambda prefix, body, suffix: f"{prefix}{body}{suffix}",
        st.sampled_from(HOSTILE_PREFIXES),
        bodies,
        st.sampled_from(HOSTILE_SUFFIXES),
    )


@pytest.fixture(scope="module")
def qualified(tmp_path_factory: pytest.TempPathFactory):
    """One workspace for the filesystem properties, built once and shared."""
    base = tmp_path_factory.mktemp("workspace-properties")
    return initialize_workspace(base / "source", base / "evidence")


def assert_contained(workspace, resolved: Path, root: Path) -> None:
    assert resolved.is_absolute()
    assert resolved.is_relative_to(root)


@given(reference=ADVERSARIAL_REFERENCE)
def test_a_generated_reference_is_either_refused_or_resolved_inside_the_root(
    qualified, reference: str
) -> None:
    root = qualified.evidence_root
    try:
        resolved = qualified.resolve(PersistenceClass.STAGING, reference)
    except PathScopeError:
        return
    assert_contained(qualified, resolved, root)


@given(reference=hostile_references())
def test_a_generated_escape_shape_is_always_refused(qualified, reference: str) -> None:
    with pytest.raises(PathScopeError):
        qualified.resolve(PersistenceClass.STAGING, reference)
    with pytest.raises(PathScopeError):
        qualified.resolve_source(SourceCategory.BENCHMARKS, reference)


@given(reference=AUTHORITY_SAFE_REFERENCE)
def test_an_authority_safe_reference_is_accepted_and_stays_inside(
    qualified, reference: str
) -> None:
    assume(len(reference) <= MAX_LOGICAL_REFERENCE_LENGTH)
    resolved = qualified.resolve(PersistenceClass.SEALED_EVIDENCE, reference)
    assert_contained(qualified, resolved, qualified.evidence_root)
    assert resolved == qualified.location(PersistenceClass.SEALED_EVIDENCE).path.joinpath(
        *reference.split("/")
    )


@given(reference=AUTHORITY_SAFE_REFERENCE)
def test_validating_a_reference_never_invents_or_drops_a_segment(qualified, reference: str) -> None:
    assume(len(reference) <= MAX_LOGICAL_REFERENCE_LENGTH)
    segments = validate_logical_reference(reference)
    assert "/".join(segments) == reference
    assert all(segment not in {".", "..", ""} for segment in segments)


@given(reference=st.lists(AUTHORED_SEGMENT, min_size=1, max_size=3).map("/".join))
def test_every_reference_the_domain_authored_path_type_accepts_is_also_resolvable(
    qualified, reference: str
) -> None:
    """``WorkspaceRelativePath`` is what a specification author is held to, and the
    resolver is what opens the file. If the resolver were stricter about an ordinary
    relative name, a perfectly valid benchmark could not be read.

    The divergence runs the other way on purpose and is stated separately below: the
    resolver also refuses names Windows cannot store, which ``WorkspaceRelativePath``
    accepts because it governs authored meaning rather than what a filesystem can hold.
    """
    assume(len(reference) <= MAX_LOGICAL_REFERENCE_LENGTH)
    AUTHORED_PATH.validate_python(reference)
    assert_contained(
        qualified,
        qualified.resolve_source(SourceCategory.REALIZATIONS, reference),
        qualified.source_root,
    )


WINDOWS_INELIGIBLE_NAMES = (
    "run.json:$DATA",
    "NUL",
    "nul.txt",
    "COM1",
    "con.log",
    'a"b',
    "a<b",
    "a>b",
    "a|b",
    "a?b",
    "a*b",
    "report.",
)
"""Names the authored-path type accepts and the resolver refuses.

Each is one Windows cannot store under that exact name, or that means something else
there: an alternate data stream, a device, an illegal character, or a trailing dot Windows
would strip. ``WorkspaceRelativePath`` governs what a specification may *say* about an
asset and therefore tolerates them; the resolver governs what a filesystem can be *asked*
to open and therefore does not. Names the domain type already rejects — a drive letter,
any whitespace, a backslash, a ``..`` segment — are excluded, since those are refused by
both and are covered by the corpus in ``test_paths.py``.
"""


@pytest.mark.parametrize("name", WINDOWS_INELIGIBLE_NAMES)
def test_the_only_way_the_resolver_is_stricter_than_the_domain_type_is_a_windows_name(
    qualified, name: str
) -> None:
    AUTHORED_PATH.validate_python(name)
    with pytest.raises(PathScopeError):
        qualified.resolve(PersistenceClass.TMP, name)


@given(
    placement=st.integers(min_value=0, max_value=3),
    segment=LEGAL_SEGMENT,
    leaf=LEGAL_SEGMENT,
)
@settings(max_examples=12)
def test_a_link_at_any_depth_cannot_become_a_way_out(
    link_maker: DirectoryLinkFactory,
    placement: int,
    segment: str,
    leaf: str,
) -> None:
    """Planted at every depth of a class location, a link pointing anywhere outside the
    root is still refused — the check is on the resolved target, not on how the request
    was spelled.

    Each example builds and tears down its own workspace rather than sharing one, because
    a link left behind by one example would change what the next one is testing.
    """
    with tempfile.TemporaryDirectory(prefix="dbench-link-property-") as base:
        root = Path(base)
        workspace = initialize_workspace(root / "source", root / "evidence")
        outside = root / "outside"
        outside.mkdir()
        (outside / "payload.txt").write_text("not ours", encoding="utf-8")

        location = workspace.location(PersistenceClass.DERIVED).path
        for _ in range(placement):
            location = location / segment
            location.mkdir(exist_ok=True)
        if link_maker(location / leaf, outside) == "unavailable":
            pytest.fail("no directory-link mechanism is available on this host")

        reference = "/".join([*([segment] * placement), leaf, "payload.txt"])
        with pytest.raises(PathScopeError):
            workspace.resolve(PersistenceClass.DERIVED, reference)
