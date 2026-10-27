"""Supervise one isolated worker subprocess with bounded I/O, time and cancellation.

This is the only module in the project that starts a scientific worker. It is deliberately
engine-independent: it knows how to launch a fixed vector, deliver one protocol request,
read one bounded response, enforce a deadline, cancel, terminate a process tree and reap it.
It does not import or construct a simulator, and it never decides what a worker's output
means scientifically.

The guarantees, in the order they matter:

**No shell, ever.** The command is ``[program, *arguments]`` with ``shell=False`` and an
absolute program. A run input cannot add an argument, change the program, choose a working
directory, or influence the environment beyond what the selected manifest declared.

**Admission is re-derived at launch.** The supervisor does not trust the mutable object that
carries a preflight decision. It recomputes the request digest, the RunSpec fingerprint, the
accepted plan, the realization and environment identities, the adapter, the capability sets
and the asset content identities immediately before creating staging and again immediately
before starting the program.

**Bounded in both directions.** The request is canonical JSON at most
:data:`~dynamisbench.execution.contracts.MAX_WORKER_MESSAGE_BYTES`; stdout is read into at
most that many bytes and an overflow kills the process; stderr is retained up to the
environment's ``max_log_bytes`` and every further byte is discarded rather than buffered.
The request is delivered by a bounded writer thread, so a worker that never reads stdin
cannot block the supervisor past its deadline or ignore cancellation.

**One deadline, one cancellation path.** Timeout and cancellation both end in the same
process-tree termination path. Windows owns the worker in a Job Object; POSIX owns it by
session/process group. Cleanup is verified against the tree primitive, not inferred from
reaping the direct child, and it also runs when the direct child exits early.

**Completion is a process fact, not a scientific one.** A run is ``COMPLETED`` only when
the worker wrote a valid response for this exact request and exited zero. Every other
outcome — abnormal exit, protocol violation, timeout, cancellation, oversized output — is
a failure state. A failed or partial run never becomes sealed evidence here: the supervisor
writes ``diagnostics.json`` into the mutable staging bundle, closes it for payload and
returns. Sealing remains the evidence layer's transaction (ADR-008), but the returned
:class:`SupervisedExecution` derives the only admissible outcome from the verified
terminal observation, so a failed or cancelled run cannot be handed to the finalizer as a
success.

**The sealable handle is a capability, not a record.** The supervisor-authored terminal
observation and the staging bundle it was written into are bound together when the handle
is created, and neither can be rebound through ordinary attribute assignment, deletion or
``dataclasses.replace``. ``finalize`` re-reads and validates the persisted
``diagnostics.json`` against that exact observation — run id, execution fingerprint,
environment, adapter, terminal state and refusals — before deriving the outcome and
delegating to ADR-008. This is an in-process integrity boundary, not cryptographic
authentication: a caller that deliberately uses ``object.__setattr__``, ``ctypes``, a
debugger, or edits the mutable staging directory outside this object is outside the
supported API. ADR-008's inventory and hashing record whatever payload is actually
promoted at seal time, and only an externally trusted evidence digest can establish
authenticity against an actor able to rewrite the whole bundle.

The only payload the supervisor writes is that diagnostic record and a bounded stderr log.
It never writes ``native/``, ``canonical/`` or ``assessment.json``; producing those is a
later adapter/normalization/evaluation responsibility, and fabricating them here would be
a false scientific claim.
"""

from __future__ import annotations

import os
import queue
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Final, final

from dynamisbench.evidence.bundle import (
    BundleConflictError,
    EvidenceError,
    RunId,
    RunOutcome,
    is_link_or_reparse_point,
)
from dynamisbench.evidence.staging import (
    SealResult,
    StagingBundle,
    create_staging_bundle,
    finalize_bundle,
)
from dynamisbench.execution._process_tree import (
    PosixProcessTree,
    ProcessTree,
    attach_windows_job,
    create_windows_job,
    windows_creation_flags,
)
from dynamisbench.execution.contracts import (
    MAX_WORKER_MESSAGE_BYTES,
    ExecutionDiagnostic,
    ExecutionError,
    ExecutionResult,
    Refusal,
    RefusalCode,
    RunLifecycleState,
    WorkerProtocolError,
    WorkerRequest,
    WorkerResponse,
    WorkerStatus,
    canonical_worker_request_bytes,
    parse_worker_response,
    refusal,
    seal_outcome_for,
    staging_locator_for,
)
from dynamisbench.execution.environment import (
    WorkerEnvironmentError,
    WorkerEnvironmentManifest,
    resolved_worker_program,
    worker_environment,
)
from dynamisbench.execution.preflight import (
    PreflightedRun,
    PreflightRefusedError,
    admission_refusals,
)
from dynamisbench.identity import canonical_semantic_bytes
from dynamisbench.workspace import PersistenceClass, Workspace

__all__ = [
    "ExecutionSealError",
    "LifecycleObserver",
    "SupervisedExecution",
    "execute_preflighted",
]

