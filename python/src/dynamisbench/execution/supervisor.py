"""Supervise one isolated worker subprocess with bounded I/O, time and cancellation.

This is the only module in the project that starts a scientific worker. It is deliberately
engine-independent: it knows how to launch a fixed vector, write one protocol request, read
one bounded response, enforce a deadline, cancel, terminate a process tree and reap it. It
does not import or construct a simulator, and it never decides what a worker's output
means scientifically.

The guarantees, in the order they matter:

**No shell, ever.** The command is ``[program, *arguments]`` with ``shell=False`` and an
absolute program. A run input cannot add an argument, change the program, choose a working
directory, or influence the environment beyond what the selected manifest declared.

**Bounded in both directions.** The request is canonical JSON at most
:data:`~dynamisbench.execution.contracts.MAX_WORKER_MESSAGE_BYTES`; stdout is read into at
most that many bytes and an overflow kills the process; stderr is retained up to the
environment's ``max_log_bytes`` and every further byte is discarded rather than buffered.
The supervisor can therefore not be made to allocate a worker's entire output.

**One deadline, one cancellation path.** Timeout and cancellation both end in the same
process-tree termination and reaping path. A worker cannot ignore either, and neither can
leave an orphan process. A cancellation that arrives before launch is honoured without
starting anything.

**Completion is a process fact, not a scientific one.** A run is ``COMPLETED`` only when
the worker wrote a valid response for this exact request and exited zero. Every other
outcome — abnormal exit, protocol violation, timeout, cancellation, oversized output — is
a failure state. A failed or partial run never becomes sealed evidence here: the
supervisor writes ``diagnostics.json`` into the mutable staging bundle, closes it for
payload and returns. Sealing remains the evidence layer's transaction (ADR-008).

The only payload the supervisor writes is that diagnostic record and a bounded stderr log.
It never writes ``native/``, ``canonical/`` or ``assessment.json``; producing those is a
later adapter/normalization/evaluation responsibility, and fabricating them here would be
a false scientific claim.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

from dynamisbench.evidence.bundle import (
    BundleConflictError,
    EvidenceError,
    RunId,
)
from dynamisbench.evidence.staging import StagingBundle, create_staging_bundle
from dynamisbench.execution.contracts import (
    MAX_WORKER_MESSAGE_BYTES,
    ExecutionDiagnostic,
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
    staging_locator_for,
)
from dynamisbench.execution.environment import (
    WorkerEnvironmentError,
    WorkerEnvironmentManifest,
    resolved_worker_program,
    worker_environment,
)
from dynamisbench.execution.preflight import PreflightedRun, PreflightRefusedError
from dynamisbench.identity import canonical_semantic_bytes
from dynamisbench.workspace import PersistenceClass, Workspace

__all__ = [
    "LifecycleObserver",
    "SupervisedExecution",
    "execute_preflighted",
]

LifecycleObserver = Callable[[RunLifecycleState], None]
"""A caller's view of the lifecycle transitions the supervisor observed.

