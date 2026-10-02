"""The staging bundle a run writes into, the inventory of what it holds, and the finalization
that turns one into a promoted sealed bundle.

A staging bundle is four things at once, and all four matter:

* **mutable** — this is the only place in the evidence root where the application writes
  payload, and :class:`StagingBundle` is the only way to do it;
* **incomplete** — a directory exists before its contents do, and an interruption leaves it
  that way;
* **non-authoritative** — a staging directory is never a run, whatever it is named
  (RES-231's invariant);
* **not disposable** — whether an interrupted run is sealed as a failure or discarded is a
  scientific decision, which is why RES-230 classed staging as mutable but not disposable
  and why nothing in this module deletes a staging *bundle*.

The handle is a class rather than a record because one piece of state is genuinely
per-process and genuinely needed: once finalization has begun, the bundle must stop
accepting payload. That is not a durable flag, not a file, and not a workflow state
machine. It is an attribute on an object the caller already holds, and it exists so that a
writer holding a stale reference cannot append to a bundle whose manifest is being written.
A second process opening the same directory is a different problem that this package does
not pretend to solve — finalization is defined to begin only after execution has yielded
the bundle over, and a filesystem watcher or a lock service would be a far larger
commitment than the authority asks for.

**Every payload write goes through the workspace resolver.** The target of a write is
computed as ``workspace.resolve(STAGING, f"{run_id}/{path}")``, so the containment proof is
the one RES-230 already makes and this module cannot forget to make. Nothing here builds a
path by hand, because a hand-built path is a second resolver and a second chance to be
wrong. The one place the package looks inside a bundle without the resolver is the
*inventory*, which enumerates from an already-proved bundle root; that is bundle-content
policy, which RES-231 owns, not path scoping, which RES-230 owns.

**Inventory is a snapshot, not a promise.** :func:`inventory_payload` reports each payload
file's path and size, in one deterministic order, and refuses a bundle that cannot be
described at all. It does not hash anything: hashing is the finalizer's step, and a snapshot
taken before hashing is exactly what lets a change between the two be *noticed* rather than
silently sealed. An empty bundle is not refused here — whether a run with no payload may be
sealed is the finalizer's judgement, made with the manifest in hand.

**Finalization is the only thing in this package that makes a run authoritative**, and it
runs in an order where every step can fail without anything looking sealed:

#. close the bundle to new payload, so the inventory cannot be invalidated from underfoot;
#. delete any leftover reserved temporary from a previous attempt — the one deletion here,
   and it can only ever remove a file the seal itself writes through;
#. take the inventory;
#. hash every payload file in bounded memory through RES-229, comparing each file's size
   against the inventory so a file that changed underneath the seal is refused rather than
   sealed ambiguously;
#. build and validate the manifest, write canonical ``manifest.json``, and compute the
   evidence digest from exactly those bytes;
#. write ``checksums.sha256`` covering payload plus manifest;
#. **verify the seal independently** — re-enumerate, re-parse, and re-hash from disk — and
   refuse to promote anything that does not verify;
#. create ``runs/`` if it is absent;
#. atomically rename the staging directory to ``runs/<run-id>``.

The two properties that make that order worth stating are: the digest is returned and never
written into the manifest it identifies, so the seal is not self-referential; and promotion
is a single same-filesystem rename, so a run becomes authoritative at one instant or not at
all. A failure anywhere before the rename leaves the staging bundle intact and diagnosable,
with ``runs/<run-id>`` never created — which is the guarantee that a failed seal attempt
cannot leave something that looks authoritative.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from dynamisbench.evidence.bundle import (
    CHECKSUMS_FILE_NAME,
    CHECKSUMS_TEMP_FILE_NAME,
    MANIFEST_FILE_NAME,
    MANIFEST_TEMP_FILE_NAME,
    RESERVED_BUNDLE_FILE_NAMES,
    BundleConflictError,
    BundleIntegrityError,
    BundleOperationError,
    BundleRelativePath,
    RunId,
    RunOutcome,
    is_link_or_reparse_point,
    parse_bundle_relative_path,
    parse_run_id,
    walk_bundle,
)
from dynamisbench.evidence.manifest import (
    EvidenceDigest,
    Manifest,
    ManifestEntry,
    canonical_manifest_bytes,
    evidence_digest_of_canonical_manifest_bytes,
    render_checksums,
)
from dynamisbench.evidence.sealed import verify_bundle_seal
from dynamisbench.identity import asset_sha256_of_file
from dynamisbench.workspace.authority import PersistenceClass
from dynamisbench.workspace.workspace import LogicalReference, Workspace, class_location_segments

__all__ = [
    "PayloadFile",
    "SealResult",
    "StagingBundle",
    "create_staging_bundle",
    "finalize_bundle",
    "inventory_payload",
]


@dataclass(frozen=True, slots=True)
class PayloadFile:
    """One payload file as it exists on disk, before it has been hashed.

    The size is part of the snapshot for a reason: the finalizer compares it against the
    size it observes while hashing, and the manifest's ``size_bytes`` is checked again
    during the independent verification pass. Two cheap comparisons catch a payload that
    changed underneath the seal without any of them being a substitute for the hash.
    """

    relative_path: BundleRelativePath
    size_bytes: int


def _payload_file(bundle: StagingBundle, relative_path: BundleRelativePath) -> Path:
    """Resolve a payload path to a file that is safe to open, or refuse.

    The path goes to the workspace resolver as ``<run-id>/<payload path>``, so it is scoped to
    the staging class and proved to be inside the staging root. That is the RES-230 containment
    check, reused rather than restated: this module never joins a validated relative path onto
    a root by hand.
    """
    path = parse_bundle_relative_path(relative_path)
    return bundle.workspace.resolve(PersistenceClass.STAGING, f"{bundle.run_id}/{path}")


class StagingBundle:
    """A mutable staging directory that a run writes payload into.

    Construct one with :func:`create_staging_bundle`, which creates the directory and
    proves it is where the workspace says staging lives. The object then offers exactly two
    ways to put bytes in — :meth:`write_payload` for a complete small artifact and
    :meth:`open_payload` for a stream large enough not to want in memory — and both are
    refused once :meth:`close_for_payload` has been called.

    There is deliberately no method that deletes anything. An abandoned staging directory
    is incomplete work whose fate is a scientific decision, so this package can classify
    one (see :mod:`dynamisbench.evidence.recovery`) but never remove one. A staging handle
    that could delete its own contents would make "the run was interrupted" and "the
    application cleaned up after itself" the same event.
    """

    __slots__ = ("_accepts_payload", "_path", "_reference", "_run_id", "_workspace")

    def __init__(
        self,
        workspace: Workspace,
        run_id: RunId,
        path: Path,
        reference: LogicalReference,
    ) -> None:
        self._workspace = workspace
        self._run_id = run_id
        self._path = path
        self._reference = reference
        self._accepts_payload = True

    @property
    def workspace(self) -> Workspace:
        """The workspace whose evidence root this bundle lives under."""
        return self._workspace

    @property
    def run_id(self) -> RunId:
        """The run's human/logical identity, which is never a digest."""
        return self._run_id

    @property
    def path(self) -> Path:
        """Where the bundle is right now.

        Operational state, and never scientific data: it is an absolute path on this
        machine. The portable name is :attr:`reference`, and it is that one which is
        stable across relocation and belongs in any read model.
        """
        return self._path

    @property
    def reference(self) -> LogicalReference:
        """The portable name ``.staging/<run-id>``, stable across relocation."""
        return self._reference

    @property
    def accepts_payload(self) -> bool:
        """Whether this handle still accepts new payload.

        False from the moment finalization begins, so a writer holding a stale reference
        cannot add a file to a bundle whose inventory has already been taken.
        """
        return self._accepts_payload

    def payload_inventory(self) -> tuple[PayloadFile, ...]:
        """Snapshot the payload this bundle currently holds.

        :raises BundleIntegrityError: if the bundle contains a link, a non-regular file, a
            name that cannot appear in a manifest, or a reserved seal name used as a
            directory.
        """
        return inventory_payload(self)

    def close_for_payload(self) -> None:
        """Stop accepting payload through this handle. Idempotent.

        Called by finalization before it takes the inventory. It is not a durable state:
        reopening the same directory with :func:`create_staging_bundle` is refused as a
        conflict, so a second handle to the same run cannot be obtained while this one
        exists or after it is sealed.
        """
        self._accepts_payload = False

    def _refuse_if_closed(self) -> None:
        if not self._accepts_payload:
            raise BundleConflictError(
                f"the staging bundle for run {self._run_id!r} is closed for payload writes; "
                "finalization has begun and its inventory is no longer a complete description "
                "of the bundle"
            )

    def _payload_target(self, relative_path: BundleRelativePath) -> Path:
        """Resolve a payload path to a file that is safe to open, or refuse."""
        return _payload_file(self, relative_path)

    def _payload_parent(self, relative_path: BundleRelativePath) -> Path:
        target = self._payload_target(relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BundleOperationError(
                f"the directory for payload {relative_path!r} could not be created: {error}"
            ) from error
        return target

    def write_payload(self, relative_path: BundleRelativePath, data: bytes) -> Path:
        """Write one complete payload artifact, creating its parent directories.

        The right call for metadata and small tables, where the whole artifact is in
        memory anyway. Larger evidence should use :meth:`open_payload`, because holding a
        multi-gigabyte Parquet file in memory to write it would be a way of losing a run.

        The bytes are flushed and closed but not fsynced. A durability barrier per artifact
        would cost a device flush for every file and would buy nothing the seal does not
        already re-verify; a power loss during a staging write is precisely the abandoned
        staging case, and it is handled by classification rather than by pretending the
        write was durable.

        :raises BundleConflictError: if the bundle is closed for payload.
        :raises BundleNamingError: if the path is not a payload path.
        :raises BundleOperationError: if the filesystem refuses the write.
        """
        self._refuse_if_closed()
        target = self._payload_parent(relative_path)
        try:
            with target.open("wb") as handle:
                handle.write(data)
        except OSError as error:
            raise BundleOperationError(
                f"payload {relative_path!r} could not be written: {error}"
            ) from error
        return target

    @contextmanager
    def open_payload(self, relative_path: BundleRelativePath) -> Iterator[BinaryIO]:
        """Open one payload artifact for streaming writes.

        The context manager exists so the handle cannot be left open — an open handle on
        Windows is an open handle that blocks the atomic promotion of the whole directory —
        and so a failure mid-stream closes the file rather than leaving a partial artifact
        that inventory would happily declare.

        :raises BundleConflictError: if the bundle is closed for payload.
        :raises BundleOperationError: if the filesystem refuses the write.
        """
        self._refuse_if_closed()
        target = self._payload_parent(relative_path)
        try:
            handle = target.open("wb")
        except OSError as error:
            raise BundleOperationError(
                f"payload {relative_path!r} could not be opened for writing: {error}"
            ) from error
        try:
            yield handle
        except OSError as error:
            raise BundleOperationError(
                f"payload {relative_path!r} could not be written: {error}"
            ) from error
        finally:
            handle.close()

    def __repr__(self) -> str:
        state = "open" if self._accepts_payload else "closed for payload"
        return f"<StagingBundle {self._reference.text!r} ({state})>"


def create_staging_bundle(workspace: Workspace, run_id: RunId) -> StagingBundle:
    """Create ``.staging/<run-id>/`` and return the handle that writes into it.

    The staging location itself is created if it is missing, so a caller does not have to
    initialize the workspace before it can start a run; the run directory is created, never
    adopted. A directory already sitting at ``.staging/<run-id>`` is a **conflict**, not an
    invitation to append: it may be a half-written bundle from an interrupted run, and
    silently reusing it would produce a manifest that describes two runs' work.

    The bundle root is checked for being a link *before* it is used, and the check is on
    the unresolved path. That ordering is what closes the last escape in this package: the
    workspace resolver dereferences a link, so a junction planted at ``.staging/<run-id>``
    would otherwise hand back a real directory somewhere else in the evidence root, and
    every subsequent containment check would then be measuring containment of the *target*
    rather than noticing that the name was redirected. A bundle that is not the directory
    its name denotes cannot be promoted to a directory that is.

    A run id that is **already sealed** is refused here, as well as at finalization. One run
    id is one execution and one sealed bundle, so re-staging a spent id would produce work
    that could only ever fail at promotion — and would be lost. Catching it here means the
    caller learns immediately that the id is taken, rather than after writing a whole run's
    evidence into a directory that can never become authoritative.

    :raises BundleNamingError: if ``run_id`` is not a run id.
    :raises BundleConflictError: if the staging location or the run directory already exists,
        or the run id is already sealed.
    :raises BundleOperationError: if a directory cannot be created.
    """
    run = parse_run_id(run_id)
    _refuse_existing_seal(workspace, run)
    staging_location = workspace.location(PersistenceClass.STAGING)
    try:
        staging_location.path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise BundleOperationError(f"the staging location could not be created: {error}") from error
    lexical = staging_location.path / run
    if lexical.exists() or lexical.is_symlink():
        if is_link_or_reparse_point(lexical):
            raise BundleConflictError(
                f"the staging path for run {run!r} is a link rather than a directory, so a "
                "bundle written there would not be the directory its name denotes"
            )
        raise BundleConflictError(
            f"a staging directory already exists for run {run!r}; it may be incomplete work "
            "from an interrupted execution, so it is not reused or overwritten"
        )
    path = workspace.resolve(PersistenceClass.STAGING, run)
    try:
        path.mkdir()
    except FileExistsError as error:
        raise BundleConflictError(
            f"a staging directory already exists for run {run!r}; it is not reused or overwritten"
        ) from error
    except OSError as error:
        raise BundleOperationError(
            f"the staging directory for run {run!r} could not be created: {error}"
        ) from error
    return StagingBundle(
        workspace,
        run,
        path,
        LogicalReference(PersistenceClass.STAGING, staging_location.reference.parts + (run,)),
    )


def inventory_payload(bundle: StagingBundle) -> tuple[PayloadFile, ...]:
    """Snapshot the payload of a staging bundle, in manifest order.

    The reserved seal names are excluded, because they are not payload: the manifest must
    not enumerate itself, and the checksum file must not hash itself. A reserved name that
    survives from a previous failed attempt is therefore invisible here — which is why
    finalization removes those leftovers *before* it calls this, and why a caller who wants
    to know about them asks
    :mod:`dynamisbench.evidence.recovery` rather than reading this list.

    Ordering is by the relative path's UTF-8 bytes, which is the same comparator the
    manifest and the checksum file use. Fixing it here rather than at serialisation time
    means the snapshot, the manifest, and the checksum file cannot disagree about order, and
    a byte comparison is not affected by the case rules of the filesystem underneath.

    :raises BundleIntegrityError: if the bundle cannot be described.
    """
    entries = walk_bundle(bundle.path)
    return tuple(
        PayloadFile(
            relative_path=parse_bundle_relative_path(entry.relative_path),
            size_bytes=entry.path.lstat().st_size,
        )
        for entry in entries
        if not entry.is_directory and entry.relative_path not in RESERVED_BUNDLE_FILE_NAMES
    )


@dataclass(frozen=True, slots=True)
class SealResult:
    """What a successful finalization produced.

    The run id is the human identity and the evidence digest is the cryptographic one; both are
    present because both are needed and neither replaces the other. ``reference`` is the
    portable name ``runs/<run-id>`` and ``path`` is where that name happens to live right now,
    the same split the workspace draws, so a read model can carry a sealed run across machines
    and a caller opening its files can use the path.
    """

    run_id: RunId
    reference: LogicalReference
    path: Path
    manifest: Manifest
    evidence_digest: EvidenceDigest


def _discard_leftover_seal_temporaries(bundle_root: Path) -> None:
    """Remove the two reserved temporary names, which are the seal's own leftovers.

    This is the only deletion in the package, and it is deliberately narrow: a reserved
    temporary is written by the seal, is excluded from payload by construction, and is never
    authoritative, so removing it cannot destroy evidence. It is done *before* the inventory
    so that a retry after an interrupted seal attempt is possible, and it is a removal of
    named files rather than of anything a caller wrote.

    A failure here is an operation error rather than a silent skip, because a temporary that
    cannot be removed would then be hashed into the manifest as if it were evidence.
    """
    for name in (MANIFEST_TEMP_FILE_NAME, CHECKSUMS_TEMP_FILE_NAME):
        temp = bundle_root / name
        if not temp.exists():
            continue
        try:
            temp.unlink()
        except OSError as error:
            raise BundleOperationError(
                f"the leftover seal temporary {name!r} could not be removed, so this bundle "
                f"cannot be sealed cleanly: {error}"
            ) from error


def _refuse_reserved_directories(bundle_root: Path) -> None:
    """Refuse a bundle holding a directory where the seal must write a file.

    Checked before the manifest is built rather than being left to the rename, so the failure
    names the cause instead of surfacing as an opaque filesystem error at the last step — by
    which point a manifest has been written and then abandoned.
    """
    for name in (MANIFEST_FILE_NAME, CHECKSUMS_FILE_NAME):
        if (bundle_root / name).is_dir():
            raise BundleIntegrityError(
                f"the bundle holds a directory named {name!r}, which the seal must write as a "
                "file, so this bundle cannot be sealed"
            )


def _hash_payload(
    bundle: StagingBundle, inventory: tuple[PayloadFile, ...]
) -> tuple[ManifestEntry, ...]:
    """Hash every inventoried payload file, refusing any that changed under the seal.

    Hashing streams in bounded memory through RES-229's ``asset_sha256_of_file``, so a
    multi-gigabyte Parquet table is sealed without being loaded. The size observed while
    hashing is compared against the size the inventory recorded: a file that grew or shrank
    between the snapshot and the hash is refused rather than sealed with a digest and a size
    that were never true at the same moment.

    Comparing sizes is the *only* cross-check the inventory supports, because the inventory
    records no digest. A writer could still replace a file with one of identical length, and
    that is why finalization re-verifies the whole seal from disk afterwards. The guarantee
    here is therefore "a change is detected where reasonably possible", not "the bundle is
    locked" — no watcher and no lock service is introduced, because finalization begins only
    after execution has yielded the bundle over and a stronger claim would not be honest.

    The digest and the size come from the same file, measured once, so the two facts recorded
    in the manifest are consistent with each other.
    """
    entries: list[ManifestEntry] = []
    for item in inventory:
        target = _payload_file(bundle, item.relative_path)
        try:
            observed = target.lstat().st_size
            digest = asset_sha256_of_file(target)
        except OSError as error:
            raise BundleOperationError(
                f"payload {item.relative_path!r} could not be hashed: {error}"
            ) from error
        if observed != item.size_bytes:
            raise BundleIntegrityError(
                f"payload {item.relative_path!r} changed size between the inventory and the "
                f"hash ({item.size_bytes} then {observed} bytes), so sealing it would record an "
                "ambiguous result"
            )
        entries.append(
            ManifestEntry(
                relative_path=item.relative_path,
                sha256=digest.hex,
                size_bytes=observed,
            )
        )
    return tuple(entries)


def _write_atomically(path: Path, data: bytes, temporary: str, what: str) -> None:
    """Write seal metadata through a reserved temporary and rename it into place.

    A partially written ``manifest.json`` must never be visible under its own name, because a
    reader that found one would have a file that is neither the old manifest nor the new one
    and no way to tell. Writing to a reserved name and renaming means the final name only ever
    holds complete content: before the rename the previous state is intact, after it the new
    state is intact, and there is no instant in between.

    ``os.replace`` is used rather than a plain rename because it is specified to replace an
    existing file atomically on both platforms. The temporary is cleaned up on failure, so a
    failed attempt leaves the bundle with no debris beyond what the next attempt already knows
    how to remove.
    """
    temp = path.parent / temporary
    try:
        with temp.open("wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except OSError as error:
        try:
            temp.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - the original failure is the one to report
            pass
        raise BundleOperationError(f"{what} could not be written: {error}") from error


def _sealed_destination(workspace: Workspace, run: RunId) -> Path:
    """The location a sealed run of this id would occupy, whether or not it exists."""
    return workspace.resolve(PersistenceClass.SEALED_EVIDENCE, run)


def _refuse_existing_seal(workspace: Workspace, run: RunId) -> None:
    """Refuse to seal a run whose id is already taken by sealed evidence.

    Checked twice on purpose. It runs at the very start of finalization, so a duplicate
    attempt never writes a manifest into staging and then discovers the conflict — the
    caller's bundle is left exactly as it was handed over. It runs again immediately before
    the rename, because between the two something else could have claimed the name, and the
    guarantee that matters is that the rename never overwrites. A single check at either end
    would leave one of the two windows open.

    :raises BundleConflictError: if ``runs/<run-id>`` exists. Sealed evidence is never
        replaced, merged into, deleted, or appended to, so a duplicate run id fails rather
        than resolving itself.
    """
    destination = _sealed_destination(workspace, run)
    if destination.exists() or destination.is_symlink():
        raise BundleConflictError(
            f"run {run!r} is already sealed as {destination.name}/; sealed evidence is never "
            "overwritten, merged into, or replaced, so this run id is spent"
        )


def finalize_bundle(bundle: StagingBundle, outcome: RunOutcome) -> SealResult:
    """Seal a staging bundle and promote it to ``runs/<run-id>``.

    The run outcome is a parameter rather than something read from the bundle, because it is
    the caller's judgement about what happened and there is no file in the bundle that can
    state it authoritatively — the failure record a failed run carries is payload, hashed and
    versioned like any other, and this is the one seal-level fact that only the supervisor
    knows. ``RunOutcome.FAILED`` is a first-class outcome: a run whose failure record is
    complete is sealed as authoritative evidence *of that failure*, which is a different and
    equally important fact from a staging directory that never produced a record at all.

    **Sealed evidence is never overwritten.** If ``runs/<run-id>`` already exists, this raises
    :class:`BundleConflictError` before touching anything. It does not replace the directory,
    merge into it, delete it, or append to it, and a second finalization of the same run fails
    the same way — so there is no path by which calling this twice quietly produces a
    different result than calling it once.

    :raises BundleConflictError: if the destination already exists, or the bundle is empty.
    :raises BundleIntegrityError: if the bundle cannot be described, or a payload changed
        while it was being sealed, or the independently written seal does not verify.
    :raises BundleOperationError: if a filesystem step fails. The staging bundle is left in
        place and diagnosable, and ``runs/<run-id>`` is not created.
    """
    run = parse_run_id(bundle.run_id)
    _refuse_existing_seal(bundle.workspace, run)
    bundle.close_for_payload()
    _discard_leftover_seal_temporaries(bundle.path)
    _refuse_reserved_directories(bundle.path)

    inventory = inventory_payload(bundle)
    if not inventory:
        raise BundleConflictError(
            f"run {run!r} has no payload to seal; an empty bundle would give a run an identity "
            "with nothing behind it, and a run that produced no record is not evidence of "
            "anything"
        )
    entries = _hash_payload(bundle, inventory)

    manifest = Manifest(run_id=run, outcome=outcome, files=entries)
    canonical = canonical_manifest_bytes(manifest)
    evidence_digest = evidence_digest_of_canonical_manifest_bytes(canonical)
    checksums = render_checksums(manifest, canonical)
    _write_atomically(
        bundle.path / MANIFEST_FILE_NAME, canonical, MANIFEST_TEMP_FILE_NAME, MANIFEST_FILE_NAME
    )
    _write_atomically(
        bundle.path / CHECKSUMS_FILE_NAME,
        checksums,
        CHECKSUMS_TEMP_FILE_NAME,
        CHECKSUMS_FILE_NAME,
    )

    verification = verify_bundle_seal(bundle.path, run, expected_evidence_digest=evidence_digest)
    if not verification.is_valid or verification.bundle is None:
        raise BundleIntegrityError(
            "the seal this finalization just wrote does not verify, so nothing was promoted: "
            + "; ".join(str(defect) for defect in verification.defects)
        )

    destination = _promote(bundle, run)
    return SealResult(
        run_id=run,
        reference=LogicalReference(
            PersistenceClass.SEALED_EVIDENCE,
            class_location_segments(PersistenceClass.SEALED_EVIDENCE) + (run,),
        ),
        path=destination,
        manifest=verification.bundle.manifest,
        evidence_digest=evidence_digest,
    )


def _promote(bundle: StagingBundle, run: RunId) -> Path:
    """Create ``runs/`` if needed, then move the sealed staging bundle into it atomically.

    The destination parent is created immediately before the rename, because a rename cannot
    create one. Creating it is not itself a sealed event: an empty ``runs/`` holds no
    authority, and the first bundle to arrive is the one that becomes authoritative. RES-230
    leaves ``runs/`` uncreated on purpose, and this is where that decision ends.

    The move is a single ``os.replace`` of a directory, which is a same-filesystem rename
    because ``.staging/`` and ``runs/`` are both under the evidence root. That is what makes
    promotion atomic: a run becomes authoritative at one instant, and there is no window in
    which a partially copied bundle is visible under ``runs/``.

    The destination is checked *before* the rename and refused if it exists. On Windows
    ``os.replace`` would itself fail rather than overwrite a directory, but the explicit check
    is what makes the behaviour identical on every platform and what produces a diagnostic
    that says the run is already sealed instead of an opaque filesystem error. The same check
    also ran at the start of finalization; repeating it here is what closes the window between
    the two.

    :raises BundleConflictError: if ``runs/<run-id>`` already exists. Sealed evidence is never
        replaced, merged into, or deleted.
    :raises BundleOperationError: if the parent cannot be created or the rename fails. The
        staging bundle is left in place, so the attempt stays diagnosable and retryable.
    """
    runs_root = bundle.workspace.location(PersistenceClass.SEALED_EVIDENCE).path
    try:
        runs_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise BundleOperationError(
            f"the sealed evidence location could not be created: {error}"
        ) from error
    _refuse_existing_seal(bundle.workspace, run)
    destination = _sealed_destination(bundle.workspace, run)
    try:
        os.replace(bundle.path, destination)
    except OSError as error:
        raise BundleOperationError(
            f"the sealed bundle for run {run!r} could not be promoted into the evidence "
            f"location: {error}"
        ) from error
    if bundle.path.exists():  # pragma: no cover - defensive
        raise BundleOperationError(
            f"the staging directory for run {run!r} still exists after promotion"
        )
    return destination