LifecycleObserver = Callable[[RunLifecycleState], None]
"""A caller's view of the lifecycle transitions the supervisor observed.

The observer is diagnostic. It cannot change the outcome, and an exception it raises is
swallowed rather than allowed to strand a running worker. It is delivered on a dedicated
daemon thread, so a callback that blocks or never returns cannot delay the deadline,
cancellation, process-tree termination, reaping or cleanup.
"""

_READ_CHUNK_BYTES: Final = 64 * 1024
_POLL_INTERVAL_SECONDS: Final = 0.02
_TERMINATION_GRACE_SECONDS: Final = 5.0
_JOIN_SECONDS: Final = 5.0
_OBSERVER_CLOSE_SECONDS: Final = 1.0
_OBSERVER_STOP: Final = object()
_DIAGNOSTIC_PAYLOAD: Final = "diagnostics.json"
_WORKER_LOG_PAYLOAD: Final = "logs/worker.stderr.txt"


class _LifecycleObserverDispatcher:
    """Deliver lifecycle transitions off the supervisor thread, in observed order.

    One queue and one daemon consumer are enough because every transition is produced by the
    supervisor alone. The dispatcher closes with a bounded join: if a callback is still
    blocked, only this daemon thread remains, never a running worker, an unreaped child or an
    unfinished cleanup. Queueing also preserves ordering, so an observer sees the same
    sequence it would have seen synchronously.
    """

    __slots__ = ("_observer", "_queue", "_thread")

    def __init__(self, observer: LifecycleObserver | None) -> None:
        self._observer = observer
        self._queue: queue.SimpleQueue[RunLifecycleState | object] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        if observer is not None:
            self._thread = threading.Thread(
                target=self._deliver,
                name="dynamisbench-lifecycle-observer",
                daemon=True,
            )
            self._thread.start()

    def notify(self, state: RunLifecycleState) -> None:
        """Queue one transition without waiting for the observer to accept it."""
        if self._thread is None:
            return
        self._queue.put(state)

    def close(self, timeout: float) -> None:
        """Ask the consumer to finish, waiting at most ``timeout`` seconds."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._queue.put(_OBSERVER_STOP)
        thread.join(timeout)

    def _deliver(self) -> None:
        observer = self._observer
        if observer is None:
            return
        while True:
            state = self._queue.get()
            if state is _OBSERVER_STOP:
                return
            assert isinstance(state, RunLifecycleState)
            try:
                observer(state)
            except Exception:
                # A view of the lifecycle is not allowed to break the lifecycle.
                continue


class ExecutionSealError(ExecutionError):
    """A supervised execution may not be sealed with the requested outcome.

    The execution boundary does not seal. It hands the evidence layer a bundle together
    with the only outcome the supervisor observed, and refuses before delegating when a
    caller asks for a different one. The sealed-bundle transaction itself remains ADR-008's.
    """


def _read_persisted_diagnostic(bundle: StagingBundle) -> ExecutionDiagnostic:
    """Read and validate the exact terminal record the supervisor persisted.

    The record is read through the workspace resolver, refused unless it is one regular,
    self-contained file, bounded in size, parsed with the same model the supervisor wrote,
    and required to be in canonical form. Canonicality distinguishes the bytes this
    supervisor writes from a same-looking record assembled by another writer: the
    supervisor always stores ``canonical_semantic_bytes(diagnostic)``.

    :raises ExecutionSealError: if the record is absent, unreadable, not a regular file, too
        large, not a valid diagnostic, or not in canonical form.
    """
    run = bundle.run_id
    path = bundle.workspace.resolve(PersistenceClass.STAGING, f"{run}/{_DIAGNOSTIC_PAYLOAD}")
    try:
        info = path.lstat()
    except OSError as error:
        raise ExecutionSealError(
            f"run {run!r} has no readable persisted {_DIAGNOSTIC_PAYLOAD}; a run whose "
            "terminal record was removed or never written cannot be sealed"
        ) from error
    if is_link_or_reparse_point(path) or not stat.S_ISREG(info.st_mode):
        raise ExecutionSealError(
            f"run {run!r} has a persisted {_DIAGNOSTIC_PAYLOAD} that is not one regular "
            "self-contained file, so it cannot be trusted as this supervisor's terminal record"
        )
    if info.st_nlink > 1:
        raise ExecutionSealError(
            f"run {run!r} has a persisted {_DIAGNOSTIC_PAYLOAD} with more than one "
            "filesystem link, so another pathname could rewrite the record behind this run"
        )
    if info.st_size > MAX_WORKER_MESSAGE_BYTES:
        raise ExecutionSealError(
            f"run {run!r} has a persisted {_DIAGNOSTIC_PAYLOAD} of {info.st_size} bytes, "
            f"larger than the {MAX_WORKER_MESSAGE_BYTES}-byte protocol bound"
        )
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_WORKER_MESSAGE_BYTES + 1)
    except OSError as error:
        raise ExecutionSealError(
            f"run {run!r} has a persisted {_DIAGNOSTIC_PAYLOAD} that could not be read"
        ) from error
    if len(raw) > MAX_WORKER_MESSAGE_BYTES:
        raise ExecutionSealError(
            f"run {run!r} has a persisted {_DIAGNOSTIC_PAYLOAD} larger than the "
            f"{MAX_WORKER_MESSAGE_BYTES}-byte protocol bound"
        )
    try:
        diagnostic = ExecutionDiagnostic.model_validate_json(raw)
    except ValueError as error:
        raise ExecutionSealError(
            f"run {run!r} has a malformed persisted {_DIAGNOSTIC_PAYLOAD}: {error}"
        ) from error
    if canonical_semantic_bytes(diagnostic) != raw:
        raise ExecutionSealError(
            f"run {run!r} has a substituted {_DIAGNOSTIC_PAYLOAD}: the stored bytes are not "
            "the canonical record this supervisor writes"
        )
    return diagnostic


def _diagnostic_disagreements(
    diagnostic: ExecutionDiagnostic, result: ExecutionResult
) -> tuple[str, ...]:
    """Name every supervisor-owned fact the persisted record does not reproduce.

    The identity fields are the minimum the seal decision depends on; the runtime facts are
    included because they are written from the same observation and a record that disagreed
    about them would not be that observation either. The returned names are field labels, not
    values, so a refusal stays bounded and does not echo possibly hostile content.
    """
    comparisons: tuple[tuple[str, bool], ...] = (
        ("run id", diagnostic.run_id == result.run_id),
        (
            "execution fingerprint",
            diagnostic.execution_fingerprint == result.execution_fingerprint,
        ),
        ("environment", diagnostic.environment == result.environment),
        ("adapter", diagnostic.adapter == result.adapter),
        ("terminal state", diagnostic.state is result.state),
        ("refusals", diagnostic.refusals == result.refusals),
        ("worker exit code", diagnostic.worker_exit_code == result.worker_exit_code),
        ("stdin delivery", diagnostic.stdin_delivered == result.stdin_delivered),
        (
            "process-tree cleanup",
            diagnostic.process_tree_cleaned == result.process_tree_cleaned,
        ),
        ("stdout truncation", diagnostic.stdout_truncated == result.stdout_truncated),
        ("stderr truncation", diagnostic.stderr_truncated == result.stderr_truncated),
        ("worker log reference", diagnostic.log_reference == result.log_reference),
    )
    return tuple(name for name, agrees in comparisons if not agrees)


@final
class SupervisedExecution:
    """One supervisor-authored execution result bound to the bundle it may seal.

    This object is the only supported way from a supervised execution to sealed evidence.
    It binds the supervisor's original terminal observation to the staging bundle that
    observation was written into, and it re-verifies the persisted ``diagnostics.json``
    against that observation before delegating to ADR-008. It is deliberately not a
    dataclass, and it has no public constructor: ordinary attribute assignment, deletion,
    ``dataclasses.replace`` and subclassing cannot produce another handle with a different
    result or bundle. The evidence transaction itself remains entirely ADR-008's.

    **In-process trust boundary.** This stops substitution through the supported Python API;
    it is not cryptographic authentication. A caller able to use ``object.__setattr__``,
    ``ctypes``, a debugger, or direct filesystem writes against the mutable staging
    directory can step outside the boundary. ADR-008 still hashes and verifies whatever
    payload is actually promoted, and only an externally trusted evidence digest can show
    that the promoted bundle is the expected one. No signing key exists here, so no token or
    in-memory secret could make a stronger claim honestly.
    """

    __slots__ = ("_bundle", "_result")

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError(
            "SupervisedExecution is created only by execute_preflighted; a caller cannot "
            "assemble a sealable handle from a result and a bundle"
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(
            "SupervisedExecution cannot be subclassed: the terminal observation and its "
            "sealing decision are supervisor-owned"
        )

    @property
    def result(self) -> ExecutionResult:
        """The supervisor's original terminal observation, never a replacement."""
        return self._result

    @property
    def has_staging_bundle(self) -> bool:
        """Whether the supervisor created a staging bundle for this execution."""
        return self._bundle is not None

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(
            "SupervisedExecution is immutable: its terminal observation and staging bundle "
            "cannot be rebound"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            "SupervisedExecution is immutable: its terminal observation and staging bundle "
            "cannot be deleted"
        )

    def __repr__(self) -> str:
        return f"<SupervisedExecution {self._result!r}>"

    def finalize(self, outcome: RunOutcome | None = None) -> SealResult:
        """Seal the staging bundle as the outcome the supervisor actually observed.

        The handle was created only by :func:`execute_preflighted`, so ``self._result`` is
        the supervisor's original terminal observation rather than a caller-supplied value.
        Before delegating, this re-reads the persisted ``diagnostics.json`` and requires it
        to be the canonical record of that exact observation: the same run id, execution
        fingerprint, environment, adapter, terminal state, refusal list, exit code,
        delivery/cleanup/truncation facts and log reference. A missing, malformed,
        substituted or inconsistent record is refused, so a fabricated ``COMPLETED`` result
        cannot authorize a successful seal over a failed bundle.

        The admissible outcome is then derived from the verified record, not from the
        caller. ADR-008 remains the sole owner of hashing, manifest construction,
        verification and atomic promotion; this method only refuses to hand it an outcome
        the supervisor did not observe.

        :param outcome: optional caller assertion. It must equal the derived outcome;
            otherwise this refuses before the evidence layer is called.
        :raises ExecutionSealError: if no staging bundle exists, the terminal diagnostic was
            not persisted or does not verify against the original observation, or an
            explicit outcome contradicts the verified terminal observation. A failed,
            cancelled, timed-out or refused run can only ever be sealed as ``FAILED``.
        """
        if self._bundle is None:
            raise ExecutionSealError(f"run {self._result.run_id!r} has no staging bundle to seal")
        if self._result.diagnostic_reference != _DIAGNOSTIC_PAYLOAD:
            raise ExecutionSealError(
                f"run {self._result.run_id!r} has no persisted {_DIAGNOSTIC_PAYLOAD}; an "
                "execution whose terminal record was not written cannot be sealed, even when "
                "a worker log was retained"
            )
        diagnostic = _read_persisted_diagnostic(self._bundle)
        disagreements = _diagnostic_disagreements(diagnostic, self._result)
        if disagreements:
            raise ExecutionSealError(
                f"run {self._result.run_id!r} has a persisted {_DIAGNOSTIC_PAYLOAD} that does "
                "not agree with the supervisor's terminal observation: " + ", ".join(disagreements)
            )
        admissible = seal_outcome_for(diagnostic.state, diagnostic.refusals)
        if admissible is not self._result.seal_outcome:
            raise ExecutionSealError(
                f"run {self._result.run_id!r} has inconsistent terminal authority: the "
                "persisted diagnostic and the supervisor observation derive different outcomes"
            )
        if outcome is not None and outcome is not admissible:
            raise ExecutionSealError(
                f"run {self._result.run_id!r} ended as {diagnostic.state.value} and can only "
                f"be sealed as {admissible.value}, not {outcome.value}"
            )
        return finalize_bundle(self._bundle, admissible)


