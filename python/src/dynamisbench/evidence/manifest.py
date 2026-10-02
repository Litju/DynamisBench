"""The manifest, the evidence digest, and the checksum file — the three things that make a
bundle verifiable without this package.

The v0 seal is deliberately **non-self-referential**, and every decision here follows from
that one choice:

* ``manifest.json`` enumerates every payload artifact by normalized relative path and
  raw-byte SHA-256, and never enumerates or hashes itself. It cannot even *try* to contain
  its own evidence digest, because the model forbids unknown fields — so a manifest carrying
  one is a validation failure, not a subtle recursion.
* The **evidence digest** is the SHA-256 of the canonical ``manifest.json`` bytes. Because
  the manifest already contains the digest of every payload file, this one value is the
  root identity of the whole sealed output: a single comparison establishes that the output
  is the expected one. It is computed *from* the manifest and returned to the caller, never
  embedded back into it.
* ``checksums.sha256`` covers every payload file **and** ``manifest.json``, excludes itself,
  and exists so the bundle can be re-checked by a person or a standard tool without this
  package. It is an aid, not the identity: the manifest-derived digest is the identity, and
  a checksum file that agreed with nothing else would be worthless.

**Three identities, never collapsed.** :class:`EvidenceDigest` is a distinct type from
``SemanticDigest`` and ``AssetDigest``, and the distinction is structural rather than
documentary. A semantic digest answers "what does this validated definition mean"; an asset
digest answers "what are these bytes"; an evidence digest answers "what did this run
produce, sealed". Passing one where another is required is a type error, and the
non-self-referential seal would be impossible if the evidence digest were a *semantic* digest
of a model that had to contain it.

**One canonical serialiser.** The manifest is serialised through RES-229's existing
:func:`canonical_semantic_bytes`, so a second canonical JSON implementation is not created
and RFC 8785's semantics, its ``-0`` handling and its number formatting are the ones the
rest of the project already depends on. Determinism then comes from three things and nothing
else: the manifest's property names are sorted by RFC 8785, the file list is sorted by the
relative path's UTF-8 bytes, and no absolute path, timestamp, hostname or enumeration order
is an input. Moving an identical bundle to another workspace therefore cannot change its
seal.

**The checksum format is the GNU ``sha256sum`` text format, restricted.** One line per
covered file, ``<64 lowercase hex><two spaces><relative path>``, LF-terminated, sorted by
path. The two-space separator is the documented GNU one, so ``sha256sum -c`` reads it on a
machine that has no DynamisBench installed. The restriction is what makes it *unambiguous*
rather than merely conventional: coreutils escapes a path containing a newline or a
backslash with a leading ``\\``, and this package's path language refuses both, so no escape
can occur and none is defined. A path can also not begin with a space, so the two spaces
after the digest are unambiguous. A file that is not exactly this — wrong separator, CRLF
line endings, a missing final newline, an unterminated last line, duplicate entries, or
entries out of canonical order — is malformed and invalid, not a variant to be tolerated.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.identifiers import Sha256Hex
from dynamisbench.evidence.bundle import (
    CHECKSUMS_FILE_NAME,
    MANIFEST_FILE_NAME,
    ArtifactRole,
    BundleIntegrityError,
    BundleNamingError,
    BundleRelativePath,
    RunId,
    RunOutcome,
    parse_bundle_relative_path,
)
from dynamisbench.identity.digests import AssetDigest, DigestAlgorithm, asset_sha256
from dynamisbench.identity.semantic import canonical_semantic_bytes

__all__ = [
    "CHECKSUM_SEPARATOR",
    "MAX_CHECKSUMS_BYTES",
    "MAX_MANIFEST_BYTES",
    "MANIFEST_SCHEMA_VERSION",
    "ChecksumEntry",
    "EvidenceDigest",
    "Manifest",
    "ManifestEntry",
    "canonical_manifest_bytes",
    "coverage_discrepancies",
    "evidence_digest_of_canonical_manifest_bytes",
    "manifest_payload_paths",
    "parse_checksums",
    "parse_manifest",
    "read_seal_file",
    "render_checksums",
]

MANIFEST_SCHEMA_VERSION: Final = 1
"""The manifest schema version, and a ``Literal`` so an unknown version cannot validate.

