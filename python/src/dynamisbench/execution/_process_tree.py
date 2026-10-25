"""Bounded ownership, termination, and verification of one worker process tree.

A supervised worker is allowed to start descendants. That makes ``Popen.kill`` and
``Popen.wait`` insufficient on their own: killing the direct child says nothing about a
grandchild that inherited its pipes, and reaping the parent says nothing about a child that
survived it. This module owns the stronger platform primitive:

* **Windows** assigns the suspended worker to a Job Object before its first instruction
  runs, with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. Descendants inherit the job. The job is
  terminated explicitly and its ``ActiveProcesses`` accounting is polled until zero.
* **POSIX** starts the worker as a session and process-group leader. ``killpg`` reaches the
  leader and every descendant that stayed in the group, including after the leader exits,
  and an empty group is the verification oracle.

Neither branch equates parent reaping with tree cleanup. The supervisor reports the two
facts separately and refuses to call a run completed when the tree could not be verified
empty. A worker that deliberately leaves its process group (``setsid``) or breaks away from
its job is outside the ownership primitive the operating system gives this supervisor; the
contract's descendants are those that inherit the supervised tree.
"""

from __future__ import annotations

import ctypes
import os
import signal
import time
from typing import Any, Final, Protocol, cast

__all__ = [
    "PosixProcessTree",
    "ProcessTree",
    "WindowsJob",
    "attach_windows_job",
    "create_windows_job",
    "windows_creation_flags",
]

_POLL_SECONDS: Final = 0.01


class ProcessTree(Protocol):
    """The supervisor's ownership of one worker and everything it started."""

    def has_live_members(self) -> bool:
        """Whether any process in the owned tree is still live."""
        ...

    def terminate(self) -> bool:
        """Terminate the whole tree and report whether it became empty in time."""
        ...

    def wait_empty(self, timeout: float) -> bool:
        """Wait for the tree to become empty, returning whether it did."""
        ...

    def close(self) -> None:
        """Release the operating-system ownership primitive, if any."""
        ...


class PosixProcessTree:
    """A session/process-group leader and every descendant that stayed in its group."""

    __slots__ = ("_pgid",)

    def __init__(self, pgid: int) -> None:
        self._pgid = pgid

    def has_live_members(self) -> bool:
        try:
            os.killpg(self._pgid, 0)  # type: ignore[attr-defined]
        except ProcessLookupError:
            return False
        except PermissionError:
            # The group exists; the supervisor may not signal it. Treat as live rather
            # than claiming a cleanup it cannot prove.
            return True
        return True

    def terminate(self) -> bool:
        try:
            os.killpg(self._pgid, signal.SIGKILL)  # type: ignore[attr-defined]
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return self.wait_empty(5.0)

    def wait_empty(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if not self.has_live_members():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_SECONDS)

    def close(self) -> None:
        return


# -- Windows Job Object -------------------------------------------------------------------

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: Final = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION: Final = 1
_TH32CS_SNAPTHREAD: Final = 0x00000004
_THREAD_SUSPEND_RESUME: Final = 0x0002
_INVALID_HANDLE_VALUE: Final = ctypes.c_void_p(-1).value

_WINDOWS_CREATE_SUSPENDED: Final = 0x00000004
_WINDOWS_CREATE_NO_WINDOW: Final = 0x08000000
_WINDOWS_CREATE_NEW_PROCESS_GROUP: Final = 0x00000200


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