def _supervised_execution(
    result: ExecutionResult, bundle: StagingBundle | None
) -> SupervisedExecution:
    """Create the one sealable handle for a supervisor-authored observation.

    ``SupervisedExecution.__init__`` refuses public assembly, so the factory allocates the
    instance directly. The observation and the bundle are bound in the same object, from the
    same :func:`_finish` call, and can be neither reassigned nor deleted afterwards.
    """
    handle = object.__new__(SupervisedExecution)
    object.__setattr__(handle, "_result", result)
    object.__setattr__(handle, "_bundle", bundle)
    return handle


class _BoundedStreamReader(threading.Thread):
    """Read a pipe into a bounded buffer, reporting truncation instead of growing."""

    def __init__(
        self,
        stream: IO[bytes],
        *,
        limit: int,
        fail_on_overflow: bool,
    ) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self._fail_on_overflow = fail_on_overflow
        self.buffer = bytearray()
        self.truncated = False
        self.overflow = threading.Event()

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(_READ_CHUNK_BYTES)
                if not chunk:
                    return
                room = self._limit - len(self.buffer)
                if room > 0:
                    self.buffer.extend(chunk[:room])
                if len(chunk) > max(room, 0):
                    self.truncated = True
                    if self._fail_on_overflow:
                        self.overflow.set()
        except (OSError, ValueError):
            # A read failure on stdout means no trustworthy response; a read failure on
            # stderr means the log excerpt is incomplete. Neither is silence to be ignored.
            if self._fail_on_overflow:
                self.overflow.set()
            else:
                self.truncated = True