A closed literal is the point: a manifest written by a future version must be refused rather
than partially understood, because half-understood integrity metadata is worse than none.
Changing what a manifest means is therefore a visible schema change, exactly as changing the
digest algorithm would be.
"""

CHECKSUM_SEPARATOR: Final = "  "
"""Two spaces, the GNU ``sha256sum`` text separator between digest and path."""

MAX_MANIFEST_BYTES: Final = 64 * 1024 * 1024
"""The largest manifest this package will read into memory.

A v0 run bundle holds tens to hundreds of artifacts, so this admits half a million entries
— three orders of magnitude more than any current run needs — while still refusing to let a
corrupt or hostile ``manifest.json`` decide how much memory the verifier allocates. The read
is bounded here as well as at the file size, so the guarantee does not depend on the caller
having checked anything.
"""

MAX_CHECKSUMS_BYTES: Final = 64 * 1024 * 1024
"""The largest checksum file this package will read, for the same reason."""


class EvidenceDigest(BaseModel):
    """The SHA-256 of a sealed bundle's canonical ``manifest.json`` bytes.

    The root identity of the sealed output, and a value that travels *beside* a run rather
    than replacing it: a reference states ``run_id`` for people and ``evidence_digest`` for
    machines, and neither is derivable from the other.

    It is a separate type from ``SemanticDigest`` and ``AssetDigest`` because it answers a
    third question, and because the seal's non-self-reference only works if this type is not
    the type of something the manifest can contain. The ``algorithm`` field reuses RES-229's
    ``DigestAlgorithm`` vocabulary rather than introducing a cryptography abstraction: SHA-256
    is the only algorithm, recorded explicitly so that a future change is a visible schema
    change and two digests can never be compared without saying which produced them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal[DigestAlgorithm.SHA256] = DigestAlgorithm.SHA256
    hex: Sha256Hex


def evidence_digest_of_canonical_manifest_bytes(canonical: bytes) -> EvidenceDigest:
    """Digest an already-canonical ``manifest.json`` byte string.

    The argument is named for what it must be — the output of
    :func:`canonical_manifest_bytes` — because a digest over bytes that were not canonical
    would depend on the serialiser rather than on the bundle, and would therefore be a
    different value for the same evidence. The hash comes from the standard library and the
    algorithm name from the existing identity vocabulary, so this adds no cryptography
    abstraction of its own; it is deliberately not
    ``semantic_sha256_of_canonical_bytes``, which returns a different identity type for a
    different question.
    """
    return EvidenceDigest(hex=hashlib.sha256(canonical).hexdigest())


def _canonical_file_order(entries: tuple[ManifestEntry, ...]) -> tuple[ManifestEntry, ...]:
    """Order the manifest's files by path bytes, and refuse an impossible file set.

    Two rules, both about the manifest being a *description* rather than a log:

    * **A duplicate path is rejected**, because two entries for one artifact mean the
      manifest is ambiguous about what was produced, and a reader picking either one would be
      guessing.
    * **An empty file list is rejected.** A bundle with no payload declares no evidence, and
      sealing one would give a run an identity with nothing behind it. This is checked here
      rather than in the finalizer so that a manifest *read back* is held to the same rule as
      one just written, which is what makes the verifier's model check meaningful.

    The sort is on the UTF-8 bytes of the relative path, not on the ``str``. A byte
    comparison is exact and locale-independent on every platform, and it is the same
    comparator the checksum file uses, so the manifest and the checksum file cannot disagree
    about which file comes first. (RFC 8785 would not have sorted this array for us: array
    order is meaning, and reordering a sequence is not a canonicalisation decision this layer
    is allowed to make on the domain's behalf.)
    """
    if not entries:
        raise ValueError(
            "a manifest must declare at least one payload artifact; a bundle with no payload "
            "would be sealing an empty claim"
        )
    seen: set[str] = set()
    duplicates: set[str] = set()
    for entry in entries:
        if entry.relative_path in seen:
            duplicates.add(entry.relative_path)
        seen.add(entry.relative_path)
    if duplicates:
        raise ValueError(
            f"the manifest declares the same payload path more than once: {sorted(duplicates)}"
        )
    return tuple(sorted(entries, key=lambda entry: entry.relative_path.encode("utf-8")))


