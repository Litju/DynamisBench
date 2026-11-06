"""The one loader of the columnar stack (NumPy and PyArrow), safe to call from any thread.

**Why this exists.** The application serves requests from a thread pool, and the columnar
stack is imported lazily so that importing the API (or starting a session that never reads a
frame) does not pay for it. On Windows, a *cold* import of NumPy and PyArrow that starts in
two request threads at once was observed to fail — the import of a C-extension package is not
reliably re-entrant across threads while its DLLs are being loaded and its modules are
partially initialized. A lazy import is safe only if exactly one thread performs it.

**What it guarantees.**

* Every part of the application that needs the stack obtains it through
  :func:`columnar_stack` — never through its own ``import pyarrow`` — and the first call
  imports the stack under one process-wide lock, in one fixed order (NumPy, PyArrow, its IPC
  and Parquet modules), completely, before any caller receives it. Later calls return the
  already-loaded stack without taking the lock.
* The session process loads it on its **main thread before it binds its socket and announces
  readiness** (:func:`preload_columnar_stack`, called by :func:`dynamisbench.api.server.serve`),
  so no request can ever be the first importer. The lock is the second line of defence for
  every other entry point (tools, tests, the pipeline's own thread).
* A failed import is recorded and re-raised to every caller as :class:`ColumnarStackError`
  with a bounded message, rather than being retried from another thread into a half-imported
  module.

Importing this module imports neither NumPy nor PyArrow.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from types import ModuleType
from typing import Final

__all__ = ["ColumnarStack", "ColumnarStackError", "columnar_stack", "preload_columnar_stack"]

_LOCK: Final = threading.Lock()
_STACK: ColumnarStack | None = None
_FAILURE: str | None = None


class ColumnarStackError(RuntimeError):
    """NumPy or PyArrow could not be imported in this environment."""


@dataclass(frozen=True, slots=True)
class ColumnarStack:
    """The imported modules, fully initialized."""

    numpy: ModuleType
    pyarrow: ModuleType
    ipc: ModuleType
    parquet: ModuleType


def _import_stack() -> ColumnarStack:
    # A fixed order: PyArrow's Python layer imports NumPy itself, and importing NumPy first
    # means that happens against a completely initialized NumPy rather than one this thread
    # is still in the middle of.
    import numpy
    import pyarrow
    import pyarrow.ipc
    import pyarrow.parquet

    return ColumnarStack(numpy=numpy, pyarrow=pyarrow, ipc=pyarrow.ipc, parquet=pyarrow.parquet)


def columnar_stack() -> ColumnarStack:
    """The columnar stack, imported exactly once per process by exactly one thread."""
    global _STACK, _FAILURE
    stack = _STACK
    if stack is not None:
        return stack
    with _LOCK:
        if _STACK is None:
            if _FAILURE is not None:
                raise ColumnarStackError(_FAILURE)
            try:
                _STACK = _import_stack()
            except Exception as error:  # noqa: BLE001 - recorded and re-raised, bounded
                reason = f"{type(error).__name__}: {str(error)[:200]}"
                _FAILURE = f"the columnar stack could not be imported: {reason}"
                raise ColumnarStackError(_FAILURE) from error
        return _STACK


def preload_columnar_stack() -> ColumnarStack:
    """Load the stack now, on the calling thread (the session's main thread at startup)."""
    return columnar_stack()
