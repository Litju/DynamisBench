"""The vocabulary of one evidence bundle: what a run is called, how it ended, and what
a path inside it is allowed to say.

Everything downstream of this module — the manifest, the checksum file, the seal, the
verifier — agrees on its terms because they all take them from here, and this is the
place those terms are fixed. There are five of them.

**A run id is a name, never a digest.** A run id is the human/logical identity of one
execution: it names the directory under ``.staging/`` and, after promotion, the directory
under ``runs/``. It is deliberately *not* replaced by the evidence digest, because the
digest answers a different question and cannot be known before the run finishes, while a
run has to be addressable while it is still being written. The two travel together once
the run is sealed. The pattern is the project's existing identifier convention,
reused rather than reinvented, with one addition: it is **lower-case only**, because
``Run-1`` and ``run-1`` are the same directory on the case-insensitive filesystems that
are the primary platform (ADR-023), and two run ids that collide on one platform and not
another are not one vocabulary.

**An outcome records whether the run produced a valid record, not why it did not.** The
v0 vocabulary is two values. A third — cancelled, timed out, killed, non-converged —
would be a claim about *why*, and every such reason is simulator- or supervisor-specific
detail that belongs in the failure record the caller writes as payload, not in the seal
metadata that identifies the run. ``FAILED`` therefore means precisely: this run has a
complete, valid failure record, and it is sealed as evidence of that failure. It is not
a synonym for abandoned staging, which has no record at all and is not evidence.

**An artifact role is an optional hint, never a schema.** Every role value is the name of
a member the current Evidence & Provenance Model v0.2 already declares in its run-bundle
layout — ``run.json``, ``run-spec.json``, ``preflight.json``, ``environment.json``,
``provenance.json``, ``diagnostics.json``, ``assessment.json``, ``native/``, ``canonical/``,
``logs/``. Nothing is added, nothing is validated about the file's *contents*, and the
field is optional throughout, so sealing typed metadata does not require any of them to
exist. A role is deliberately **not** cross-checked against the path, because a check
like "``native_evidence`` implies the file is under ``native/``" would encode a bundle
schema this module does not own. Its one job is to let a later reader tell an assessment
table from a solver log without parsing names.

**A bundle path is relative, normalized, and portable.** Manifest paths are the *only*
place in a sealed bundle where a path is scientific data, so the language is as narrow as
it can be made to be: relative, ``/``-separated, already normalized, no whitespace, no
control characters, no traversal, and no name that means one file on one platform and
another elsewhere. The generic half of that judgement is not re-invented here: the
traversal, drive, UNC, DOS-device, trailing-dot and Windows-illegal-character rules all
come from :func:`dynamisbench.workspace.paths.validate_logical_reference`, the RES-230
gate that every other workspace reference already passes. This module adds only the
*bundle-content* constraints on top — one canonical spelling, no whitespace, and no path
that may name the seal's own metadata — and converts the workspace refusal into a value
error so a malformed path is a validation failure rather than an exception escaping from
inside a model.

**A sealed bundle contains regular files and directories, and nothing else.** Symlinks,
junctions, and every other reparse point are refused. This is not only about escapes: a
bundle whose bytes can be redirected elsewhere is not a self-contained portable artifact,
so a copy of it is not necessarily the evidence that was sealed. A junction is called out
specifically because :meth:`pathlib.Path.is_symlink` reports it as *not* a link, which
makes a symlink-only check the standard way for a bundle to escape unnoticed on the
authoritative platform. A **hard link is deliberately allowed**: it is a second directory
entry for bytes already inside the bundle rather than a redirection out of it, and both
entries hash to the same value, so it costs the seal no integrity.

The errors here are the vocabulary's, and each one is a decision a caller might make
differently: a *naming* failure is a caller mistake, a *conflict* means a location is
already occupied, an *integrity* failure means content that must not be sealed or must not
be believed, and an *operation* failure means the filesystem refused a step and nothing
became authoritative. A :class:`dynamisbench.workspace.PathScopeError` is deliberately
allowed to propagate out of the workspace resolver rather than being re-wrapped: it is
the same failure, it already carries the offending reference, and re-wrapping it would be
the second generic resolver this package must not grow.
"""

from __future__ import annotations

import stat
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