class WindowsJob:
    """One kill-on-close Job Object that owns the worker and its descendants."""

    __slots__ = (
        "_assign",
        "_close",
        "_create",
        "_handle",
        "_kernel32",
        "_query",
        "_set",
        "_terminate",
    )

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("a Windows Job Object is only available on Windows")
        kernel32: Any = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        self._create = kernel32.CreateJobObjectW
        self._create.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self._create.restype = ctypes.c_void_p
        self._set = kernel32.SetInformationJobObject
        self._set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self._set.restype = ctypes.c_bool
        self._assign = kernel32.AssignProcessToJobObject
        self._assign.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._assign.restype = ctypes.c_bool
        self._terminate = kernel32.TerminateJobObject
        self._terminate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._terminate.restype = ctypes.c_bool
        self._query = kernel32.QueryInformationJobObject
        self._query.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        self._query.restype = ctypes.c_bool
        self._close = kernel32.CloseHandle
        self._close.argtypes = [ctypes.c_void_p]
        self._close.restype = ctypes.c_bool

        handle = self._create(None, None)
        if not handle:
            raise OSError(f"CreateJobObjectW failed with error {_last_error()}")
        self._handle: int | None = cast(int, handle)
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._set(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close()
            raise OSError(f"SetInformationJobObject failed with error {_last_error()}")

    def assign_and_resume(self, process: Any) -> None:
        """Assign a suspended process to this job, then resume its primary thread."""
        if self._handle is None:
            raise OSError("the worker Job Object has already been closed")
        process_handle = int(process._handle)
        if not self._assign(self._handle, ctypes.c_void_p(process_handle)):
            raise OSError(f"AssignProcessToJobObject failed with error {_last_error()}")
        if not _resume_process_threads(process.pid):
            raise OSError("the suspended worker's primary thread could not be resumed")

    def has_live_members(self) -> bool:
        return self._active_processes() > 0

    def terminate(self) -> bool:
        if self._handle is None:
            return True
        if not self._terminate(self._handle, 1):
            error = _last_error()
            if error:
                return False
        return self.wait_empty(5.0)

    def wait_empty(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            try:
                active = self._active_processes()
            except OSError:
                return False
            if active == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_SECONDS)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            self._close(handle)

    def _active_processes(self) -> int:
        if self._handle is None:
            return 0
        accounting = _BasicAccountingInformation()
        if not self._query(
            self._handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise OSError(f"QueryInformationJobObject failed with error {_last_error()}")
        return int(accounting.ActiveProcesses)


def _last_error() -> int:
    kernel32: Any = cast(Any, ctypes)
    get_last_error = getattr(kernel32, "get_last_error", None)
    return int(get_last_error()) if get_last_error is not None else 0


def _resume_process_threads(pid: int) -> bool:
    """Resume every thread of a just-created suspended process.

    ``Popen`` exposes the process handle but not the primary thread handle. The process was
    created suspended, so it has exactly the primary thread at this instant; enumerating
    threads by owner pid and resuming each matching one is the documented way to release
    it without relying on an undocumented ``NtResumeProcess``.
    """
    kernel32: Any = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    create_snapshot.restype = ctypes.c_void_p
    thread_first = kernel32.Thread32First
    thread_first.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry)]
    thread_first.restype = ctypes.c_bool
    thread_next = kernel32.Thread32Next
    thread_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry)]
    thread_next.restype = ctypes.c_bool
    open_thread = kernel32.OpenThread
    open_thread.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    open_thread.restype = ctypes.c_void_p
    resume_thread = kernel32.ResumeThread
    resume_thread.argtypes = [ctypes.c_void_p]
    resume_thread.restype = ctypes.c_uint32
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_bool

    snapshot = create_snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        return False
    resumed = False
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        present = thread_first(snapshot, ctypes.byref(entry))
        while present:
            if entry.th32OwnerProcessID == pid:
                thread = open_thread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread:
                    try:
                        if resume_thread(thread) != 0xFFFFFFFF:
                            resumed = True
                    finally:
                        close_handle(thread)
            present = thread_next(snapshot, ctypes.byref(entry))
    finally:
        close_handle(snapshot)
    return resumed


def create_windows_job() -> WindowsJob | None:
    """Create the Windows ownership primitive, or ``None`` on another platform."""
    return WindowsJob() if os.name == "nt" else None


def attach_windows_job(job: WindowsJob, process: Any) -> None:
    """Assign and resume ``process``, which must have been created suspended."""
    job.assign_and_resume(process)


def windows_creation_flags() -> int:
    """The fixed Windows creation flags used with a suspended, job-owned worker."""
    return _WINDOWS_CREATE_SUSPENDED | _WINDOWS_CREATE_NO_WINDOW | _WINDOWS_CREATE_NEW_PROCESS_GROUP
