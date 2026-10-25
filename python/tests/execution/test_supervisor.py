"""The supervisor is bounded, cancellable, reaping, and never seals a failed run."""

from __future__ import annotations

import ast
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from dynamisbench.api import create_app
from dynamisbench.evidence import (
    RunOutcome,
    StagingState,
    create_staging_bundle,
    discover_staging,
    finalize_bundle,
    verify_sealed_bundle,
)
from dynamisbench.execution import (
    ExecutionDiagnostic,
    RefusalCode,
    RunLifecycleState,
    execute_preflighted,
)
from dynamisbench.workspace import PersistenceClass
from tests.execution.support import (
    MISBEHAVING_WORKER,
    ExecutionFixture,
    execute,
    preflight,
    seal_control_bundle,
    worker_manifest,
)


def _staging_root(fixture: ExecutionFixture) -> Path:
    return fixture.workspace.location(PersistenceClass.STAGING).path / fixture.run_id


def _sealed_root(fixture: ExecutionFixture) -> Path:
    return fixture.workspace.location(PersistenceClass.SEALED_EVIDENCE).path / fixture.run_id


def _diagnostic(fixture: ExecutionFixture):
    path = _staging_root(fixture) / "diagnostics.json"
    return ExecutionDiagnostic.model_validate_json(path.read_bytes())


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_control_worker_completes_and_writes_only_a_diagnostic(
    execution_fixture: ExecutionFixture,
) -> None:
    supervised = execute(execution_fixture)
    result = supervised.result

    assert result.state is RunLifecycleState.COMPLETED
    assert result.successful
    assert result.worker_exit_code == 0
    assert result.worker_reaped
    assert result.refusals == ()
    assert result.diagnostic_reference == "diagnostics.json"
    assert result.log_reference is None
    assert result.evidence_locator == f".staging/{execution_fixture.run_id}"

    staging = _staging_root(execution_fixture)
    assert (staging / "diagnostics.json").is_file()
    assert not (staging / "native").exists()
    assert not (staging / "canonical").exists()
    assert not (staging / "assessment.json").exists()
    assert not _sealed_root(execution_fixture).exists()

    diagnostic = _diagnostic(execution_fixture)
    assert diagnostic.state is RunLifecycleState.COMPLETED
    assert diagnostic.refusals == ()
    assert diagnostic.execution_fingerprint == execution_fixture.fingerprint

    report = discover_staging(execution_fixture.workspace)
    assert len(report.candidates) == 1
    assert report.candidates[0].state is StagingState.IN_PROGRESS
    assert report.candidates[0].payload_files == 1
    assert not verify_sealed_bundle(execution_fixture.workspace, execution_fixture.run_id).is_valid

    assert supervised.bundle is not None
    sealed = finalize_bundle(supervised.bundle, RunOutcome.SUCCEEDED)
    verification = verify_sealed_bundle(execution_fixture.workspace, execution_fixture.run_id)
    assert verification.is_valid
    assert verification.bundle is not None
    assert verification.bundle.evidence_digest == sealed.evidence_digest


def test_abnormal_exit_is_failed_and_can_only_be_sealed_as_failed(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("crash",),
    )
    supervised = execute(execution_fixture, manifest)
    result = supervised.result

    assert result.state is RunLifecycleState.FAILED
    assert not result.successful
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_ABNORMAL_EXIT}
    assert result.worker_exit_code == 7
    assert result.worker_reaped
    assert result.log_reference == "logs/worker.stderr.txt"
    assert not _sealed_root(execution_fixture).exists()
    assert _diagnostic(execution_fixture).state is RunLifecycleState.FAILED

    assert supervised.bundle is not None
    sealed = finalize_bundle(supervised.bundle, RunOutcome.FAILED)
    verification = verify_sealed_bundle(execution_fixture.workspace, execution_fixture.run_id)
    assert verification.is_valid
    assert verification.bundle is not None
    assert verification.bundle.manifest.outcome is RunOutcome.FAILED
    assert verification.bundle.evidence_digest == sealed.evidence_digest


def test_a_malformed_response_is_a_protocol_violation(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("invalid",),
    )
    result = execute(execution_fixture, manifest).result

    assert result.state is RunLifecycleState.FAILED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_PROTOCOL_VIOLATION}


def test_a_response_about_another_run_is_a_protocol_violation(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("wrong-identity",),
    )
    result = execute(execution_fixture, manifest).result

    assert result.state is RunLifecycleState.FAILED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_PROTOCOL_VIOLATION}


def test_a_worker_reported_failure_is_a_failed_run(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("failed",),
    )
    result = execute(execution_fixture, manifest).result

    assert result.state is RunLifecycleState.FAILED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_FAILED}
    assert result.worker_exit_code == 0


def test_a_timeout_terminates_the_tree_and_reaps(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("sleep",),
        timeout_seconds=0.3,
    )
    started = time.monotonic()
    result = execute(execution_fixture, manifest).result
    elapsed = time.monotonic() - started

    assert result.state is RunLifecycleState.TIMED_OUT
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_TIMEOUT}
    assert result.worker_reaped
    assert result.worker_pid is not None
    assert not _pid_is_alive(result.worker_pid)
    assert elapsed < 15.0
    assert _diagnostic(execution_fixture).state is RunLifecycleState.TIMED_OUT