class ManifestEntry(DomainModel):
    """One payload artifact as the manifest declares it.

    ``relative_path`` is the portable name, ``sha256`` the raw-byte digest and
    ``size_bytes`` the length of those bytes. The size is not decoration: it is a second,
    independent fact that a reader can check without hashing, so a truncated or swapped
    artifact is visible even to a reader that only has the manifest, and it is what the
    verifier compares before it trusts a digest.

    ``role`` is optional and is a reader's hint, never a schema: see
    :class:`~dynamisbench.evidence.bundle.ArtifactRole`. It is not cross-checked against the
    path, because a rule like "``native_evidence`` implies the file is under ``native/````
    would encode a bundle layout this package does not own.
    """

    relative_path: BundleRelativePath
    sha256: Sha256Hex
    size_bytes: Annotated[int, Field(ge=0, strict=True)]
    role: ArtifactRole | None = None


class Manifest(DomainModel):
    """The complete, self-consistent description of one sealed bundle's payload.

    Minimal on purpose — ``schema_version``, ``run_id``, ``outcome``, ``files`` — because
    every field here is a claim the package is responsible for keeping true. A
    ``created_at`` timestamp, a hostname, an absolute path or an execution fingerprint would
    each add a field whose value is either machine state or another issue's authority, and
    each would make two otherwise identical bundles differ. The run's own metadata is
    payload: ``run.json`` is a declared file like any other, hashed and versioned by the same
    rules, so no evidence schema is pre-empted here.

    ``run_id`` and ``outcome`` are the manifest's only non-file facts, and both are
    authoritative: they are what a reader sees before it can check a single digest, and they
    are inside the bytes the evidence digest is taken over, so neither can be altered without
    changing the bundle's identity.

    The ``Literal[1]`` schema version is a closed literal, so a manifest written by a future
    schema is refused rather than partially understood. It is spelled as the literal rather
    than as :data:`MANIFEST_SCHEMA_VERSION` because a ``Final`` variable is not a valid
    ``Literal`` argument; a gate asserts the two agree, so they cannot drift apart unnoticed.

    The model is ``extra="forbid"``, which is what makes the non-self-referential seal
    structural: a manifest that tried to embed its own evidence digest would fail to
    validate rather than quietly containing a value that could not be true.
    """

    schema_version: Literal[1] = MANIFEST_SCHEMA_VERSION
    run_id: RunId
    outcome: RunOutcome
    files: Annotated[tuple[ManifestEntry, ...], AfterValidator(_canonical_file_order)]


def canonical_manifest_bytes(manifest: Manifest) -> bytes:
    """Return the RFC 8785 canonical bytes this bundle's manifest must be stored as.

    These bytes are three things at once: what is written to ``manifest.json``, what the
    evidence digest is taken over, and what a verifier requires the stored file to equal. The
    last of those is why the same function is used for all three — a manifest stored in any
    other form has an ambiguous identity, because its evidence digest would then depend on
    how it happened to be serialised.
    """
    return canonical_semantic_bytes(manifest)


def parse_manifest(raw: bytes) -> Manifest:
    """Parse and validate manifest bytes.

    Canonicality is *not* checked here, so the verifier can report "this manifest is not in
    canonical form" as a distinct finding from "this manifest is not a manifest". Both are
    invalid; a caller that only wants a value compares
    :func:`canonical_manifest_bytes` against ``raw`` itself.

    :raises BundleIntegrityError: if the bytes are too large, are not UTF-8 JSON, or do not
        satisfy the manifest model — including a manifest that embeds an evidence digest.
    """
    if len(raw) > MAX_MANIFEST_BYTES:
        raise BundleIntegrityError(
            f"{MANIFEST_FILE_NAME} is {len(raw)} bytes, larger than the "
            f"{MAX_MANIFEST_BYTES} bytes this package will read"
        )
    try:
        return Manifest.model_validate_json(raw)
    except PydanticValidationError as error:
        raise BundleIntegrityError(
            f"{MANIFEST_FILE_NAME} is not a valid manifest: {error}"
        ) from error
    except ValueError as error:
        raise BundleIntegrityError(
            f"{MANIFEST_FILE_NAME} could not be read as JSON: {error}"
        ) from error