from pydantic import AfterValidator, StringConstraints, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from dynamisbench.domain.spec.identifiers import IDENTIFIER_MAX_LENGTH, IDENTIFIER_PATTERN
from dynamisbench.workspace.authority import PathScopeError
from dynamisbench.workspace.paths import validate_logical_reference

__all__ = [
    "CHECKSUMS_FILE_NAME",
    "CHECKSUMS_TEMP_FILE_NAME",
    "MANIFEST_FILE_NAME",
    "MANIFEST_TEMP_FILE_NAME",
    "RESERVED_BUNDLE_FILE_NAMES",
    "SEAL_FILE_NAMES",
    "ArtifactRole",
    "BundleConflictError",
    "BundleIntegrityError",
    "BundleNamingError",
    "BundleOperationError",
    "BundleRelativePath",
    "EvidenceError",
    "RunId",
    "RunOutcome",
    "is_link_or_reparse_point",
    "parse_bundle_relative_path",
    "parse_run_id",
]

MANIFEST_FILE_NAME: Final = "manifest.json"
CHECKSUMS_FILE_NAME: Final = "checksums.sha256"

MANIFEST_TEMP_FILE_NAME: Final = f"{MANIFEST_FILE_NAME}.seal-tmp"
CHECKSUMS_TEMP_FILE_NAME: Final = f"{CHECKSUMS_FILE_NAME}.seal-tmp"

SEAL_FILE_NAMES: Final = frozenset({MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME})
"""The two files the seal itself writes, which are therefore never payload.

They are excluded from the manifest because ``manifest.json`` must not enumerate or hash
itself, and from ``checksums.sha256`` because that file must not hash itself. Both facts
are what make the v0 seal non-self-referential (Evidence & Provenance Model v0.2).
"""

RESERVED_BUNDLE_FILE_NAMES: Final = SEAL_FILE_NAMES | frozenset(
    {MANIFEST_TEMP_FILE_NAME, CHECKSUMS_TEMP_FILE_NAME}
)
"""Every name the seal owns inside a bundle, including the two it writes through.

The temporary names are reserved so that a half-written seal can never be mistaken for
payload. If they were ordinary names, a checksum write that failed part-way through would
leave a file the next inventory would declare as evidence of the run, and the debris would
be sealed as science. Reserving them means the finalizer can delete its own leftovers
without ever touching anything a caller wrote.
"""


class EvidenceError(Exception):
    """Base class for every refusal this package makes.

    Evidence operations fail closed. A bundle that cannot be fully described, fully
    hashed, or fully verified has no identity, and reporting it as anything weaker — a
    warning, a partial manifest, a "probably fine" checksum set — would put an unverifiable
    claim where an auditable one belongs.
    """


class BundleNamingError(EvidenceError, ValueError):
    """A run id or bundle-relative path is not in the sealed-bundle naming language.

    A caller mistake, and the only failure in this package that is a value error as well
    as an evidence error, so that ordinary ``except ValueError`` handling at a
    deserialising boundary still catches it.
    """


class BundleConflictError(EvidenceError):
    """A location this operation needs is already occupied.

    Raised for a staging directory that already exists, for a run that is already sealed,
    and for a second finalization of the same bundle. Sealed evidence is never
    overwritten, merged into, or replaced (Evidence & Provenance Model v0.2), so the
    duplicate case is the common one and it fails rather than resolving itself.
    """


class BundleIntegrityError(EvidenceError):
    """Bundle content cannot be sealed, or does not verify as claimed.

    Content-level only: a link, a non-regular file, a missing or extra artifact, a
    modified payload, a manifest that will not validate, a checksum file that will not
    parse. The sealing path raises this; the verification path reports the same
    information as a defect so a caller inspecting a bundle gets a report rather than an
    exception.
    """


class BundleOperationError(EvidenceError):
    """A filesystem step required to seal or promote a bundle failed.

    Distinct from a conflict and from an integrity failure because the guarantee is
    about the *attempt*: nothing became authoritative, and the staging directory is left
    exactly as diagnosable as it was before the step that failed.
    """


