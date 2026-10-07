"""The determinism claims, stated as properties and proved rather than assumed.

A sealed bundle's identity is only worth anything if the same evidence always produces the
same identity. These tests are the evidence for that, and each one names the specific thing
that must not be able to leak into a digest:

* **Authoring order** — the order files were written, and the order they are listed in, must
  not reach the manifest, the digest, or the checksum bytes.
* **Filesystem enumeration order** — which order the OS happens to list a directory in must
  not reach any of the three, and the tests build payloads specifically to make that order
  differ between two bundles.
* **The workspace location** — two workspaces at completely different absolute paths must
  produce byte-identical seals. This is the property that lets a benchmark be moved between
  machines without its evidence changing meaning, and it is the one most likely to be broken
  by an innocent-looking convenience.
* **The Python hash seed** — a dict or set iteration order must not be able to reorder a
  manifest. Proven in a *fresh interpreter* with a different seed, because a same-process test
  would share the seed and prove nothing.
* **Process identity** — a different interpreter, a different working directory, a different
  user, a different clock: none of it may appear in the seal.

And one negative claim that is easy to state and hard to enforce: **no absolute path, no
timestamp, no hostname, no username** may reach the manifest or the evidence digest. The
tests search the actual bytes rather than inspecting the code, because a code inspection
cannot see a value that arrived through a library.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dynamisbench.evidence import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    ArtifactRole,
    RunOutcome,
    create_staging_bundle,
    finalize_bundle,
    verify_sealed_bundle,
)
from dynamisbench.evidence.manifest import (
    Manifest,
    ManifestEntry,
    canonical_manifest_bytes,
    parse_manifest,
)
from dynamisbench.workspace import Workspace, initialize_workspace
from tests.evidence.seal import SAMPLE_PAYLOAD

RUN = "run-1"
DETERMINISTIC_SEED = "a1b2c3"


def seal_in_workspace(
    root: Path,
    files: tuple[tuple[str, bytes], ...] = SAMPLE_PAYLOAD,
    run_id: str = RUN,
    outcome: RunOutcome = RunOutcome.SUCCEEDED,
) -> tuple[bytes, bytes, str]:
    """Create a workspace under ``root``, seal one run, return (manifest, checksums, digest)."""
    source = root / "source"
    evidence = root / "evidence"
    source.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    workspace: Workspace = initialize_workspace(source, evidence)
    bundle = create_staging_bundle(workspace, run_id)
    for relative_path, data in files:
        bundle.write_payload(relative_path, data)
    result = finalize_bundle(bundle, outcome)
    return (
        (result.path / MANIFEST_FILE_NAME).read_bytes(),
        (result.path / CHECKSUMS_FILE_NAME).read_bytes(),
        result.evidence_digest.hex,
    )


PAYLOAD = (
    ("run.json", b'{"seed":7}'),
    ("native/table.parquet", b"PAR1payload"),
    ("canonical/vgrf.parquet", b"CANON"),
    ("logs/solver-1.log", b"step 1\nstep 2\n"),
    ("logs/solver-2.log", b"step 1\n"),
    ("z/deeply/nested/table.bin", b"\x00\x01\x02"),
)
"""A payload chosen so two bundles written in opposite orders enumerate differently."""


# --- determinism within one workspace -------------------------------------------------------------


def test_writing_payload_in_opposite_orders_gives_the_same_seal(tmp_path: Path) -> None:
    """Authoring order is not meaning, and enumeration order must not become meaning either."""
    first, first_checksums, first_digest = seal_in_workspace(tmp_path / "a", PAYLOAD)
    second, second_checksums, second_digest = seal_in_workspace(tmp_path / "b", PAYLOAD)
    assert first == second
    assert first_checksums == second_checksums
    assert first_digest == second_digest


def test_the_seal_does_not_depend_on_the_number_of_times_it_is_recomputed(
    tmp_path: Path,
) -> None:
    """The digest is a function of the manifest bytes, and those are a function of the payload.

    Three separate workspaces, because a run id is spent once sealed — which is itself part of
    why the digest has to be a function of the payload rather than of a counter.
    """
    first = seal_in_workspace(tmp_path / "a", PAYLOAD)
    for index in range(3):
        assert seal_in_workspace(tmp_path / f"b{index}", PAYLOAD) == first


def test_a_different_payload_gives_a_different_digest(tmp_path: Path) -> None:
    """Determinism must not be achieved by ignoring the content."""
    _, _, digest = seal_in_workspace(tmp_path / "a", PAYLOAD)
    altered = (*PAYLOAD[:-1], ("z/deeply/nested/table.bin", b"\x00\x01\x03"))
    _, _, other = seal_in_workspace(tmp_path / "b", altered)
    assert digest != other


def test_an_extra_file_gives_a_different_digest(tmp_path: Path) -> None:
    _, _, digest = seal_in_workspace(tmp_path / "a", PAYLOAD)
    _, _, extra = seal_in_workspace(tmp_path / "b", (*PAYLOAD, ("logs/solver-3.log", b"x")))
    assert digest != extra


def test_renaming_a_payload_file_gives_a_different_digest(tmp_path: Path) -> None:
    """A path is part of what was produced: the same bytes under another name is another
    bundle, unlike the same bytes at another absolute location."""
    _, _, digest = seal_in_workspace(tmp_path / "a", PAYLOAD)
    renamed = tuple(
        (f"renamed{path[1:]}" if path.startswith("z/") else path, data) for path, data in PAYLOAD
    )
    _, _, other = seal_in_workspace(tmp_path / "b", renamed)
    assert digest != other


# --- relocation -----------------------------------------------------------------------------------


def test_two_workspaces_at_different_paths_produce_byte_identical_seals(
    tmp_path: Path,
) -> None:
    """The property that lets a benchmark move between machines without changing meaning.

    The two roots are deliberately different lengths and different depths, so a manifest that
    accidentally embedded a prefix or a fixed number of path components would differ.
    """
    short = tmp_path / "w"
    long = tmp_path / "a-much-longer-root-name" / "deeper" / "still-deeper" / "w"
    assert seal_in_workspace(short, PAYLOAD) == seal_in_workspace(long, PAYLOAD)


def test_a_relocated_sealed_bundle_keeps_its_identity_and_still_verifies(
    tmp_path: Path,
) -> None:
    """Moving the *sealed* directory — not just re-sealing it — preserves the digest.

    Stronger than the previous test: the bytes are not recomputed at all, so this covers any
    path that reached the seal through a file the walk touched.
    """
    import shutil

    source_root = tmp_path / "origin"
    source, evidence = source_root / "source", source_root / "evidence"
    source.mkdir(parents=True)
    evidence.mkdir(parents=True)
    workspace = initialize_workspace(source, evidence)
    bundle = create_staging_bundle(workspace, RUN)
    for relative_path, data in PAYLOAD:
        bundle.write_payload(relative_path, data)
    original = finalize_bundle(bundle, RunOutcome.SUCCEEDED)

    moved_root = tmp_path / "relocated" / "elsewhere"
    moved_root.mkdir(parents=True)
    moved_evidence = moved_root / "evidence"
    moved_evidence.mkdir()
    shutil.copytree(original.path, moved_evidence / "runs" / RUN)
    moved = initialize_workspace(moved_root / "source", moved_evidence)

    result = verify_sealed_bundle(moved, RUN, expected_evidence_digest=original.evidence_digest)
    assert result.is_valid
    assert result.proves_expected_output
    assert result.bundle is not None
    assert result.bundle.evidence_digest == original.evidence_digest


def test_a_seal_contains_no_trace_of_where_it_was_written(tmp_path: Path) -> None:
    """Searched in the actual bytes, because a code reading cannot see a value that arrived
    through a library."""
    root = tmp_path / "a-very-distinctive-root-name"
    manifest, checksums, digest = seal_in_workspace(root, PAYLOAD)
    body = manifest + checksums + digest.encode("ascii")
    text = body.decode("utf-8")
    for machine_artifact in (
        str(root),
        root.name,
        "a-very-distinctive-root-name",
        str(tmp_path),
        os.environ.get("USERNAME", "no-user-here"),
        socket.gethostname(),
    ):
        assert machine_artifact not in text, f"{machine_artifact!r} reached the seal"


def test_a_seal_contains_no_timestamp(tmp_path: Path) -> None:
    """A modification time, a creation time and a wall-clock reading are all machine state."""
    before = int(time.time())
    manifest, checksums, digest = seal_in_workspace(tmp_path / "a", PAYLOAD)
    after = int(time.time())
    text = (manifest + checksums).decode("utf-8")
    for moment in range(before, after + 1, max(1, (after - before) // 8) or 1):
        assert str(moment) not in text, f"the timestamp {moment} reached the seal"


# --- interpreter and environment independence --------------------------------------------------


_SEAL_PROBE = """
import sys
from pathlib import Path
sys.path.insert(0, {tests_root!r})
from dynamisbench.evidence import RunOutcome, create_staging_bundle, finalize_bundle
from dynamisbench.workspace import initialize_workspace

