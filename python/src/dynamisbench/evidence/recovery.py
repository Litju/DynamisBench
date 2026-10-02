"""Finding the staging directories an interrupted run left behind, and classifying them.

An interrupted run leaves a directory in ``.staging/``, and what that directory *is* depends
on how far it got. Four states are distinguishable from the directory's own contents alone,
and telling them apart is the difference between resuming work, promoting a finished seal,
and cleaning up a mess:

* ``EMPTY`` — the directory exists and holds nothing. A run that was created and then died.
* ``IN_PROGRESS`` — payload and no seal metadata. The ordinary interrupted run.
* ``INTERRUPTED_SEAL`` — seal metadata is present but does not verify. A run whose manifest was
  written, or half-written, and whose finalization did not finish.
* ``SEALED_IN_STAGING`` — a complete, valid seal sitting in ``.staging/``. Finalization
  finished and the promotion did not, or was refused. This is *not* an authoritative run —
  authority means being under ``runs/`` — but it is a valid seal that can be promoted, which
  makes it the one state where the right action is obvious.

**No clock.** There is no age threshold anywhere in this module, and there will not be one.
"Older than 24 hours" is not a scientific fact: a run on a slow machine can legitimately be
older than a fast one, a laptop can sleep for a day mid-run, and a workspace can be archived
and reopened. A wall-clock heuristic would let a cleanup routine delete the record of what
happened to an interrupted run, and RES-230 classed staging as *not disposable* for exactly
that reason. What is a fact is *which runs the caller says are active* — so that is an
argument, and a staging directory not associated with active work is reported as a recovery
candidate and nothing more.

**Discovery never deletes and never repairs.** It reports. Cleaning up abandoned staging is a
decision made by a person or a policy that knows what the run was for, and this package has no
opinion about it. It also does not touch ``derived/``, ``cache/`` or ``tmp/``: those are
disposable by declaration and a run that swept them would be doing something the persistence
classes explicitly forbid it from doing.

**A directory it cannot read is reported, not raised.** Recovery is exactly when something is
wrong with the evidence root, so a discovery pass that crashed on the first surprise would be
useless precisely when it is needed. A directory whose name is not a valid run id, or whose
contents cannot be classified, appears in the report as an unrecognised entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dynamisbench.evidence.bundle import (
    CHECKSUMS_TEMP_FILE_NAME,
    MANIFEST_TEMP_FILE_NAME,
    SEAL_FILE_NAMES,
    BundleIntegrityError,
    BundleNamingError,
    RunId,
    is_link_or_reparse_point,
    parse_run_id,
    walk_bundle,
)
from dynamisbench.evidence.sealed import SealedBundle, verify_bundle_seal
from dynamisbench.workspace.authority import PersistenceClass
from dynamisbench.workspace.workspace import LogicalReference, Workspace, class_location_segments

__all__ = [
    "StagingCandidate",
    "StagingReport",
    "StagingState",
    "discover_staging",
]

SEAL_TEMP_FILE_NAMES = frozenset({MANIFEST_TEMP_FILE_NAME, CHECKSUMS_TEMP_FILE_NAME})
"""The reserved temporary names, which mean a finalization was interrupted mid-write.

