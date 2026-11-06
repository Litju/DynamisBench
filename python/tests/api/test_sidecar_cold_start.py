"""Cold starts and concurrent first requests of the real session process.

The Windows regression: the first requests that needed NumPy and PyArrow arrived together
from the browser (three frame groups, the figure, a run's frames) and imported those packages
concurrently in the server's request threads, and the import failed. The permanent fix loads
the columnar stack on the session's main thread before the socket is bound and readiness is
announced (:func:`dynamisbench.api.server.serve`), and makes every later lazy use go through
one lock-guarded loader (:mod:`dynamisbench.transport.columnar`).

These gates run a fresh ``python -m dynamisbench api serve`` (the command the desktop shell
launches) several times and, the instant it announces readiness, fire many requests at once at
every route that uses the columnar stack: laboratory frames, the anatomical figure and — with a
sealed run in an opened workspace — a run's frames, recording, model and evidence. Every answer
must be complete and correct, and the process must stop cleanly with no traceback. They run on
every platform and are a required regression gate of the Windows job.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from dynamisbench.api import API_V1_PREFIX
from dynamisbench.api import server as server_module
from dynamisbench.api.server import Exit
from dynamisbench.laboratory.figure import FIGURE_MEDIA_TYPE, FIGURE_SHA256
from dynamisbench.transport.columnar import ColumnarStackError

from .factories import session_environment
from .live_sidecar import LiveSidecar, assert_clean_shutdown, running_sidecar

ARROW = "application/vnd.apache.arrow.stream"
COLD_STARTS = 4
CONCURRENCY = 24


def _arrow_rows(body: bytes) -> tuple[list[str], int]:
    import pyarrow.ipc as ipc

    table = ipc.open_stream(io.BytesIO(body)).read_all()
    return list(table.schema.names), table.num_rows


def _fire(sidecar: LiveSidecar, calls: list[tuple[str, str, dict[str, Any] | None]]) -> list[Any]:
    """Send every call at once (released together from a barrier) and return the answers."""
    barrier = threading.Barrier(len(calls))
    answers: list[Any] = [None] * len(calls)

    def send(index: int, method: str, path: str, body: dict[str, Any] | None) -> None:
        barrier.wait()
        try:
            answers[index] = sidecar.request(method, path, body=body)
        except Exception as error:  # noqa: BLE001 - reported by the assertion below
            answers[index] = error

    threads = [
        threading.Thread(target=send, args=(i, method, path, body))
        for i, (method, path, body) in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    return answers


def _stderr_after_stop(sidecar: LiveSidecar) -> str:
    assert_clean_shutdown(sidecar)
    assert sidecar.process.stderr is not None
    return sidecar.process.stderr.read()


LABORATORY_CALLS = [
    f"{API_V1_PREFIX}/laboratory/recordings/{recording}/frames/{group}"
    for recording in ("repetition", "ablation-no-internal-model")
    for group in ("pose", "kinematics", "kinetics")
]


def _check_laboratory_answer(path: str, answer: Any) -> None:
    assert not isinstance(answer, Exception), (path, answer)
    status, headers, body = answer
    assert status == 200, (path, status, body[:300])
    if path.endswith("/figure"):
        assert headers["content-type"] == FIGURE_MEDIA_TYPE
        assert hashlib.sha256(body).hexdigest() == FIGURE_SHA256
    elif "/frames/" in path:
        assert headers["content-type"] == ARROW
        names, rows = _arrow_rows(body)
        assert names[0] == "t" and rows > 500, path


def test_serve_loads_the_columnar_stack_before_it_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(server_module, "preload_columnar_stack", lambda: order.append("preload"))

    def build(*_: Any, **__: Any) -> Any:
        order.append("bind")
        raise OSError("stop here")

    monkeypatch.setattr(server_module, "build_sidecar", build)
    assert server_module.serve(session_environment()) == Exit.STARTUP_FAILED
    assert order == ["preload", "bind"]


def test_a_stack_that_cannot_be_imported_fails_startup_before_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound: list[str] = []

    def broken() -> None:
        raise ColumnarStackError("the columnar stack could not be imported: ImportError: x")

    monkeypatch.setattr(server_module, "preload_columnar_stack", broken)
    monkeypatch.setattr(server_module, "build_sidecar", lambda *_, **__: bound.append("bind"))
    assert server_module.serve(session_environment()) == Exit.STARTUP_FAILED
    assert bound == []


def test_repeated_cold_starts_answer_concurrent_first_requests_completely() -> None:
    figure = f"{API_V1_PREFIX}/laboratory/figure"
    for start in range(COLD_STARTS):
        with running_sidecar() as sidecar:
            paths = (LABORATORY_CALLS * 3)[: CONCURRENCY - 3] + [
                figure,
                f"{API_V1_PREFIX}/laboratory",
                f"{API_V1_PREFIX}/laboratory/model",
            ]
            answers = _fire(sidecar, [("GET", path, None) for path in paths])
            for path, answer in zip(paths, answers, strict=True):
                _check_laboratory_answer(path, answer)
            stderr = _stderr_after_stop(sidecar)
            assert "Traceback" not in stderr, (start, stderr[-3000:])


# --- with a sealed run in an opened workspace ------------------------------------------------


@pytest.fixture(scope="module")
def sealed_workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, str]]:
    """A squat workspace holding one sealed, verified nominal run (executed once)."""
    authority = cast(
        Any,
        pytest.importorskip(
            "tools.mujoco_squat_authority",
            reason="the squat worker and run pipeline are integrated in the M2 execution slice",
        ),
    )
    coordinator_module = cast(Any, pytest.importorskip("dynamisbench.pipeline.coordinator"))
    environments_module = cast(Any, pytest.importorskip("dynamisbench.pipeline.environments"))
    workspace_module = cast(Any, pytest.importorskip("dynamisbench.workspace"))
    support = cast(Any, pytest.importorskip("tests.execution.mujoco.support"))
    write_workspace = authority.write_workspace
    run_coordinator_type = coordinator_module.RunCoordinator
    worker_environments_type = environments_module.WorkerEnvironments
    open_workspace = workspace_module.open_workspace
    worker_python = support.worker_python

    root = tmp_path_factory.mktemp("cold-start-workspace")
    write_workspace(root)
    workspace = open_workspace(root / "source", root / "evidence")
    coordinator = run_coordinator_type(worker_environments_type(worker_python()))
    try:
        started = coordinator.start(workspace, "st.squat.configuration", "nominal", {})
        coordinator.wait(str(started["run_id"]), timeout=900)
        progress = coordinator.progress(workspace, str(started["run_id"]))
        assert progress is not None and progress["state"] == "completed", progress
    finally:
        coordinator.close()
    yield root, str(started["run_id"])
    shutil.rmtree(root, ignore_errors=True)


def _open(sidecar: LiveSidecar, root: Path) -> str:
    status, _, body = sidecar.request(
        "POST",
        f"{API_V1_PREFIX}/workspaces/open",
        body={"source_root": str(root / "source"), "evidence_root": str(root / "evidence")},
    )
    assert status == 200, body
    return str(json.loads(body)["workspace_id"])


def test_repeated_cold_starts_serve_a_sealed_run_to_concurrent_requests(
    sealed_workspace: tuple[Path, str],
) -> None:
    root, run_id = sealed_workspace
    for start in range(COLD_STARTS):
        with running_sidecar() as sidecar:
            workspace_id = _open(sidecar, root)
            base = f"{API_V1_PREFIX}/workspaces/{workspace_id}/runs"
            run_paths = [
                f"{base}/{run_id}/frames/pose",
                f"{base}/{run_id}/frames/kinematics",
                f"{base}/{run_id}/frames/kinetics",
                f"{base}/{run_id}/recording",
                f"{base}/{run_id}/model",
                f"{base}/{run_id}/evidence",
                base,
            ]
            paths = run_paths * 2 + LABORATORY_CALLS + [f"{API_V1_PREFIX}/laboratory/figure"]
            answers = _fire(sidecar, [("GET", path, None) for path in paths])
            for path, answer in zip(paths, answers, strict=True):
                if path.startswith(base):
                    assert not isinstance(answer, Exception), (path, answer)
                    status, headers, body = answer
                    assert status == 200, (start, path, status, body[:300])
                    if "/frames/" in path:
                        names, rows = _arrow_rows(body)
                        assert headers["content-type"] == ARROW and names[0] == "t" and rows == 551
                    elif path.endswith("/evidence"):
                        assert json.loads(body)["status"] == "verified"
                    elif path == base:
                        assert [r["status"] for r in json.loads(body)["runs"]] == ["verified"]
                else:
                    _check_laboratory_answer(path, answer)
            stderr = _stderr_after_stop(sidecar)
            assert "Traceback" not in stderr, (start, stderr[-3000:])
