"""Verifying a sealed bundle, and reading one without modifying it.

The invariant this module exists to enforce is RES-231's own: **a directory is not
authoritative merely because it is named like a run.** Authority requires a valid sealed
state, and the test of that is an exact file-set equality:

    actual files == manifest payload files + manifest.json + checksums.sha256

Every deviation from that equality is a defect, and *every* one is reported. A missing
declared file, an extra undeclared file, a modified payload, a modified manifest, a malformed
checksum file, and a checksum that disagrees with the bytes are all invalid — there is no
"close enough" branch and no class of unknown file that is quietly ignored, because a
verifier that tolerates an unexpected file cannot detect evidence that has been added to a
bundle after the fact.

**The manifest is authoritative and the checksum file must agree with it.** They are
independent records of the same fact, so both are checked and their disagreement is itself a
finding: a checksum file that omits a declared file, or names one the manifest does not
declare, means the two are describing different bundles. The manifest is the record the
evidence digest is taken over, so it decides; the checksum file is held to it.

**Canonicality is checked separately from validity**, because the two have different causes
and a reader deserves to know which one it hit. A manifest in any form other than its
canonical bytes still describes the bundle, but its *evidence digest* would then depend on
how it happened to be serialised — so the bytes must equal
:func:`canonical_manifest_bytes` of the model they parse to, and the evidence digest is taken
over exactly those bytes.

**Verification proves self-consistency, and says so.** Given an externally trusted expected
evidence digest, this module can also establish that the bundle *is the expected output*,
which is the only claim that survives an actor able to rewrite the whole bundle and recompute
its seal. Without one, a valid result means internal consistency and nothing more. The
distinction is a parameter, not a mode: :func:`verify_bundle_seal` takes the expected digest
or does not, and :attr:`VerificationResult` reports which kind of claim was established.

**Immutability is not enforced here, and deliberately.** The application never mutates a
sealed bundle, verification detects corruption, and an administrator can always alter local
files. Windows read-only bits, ACLs and WDAC are not the source of scientific immutability
here, and this module does not set them: a permission bit is not a scientific claim, and
claiming tamper-resistance from a self-contained checksum file would be overstating what it
proves. :class:`SealedBundle` is read-only in the only sense that matters — it exposes the
bundle's description and no way to write through it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from dynamisbench.evidence.bundle import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    RESERVED_BUNDLE_FILE_NAMES,
    SEAL_FILE_NAMES,
    BundleIntegrityError,
    RunId,
    parse_run_id,
    walk_bundle,
)
from dynamisbench.evidence.manifest import (
    MAX_CHECKSUMS_BYTES,
    MAX_MANIFEST_BYTES,
    ChecksumEntry,
    EvidenceDigest,
    Manifest,
    canonical_manifest_bytes,
    coverage_discrepancies,
    evidence_digest_of_canonical_manifest_bytes,
    parse_checksums,
    parse_manifest,
    read_seal_file,
)
from dynamisbench.identity import asset_sha256_of_file
from dynamisbench.workspace.authority import PersistenceClass
from dynamisbench.workspace.workspace import LogicalReference, Workspace, class_location_segments

__all__ = [
    "Defect",
    "DefectKind",
    "SealedBundle",
    "VerificationResult",
    "verify_bundle_seal",
    "verify_sealed_bundle",
]

SEAL_TEMP_FILE_NAMES: Final = frozenset(RESERVED_BUNDLE_FILE_NAMES - SEAL_FILE_NAMES)
"""The reserved temporary names, isolated from the two files a valid seal must contain.

Kept as a named constant because the difference between "a file the seal writes" and "a
temporary the seal was writing through" is the whole content of :attr:`DefectKind.SEAL_DEBRIS`,
and computing it as a set difference at every use site would be an easy place to invert a
condition — which is exactly the bug this constant exists to prevent.
"""

_LINK_REFUSAL_MARKERS: Final = ("link or reparse point", "is a link", "hard link")
"""The phrases that mark a link refusal among the walk's integrity errors.