def test_cancellation_terminates_the_tree_and_reaps(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("sleep",),
        timeout_seconds=30.0,
    )
    cancel_event = threading.Event()
    states: list[RunLifecycleState] = []

    def observe(state: RunLifecycleState) -> None:
        states.append(state)
        if state is RunLifecycleState.RUNNING:
            cancel_event.set()

    result = execute(
        execution_fixture,
        manifest,
        cancel_event=cancel_event,
        observer=observe,
    ).result

    assert result.state is RunLifecycleState.CANCELED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_CANCELED}
    assert states == [
        RunLifecycleState.STARTING,
        RunLifecycleState.RUNNING,
        RunLifecycleState.CANCELING,
        RunLifecycleState.CANCELED,
    ]
    assert result.worker_reaped
    assert result.worker_pid is not None
    assert not _pid_is_alive(result.worker_pid)


def test_cancellation_before_launch_starts_no_process(
    execution_fixture: ExecutionFixture,
) -> None:
    cancel_event = threading.Event()
    cancel_event.set()
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("sleep",),
    )
    supervised = execute(execution_fixture, manifest, cancel_event=cancel_event)
    result = supervised.result

    assert result.state is RunLifecycleState.CANCELED
    assert result.worker_pid is None
    assert not result.worker_reaped
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_CANCELED}
    assert _diagnostic(execution_fixture).state is RunLifecycleState.CANCELED


def test_oversized_stdout_is_a_failure_not_a_large_allocation(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("flood",),
    )
    result = execute(execution_fixture, manifest).result

    assert result.state is RunLifecycleState.FAILED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_OUTPUT_TOO_LARGE}
    assert result.stdout_truncated
    assert result.worker_reaped


def test_stderr_is_truncated_to_the_environment_bound(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("stderr",),
        max_log_bytes=1024,
    )
    result = execute(execution_fixture, manifest).result

    assert result.state is RunLifecycleState.COMPLETED
    assert result.stderr_truncated
    assert result.log_reference == "logs/worker.stderr.txt"
    log = _staging_root(execution_fixture) / "logs" / "worker.stderr.txt"
    assert log.is_file()
    assert log.stat().st_size <= 1024


def test_a_program_that_the_os_will_not_execute_is_a_start_failure(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    program = tmp_path / "not-a-program.txt"
    program.write_text("this is not an executable format", encoding="utf-8")
    if os.name != "nt":
        program.chmod(0o755)

    manifest = worker_manifest(execution_fixture, program=str(program))
    admission = preflight(execution_fixture, manifest)
    assert admission.ready

    result = execute_preflighted(admission).result

    assert result.state is RunLifecycleState.FAILED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_START_FAILED}
    assert result.worker_pid is None


def test_a_duplicate_execution_after_preflight_is_refused(
    execution_fixture: ExecutionFixture,
) -> None:
    admission = preflight(execution_fixture)
    assert admission.ready
    create_staging_bundle(execution_fixture.workspace, execution_fixture.run_id)

    supervised = execute_preflighted(admission)

    assert supervised.result.state is RunLifecycleState.REFUSED
    assert {item.code for item in supervised.result.refusals} == {RefusalCode.DUPLICATE_EXECUTION}
    assert supervised.bundle is None


def test_a_failed_run_does_not_mutate_sealed_authority(
    execution_fixture: ExecutionFixture,
) -> None:
    sealed = seal_control_bundle(execution_fixture.workspace, "sealed-control")
    before = verify_sealed_bundle(execution_fixture.workspace, "sealed-control")
    assert before.is_valid
    assert before.bundle is not None
    assert before.bundle.evidence_digest == sealed.evidence_digest

    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("crash",),
    )
    result = execute(execution_fixture, manifest).result
    assert result.state is RunLifecycleState.FAILED

    after = verify_sealed_bundle(execution_fixture.workspace, "sealed-control")
    assert after.is_valid
    assert after.bundle is not None
    assert after.bundle.evidence_digest == before.bundle.evidence_digest
    assert not _sealed_root(execution_fixture).exists()


def test_the_application_api_stays_responsive_while_a_worker_runs(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("sleep",),
        timeout_seconds=30.0,
    )
    started = threading.Event()
    cancel_event = threading.Event()
    results: list = []

    def run_worker() -> None:
        results.append(
            execute(
                execution_fixture,
                manifest,
                cancel_event=cancel_event,
                observer=lambda state: (
                    started.set() if state is RunLifecycleState.RUNNING else None
                ),
            ).result
        )

    thread = threading.Thread(target=run_worker)
    thread.start()
    assert started.wait(15.0)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200

    cancel_event.set()
    thread.join(15.0)
    assert not thread.is_alive()
    assert results[0].state is RunLifecycleState.CANCELED


def test_the_execution_source_has_no_shell_or_network_surface() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "dynamisbench" / "execution"
    forbidden_imports = {
        "mujoco",
        "opensim",
        "simtk",
        "gym",
        "gymnasium",
        "pybullet",
        "brax",
        "dm_control",
        "socket",
        "urllib",
        "http",
        "requests",
    }
    offenders: set[str] = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders.update(
                    alias.name.split(".")[0]
                    for alias in node.names
                    if alias.name.split(".")[0] in forbidden_imports
                )
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root = node.module.split(".")[0]
                if root in forbidden_imports:
                    offenders.add(root)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "system",
                    "popen",
                }:
                    offenders.add(f"os.{node.func.attr}")
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        offenders.add("shell=True")
    assert not offenders


def test_the_execution_import_graph_loads_no_simulator() -> None:
    probe = "\n".join(
        [
            "import sys",
            "import dynamisbench.execution",
            "print('\\n'.join(sorted(sys.modules)))",
        ]
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    forbidden = {
        "mujoco",
        "opensim",
        "simtk",
        "gym",
        "gymnasium",
        "pybullet",
        "brax",
        "dm_control",
    }
    assert not set(loaded) & forbidden