class _StdinWriter(threading.Thread):
    """Deliver one request from a thread so the deadline can interrupt a blocked pipe.

    A synchronous write is unbounded: a worker that never reads stdin eventually fills the
    pipe buffer and the supervisor blocks inside ``write`` before its deadline or
    cancellation check ever runs. The write is therefore always performed here, while the
    supervisor's main loop continues to own the deadline, cancellation and tree cleanup.
    """

    def __init__(self, stream: IO[bytes], payload: bytes) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._payload = payload
        self.delivered = False
        self.failure: str | None = None

    def run(self) -> None:
        view = memoryview(self._payload)
        try:
            while view:
                written = self._stream.write(view)
                if written <= 0:
                    raise BrokenPipeError("the worker closed its stdin")
                view = view[written:]
            self._stream.flush()
            self.delivered = True
        except (BrokenPipeError, OSError, ValueError) as error:
            self.failure = f"{type(error).__name__}: {error}"
        finally:
            try:
                self._stream.close()
            except OSError:
                return


def _notify(observer: _LifecycleObserverDispatcher | None, state: RunLifecycleState) -> None:
    if observer is None:
        return
    observer.notify(state)


def _terminate_and_reap(process: subprocess.Popen[bytes], tree: ProcessTree) -> tuple[bool, bool]:
    """Terminate the whole tree, reap the direct child, and verify the tree is empty.

    The two returned facts are deliberately separate. ``worker_reaped`` is about the direct
    child only; ``process_tree_cleaned`` is about every process the tree primitive owns,
    including descendants that outlived an early parent exit. A caller must not read the
    first as the second.
    """
    try:
        tree.request_termination()
    except OSError:
        pass
    # Reap the direct child before waiting for the tree. On POSIX the group leader remains
    # visible to ``killpg`` until it is reaped, so asking the tree to drain first would spend
    # the entire grace period observing the supervisor's own zombie instead of descendants.
    try:
        process.wait(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    worker_reaped = process.poll() is not None
    try:
        process_tree_cleaned = tree.wait_empty(_TERMINATION_GRACE_SECONDS)
    except OSError:
        process_tree_cleaned = False
    return worker_reaped, process_tree_cleaned


def _response_refusals(response: WorkerResponse, request: WorkerRequest) -> list[Refusal]:
    """Require the response to describe exactly the request that was sent."""
    if (
        response.protocol_version != request.protocol_version
        or response.run_id != request.run_id
        or response.execution_fingerprint != request.execution_fingerprint
        or response.environment != request.environment
        or response.adapter != request.adapter
    ):
        return [
            refusal(
                RefusalCode.WORKER_PROTOCOL_VIOLATION,
                "the worker response does not describe the run, environment and adapter "
                "it was given",
            )
        ]
    return []


def _launch_command(program: Path, manifest: WorkerEnvironmentManifest) -> list[str]:
    return [str(program), *manifest.command.arguments]


def _launch(
    command: list[str],
    *,
    working_directory: Path,
    environment: dict[str, str],
) -> tuple[subprocess.Popen[bytes], ProcessTree]:
    """Start one worker suspended, attach it to its tree primitive, then resume it."""
    job = create_windows_job()
    options: dict[str, object] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": working_directory,
        "env": environment,
        "shell": False,
        "bufsize": 0,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = windows_creation_flags()
    else:
        options["start_new_session"] = True

    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(command, **options)  # type: ignore[arg-type]
        if job is not None:
            attach_windows_job(job, process)
            return process, job
        return process, PosixProcessTree(process.pid)
    except BaseException:
        if job is not None:
            job.terminate()
            job.close()
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=_TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        raise


def _working_directory(workspace: Workspace, run: RunId) -> Path:
    """Create the one disposable scratch directory this worker may use."""
    root = workspace.location(PersistenceClass.TMP).path
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"worker-{run}-", dir=root))