class RunOutcome(StrEnum):
    """Whether a run produced a valid record, recorded at seal time.

    Two values, and the distinction between them is the whole point of the vocabulary:

    * ``SUCCEEDED`` — the run completed and its payload is the result.
    * ``FAILED`` — the run did not complete, and its payload contains a complete failure
      record. A sealed failed run is authoritative evidence *of the failure*, which is a
      different and equally important scientific fact from a run that never produced
      anything.

    The reason a run failed is not encoded here. A cancellation, a timeout, a non-converged
    solver and a killed worker are simulator- and supervisor-specific facts, and they
    belong in the failure record the caller writes as payload, where they are hashed,
    versioned and extensible. Putting them in the seal metadata would mean inventing a
    failure vocabulary this package has no authority to define, and would make a run
    unsealable the moment a new simulator arrives.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ArtifactRole(StrEnum):
    """What a payload artifact is for, recorded optionally in the manifest.

    Every value names a member of the run-bundle layout Evidence & Provenance Model v0.2
    already declares, and the vocabulary is closed. The field is optional so that sealing
    works before any of those files exists, and it is not validated against the file's
    contents or its path: a role is a reader's hint about a file's purpose, not a schema
    for the file.

    Its purpose is forward compatibility without pre-emption. A query projection over
    sealed evidence has to tell an assessment table from a solver diagnostic without
    parsing file names, and this is the smallest amount of authority that lets it. Adding
    a value later is a visible schema change, which is the correct cost for changing what a
    sealed manifest means.
    """

    RUN_METADATA = "run_metadata"
    RUN_SPEC = "run_spec"
    PREFLIGHT = "preflight"
    ENVIRONMENT = "environment"
    PROVENANCE = "provenance"
    DIAGNOSTICS = "diagnostics"
    ASSESSMENT = "assessment"
    NATIVE_EVIDENCE = "native_evidence"
    CANONICAL_EVIDENCE = "canonical_evidence"
    LOG = "log"


def _reject_control_and_whitespace(value: str, kind: str) -> None:
    for character in value:
        if not character.isprintable() or character.isspace():
            raise ValueError(
                f"a {kind} must not contain whitespace or control characters, but {value!r} does"
            )


def _platform_name_gate(value: str, kind: str) -> tuple[str, ...]:
    """Run the RES-230 workspace name gate, reporting it as a value error.

    The gate is reused rather than reimplemented, and its refusal is converted from
    :class:`~dynamisbench.workspace.PathScopeError` into a ``ValueError`` for one reason:
    these rules are enforced by a Pydantic validator, and Pydantic turns a ``ValueError``
    into a validation failure while letting any other exception escape from inside a
    model. Escaping exceptions would mean a manifest containing a traversal path raised
    through the middle of ``model_validate_json`` instead of being rejected as an invalid
    manifest, so the verifier could not report it as a defect.

    The original refusal is chained, so the reference and the class that produced it are
    still on the error, and the message is carried across in full.
    """
    try:
        return validate_logical_reference(value)
    except PathScopeError as error:
        raise ValueError(f"a {kind} {value!r} is not usable: {error}") from error


def _validate_run_id(value: str) -> str:
    """Apply the project identifier convention, then the platform name gate.

    The pattern is the one every other DynamisBench identifier already uses, so a run id
    is safe to use verbatim as a path segment and as a stable artifact key. The pattern
    alone is not enough: it admits ``con``, ``nul`` and ``com1``, which are Windows device
    names and never files, so the RES-230 name gate is consulted as well. A run id that is
    a device name would be a directory that cannot be created on the primary platform and
    an ordinary directory everywhere else, which is exactly the portability split this
    package refuses to have.
    """
    _reject_control_and_whitespace(value, "run id")
    _platform_name_gate(value, "run id")
    if value in RESERVED_BUNDLE_FILE_NAMES:
        raise ValueError(f"{value!r} is a name the seal reserves for its own metadata")
    return value


RunId = Annotated[
    str,
    StringConstraints(pattern=IDENTIFIER_PATTERN, max_length=IDENTIFIER_MAX_LENGTH),
    AfterValidator(_validate_run_id),
]
"""A validated run identifier: the human/logical name of one run, never a digest."""


def _validate_bundle_relative_path(value: str) -> str:
    """Apply the platform reference gate, then the three bundle-content rules.

    Order matters. Traversal, drives, UNC prefixes, reserved device names and characters
    Windows cannot store are all decided by the workspace gate, because that gate is the
    one place in the project that decides them. What is left for this module is what makes
    a path *manifest data* rather than a workspace reference:

    * **one canonical spelling.** The value must already equal its normalized ``/`` form.
      Accepting ``a\\b`` and normalising it to ``a/b`` would let two spellings of one
      artifact be written into a manifest whose every other byte is canonical.
    * **no whitespace.** A checksum line is ``<64 hex><two spaces><path>``; refusing
      whitespace keeps that line parseable by any reader rather than only by a careful one,
      and matches the domain's own workspace-relative path rule.
    * **no seal metadata.** A manifest that listed ``manifest.json`` would be
      self-referential, and one that listed ``checksums.sha256`` would require that file to
      exist before it is written.
    """
    _reject_control_and_whitespace(value, "bundle-relative path")
    segments = _platform_name_gate(value, "bundle-relative path")
    if "/".join(segments) != value:
        raise ValueError(
            f"must already be the normalized '/' form of its own segments, not {value!r}"
        )
    if value in RESERVED_BUNDLE_FILE_NAMES:
        raise ValueError(f"{value!r} is written by the seal and cannot be a payload artifact")
    return value


BundleRelativePath = Annotated[str, AfterValidator(_validate_bundle_relative_path)]
"""A validated path of a payload artifact relative to its bundle root.