Named at module level rather than rebuilt at each use so the "did a seal start?" question has
one answer in this module, matching the sealed-bundle check that reports the same names as
``SEAL_DEBRIS``.
"""


class StagingState(StrEnum):
    """How far one staging directory got, decided by its contents and nothing else.

    Every value is a function of the directory's own bytes, so two passes over an unchanged
    workspace always agree. None of them is a judgement about whether the run should be kept:
    that is a scientific decision this package reports on and does not make.
    """

    EMPTY = "empty"
    """The directory exists and holds no files at all."""

    IN_PROGRESS = "in_progress"
    """Payload is present and no seal metadata has been written."""

    INTERRUPTED_SEAL = "interrupted_seal"
    """Seal metadata is present but does not verify, so a finalization did not complete."""

    SEALED_IN_STAGING = "sealed_in_staging"
    """A complete, valid seal that has not been promoted, and is therefore not yet a run."""


@dataclass(frozen=True, slots=True)
class StagingCandidate:
    """One staging directory, classified.

    ``active`` is the caller's statement that this run is still in progress, and
    ``recovery_candidate`` is the consequence: a directory that is not active and holds
    something worth a human's attention. Both are derived from the supplied active set and the
    directory's own contents — never from a clock, so a report is reproducible.

    ``seal`` is populated only for :attr:`StagingState.SEALED_IN_STAGING`, where a complete
    valid seal exists that could be promoted. It is ``None`` for every other state, including
    an interrupted one: a half-written manifest is not a seal and is not offered as one.
    """

    run_id: RunId
    reference: LogicalReference
    path: Path
    state: StagingState
    active: bool
    payload_files: int
    seal: SealedBundle | None = None

    @property
    def recovery_candidate(self) -> bool:
        """Whether this directory is not associated with active work and holds something.

        A directory with nothing in it is not a recovery candidate: there is no work to
        recover and no decision to make about it. Everything else that is not active is.
        """
        return not self.active and self.state is not StagingState.EMPTY


@dataclass(frozen=True, slots=True)
class StagingReport:
    """What a discovery pass found, in a stable order.

    ``candidates`` is ordered by run id's UTF-8 bytes, so two passes over an unchanged
    workspace produce equal reports and a diff between them is meaningful. ``unrecognised``
    holds directory names that are not valid run ids, or that could not be classified; they are
    reported rather than raising, because recovery is when something is wrong and a discovery
    pass that crashed on the first surprise would be useless exactly then.
    """

    candidates: tuple[StagingCandidate, ...]
    unrecognised: tuple[str, ...] = ()

    @property
    def active(self) -> tuple[StagingCandidate, ...]:
        """Directories the caller said are still in progress."""
        return tuple(candidate for candidate in self.candidates if candidate.active)

    @property
    def recovery_candidates(self) -> tuple[StagingCandidate, ...]:
        """Directories that are not active and hold something, in report order."""
        return tuple(candidate for candidate in self.candidates if candidate.recovery_candidate)

    @property
    def promotable(self) -> tuple[StagingCandidate, ...]:
        """Directories holding a complete valid seal that was never promoted.

        The one state where the next action is not a judgement: the seal is already written
        and verified, and all that is missing is the rename that makes it a run.
        """
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.state is StagingState.SEALED_IN_STAGING
        )

    def __bool__(self) -> bool:
        """Whether anything at all needs attention."""
        return bool(self.candidates or self.unrecognised)


def _classify(bundle_root: Path, run: RunId) -> tuple[StagingState, int, SealedBundle | None]:
    """Decide a staging directory's state from its contents alone.

    The order of the questions is the design. Existence of a *complete, valid* seal is asked
    first, because a valid seal is the only state from which a run becomes authoritative by
    promotion. Only if that fails does the presence of any seal metadata at all matter, and
    only then does the payload count. A directory that is not there yields
    :attr:`StagingState.EMPTY` rather than raising, so a name that vanished mid-pass is simply
    not a candidate.

    :raises BundleIntegrityError: if the directory holds a link, an irregular file, or a name
        that cannot appear in a manifest — all of which mean it cannot be classified *and*
        cannot be sealed, which the caller needs to see.
    """
    if not bundle_root.is_dir():
        return StagingState.EMPTY, 0, None
    entries = walk_bundle(bundle_root)
    files = frozenset(entry.relative_path for entry in entries if not entry.is_directory)
    payload = files - SEAL_FILE_NAMES
    if not files:
        return StagingState.EMPTY, 0, None
    if SEAL_FILE_NAMES <= files:
        verification = verify_bundle_seal(bundle_root, run)
        if verification.is_valid and verification.bundle is not None:
            return StagingState.SEALED_IN_STAGING, len(payload), verification.bundle
    if files & SEAL_FILE_NAMES or files & SEAL_TEMP_FILE_NAMES:
        return StagingState.INTERRUPTED_SEAL, len(payload), None
    return StagingState.IN_PROGRESS, len(payload), None


def discover_staging(
    workspace: Workspace, *, active_run_ids: Iterable[RunId] = ()
) -> StagingReport:
    """Classify every staging directory in ``workspace``, without changing any of them.

    ``active_run_ids`` is the caller's knowledge — the runs this process is currently working
    on, or the set a recovery context can prove is live. It is the *only* input that decides
    whether a directory belongs to active work, and it is supplied rather than inferred,
    because the alternative is a wall-clock age heuristic, and an age heuristic is not a
    scientific fact: a slow run can be older than a fast one, a machine can sleep for a day
    mid-run, and an archive can be reopened. Given the active set, everything else is a
    function of the directories' own contents, so the report is reproducible.

    Nothing is deleted, moved, or repaired. A recovery candidate is a report entry, and what
    to do about it is a decision about what the run was for — which is exactly why staging is
    mutable but not disposable.

    Only ``.staging/`` is enumerated. ``derived/``, ``cache/`` and ``tmp/`` are disposable by
    declaration and are never swept here, because a routine that could reach them would be a
    routine that could delete a DuckDB projection or scratch space on the same pass.

    :param active_run_ids: run ids the caller knows are still in progress. An id that names no
        staging directory is simply unused.
    """
    active = {parse_run_id(run_id) for run_id in active_run_ids}
    staging_root = workspace.location(PersistenceClass.STAGING).path
    if not staging_root.is_dir():
        return StagingReport(candidates=(), unrecognised=())

    classified: list[StagingCandidate] = []
    unrecognised: list[str] = []
    for child in sorted(staging_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or is_link_or_reparse_point(child):
            unrecognised.append(child.name)
            continue
        try:
            run = parse_run_id(child.name)
        except BundleNamingError:
            unrecognised.append(child.name)
            continue
        try:
            state, payload_files, seal = _classify(child, run)
        except BundleIntegrityError:
            unrecognised.append(child.name)
            continue
        classified.append(
            StagingCandidate(
                run_id=run,
                reference=LogicalReference(
                    PersistenceClass.STAGING,
                    class_location_segments(PersistenceClass.STAGING) + (run,),
                ),
                path=child,
                state=state,
                active=run in active,
                payload_files=payload_files,
                seal=seal,
            )
        )
    return StagingReport(
        candidates=tuple(sorted(classified, key=lambda item: item.run_id.encode("utf-8"))),
        unrecognised=tuple(sorted(unrecognised)),
    )