def _finish(
    *,
    bundle: StagingBundle | None,
    request: WorkerRequest,
    state: RunLifecycleState,
    refusals: list[Refusal],
    worker_exit_code: int | None,
    worker_pid: int | None,
    worker_reaped: bool,
    stdin_delivered: bool,
    process_tree_cleaned: bool,
    stdout_truncated: bool,
    stderr_truncated: bool,
    stderr_bytes: bytes,
    observer: _LifecycleObserverDispatcher | None,
) -> SupervisedExecution:
    """Write the bounded diagnostic payload, close staging, and bind the sealable handle.

    The diagnostic is written only after every evidence-write failure that can still be
    observed has been folded into the state and refusal list. A log write that fails turns
    a ``COMPLETED`` run into ``FAILED`` *before* ``diagnostics.json`` is written, so the
    persisted state and the returned terminal state cannot disagree. If the diagnostic
    write itself fails, no diagnostic reference is returned and the run becomes ``FAILED``.

    The returned handle is the only object that can seal this run. It is constructed here,
    with the result and the bundle from this one call, so a caller cannot pair an observation
    with another bundle or replace the observation afterwards.
    """
    diagnostic_reference: str | None = None
    log_reference: str | None = None

    final_state = state
    final_refusals = list(refusals)
    if final_state is RunLifecycleState.COMPLETED and final_refusals:
        final_state = RunLifecycleState.FAILED

    if bundle is not None:
        if stderr_bytes:
            try:
                bundle.write_payload(_WORKER_LOG_PAYLOAD, stderr_bytes)
                log_reference = _WORKER_LOG_PAYLOAD
            except EvidenceError:
                final_refusals.append(
                    refusal(
                        RefusalCode.EVIDENCE_WRITE_FAILED,
                        "the bounded worker log could not be written into staging",
                    )
                )
                if final_state is RunLifecycleState.COMPLETED:
                    final_state = RunLifecycleState.FAILED

        diagnostic = ExecutionDiagnostic(
            run_id=request.run_id,
            execution_fingerprint=request.execution_fingerprint,
            environment=request.environment,
            adapter=request.adapter,
            state=final_state,
            refusals=tuple(final_refusals),
            worker_exit_code=worker_exit_code,
            stdin_delivered=stdin_delivered,
            process_tree_cleaned=process_tree_cleaned,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            log_reference=log_reference,
        )
        try:
            bundle.write_payload(_DIAGNOSTIC_PAYLOAD, canonical_semantic_bytes(diagnostic))
            diagnostic_reference = _DIAGNOSTIC_PAYLOAD
        except EvidenceError:
            # No complete diagnostic exists, so a completed process cannot be reported as
            # completed: the operator would have a success with no trace of it. A failed
            # write can leave a partial file behind on some filesystems; remove it so a
            # later reader cannot mistake a truncated record for a persisted terminal state.
            try:
                partial = bundle.workspace.resolve(
                    PersistenceClass.STAGING,
                    f"{bundle.run_id}/{_DIAGNOSTIC_PAYLOAD}",
                )
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            final_refusals.append(
                refusal(
                    RefusalCode.EVIDENCE_WRITE_FAILED,
                    "the execution diagnostic could not be written into staging",
                )
            )
            final_state = RunLifecycleState.FAILED
        bundle.close_for_payload()

    if final_state is RunLifecycleState.COMPLETED and final_refusals:
        final_state = RunLifecycleState.FAILED
    _notify(observer, final_state)

    staging = bundle.reference.text if bundle is not None else staging_locator_for(request.run_id)
    result = ExecutionResult(
        run_id=request.run_id,
        execution_fingerprint=request.execution_fingerprint,
        environment=request.environment,
        adapter=request.adapter,
        state=final_state,
        staging=staging,
        refusals=tuple(final_refusals),
        diagnostic_reference=diagnostic_reference,
        log_reference=log_reference,
        worker_exit_code=worker_exit_code,
        worker_pid=worker_pid,
        worker_reaped=worker_reaped,
        stdin_delivered=stdin_delivered,
        process_tree_cleaned=process_tree_cleaned,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )
    return _supervised_execution(result, bundle)