There is one place that decides what a bundle may contain, and it raises a single exception
type for several distinct situations, so a caller told only "integrity error" would have to
guess which. These are the phrases every link refusal names, including the hard-link rule:
one list is what keeps the verifier's vocabulary honest as refusals are added, and a new
refusal that is not a link simply falls through to ``BUNDLE_UNREADABLE`` rather than being
misreported as one.
"""


class DefectKind(StrEnum):
    """Every way a sealed bundle can fail to be exactly what it claims to be.

    A closed vocabulary, because a verifier that answers "something is wrong" cannot be acted
    on. The distinctions that earn their own value are the ones that have different fixes:
    a missing file and an extra file are different problems, a modified payload and a
    modified manifest are different attacks, and a manifest that is valid but not canonical is
    a different fault from one that is not a manifest at all.
    """

    BUNDLE_MISSING = "bundle_missing"
    BUNDLE_UNREADABLE = "bundle_unreadable"
    LINK_IN_BUNDLE = "link_in_bundle"
    """Some entry reaches, or can be reached through, another pathname: a symlink, a junction,
    any other reparse point, or a hard-linked file. One kind for all of them because the
    finding is the same — the bundle is not self-contained — and the fix is the same: replace
    the entry with a real file of its own."""
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_INVALID = "manifest_invalid"
    MANIFEST_NOT_CANONICAL = "manifest_not_canonical"
    CHECKSUMS_MISSING = "checksums_missing"
    CHECKSUMS_MALFORMED = "checksums_malformed"
    PAYLOAD_MISSING = "payload_missing"
    PAYLOAD_UNEXPECTED = "payload_unexpected"
    PAYLOAD_MODIFIED = "payload_modified"
    MANIFEST_MODIFIED = "manifest_modified"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    COVERAGE_MISMATCH = "coverage_mismatch"
    EVIDENCE_DIGEST_MISMATCH = "evidence_digest_mismatch"
    SEAL_DEBRIS = "seal_debris"
    """A reserved temporary name is present, so a previous seal attempt did not finish."""


@dataclass(frozen=True, slots=True)
class Defect:
    """One finding about one bundle.

    ``relative_path`` names the artifact at fault and is ``None`` for a finding about the
    bundle as a whole. The message is written for a person reading a diagnostic: it says what
    was expected and what was found, and it deliberately does not include the absolute path,
    because an evidence diagnostic is going to be stored and shared and a machine's directory
    layout is not part of the finding.
    """

    kind: DefectKind
    message: str
    relative_path: str | None = None

    def __str__(self) -> str:
        where = f" [{self.relative_path}]" if self.relative_path is not None else ""
        return f"{self.kind.value}{where}: {self.message}"


@dataclass(frozen=True, slots=True)
class SealedBundle:
    """A read-only description of one sealed bundle, obtained only from a valid seal.

    There is no constructor that skips verification: the fields are exactly what a reader
    needs to make claims about the bundle — its run id, its outcome, its file inventory, its
    evidence digest — and they are only reachable through
    :func:`verify_sealed_bundle` returning a valid result. ``reference`` is the portable name
    and ``path`` is the operational location, the same split the workspace draws, so a read
    model can carry a bundle across machines and a caller opening files can use the path.
    """

    run_id: RunId
    reference: LogicalReference
    path: Path
    manifest: Manifest
    evidence_digest: EvidenceDigest
    checksums: tuple[ChecksumEntry, ...]

    @property
    def payload_paths(self) -> tuple[str, ...]:
        """The bundle's declared payload paths, in manifest order."""
        return tuple(entry.relative_path for entry in self.manifest.files)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """What verification found, and what claim it can therefore support.

    A result is returned rather than raised because a caller inspecting a bundle wants a
    report. A sealed bundle that has been corrupted is an expected thing to encounter, not an
    exceptional one, and the interesting question is always *which* of several things is
    wrong. :attr:`bundle` is populated only when there are no defects, so a caller cannot
    accidentally treat a failed verification as a description.
    """

    run_id: RunId
    defects: tuple[Defect, ...]
    bundle: SealedBundle | None
    expected_evidence_digest: EvidenceDigest | None = None

    @property
    def is_valid(self) -> bool:
        """Whether the bundle is exactly what its own manifest and checksum file claim."""
        return not self.defects and self.bundle is not None

    @property
    def proves_expected_output(self) -> bool:
        """Whether this result establishes the bundle *is* the expected sealed output.

        True only for a valid bundle whose recomputed evidence digest equals an externally
        supplied expected digest. Without one, a valid result establishes internal consistency
        and nothing more, and this property is the honest boundary between the two claims.
        """
        return (
            self.is_valid
            and self.expected_evidence_digest is not None
            and self.bundle is not None
            and self.bundle.evidence_digest == self.expected_evidence_digest
        )

    @property
    def summary(self) -> str:
        """A one-line human summary, for a log line or an API response."""
        if self.is_valid and self.bundle is not None:
            scope = (
                "expected output"
                if self.proves_expected_output
                else "internally consistent (no external expected digest was supplied)"
            )
            return (
                f"run {self.bundle.run_id} is sealed and {scope}; "
                f"evidence digest {self.bundle.evidence_digest.hex}"
            )
        return f"run {self.run_id} is not validly sealed: " + "; ".join(
            str(defect) for defect in self.defects
        )