def read_seal_file(path: Path, *, max_bytes: int, what: str) -> bytes:
    """Read a seal metadata file, refusing to read an implausibly large one.

    The size is taken from the filesystem *before* the read rather than after it, so a file
    that claims to be enormous never becomes a large allocation. ``what`` names the file in
    the diagnostic without the path, because a refusal should report which artifact is wrong
    without handing out the resolved location.
    """
    try:
        size = path.lstat().st_size
    except OSError as error:
        raise BundleIntegrityError(f"{what} could not be read: {error}") from error
    if size > max_bytes:
        raise BundleIntegrityError(
            f"{what} is {size} bytes, larger than the {max_bytes} bytes allowed"
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise BundleIntegrityError(f"{what} could not be read: {error}") from error


@dataclass(frozen=True, slots=True)
class ChecksumEntry:
    """One line of ``checksums.sha256``: a covered file and the digest declared for it.

    ``relative_path`` is a plain string because the checksum file covers one file that is not
    payload — ``manifest.json`` — and a payload path type that refuses seal names would
    refuse to describe the file that gives those paths their meaning. The digest is an
    ``AssetDigest``, so comparing a checksum line against a recomputed hash is a comparison of
    two values of the same type rather than a string exercise.
    """

    relative_path: str
    digest: AssetDigest


def _checksum_sort_key(entry: ChecksumEntry) -> bytes:
    return entry.relative_path.encode("utf-8")


def render_checksums(manifest: Manifest, canonical_manifest: bytes) -> bytes:
    """Render the deterministic ``checksums.sha256`` bytes for a sealed bundle.

    Coverage is exactly the manifest's payload files plus ``manifest.json``, sorted by the
    relative path's UTF-8 bytes, one ``<digest><two spaces><path>\\n`` line each, and the
    file never covers itself. The manifest's own entry is hashed from the canonical bytes
    passed in — the very bytes that were written — so the checksum file and the evidence
    digest are derived from one identical byte string rather than from two independent
    serialisations that might not agree.

    :raises BundleIntegrityError: if ``canonical_manifest`` is not the canonical serialisation
        of ``manifest``, which would mean the two were derived from different bytes.
    """
    if canonical_manifest != canonical_manifest_bytes(manifest):
        raise BundleIntegrityError(
            "the checksum file would cover different manifest bytes from the ones stored, so "
            "the evidence digest and the checksum file would describe two different bundles"
        )
    entries = [
        ChecksumEntry(relative_path=entry.relative_path, digest=AssetDigest(hex=entry.sha256))
        for entry in manifest.files
    ]
    entries.append(
        ChecksumEntry(relative_path=MANIFEST_FILE_NAME, digest=asset_sha256(canonical_manifest))
    )
    lines = [
        f"{entry.digest.hex}{CHECKSUM_SEPARATOR}{entry.relative_path}\n"
        for entry in sorted(entries, key=_checksum_sort_key)
    ]
    return "".join(lines).encode("utf-8")


def _validated_checksum_path(value: str) -> str:
    """Accept a payload path, or ``manifest.json``; refuse a self-reference.

    ``checksums.sha256`` is refused here rather than left to the coverage comparison,
    because a checksum file that covers itself is self-referential *by construction* — the
    digest it would record cannot exist before the file is written — so it is a malformed
    file of this type rather than a coverage disagreement to be diagnosed later.
    """
    if value == CHECKSUMS_FILE_NAME:
        raise BundleNamingError(
            f"{CHECKSUMS_FILE_NAME} must not cover itself, so this line is self-referential"
        )
    if value == MANIFEST_FILE_NAME:
        return value
    return parse_bundle_relative_path(value)


def parse_checksums(raw: bytes) -> tuple[ChecksumEntry, ...]:
    """Parse ``checksums.sha256`` bytes, or refuse them.

    Everything that could make the file ambiguous to *another* reader is refused here, not
    tolerated: a wrong separator, CRLF endings, a missing final newline, a blank line, a
    digest that is not 64 lower-case hex characters, a path outside the bundle language, a
    duplicate, and entries that are not in the canonical order. The order requirement is what
    makes "the same bundle produces the same checksum bytes" a checkable property rather than
    a hope: a reordered file is corruption, not a variant.

    :raises BundleIntegrityError: if the bytes are not exactly a checksum file this package
        would have written.
    """
    if len(raw) > MAX_CHECKSUMS_BYTES:
        raise BundleIntegrityError(
            f"{CHECKSUMS_FILE_NAME} is {len(raw)} bytes, larger than the "
            f"{MAX_CHECKSUMS_BYTES} bytes this package will read"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleIntegrityError(f"{CHECKSUMS_FILE_NAME} is not valid UTF-8: {error}") from error
    if not text:
        raise BundleIntegrityError(f"{CHECKSUMS_FILE_NAME} is empty")
    if not text.endswith("\n"):
        raise BundleIntegrityError(
            f"{CHECKSUMS_FILE_NAME} does not end with a newline, so its last entry is unterminated"
        )
    entries: list[ChecksumEntry] = []
    for number, line in enumerate(text.split("\n")[:-1], start=1):
        if not line:
            raise BundleIntegrityError(f"{CHECKSUMS_FILE_NAME} line {number} is blank")
        digest_text, separator, path_text = line.partition(CHECKSUM_SEPARATOR)
        if not separator:
            raise BundleIntegrityError(
                f"{CHECKSUMS_FILE_NAME} line {number} does not separate a digest from a path "
                f"with exactly two spaces"
            )
        if len(digest_text) != 64 or any(
            character not in "0123456789abcdef" for character in digest_text
        ):
            raise BundleIntegrityError(
                f"{CHECKSUMS_FILE_NAME} line {number} does not begin with 64 lower-case "
                "hexadecimal characters"
            )
        if not path_text:
            raise BundleIntegrityError(f"{CHECKSUMS_FILE_NAME} line {number} names no file")
        try:
            relative_path = _validated_checksum_path(path_text)
        except BundleNamingError as error:
            raise BundleIntegrityError(
                f"{CHECKSUMS_FILE_NAME} line {number} names a file that cannot appear in a "
                f"bundle: {error}"
            ) from error
        entries.append(
            ChecksumEntry(relative_path=relative_path, digest=AssetDigest(hex=digest_text))
        )
    paths = [entry.relative_path for entry in entries]
    if len(set(paths)) != len(paths):
        raise BundleIntegrityError(f"{CHECKSUMS_FILE_NAME} lists the same file more than once")
    if paths != sorted(paths, key=lambda path: path.encode("utf-8")):
        raise BundleIntegrityError(
            f"{CHECKSUMS_FILE_NAME} is not sorted by relative path, so it is not the file this "
            "package writes"
        )
    return tuple(entries)


def manifest_payload_paths(manifest: Manifest) -> tuple[str, ...]:
    """The manifest's payload paths, in the manifest's own order."""
    return tuple(entry.relative_path for entry in manifest.files)


def coverage_discrepancies(
    declared: Iterable[str], covered: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(declared_but_uncovered, covered_but_undeclared)`` for a coverage comparison.

    Both directions matter and they are not the same check. A file the manifest declares that
    the checksum file omits is a file with no digest record; a file the checksum file lists
    that the manifest does not declare is a claim about evidence the manifest does not
    describe. Either way the two are describing different bundles.
    """
    declared_set = set(declared)
    covered_set = set(covered)
    return (
        tuple(sorted(declared_set - covered_set)),
        tuple(sorted(covered_set - declared_set)),
    )