def _refused_without_process(
    *,
    request: WorkerRequest,
    state: RunLifecycleState,
    refusals: list[Refusal],
    observer: _LifecycleObserverDispatcher | None,
) -> SupervisedExecution:
    """Describe a run refused before a process existed, with no staging side effects."""
    return _finish(
        bundle=None,
        request=request,
        state=state,
        refusals=refusals,
        worker_exit_code=None,
        worker_pid=None,
        worker_reaped=False,
        stdin_delivered=False,
        process_tree_cleaned=False,
        stdout_truncated=False,
        stderr_truncated=False,
        stderr_bytes=b"",
        observer=observer,
    )


def execute_preflighted(
    preflighted: PreflightedRun,
    *,
    cancel_event: threading.Event | None = None,
    observer: LifecycleObserver | None = None,
) -> SupervisedExecution:
    """Launch, supervise and describe one preflight-admitted run.

    The caller receives both the operator-visible result and a ``finalize`` operation,
    which is closed for payload and *not* sealed. The caller's next action is an evidence
    decision, not an execution decision.

    Lifecycle observations are queued to a daemon thread and the dispatcher is closed with
    a bounded join, so no observer can extend the worker's deadline, cancellation, cleanup
    or return path.

    :raises PreflightRefusedError: if ``preflighted`` was refused or carries no request.
        Executing a refused run is a programming error, and silently starting one would
        defeat the admission gate.
    """
    dispatcher = _LifecycleObserverDispatcher(observer)
    try:
        return _execute_preflighted(
            preflighted,
            cancel_event=cancel_event,
            observer=dispatcher,
        )
    finally:
        dispatcher.close(_OBSERVER_CLOSE_SECONDS)


