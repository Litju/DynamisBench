"""The columnar stack is imported once, by one thread, and only through one loader.

Regression for the Windows cold-import failure: when the first uses of NumPy and PyArrow came
from several request threads at once, the concurrent import of those C-extension packages
failed. The permanent fix has three parts, each held here:

* one loader (:mod:`dynamisbench.transport.columnar`) that imports the stack under a
  process-wide lock, in a fixed order, completely, before any caller receives it — proved by
  racing many threads at a cold interpreter, many times, in fresh processes;
* no other application module imports NumPy or PyArrow itself (an AST scan), so nothing can
  bypass the lock;
* a failed import is reported to every caller and never retried into a half-imported package.

The session's own preload before readiness is held in ``tests/api/test_sidecar_cold_start.py``.
These tests run on every platform, and the Windows job of the quality workflow runs them as a
required regression gate (``.github/workflows/quality.yml``).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import dynamisbench

SOURCE = Path(dynamisbench.__file__).resolve().parent
COLUMNAR = SOURCE / "transport" / "columnar.py"
HEAVY = ("numpy", "pyarrow")

# Modules that only ever run inside the isolated MuJoCo worker process (single-threaded, own
# environment): they may import the stack directly. Everything the application process imports
# may not.
WORKER_ONLY = {
    "adapters/mujoco/physics.py",
    "adapters/mujoco/squat/__main__.py",
    "adapters/mujoco/squat/analysis.py",
    "adapters/mujoco/squat/control.py",
    "adapters/mujoco/squat/engine.py",
    "adapters/mujoco/squat/movement.py",
    "adapters/mujoco/squat/worker.py",
}


def _run(code: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout, check=False
    )


RACE = r"""
import json, sys, threading
from dynamisbench.transport import columnar
assert 'numpy' not in sys.modules and 'pyarrow' not in sys.modules, 'cold interpreter expected'
N = 32
barrier = threading.Barrier(N)
stacks, errors = [], []
def use(i):
    barrier.wait()
    try:
        stack = columnar.columnar_stack()
        pa, pq = stack.pyarrow, stack.parquet
        table = pa.table({'t': pa.array([0.0, 0.01], type=pa.float64())})
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        back = pq.read_table(pa.BufferReader(sink.getvalue()))
        assert back.column('t').to_pylist() == [0.0, 0.01]
        assert float(stack.numpy.asarray([1.0, 2.0]).sum()) == 3.0
        stacks.append(id(stack))
    except Exception as error:
        errors.append(f'{type(error).__name__}: {error}')
threads = [threading.Thread(target=use, args=(i,)) for i in range(N)]
for t in threads: t.start()
for t in threads: t.join()
print(json.dumps({'errors': errors, 'distinct': len(set(stacks)), 'count': len(stacks)}))
"""


def test_importing_the_loader_imports_no_columnar_package() -> None:
    result = _run(
        "import sys; import dynamisbench.transport.columnar; "
        "print(sorted(m for m in ('numpy','pyarrow') if m in sys.modules))"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_many_threads_racing_a_cold_interpreter_get_one_complete_stack() -> None:
    # Ten fresh interpreters, thirty-two threads each, released together at a barrier onto a
    # stack that no thread has imported yet.
    for attempt in range(10):
        result = _run(RACE)
        assert result.returncode == 0, (attempt, result.stderr[-2000:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["errors"] == [], (attempt, report)
        assert report["count"] == 32
        assert report["distinct"] == 1, "every thread received the same loaded stack"


def test_a_failed_import_is_reported_to_every_caller_and_never_retried() -> None:
    code = r"""
import json, threading
from dynamisbench.transport import columnar
calls = []
def broken():
    calls.append(1)
    raise ImportError('DLL load failed while importing lib: module not found')
columnar._import_stack = broken
barrier = threading.Barrier(8)
failures = []
def use():
    barrier.wait()
    try:
        columnar.columnar_stack()
    except columnar.ColumnarStackError as error:
        failures.append(str(error))
threads = [threading.Thread(target=use) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()
print(json.dumps({'imports': len(calls), 'failures': failures}))
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["imports"] == 1, "the import was attempted once, not once per thread"
    assert len(report["failures"]) == 8
    assert all(
        "could not be imported: ImportError: DLL load failed" in f for f in report["failures"]
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_no_application_module_imports_the_columnar_stack_except_the_loader() -> None:
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        if path == COLUMNAR or relative in WORKER_ONLY:
            continue
        heavy = _imports(path) & set(HEAVY)
        if heavy:
            offenders.append(f"{relative}: {sorted(heavy)}")
    assert offenders == [], offenders


def test_the_application_composition_loads_no_columnar_package_until_asked() -> None:
    # Everything ``dbench api serve`` composes, imported in a fresh interpreter: the stack is
    # loaded only by the explicit preload, never as a side effect of an import.
    code = (
        "import sys\n"
        "import dynamisbench.api.app, dynamisbench.api.server, dynamisbench.cli\n"
        "import dynamisbench.laboratory.figure, dynamisbench.transport.arrow\n"
        "before = sorted(m for m in ('numpy','pyarrow') if m in sys.modules)\n"
        "from dynamisbench.transport.columnar import preload_columnar_stack\n"
        "preload_columnar_stack()\n"
        "names = ('numpy', 'pyarrow', 'pyarrow.parquet', 'pyarrow.ipc')\n"
        "after = sorted(m for m in names if m in sys.modules)\n"
        "print(before, after)\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[] ['numpy', 'pyarrow', 'pyarrow.ipc', 'pyarrow.parquet']"