The observer is diagnostic. It cannot change the outcome, and an exception it raises is
swallowed rather than allowed to strand a running worker.
"""

_READ_CHUNK_BYTES: Final = 64 * 1024
_POLL_INTERVAL_SECONDS: Final = 0.02
_TERMINATION_GRACE_SECONDS: Final = 5.0
_JOIN_SECONDS: Final = 5.0


@dataclass(frozen=True, slots=True)
class SupervisedExecution:
    """An execution result together with the staging bundle the caller may now seal.

    ``bundle`` is mutable and still in ``.staging/``. It is not authoritative and is not
    sealed; the caller decides whether to finalize it as succeeded or failed evidence, and
    the evidence layer performs that transaction.
    """

    result: ExecutionResult
    bundle: StagingBundle | None


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


def _notify(observer: LifecycleObserver | None, state: RunLifecycleState) -> None:
    if observer is None:
        return
    try:
        observer(state)
    except Exception:
        # A view of the lifecycle is not allowed to break the lifecycle. The worker is
        # still running, and the supervisor still owes it a deadline and a reap.
        return


def _terminate_tree(process: subprocess.Popen[bytes]) -> bool:
    """Terminate a worker and its descendants, then reap it.

    Windows uses the operating system's tree-aware ``taskkill`` from an absolute system
    path, because ``Popen.kill`` terminates one process and a worker is allowed to have
    descendants. POSIX kills the process group created by ``start_new_session``. Both
    paths fall back to killing the process itself if the tree mechanism is unavailable,
    and both end by waiting for the process so the supervisor never returns while a
    worker is still unreaped.
    """
    if process.poll() is None:
        if os.name == "nt":
            taskkill = (
                Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            )
            terminated = False
            if taskkill.is_file():
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                try:
                    subprocess.run(
                        [
                            str(taskkill),
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        shell=False,
                        capture_output=True,
                        timeout=_TERMINATION_GRACE_SECONDS,
                        creationflags=flags,
                        check=False,
                    )
                    terminated = True
                except (OSError, subprocess.TimeoutExpired):
                    terminated = False
            if not terminated:
                try:
                    process.kill()
                except OSError:
                    pass
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    process.kill()
                except OSError:
                    pass
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
            return False
    return True


def _write_request(process: subprocess.Popen[bytes], payload: bytes) -> None:
    """Write the one request and close stdin, treating a broken pipe as a worker failure."""
    try:
        if process.stdin is None:  # pragma: no cover - PIPE is always requested
            return
        process.stdin.write(payload)
        process.stdin.flush()
    except (BrokenPipeError, OSError):
        # The process died before reading its request. The exit code and stderr are the
        # authoritative account; the supervisor does not invent a second one here.
        return
    finally:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass


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
) -> subprocess.Popen[bytes]:
    """Start one worker with an explicit vector, no shell and no inherited descriptors."""
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
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)  # type: ignore[arg-type]


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
    stdout_truncated: bool,
    stderr_truncated: bool,
    stderr_bytes: bytes,
    observer: LifecycleObserver | None,
) -> ExecutionResult:
    """Write the bounded diagnostic payload, close staging, and describe the outcome.

    A failure to write the diagnostic is itself a refusal. A worker that reported success
    but whose supervisor could not record what happened is not reported as completed,
    because the operator would then have a success with no trace of it.
    """
    diagnostic_reference: str | None = None
    log_reference: str | None = None

    if bundle is not None:
        if stderr_bytes:
            try:
                bundle.write_payload("logs/worker.stderr.txt", stderr_bytes)
                log_reference = "logs/worker.stderr.txt"
            except EvidenceError:
                refusals.append(
                    refusal(
                        RefusalCode.EVIDENCE_WRITE_FAILED,
                        "the bounded worker log could not be written into staging",
                    )
                )
        diagnostic = ExecutionDiagnostic(
            run_id=request.run_id,
            execution_fingerprint=request.execution_fingerprint,
            environment=request.environment,
            adapter=request.adapter,
            state=state,
            refusals=tuple(refusals),
            worker_exit_code=worker_exit_code,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            log_reference=log_reference,
        )
        try:
            bundle.write_payload("diagnostics.json", canonical_semantic_bytes(diagnostic))
            diagnostic_reference = "diagnostics.json"
        except EvidenceError:
            refusals.append(
                refusal(
                    RefusalCode.EVIDENCE_WRITE_FAILED,
                    "the execution diagnostic could not be written into staging",
                )
            )
        bundle.close_for_payload()

    if state is RunLifecycleState.COMPLETED and refusals:
        state = RunLifecycleState.FAILED
    _notify(observer, state)

    staging = bundle.reference.text if bundle is not None else staging_locator_for(request.run_id)
    return ExecutionResult(
        run_id=request.run_id,
        execution_fingerprint=request.execution_fingerprint,
        environment=request.environment,
        adapter=request.adapter,
        state=state,
        staging=staging,
        refusals=tuple(refusals),
        diagnostic_reference=diagnostic_reference,
        log_reference=log_reference,
        worker_exit_code=worker_exit_code,
        worker_pid=worker_pid,
        worker_reaped=worker_reaped,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def execute_preflighted(
    preflighted: PreflightedRun,
    *,
    cancel_event: threading.Event | None = None,
    observer: LifecycleObserver | None = None,
) -> SupervisedExecution:
    """Launch, supervise and describe one preflight-admitted run.

    The caller receives both the operator-visible result and the staging bundle, which is
    closed for payload and *not* sealed. The caller's next action is an evidence decision,
    not an execution decision.

    :raises PreflightRefusedError: if ``preflighted`` was refused. Executing a refused run
        is a programming error, and silently starting one would defeat the admission gate.
    """
    report = preflighted.report
    request = preflighted.request
    if not preflighted.ready or request is None:
        raise PreflightRefusedError(report)

    workspace = preflighted.workspace
    manifest = preflighted.manifest
    run = request.run_id
    bundle: StagingBundle | None = None
    process: subprocess.Popen[bytes] | None = None
    stdout_reader: _BoundedStreamReader | None = None
    stderr_reader: _BoundedStreamReader | None = None
    working_directory: Path | None = None
    state = RunLifecycleState.FAILED
    refusals: list[Refusal] = []
    exit_code: int | None = None
    worker_pid: int | None = None
    worker_reaped = False
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
            return SupervisedExecution(
                result=_finish(
                    bundle=None,
                    request=request,
                    state=state,
                    refusals=refusals,
                    worker_exit_code=None,
                    worker_pid=None,
                    worker_reaped=False,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    stderr_bytes=b"",
                    observer=observer,
                ),
                bundle=None,
            )
        except EvidenceError:
            refusals.append(
                refusal(
                    RefusalCode.EVIDENCE_WRITE_FAILED,
                    "the staging bundle could not be created, so no worker was started",
                )
            )
            state = RunLifecycleState.FAILED
            return SupervisedExecution(
                result=_finish(
                    bundle=None,
                    request=request,
                    state=state,
                    refusals=refusals,
                    worker_exit_code=None,
                    worker_pid=None,
                    worker_reaped=False,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    stderr_bytes=b"",
                    observer=observer,
                ),
                bundle=None,
            )

        if cancel_event is not None and cancel_event.is_set():
            refusals.append(
                refusal(
                    RefusalCode.WORKER_CANCELED,
                    "the run was canceled before any worker process was started",
                )
            )
            state = RunLifecycleState.CANCELED
            return SupervisedExecution(
                result=_finish(
                    bundle=bundle,
                    request=request,
                    state=state,
                    refusals=refusals,
                    worker_exit_code=None,
                    worker_pid=None,
                    worker_reaped=False,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    stderr_bytes=b"",
                    observer=observer,
                ),
                bundle=bundle,
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
            return SupervisedExecution(
                result=_finish(
                    bundle=bundle,
                    request=request,
                    state=state,
                    refusals=refusals,
                    worker_exit_code=None,
                    worker_pid=None,
                    worker_reaped=False,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    stderr_bytes=b"",
                    observer=observer,
                ),
                bundle=bundle,
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
            return SupervisedExecution(
                result=_finish(
                    bundle=bundle,
                    request=request,
                    state=state,
                    refusals=refusals,
                    worker_exit_code=None,
                    worker_pid=None,
                    worker_reaped=False,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    stderr_bytes=b"",
                    observer=observer,
                ),
                bundle=bundle,
            )

        launch_environment = worker_environment(manifest, temporary_directory=working_directory)
        command = _launch_command(program, manifest)
        try:
            process = _launch(
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
            return SupervisedExecution(
                result=_finish(
                    bundle=bundle,
                    request=request,
                    state=state,
                    refusals=refusals,
                    worker_exit_code=None,
                    worker_pid=None,
                    worker_reaped=False,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    stderr_bytes=b"",
                    observer=observer,
                ),
                bundle=bundle,
            )

        worker_pid = process.pid
        _notify(observer, RunLifecycleState.RUNNING)
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_reader = _BoundedStreamReader(
            process.stdout, limit=MAX_WORKER_MESSAGE_BYTES, fail_on_overflow=True
        )
        stderr_reader = _BoundedStreamReader(
            process.stderr, limit=manifest.max_log_bytes, fail_on_overflow=False
        )
        stdout_reader.start()
        stderr_reader.start()
        _write_request(process, request_bytes)

        deadline = time.monotonic() + manifest.timeout_seconds
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

        if stop_reason is not None:
            worker_reaped = _terminate_tree(process)
        else:
            try:
                process.wait(timeout=_TERMINATION_GRACE_SECONDS)
                worker_reaped = True
            except subprocess.TimeoutExpired:
                worker_reaped = _terminate_tree(process)

        stdout_reader.join(_JOIN_SECONDS)
        stderr_reader.join(_JOIN_SECONDS)
        if stdout_reader.is_alive():
            try:
                assert process.stdout is not None
                process.stdout.close()
            except OSError:
                pass
            stdout_reader.join(_JOIN_SECONDS)
        if stderr_reader.is_alive():
            try:
                assert process.stderr is not None
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
    except BaseException:
        if bundle is not None:
            bundle.close_for_payload()
        raise
    finally:
        if process is not None and process.poll() is None:
            _terminate_tree(process)
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
    if process is not None:
        exit_code = process.returncode
        worker_reaped = worker_reaped or process.poll() is not None

    return SupervisedExecution(
        result=_finish(
            bundle=bundle,
            request=request,
            state=state,
            refusals=refusals,
            worker_exit_code=exit_code,
            worker_pid=worker_pid,
            worker_reaped=worker_reaped,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stderr_bytes=stderr_bytes,
            observer=observer,
        ),
        bundle=bundle,
    )