def _execute_preflighted(
    preflighted: PreflightedRun,
    *,
    cancel_event: threading.Event | None,
    observer: _LifecycleObserverDispatcher | None,
) -> SupervisedExecution:
    """Supervise one admitted run on behalf of :func:`execute_preflighted`."""
    report = preflighted.report
    request = preflighted.request
    if not preflighted.ready or request is None:
        raise PreflightRefusedError(report)

    workspace = preflighted.workspace
    manifest = preflighted.manifest
    run = request.run_id

    initial_refusals = admission_refusals(
        preflighted,
        check_assets=True,
        check_duplicates=True,
    )
    if initial_refusals:
        return _refused_without_process(
            request=request,
            state=RunLifecycleState.REFUSED,
            refusals=initial_refusals,
            observer=observer,
        )

    bundle: StagingBundle | None = None
    process: subprocess.Popen[bytes] | None = None
    tree: ProcessTree | None = None
    stdin_writer: _StdinWriter | None = None
    stdout_reader: _BoundedStreamReader | None = None
    stderr_reader: _BoundedStreamReader | None = None
    working_directory: Path | None = None
    state = RunLifecycleState.FAILED
    refusals: list[Refusal] = []
    exit_code: int | None = None
    worker_pid: int | None = None
    worker_reaped = False
    stdin_delivered = False
    process_tree_cleaned = False
    stdout_truncated = False
    stderr_truncated = False
    stderr_bytes = b""
    stdout_bytes = b""

    _notify(observer, RunLifecycleState.STARTING)
    try:
        try:
            bundle = create_staging_bundle(workspace, run)
        except BundleConflictError:
            refusals.append(
                refusal(
                    RefusalCode.DUPLICATE_EXECUTION,
                    f"run {run!r} already has a staging or sealed directory; one run id is "
                    "one execution and is never reused",
                )
            )
            state = RunLifecycleState.REFUSED
            return _finish(
                bundle=None,
                request=request,
                state=state,
                refusals=refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )
        except EvidenceError:
            refusals.append(
                refusal(
                    RefusalCode.EVIDENCE_WRITE_FAILED,
                    "the staging bundle could not be created, so no worker was started",
                )
            )
            state = RunLifecycleState.FAILED
            return _finish(
                bundle=None,
                request=request,
                state=state,
                refusals=refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )

        if cancel_event is not None and cancel_event.is_set():
            refusals.append(
                refusal(
                    RefusalCode.WORKER_CANCELED,
                    "the run was canceled before any worker process was started",
                )
            )
            state = RunLifecycleState.CANCELED
            return _finish(
                bundle=bundle,
                request=request,
                state=state,
                refusals=refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )

        try:
            program = resolved_worker_program(manifest)
        except WorkerEnvironmentError:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_PROGRAM_UNRESOLVED,
                    "the selected worker program was not an executable file at launch time",
                )
            )
            state = RunLifecycleState.FAILED
            return _finish(
                bundle=bundle,
                request=request,
                state=state,
                refusals=refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )

        working_directory = _working_directory(workspace, run)
        request_bytes = canonical_worker_request_bytes(request) + b"\n"
        if len(request_bytes) > MAX_WORKER_MESSAGE_BYTES:
            refusals.append(
                refusal(
                    RefusalCode.INVALID_RUN_SPEC,
                    "the canonical worker request exceeds the protocol message bound",
                )
            )
            state = RunLifecycleState.FAILED
            return _finish(
                bundle=bundle,
                request=request,
                state=state,
                refusals=refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )

        # Re-derive the admission tuple immediately before the fixed program starts. This
        # catches a manifest, plan, definition or asset that changed after preflight.
        launch_refusals = admission_refusals(preflighted, check_assets=True)
        if launch_refusals:
            return _finish(
                bundle=bundle,
                request=request,
                state=RunLifecycleState.REFUSED,
                refusals=launch_refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )

        launch_environment = worker_environment(manifest, temporary_directory=working_directory)
        command = _launch_command(program, manifest)
        try:
            process, tree = _launch(
                command,
                working_directory=working_directory,
                environment=launch_environment,
            )
        except OSError:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_START_FAILED,
                    "the operating system refused to start the selected worker program",
                )
            )
            state = RunLifecycleState.FAILED
            return _finish(
                bundle=bundle,
                request=request,
                state=state,
                refusals=refusals,
                worker_exit_code=None,
                worker_pid=None,
                worker_reaped=False,
                stdin_delivered=False,
                process_tree_cleaned=False,
                stdout_truncated=False,
                stderr_truncated=False,
                stderr_bytes=b"",
                observer=observer,
            )

        worker_pid = process.pid
        deadline = time.monotonic() + manifest.timeout_seconds
        _notify(observer, RunLifecycleState.RUNNING)
        assert process.stdout is not None
        assert process.stderr is not None
        assert process.stdin is not None
        stdout_reader = _BoundedStreamReader(
            process.stdout, limit=MAX_WORKER_MESSAGE_BYTES, fail_on_overflow=True
        )
        stderr_reader = _BoundedStreamReader(
            process.stderr, limit=manifest.max_log_bytes, fail_on_overflow=False
        )
        stdin_writer = _StdinWriter(process.stdin, request_bytes)
        stdout_reader.start()
        stderr_reader.start()
        stdin_writer.start()

        stop_reason: RefusalCode | None = None
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                _notify(observer, RunLifecycleState.CANCELING)
                stop_reason = RefusalCode.WORKER_CANCELED
                break
            if stdout_reader.overflow.is_set():
                stop_reason = RefusalCode.WORKER_OUTPUT_TOO_LARGE
                break
            if time.monotonic() >= deadline:
                stop_reason = RefusalCode.WORKER_TIMEOUT
                break
            time.sleep(_POLL_INTERVAL_SECONDS)

        # Even a direct child that exited on its own is not proof that its descendants are
        # gone. The tree is terminated and verified empty on every path.
        worker_reaped, process_tree_cleaned = _terminate_and_reap(process, tree)
        try:
            process.stdin.close()
        except OSError:
            pass
        stdin_writer.join(_JOIN_SECONDS)
        if stdin_writer.is_alive():
            stdin_writer.join(_JOIN_SECONDS)
        stdin_delivered = stdin_writer.delivered

        stdout_reader.join(_JOIN_SECONDS)
        stderr_reader.join(_JOIN_SECONDS)
        if stdout_reader.is_alive():
            try:
                process.stdout.close()
            except OSError:
                pass
            stdout_reader.join(_JOIN_SECONDS)
        if stderr_reader.is_alive():
            try:
                process.stderr.close()
            except OSError:
                pass
            stderr_reader.join(_JOIN_SECONDS)

        stdout_bytes = bytes(stdout_reader.buffer)
        stderr_bytes = bytes(stderr_reader.buffer)
        stdout_truncated = stdout_reader.truncated
        stderr_truncated = stderr_reader.truncated
        exit_code = process.returncode

        if stop_reason is RefusalCode.WORKER_CANCELED:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_CANCELED,
                    "the run was canceled and the worker process tree was terminated",
                )
            )
            state = RunLifecycleState.CANCELED
        elif stop_reason is RefusalCode.WORKER_TIMEOUT:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_TIMEOUT,
                    "the run exceeded the selected environment's deadline and the worker "
                    "process tree was terminated",
                )
            )
            state = RunLifecycleState.TIMED_OUT
        elif stop_reason is RefusalCode.WORKER_OUTPUT_TOO_LARGE:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_OUTPUT_TOO_LARGE,
                    "the worker wrote more than the response message bound and was terminated",
                )
            )
            state = RunLifecycleState.FAILED
        elif stdout_truncated:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_OUTPUT_TOO_LARGE,
                    "the worker response exceeded the response message bound",
                )
            )
            state = RunLifecycleState.FAILED
        elif exit_code != 0:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_ABNORMAL_EXIT,
                    f"the worker exited with code {exit_code} instead of zero",
                )
            )
            state = RunLifecycleState.FAILED
        elif not stdin_delivered:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_PROTOCOL_VIOLATION,
                    "the worker exited before the complete request was delivered to its stdin",
                )
            )
            state = RunLifecycleState.FAILED
        else:
            try:
                response = parse_worker_response(stdout_bytes)
            except WorkerProtocolError:
                refusals.append(
                    refusal(
                        RefusalCode.WORKER_PROTOCOL_VIOLATION,
                        "the worker did not write exactly one valid protocol response",
                    )
                )
                state = RunLifecycleState.FAILED
            else:
                refusals.extend(_response_refusals(response, request))
                if refusals:
                    state = RunLifecycleState.FAILED
                elif response.status is WorkerStatus.FAILED:
                    refusals.append(
                        refusal(
                            RefusalCode.WORKER_FAILED,
                            "the worker reported a failed status; its bounded diagnostics "
                            "are the account of why",
                        )
                    )
                    state = RunLifecycleState.FAILED
                else:
                    state = RunLifecycleState.COMPLETED

        if not process_tree_cleaned:
            refusals.append(
                refusal(
                    RefusalCode.WORKER_FAILED,
                    "the worker process tree could not be verified empty after termination",
                )
            )
            if state is RunLifecycleState.COMPLETED:
                state = RunLifecycleState.FAILED
    except BaseException:
        if bundle is not None:
            bundle.close_for_payload()
        raise
    finally:
        if process is not None and process.poll() is None:
            if tree is not None:
                worker_reaped, process_tree_cleaned = _terminate_and_reap(process, tree)
            else:  # pragma: no cover - a launched process always has a tree primitive
                try:
                    process.kill()
                except OSError:
                    pass
        if tree is not None:
            try:
                process_tree_cleaned = tree.wait_empty(_TERMINATION_GRACE_SECONDS) and (
                    process_tree_cleaned or process is None
                )
            except OSError:
                process_tree_cleaned = False
            tree.close()
        if stdin_writer is not None:
            stdin_writer.join(_JOIN_SECONDS)
            stdin_delivered = stdin_delivered or stdin_writer.delivered
        if stderr_reader is not None:
            stderr_reader.join(_JOIN_SECONDS)
        if stdout_reader is not None:
            stdout_reader.join(_JOIN_SECONDS)
        if working_directory is not None:
            shutil.rmtree(working_directory, ignore_errors=True)

    if stdout_reader is not None and not stdout_bytes:
        stdout_bytes = bytes(stdout_reader.buffer)
    if stderr_reader is not None:
        if not stderr_bytes:
            stderr_bytes = bytes(stderr_reader.buffer)
        stderr_truncated = stderr_reader.truncated
    if stdout_reader is not None:
        stdout_truncated = stdout_reader.truncated
    if stdin_writer is not None:
        stdin_delivered = stdin_writer.delivered
    if process is not None:
        exit_code = process.returncode
        worker_reaped = worker_reaped or process.poll() is not None

    return _finish(
        bundle=bundle,
        request=request,
        state=state,
        refusals=refusals,
        worker_exit_code=exit_code,
        worker_pid=worker_pid,
        worker_reaped=worker_reaped,
        stdin_delivered=stdin_delivered,
        process_tree_cleaned=process_tree_cleaned,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stderr_bytes=stderr_bytes,
        observer=observer,
    )