def _defects_from_exception(error: BundleIntegrityError) -> tuple[Defect, ...]:
    """Turn a content failure raised while walking into a defect of the right kind.

    The walk raises one exception type for several distinct situations, and a caller told
    only "integrity error" has to guess which. The message is inspected to recover the kind,
    which is sound because every raise site names its own situation, and it keeps the single
    exception type that the sealing path also relies on. The link phrases live in
    :data:`_LINK_REFUSAL_MARKERS`, so the two files cannot drift on what counts as a link.
    """
    message = str(error)
    if any(marker in message for marker in _LINK_REFUSAL_MARKERS):
        return (Defect(DefectKind.LINK_IN_BUNDLE, message),)
    return (Defect(DefectKind.BUNDLE_UNREADABLE, message),)


def _read_manifest(bundle_root: Path) -> tuple[Manifest | None, bytes, tuple[Defect, ...]]:
    """Read, validate and canonicality-check ``manifest.json``."""
    path = bundle_root / MANIFEST_FILE_NAME
    if not path.is_file():
        return (
            None,
            b"",
            (
                Defect(
                    DefectKind.MANIFEST_MISSING,
                    f"the bundle has no {MANIFEST_FILE_NAME}, so it has no description of its "
                    "contents and cannot be authoritative",
                ),
            ),
        )
    try:
        raw = read_seal_file(path, max_bytes=MAX_MANIFEST_BYTES, what=MANIFEST_FILE_NAME)
    except BundleIntegrityError as error:
        return None, b"", (Defect(DefectKind.MANIFEST_INVALID, str(error)),)
    try:
        manifest = parse_manifest(raw)
    except BundleIntegrityError as error:
        return None, b"", (Defect(DefectKind.MANIFEST_INVALID, str(error)),)
    if raw != canonical_manifest_bytes(manifest):
        return (
            manifest,
            raw,
            (
                Defect(
                    DefectKind.MANIFEST_NOT_CANONICAL,
                    f"{MANIFEST_FILE_NAME} is not in its canonical form, so its evidence "
                    "digest would depend on how it was serialised rather than on the bundle",
                ),
            ),
        )
    return manifest, raw, ()