This is the only path type that enters a manifest, and therefore the only path that
becomes scientific data. It is a plain ``str`` at runtime so that canonical serialisation
and the checksum line need no conversion; the guarantee lives in the validator, which is
applied on every construction and on every manifest read.
"""

_RUN_ID_ADAPTER: Final = TypeAdapter(RunId)
_BUNDLE_RELATIVE_PATH_ADAPTER: Final = TypeAdapter(BundleRelativePath)


def parse_run_id(value: str) -> RunId:
    """Validate ``value`` as a run id at an API boundary.

    Public functions accept a ``RunId`` annotation, which is a ``str`` at runtime, so a
    caller that skipped the type checker must not be able to skip the naming rules too.

    :raises BundleNamingError: if the value is not a run id.
    """
    try:
        return _RUN_ID_ADAPTER.validate_python(value)
    except PydanticValidationError as error:
        raise BundleNamingError(f"{value!r} is not a run id: {error}") from error


def parse_bundle_relative_path(value: str) -> BundleRelativePath:
    """Validate ``value`` as a payload path relative to a bundle root.

    :raises BundleNamingError: if the value is not a bundle-relative path.
    """
    try:
        return _BUNDLE_RELATIVE_PATH_ADAPTER.validate_python(value)
    except PydanticValidationError as error:
        raise BundleNamingError(f"{value!r} is not a bundle-relative path: {error}") from error


_REPARSE_POINT_ATTRIBUTE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
"""The Windows reparse-point attribute, or zero on a platform that has no such concept."""


def is_link_or_reparse_point(path: Path) -> bool:
    """Whether ``path`` is any kind of filesystem indirection, on any platform.

    Three independent signals, because none of them alone is sufficient:

    * :meth:`pathlib.Path.is_symlink` — a POSIX symbolic link, and a Windows symbolic
      link.
    * :meth:`pathlib.Path.is_junction` — a Windows mount-point junction. This is the one
      that matters most here: ``is_symlink()`` reports a junction as *not* a link, so a
      symlink-only check is the ordinary way a sealed bundle ends up resolving its bytes
      somewhere outside itself on the authoritative platform.
    * ``FILE_ATTRIBUTE_REPARSE_POINT`` — the attribute behind both of the above, and also
      behind deduplicated extents, cloud placeholders and other filesystem-level
      indirections that are neither a symlink nor a junction yet still resolve elsewhere.
      It does not exist on POSIX, where it is therefore simply absent.

    A hard link is deliberately **not** reported. It is a second directory entry for bytes
    that are already inside the bundle rather than a redirection out of it, so both entries
    hash identically and the seal loses nothing by allowing it.

    A path that does not exist is not a link. The predicate is total so that a caller
    asking "is this an ordinary file?" before deciding what to do about a missing entry
    gets an answer instead of an exception, and absence is reported as absence rather than
    guessed at.
    """
    if path.is_symlink() or path.is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & _REPARSE_POINT_ATTRIBUTE)
