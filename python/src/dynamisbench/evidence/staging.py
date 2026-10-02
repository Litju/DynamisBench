"""The staging bundle a run writes into, and the inventory of what it holds.

A staging bundle is four things at once, and all four matter:

* **mutable** — this is the only place in the evidence root where the application writes
  payload, and :class:`StagingBundle` is the only way to do it;
* **incomplete** — a directory exists before its contents do, and an interruption leaves it
  that way;
* **non-authoritative** — a staging directory is never a run, whatever it is named
  (RES-231's invariant);
* **not disposable** — whether an interrupted run is sealed as a failure or discarded is a
  scientific decision, which is why RES-230 classed staging as mutable but not disposable
  and why nothing in this module deletes anything.

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
*inventory*, which enumerates from an already-proved bundle root; that is
bundle-content policy, which RES-231 owns, not path scoping, which RES-230 owns.

**Inventory is a snapshot, not a promise.** :func:`inventory_payload` reports each payload
file's path and size, in one deterministic order, and refuses a bundle that cannot be
described at all. It does not hash anything: hashing is the finalizer's step, and a
snapshot taken before hashing is exactly what lets a change between the two be *noticed*
rather than silently sealed. An empty bundle is not refused here — whether a run with no
payload may be sealed is the finalizer's judgement, made with the manifest in hand.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from dynamisbench.evidence.bundle import (
    RESERVED_BUNDLE_FILE_NAMES,
    BundleConflictError,
    BundleOperationError,
    BundleRelativePath,
    RunId,
    is_link_or_reparse_point,
    parse_bundle_relative_path,
    parse_run_id,
    walk_bundle,
)
from dynamisbench.workspace.authority import PersistenceClass
from dynamisbench.workspace.workspace import LogicalReference, Workspace

__all__ = [
    "PayloadFile",
    "StagingBundle",
    "create_staging_bundle",
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
        """Resolve a payload path to a file that is safe to open, or refuse.

        The path goes to the workspace resolver as ``<run-id>/<payload path>``, so it is
        scoped to the staging class and proved to be inside the staging root. That is the
        RES-230 containment check, reused rather than restated: this module never joins a
        validated relative path onto a root by hand.
        """
        path = parse_bundle_relative_path(relative_path)
        return self._workspace.resolve(PersistenceClass.STAGING, f"{self._run_id}/{path}")

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

    :raises BundleNamingError: if ``run_id`` is not a run id.
    :raises BundleConflictError: if the staging location or the run directory already exists.
    :raises BundleOperationError: if a directory cannot be created.
    """
    run = parse_run_id(run_id)
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