def _read_checksums(
    bundle_root: Path,
) -> tuple[tuple[ChecksumEntry, ...] | None, tuple[Defect, ...]]:
    """Read and parse ``checksums.sha256``."""
    path = bundle_root / CHECKSUMS_FILE_NAME
    if not path.is_file():
        return None, (
            Defect(
                DefectKind.CHECKSUMS_MISSING,
                f"the bundle has no {CHECKSUMS_FILE_NAME}, so its digests have no independent "
                "record and the seal is incomplete",
            ),
        )
    try:
        raw = read_seal_file(path, max_bytes=MAX_CHECKSUMS_BYTES, what=CHECKSUMS_FILE_NAME)
        return parse_checksums(raw), ()
    except BundleIntegrityError as error:
        return None, (Defect(DefectKind.CHECKSUMS_MALFORMED, str(error)),)


def _check_file_set(actual_files: frozenset[str], declared: Iterable[str]) -> tuple[Defect, ...]:
    """Require the actual file set to equal the declared payload plus the two seal files.

    Both directions are checked and neither is warned about. The expected set is built by
    *adding* the two seal files to the declared payload rather than by filtering the actual
    set, so there is no path by which an undeclared file can be quietly excluded from the
    comparison.
    """
    expected = set(declared) | set(SEAL_FILE_NAMES)
    missing = sorted(expected - actual_files)
    unexpected = sorted(actual_files - expected)
    defects = [
        Defect(
            DefectKind.PAYLOAD_MISSING,
            f"the manifest declares {len(missing)} file(s) that are not in the bundle",
            path,
        )
        for path in missing
    ]
    defects.extend(
        Defect(
            DefectKind.PAYLOAD_UNEXPECTED,
            "the bundle contains a file the manifest does not declare, so its content is not "
            "covered by the evidence digest",
            path,
        )
        for path in unexpected
    )
    return tuple(defects)


def _check_payload_digests(bundle_root: Path, manifest: Manifest) -> tuple[Defect, ...]:
    """Re-hash every declared payload file and compare against the manifest.

    The size is compared as well as the digest, and the two are reported as one finding: a
    file that changed length is the same event as one whose content changed, and separating
    them would produce two defects for one cause. Hashing streams in bounded memory through
    RES-229's ``asset_sha256_of_file``, so a multi-gigabyte Parquet table is verified without
    being loaded.
    """
    defects: list[Defect] = []
    for entry in manifest.files:
        path = bundle_root.joinpath(*entry.relative_path.split("/"))
        if not path.is_file():
            continue
        try:
            actual_size = path.lstat().st_size
            actual_digest = asset_sha256_of_file(path)
        except (OSError, RuntimeError) as error:
            defects.append(
                Defect(
                    DefectKind.PAYLOAD_MODIFIED,
                    f"the declared payload could not be read to be verified: {error}",
                    entry.relative_path,
                )
            )
            continue
        if actual_size != entry.size_bytes or actual_digest.hex != entry.sha256:
            defects.append(
                Defect(
                    DefectKind.PAYLOAD_MODIFIED,
                    "the declared payload no longer matches the digest and size the manifest "
                    f"records (expected {entry.sha256} and {entry.size_bytes} bytes)",
                    entry.relative_path,
                )
            )
    return tuple(defects)


def _check_coverage(manifest: Manifest, checksums: tuple[ChecksumEntry, ...]) -> tuple[Defect, ...]:
    """Require the checksum file to cover exactly the payload plus ``manifest.json``."""
    covered = tuple(entry.relative_path for entry in checksums)
    expected = {entry.relative_path for entry in manifest.files} | {MANIFEST_FILE_NAME}
    uncovered, undeclared = coverage_discrepancies(expected, covered)
    defects = [
        Defect(
            DefectKind.COVERAGE_MISMATCH,
            "the manifest declares a file that the checksum file does not cover",
            path,
        )
        for path in uncovered
    ]
    defects.extend(
        Defect(
            DefectKind.COVERAGE_MISMATCH,
            "the checksum file covers a file that the manifest does not declare, so the two "
            "records describe different bundles",
            path,
        )
        for path in undeclared
    )
    return tuple(defects)