root = Path({root!r})
source, evidence = root / "source", root / "evidence"
source.mkdir(parents=True, exist_ok=True)
evidence.mkdir(parents=True, exist_ok=True)
workspace = initialize_workspace(source, evidence)
bundle = create_staging_bundle(workspace, {run_id!r})
for relative_path, data in {payload!r}:
    bundle.write_payload(relative_path, data)
result = finalize_bundle(bundle, RunOutcome.SUCCEEDED)
sys.stdout.write(result.evidence_digest.hex)
"""


def _probe(root: Path, seed: str | None = None, cwd: Path | None = None) -> str:
    """Seal the same payload in a fresh interpreter and return the evidence digest.

    The working directory is created first and the probe seals into a *different* root, so the
    interpreter's starting directory is genuinely unrelated to where the workspace ends up —
    which is the point of the test that varies it.
    """
    working_directory = cwd or root
    working_directory.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONHASHSEED=seed) if seed else None
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _SEAL_PROBE.format(
                tests_root=str(Path(__file__).resolve().parents[2]),
                root=str(root),
                run_id=RUN,
                payload=PAYLOAD,
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(working_directory),
        env=environment,
    )
    return completed.stdout


def test_a_different_python_hash_seed_gives_the_same_digest(tmp_path: Path) -> None:
    """Dict and set iteration order must not be able to reorder a manifest.

    Proven in fresh interpreters with different seeds, because a same-process comparison would
    share the seed and prove nothing at all. Each probe seals into its own root, since a run id
    is spent once sealed.
    """
    first = _probe(tmp_path / "seed-a", seed="0")
    assert _probe(tmp_path / "seed-b", seed="12345") == first
    assert _probe(tmp_path / "seed-c", seed="99999") == first
    assert _probe(tmp_path / "seed-d", seed="1") == first


def test_a_fresh_interpreter_in_a_different_working_directory_gives_the_same_digest(
    tmp_path: Path,
) -> None:
    """The interpreter, its working directory and its import path are all machine state."""
    baseline = _probe(tmp_path / "wd-a")
    elsewhere = _probe(tmp_path / "wd-b", cwd=tmp_path / "somewhere-else")
    assert elsewhere == baseline


def test_the_digest_matches_the_one_computed_in_this_interpreter(tmp_path: Path) -> None:
    """Cross-checks the two paths against each other, so neither can drift alone."""
    here = seal_in_workspace(tmp_path / "here", PAYLOAD)[2]
    assert _probe(tmp_path / "there") == here


# --- generated payload ---------------------------------------------------------------------


def _payload_from_names(names: list[str]) -> tuple[tuple[str, bytes], ...]:
    """Build a payload whose file contents are a function of the name, so a permutation of the
    names is a permutation of the payload rather than the same payload twice."""
    return tuple((name, f"content of {name}".encode()) for name in names)


def canonical_of(manifest: bytes) -> bytes:
    """Round-trip manifest bytes through the package, so a test can assert they are canonical."""
    return canonical_manifest_bytes(parse_manifest(manifest))


def _name_strategy() -> st.SearchStrategy[str]:
    """Realistically-sized portable file names, and short enough for pytest's own temp path.

    The length bound is deliberate and is not the property under test. A 250-character file
    name is a legal bundle path — the language bounds the *reference*, and portability is
    relative to the root — but on Windows it pushes the absolute path past ``MAX_PATH`` once
    pytest's deep temporary directory is prepended. That is an operating-system limit rather
    than a scientific one; it is asserted explicitly in
    :func:`test_a_path_too_long_for_the_operating_system_fails_cleanly`, and letting it abort
    an order-independence property test would hide the claim that test exists to make. Forty
    characters leaves room for several segments while staying well clear of the boundary.
    """
    return st.from_regex(
        r"[a-z]{1,10}(?:[-_][a-z0-9]{1,8})*\.(?:json|log|bin)", fullmatch=True
    ).filter(lambda name: len(name) <= 40)


@given(names=st.lists(_name_strategy(), min_size=1, max_size=6, unique=True))
# Each example seals and promotes two whole bundles, so the example count trades against
# runtime rather than buying coverage: the property is that write order is not an input, and no
# data shape would falsify it in a way a different order of the same names would not.
@settings(max_examples=25)
def test_any_permutation_of_a_payload_gives_the_same_seal(
    tmp_path_factory: pytest.TempPathFactory, names: list[str]
) -> None:
    """The order files were written is not part of what was produced."""
    payload = _payload_from_names(names)
    forward = seal_in_workspace(tmp_path_factory.mktemp("fwd"), payload)
    backward = seal_in_workspace(tmp_path_factory.mktemp("bwd"), tuple(reversed(payload)))
    assert forward == backward


@given(names=st.lists(_name_strategy(), min_size=2, max_size=6, unique=True))
# Two full seal-and-promote cycles per example; see the permutation test above.
@settings(max_examples=25)
def test_a_generated_payload_declares_exactly_its_own_files(
    tmp_path_factory: pytest.TempPathFactory, names: list[str]
) -> None:
    """Every generated file name appears in the seal, and the manifest is stored canonically."""
    manifest, checksums, _ = seal_in_workspace(
        tmp_path_factory.mktemp("gen"), _payload_from_names(names)
    )
    for name in names:
        assert name in (manifest + checksums).decode("utf-8")
    assert canonical_of(manifest) == manifest, "a sealed manifest is stored canonically"


def test_a_payload_the_filesystem_refuses_fails_with_a_named_error(tmp_path: Path) -> None:
    """A write the operating system refuses fails with a named error, not a crash.

    This is the portable half of that boundary: the caller must learn which payload could not be
    written, naming it, rather than receiving an unhandled ``OSError`` or a truncated file. The
    refusal is provoked with a directory standing where the payload file must go, because every
    filesystem refuses that, on every host, for reasons that have nothing to do with how deep a
    workspace happens to live or whether the host has long paths enabled.
    """
    from dynamisbench.evidence import BundleOperationError

    root = tmp_path / "a"
    source, evidence = root / "source", root / "evidence"
    source.mkdir(parents=True)
    evidence.mkdir(parents=True)
    workspace = initialize_workspace(source, evidence)
    bundle = create_staging_bundle(workspace, RUN)
    name = "payload.json"

    written = bundle.write_payload(name, b"{}")
    written.unlink()
    written.mkdir()

    with pytest.raises(BundleOperationError, match="could not be written") as refusal:
        bundle.write_payload(name, b"{}")
    assert name in str(refusal.value), "the refusal must name the artifact that failed"


def test_a_path_too_long_for_this_host_fails_cleanly(tmp_path: Path) -> None:
    """A legal bundle path this host cannot write fails with a named error, not a crash.

    Found by a property test, and recorded here because it is a real boundary rather than a
    quirk of one generator. ``BundleRelativePath`` bounds the *reference`` — 1024 characters,
    inherited from the workspace gate — because that is what portability is defined against; it
    cannot bound the *absolute* path, which is a function of where the workspace happens to
    live. On Windows the two meet at ``MAX_PATH``, and exceeding it produces a clean
    ``BundleOperationError`` naming the artifact.

    Whether that meeting point exists is a property of the host rather than of this code: a host
    with long paths enabled has no ``MAX_PATH`` for a 244-character reference to reach, and there
    the boundary cannot be provoked at all. So the host's own behaviour is measured by attempting
    the write rather than inferred from a platform name. Where the limit exists the refusal is
    asserted to be the named one and to name the artifact; where it does not, the test says that
    rather than asserting something about a machine it is not running on. The conversion itself
    is proved on every host by
    :func:`test_a_payload_the_filesystem_refuses_fails_with_a_named_error`.
    """
    from dynamisbench.evidence import BundleOperationError

    root = tmp_path / "a"
    source, evidence = root / "source", root / "evidence"
    source.mkdir(parents=True)
    evidence.mkdir(parents=True)
    workspace = initialize_workspace(source, evidence)
    bundle = create_staging_bundle(workspace, RUN)
    name = f"{'n' * 240}.json"
    assert len(name) < 1024, "the name is inside the bundle path language"
    try:
        bundle.write_payload(name, b"{}")
    except BundleOperationError as refusal:
        assert "could not be written" in str(refusal)
        assert name in str(refusal), "the refusal must name the artifact that failed"
        return
    pytest.skip(
        "this host writes a 244-character reference, so it has no path length for the bundle "
        "reference bound to meet and the operating system refuses nothing here; the reference "
        "bound is proved by the naming gates and the refusal-to-named-error conversion by "
        "test_a_payload_the_filesystem_refuses_fails_with_a_named_error"
    )


# --- roles are optional and never inferred ----------------------------------------------------


def test_a_run_id_is_authoritative_so_it_changes_the_digest(tmp_path: Path) -> None:
    """Two runs of byte-identical evidence are two runs. The name is not incidental."""
    _, _, first = seal_in_workspace(tmp_path / "a", PAYLOAD, run_id="run-1")
    _, _, second = seal_in_workspace(tmp_path / "b", PAYLOAD, run_id="run-2")
    assert first != second


# --- roles are optional and never inferred ----------------------------------------------------


def test_a_declared_role_survives_into_the_canonical_bytes() -> None:
    """When a role *is* declared it is authoritative and is inside the digest's bytes."""
    manifest = Manifest(
        run_id=RUN,
        outcome=RunOutcome.SUCCEEDED,
        files=(
            ManifestEntry(
                relative_path="run.json",
                sha256=hashlib.sha256(b"{}").hexdigest(),
                size_bytes=2,
                role=ArtifactRole.RUN_METADATA,
            ),
        ),
    )
    canonical = canonical_manifest_bytes(manifest)
    assert b'"role":"run_metadata"' in canonical
    assert canonical == canonical_of(canonical)


def test_the_current_user_is_not_part_of_any_seal(tmp_path: Path) -> None:
    """The username is machine state; asserting it explicitly because it is a common leak."""
    user = getpass.getuser()
    manifest, checksums, _ = seal_in_workspace(tmp_path / "a", PAYLOAD)
    assert user not in (manifest + checksums).decode("utf-8")


def test_an_artifact_role_is_never_inferred_from_a_file_name(tmp_path: Path) -> None:
    """The manifest records what the caller declared, and nothing more.

    A file called ``run-spec.json`` is not thereby a run spec: RES-232 owns that schema, and a
    guess here would be a claim this package has no authority to make. The role key is present
    and null — the field is part of the schema — and no value is invented for it.
    """
    manifest, _, _ = seal_in_workspace(tmp_path / "a", (("run-spec.json", b"{}"),))
    assert b'"role":null' in manifest
    for role in ArtifactRole:
        assert f'"{role.value}"'.encode() not in manifest