def _check_checksum_agreement(
    bundle_root: Path, checksums: tuple[ChecksumEntry, ...]
) -> tuple[Defect, ...]:
    """Re-hash every covered file and compare against the checksum line for it.

    Done independently of the manifest comparison, so a bundle whose manifest and checksum
    file were *both* rewritten still shows as self-consistent here and is caught instead by
    :attr:`VerificationResult.proves_expected_output`. That is the honest boundary of a
    self-contained seal, and pretending otherwise would be the overstatement this package
    exists to avoid.
    """
    defects: list[Defect] = []
    for entry in checksums:
        path = bundle_root.joinpath(*entry.relative_path.split("/"))
        if not path.is_file():
            continue
        try:
            actual = asset_sha256_of_file(path)
        except (OSError, RuntimeError) as error:
            defects.append(
                Defect(
                    DefectKind.CHECKSUM_MISMATCH,
                    f"the covered file could not be read to be verified: {error}",
                    entry.relative_path,
                )
            )
            continue
        if actual != entry.digest:
            kind = (
                DefectKind.MANIFEST_MODIFIED
                if entry.relative_path == MANIFEST_FILE_NAME
                else DefectKind.CHECKSUM_MISMATCH
            )
            defects.append(
                Defect(
                    kind,
                    f"the file no longer matches the digest the checksum file records "
                    f"(expected {entry.digest.hex})",
                    entry.relative_path,
                )
            )
    return tuple(defects)


def _check_seal_debris(actual_files: frozenset[str]) -> tuple[Defect, ...]:
    """Report a reserved temporary name as debris from an unfinished seal attempt.

    This is a defect rather than an ignored file, and it is a separate kind from
    ``payload_unexpected`` because the fix is different: a leftover temporary is a *seal*
    failure to be retried, not evidence that has been added to the bundle. It cannot normally
    happen — the names are reserved, the finalizer deletes its own leftovers before it takes
    the inventory, and promotion is atomic — so finding one means the bundle was assembled
    outside this package or a promotion was interrupted in a way that should not be possible.
    Either way it is reported rather than tolerated.
    """
    return tuple(
        Defect(
            DefectKind.SEAL_DEBRIS,
            "a reserved temporary name from an unfinished seal attempt is present, so this "
            "bundle was not produced by a completed finalization",
            path,
        )
        for path in sorted(actual_files & SEAL_TEMP_FILE_NAMES)
    )


def verify_bundle_seal(
    bundle_root: Path,
    run_id: RunId,
    *,
    expected_evidence_digest: EvidenceDigest | None = None,
) -> VerificationResult:
    """Verify the seal of the bundle rooted at ``bundle_root`` and return what was found.

    ``bundle_root`` is expected to be a path already proved inside its workspace class by
    :meth:`Workspace.resolve`; this function does not re-derive containment, and it is the
    reason the verification path can be exercised against a staging directory during
    finalization as well as against a promoted one. It is not exported from the package, so
    the public way to verify a bundle is :func:`verify_sealed_bundle`.

    Every finding is collected rather than short-circuited on the first one. A caller
    diagnosing a corrupted bundle wants the whole picture: knowing that the payload was
    modified *and* the manifest was not canonical is more useful than being told about the
    first of those and having to ask again.

    The claim a result supports is deliberately narrow, and
    :attr:`VerificationResult.proves_expected_output` is the boundary. With no expected digest
    supplied, a valid result means the bundle is internally consistent — that its manifest,
    its checksum file and its bytes agree with each other. That is a real and useful
    guarantee, and it is not the same claim as "this is the bundle I expected", which only an
    external digest can establish. Neither claim is ever described as tamper-proof.
    """
    if not bundle_root.is_dir():
        return VerificationResult(
            run_id=run_id,
            defects=(
                Defect(
                    DefectKind.BUNDLE_MISSING,
                    "there is no bundle directory for this run, so nothing has been promoted "
                    "into sealed evidence",
                ),
            ),
            bundle=None,
            expected_evidence_digest=expected_evidence_digest,
        )

    defects: list[Defect] = []
    try:
        entries = walk_bundle(bundle_root)
    except BundleIntegrityError as error:
        return VerificationResult(
            run_id=run_id,
            defects=_defects_from_exception(error),
            bundle=None,
            expected_evidence_digest=expected_evidence_digest,
        )

    actual_files = frozenset(entry.relative_path for entry in entries if not entry.is_directory)
    defects.extend(_check_seal_debris(actual_files))

    manifest, canonical, manifest_defects = _read_manifest(bundle_root)
    defects.extend(manifest_defects)
    checksums, checksum_defects = _read_checksums(bundle_root)
    defects.extend(checksum_defects)

    if manifest is not None:
        defects.extend(
            _check_file_set(actual_files, (entry.relative_path for entry in manifest.files))
        )
        defects.extend(_check_payload_digests(bundle_root, manifest))
    if checksums is not None:
        defects.extend(_check_checksum_agreement(bundle_root, checksums))
    if manifest is not None and checksums is not None:
        defects.extend(_check_coverage(manifest, checksums))

    if defects:
        return VerificationResult(
            run_id=run_id,
            defects=tuple(defects),
            bundle=None,
            expected_evidence_digest=expected_evidence_digest,
        )

    if manifest is None or checksums is None:  # pragma: no cover - defensive
        raise AssertionError("a defect-free verification must have read both seal files")

    evidence_digest = evidence_digest_of_canonical_manifest_bytes(canonical)
    if expected_evidence_digest is not None and evidence_digest != expected_evidence_digest:
        defects.append(
            Defect(
                DefectKind.EVIDENCE_DIGEST_MISMATCH,
                "the bundle is internally consistent but its evidence digest is not the one "
                "an external reference expects, so this is not the expected sealed output "
                f"(expected {expected_evidence_digest.hex}, found {evidence_digest.hex})",
            )
        )
    if defects:
        return VerificationResult(
            run_id=run_id,
            defects=tuple(defects),
            bundle=None,
            expected_evidence_digest=expected_evidence_digest,
        )

    return VerificationResult(
        run_id=run_id,
        defects=(),
        bundle=SealedBundle(
            run_id=manifest.run_id,
            reference=LogicalReference(
                PersistenceClass.SEALED_EVIDENCE,
                class_location_segments(PersistenceClass.SEALED_EVIDENCE) + (manifest.run_id,),
            ),
            path=bundle_root,
            manifest=manifest,
            evidence_digest=evidence_digest,
            checksums=checksums,
        ),
        expected_evidence_digest=expected_evidence_digest,
    )


def verify_sealed_bundle(
    workspace: Workspace,
    run_id: RunId,
    *,
    expected_evidence_digest: EvidenceDigest | None = None,
) -> VerificationResult:
    """Verify the sealed bundle of ``run_id`` in ``workspace``.

    The bundle is located through the workspace resolver, scoped to the sealed-evidence class,
    so a run id cannot reach a staging directory, a derived index, or anything outside the
    evidence root. A run that was never promoted reports
    :attr:`DefectKind.BUNDLE_MISSING` rather than raising, because "this run has not been
    sealed" is an answer, not an error.

    Pass ``expected_evidence_digest`` to establish that the bundle is the *expected* sealed
    output. Without it, a valid result establishes internal consistency only — see
    :attr:`VerificationResult.proves_expected_output`.
    """
    run = parse_run_id(run_id)
    bundle_root = workspace.resolve(PersistenceClass.SEALED_EVIDENCE, run)
    return verify_bundle_seal(bundle_root, run, expected_evidence_digest=expected_evidence_digest)
