"""The supervisor is bounded, cancellable, reaping, and never seals a failed run."""

from __future__ import annotations

import ast
import ctypes
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api import create_app
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.evidence import (
    RunOutcome,
    StagingState,
    create_staging_bundle,
    discover_staging,
    verify_sealed_bundle,
)
from dynamisbench.evidence.bundle import BundleOperationError
from dynamisbench.evidence.staging import StagingBundle
from dynamisbench.execution import (
    ExecutionDiagnostic,
    ExecutionSealError,
    RefusalCode,
    RunLifecycleState,
    canonical_worker_request_bytes,
    execute_preflighted,
)
from dynamisbench.workspace import PersistenceClass
from tests.execution.support import (
    MISBEHAVING_WORKER,
    ExecutionFixture,
    adapter_identity,
    asset_realization,
    build_fixture,
    control_study,
    execute,
    preflight,
    seal_control_bundle,
    worker_manifest,
    write_source_asset,
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


def _wait_until(predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _wait_until_dead(pid: int) -> None:
    assert _wait_until(lambda: not _pid_is_alive(pid)), f"process {pid} is still alive"


def _large_request_fixture(tmp_path: Path) -> ExecutionFixture:
    """A control run whose canonical request is larger than a pipe buffer.

    The exact size is not part of the contract; the assertion in the regression proves it
    exceeds 64 KiB, which is the largest common pipe capacity on the qualification
    platforms. Without this the non-reading-worker test could pass merely because the
    request fit in the kernel buffer.
    """
    outcomes = tuple(f"q.outcome.{index:04d}" for index in range(4000))
    return build_fixture(tmp_path, study=control_study(outcomes=outcomes))


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

    assert supervised.has_staging_bundle
    sealed = supervised.finalize()
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

    assert supervised.has_staging_bundle
    with pytest.raises(ExecutionSealError):
        supervised.finalize(RunOutcome.SUCCEEDED)
    sealed = supervised.finalize()
    verification = verify_sealed_bundle(execution_fixture.workspace, execution_fixture.run_id)
    assert verification.is_valid
    assert verification.bundle is not None
    assert verification.bundle.manifest.outcome is RunOutcome.FAILED
    assert verification.bundle.evidence_digest == sealed.evidence_digest


def test_a_failed_result_cannot_be_mutated_into_a_successful_seal(
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
    assert isinstance(result.refusals, tuple)
    with pytest.raises(AttributeError, match="immutable"):
        result.state = RunLifecycleState.COMPLETED
    with pytest.raises(AttributeError, match="immutable"):
        result.refusals = ()
    with pytest.raises(AttributeError, match="immutable"):
        del result.state
    assert result.state is RunLifecycleState.FAILED
    assert result.refusals
    assert result.seal_outcome is RunOutcome.FAILED

    with pytest.raises(ExecutionSealError):
        supervised.finalize(RunOutcome.SUCCEEDED)
    assert not _sealed_root(execution_fixture).exists()


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

    with pytest.raises(ExecutionSealError):
        supervised.finalize(RunOutcome.SUCCEEDED)
    sealed = supervised.finalize()
    assert sealed.manifest.outcome is RunOutcome.FAILED


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
    assert not supervised.has_staging_bundle


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


def test_a_blocking_observer_cannot_delay_timeout_or_cleanup(
    execution_fixture: ExecutionFixture,
) -> None:
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("sleep",),
        timeout_seconds=0.4,
    )
    entered = threading.Event()
    release = threading.Event()

    def block(state: RunLifecycleState) -> None:
        entered.set()
        release.wait(60.0)

    outcomes: list = []
    runner = threading.Thread(
        target=lambda: outcomes.append(execute(execution_fixture, manifest, observer=block))
    )
    started = time.monotonic()
    runner.start()
    try:
        assert entered.wait(10.0)
        runner.join(10.0)
        elapsed = time.monotonic() - started
        assert not runner.is_alive()
        result = outcomes[0].result
        assert result.state is RunLifecycleState.TIMED_OUT
        assert {item.code for item in result.refusals} == {RefusalCode.WORKER_TIMEOUT}
        assert result.worker_reaped
        assert result.process_tree_cleaned
        assert result.worker_pid is not None
        assert not _pid_is_alive(result.worker_pid)
        assert elapsed < 10.0
    finally:
        release.set()
        runner.join(10.0)


def test_a_blocking_observer_cannot_delay_cancellation_or_cleanup(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    pid_file = tmp_path / "blocked-observer-worker.pid"
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("pid-sleep", str(pid_file)),
        timeout_seconds=30.0,
    )
    entered = threading.Event()
    release = threading.Event()

    def block(state: RunLifecycleState) -> None:
        entered.set()
        release.wait(60.0)

    cancel_event = threading.Event()
    outcomes: list = []
    runner = threading.Thread(
        target=lambda: outcomes.append(
            execute(
                execution_fixture,
                manifest,
                cancel_event=cancel_event,
                observer=block,
            )
        )
    )
    started = time.monotonic()
    runner.start()
    try:
        assert entered.wait(10.0)
        assert _wait_until(pid_file.is_file)
        worker_pid = int(pid_file.read_text(encoding="ascii"))
        cancel_event.set()
        runner.join(10.0)
        elapsed = time.monotonic() - started
        assert not runner.is_alive()
        result = outcomes[0].result
        assert result.state is RunLifecycleState.CANCELED
        assert {item.code for item in result.refusals} == {RefusalCode.WORKER_CANCELED}
        assert result.worker_pid is not None
        assert result.worker_reaped
        assert result.process_tree_cleaned
        assert not _pid_is_alive(result.worker_pid)
        assert not _pid_is_alive(worker_pid)
        assert elapsed < 10.0
    finally:
        release.set()
        runner.join(10.0)


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


def test_a_non_reading_worker_cannot_block_stdin_past_the_deadline(
    tmp_path: Path,
) -> None:
    fixture = _large_request_fixture(tmp_path)
    manifest = worker_manifest(
        fixture,
        script=MISBEHAVING_WORKER,
        arguments=("no-read-sleep",),
        timeout_seconds=0.4,
    )
    admission = preflight(fixture, manifest)
    assert admission.ready
    assert admission.request is not None
    assert len(canonical_worker_request_bytes(admission.request)) > 64 * 1024

    started = time.monotonic()
    result = execute_preflighted(admission).result
    elapsed = time.monotonic() - started

    assert result.state is RunLifecycleState.TIMED_OUT
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_TIMEOUT}
    assert not result.stdin_delivered
    assert result.worker_reaped
    assert result.process_tree_cleaned
    assert result.worker_pid is not None
    assert not _pid_is_alive(result.worker_pid)
    assert elapsed < 15.0


def test_a_blocked_stdin_delivery_is_cancellable(tmp_path: Path) -> None:
    fixture = _large_request_fixture(tmp_path)
    manifest = worker_manifest(
        fixture,
        script=MISBEHAVING_WORKER,
        arguments=("no-read-sleep",),
        timeout_seconds=30.0,
    )
    admission = preflight(fixture, manifest)
    assert admission.ready
    assert admission.request is not None
    assert len(canonical_worker_request_bytes(admission.request)) > 64 * 1024

    cancel_event = threading.Event()
    started = time.monotonic()
    result = execute_preflighted(
        admission,
        cancel_event=cancel_event,
        observer=lambda state: cancel_event.set() if state is RunLifecycleState.RUNNING else None,
    ).result
    elapsed = time.monotonic() - started

    assert result.state is RunLifecycleState.CANCELED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_CANCELED}
    assert result.worker_reaped
    assert result.process_tree_cleaned
    assert result.worker_pid is not None
    assert not _pid_is_alive(result.worker_pid)
    assert elapsed < 15.0


def test_an_early_exiting_parent_does_not_orphan_its_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    fixture = build_fixture(fixture_root)
    manifest = worker_manifest(
        fixture,
        script=MISBEHAVING_WORKER,
        arguments=("early-exit-child", str(pid_file)),
    )
    result = execute(fixture, manifest).result

    assert result.state is RunLifecycleState.FAILED
    assert {item.code for item in result.refusals} == {RefusalCode.WORKER_PROTOCOL_VIOLATION}
    assert result.worker_reaped
    assert result.process_tree_cleaned
    assert _wait_until(pid_file.is_file)
    child_pid = int(pid_file.read_text(encoding="ascii"))
    assert child_pid != result.worker_pid
    _wait_until_dead(child_pid)


def test_cleanup_reaps_the_leader_before_waiting_for_the_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    fixture = build_fixture(fixture_root)
    manifest = worker_manifest(
        fixture,
        script=MISBEHAVING_WORKER,
        arguments=("early-exit-child", str(pid_file)),
    )

    started = time.monotonic()
    result = execute(fixture, manifest).result
    elapsed = time.monotonic() - started

    assert result.state is RunLifecycleState.FAILED
    assert result.worker_reaped
    assert result.process_tree_cleaned
    assert _wait_until(pid_file.is_file)
    child_pid = int(pid_file.read_text(encoding="ascii"))
    _wait_until_dead(child_pid)
    if os.name != "nt":
        # Before the repair, POSIX spent the full five-second grace period on the unreaped
        # zombie leader and only then reaped it. Four seconds leaves scheduling margin while
        # still failing the old ordering; the descendant check above preserves containment.
        assert elapsed < 4.0


def test_a_completed_worker_cannot_leave_a_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    fixture = build_fixture(fixture_root)
    manifest = worker_manifest(
        fixture,
        script=MISBEHAVING_WORKER,
        arguments=("response-with-child", str(pid_file)),
    )
    result = execute(fixture, manifest).result

    assert result.state is RunLifecycleState.COMPLETED
    assert result.worker_reaped
    assert result.process_tree_cleaned
    assert _wait_until(pid_file.is_file)
    child_pid = int(pid_file.read_text(encoding="ascii"))
    assert child_pid != result.worker_pid
    _wait_until_dead(child_pid)


def test_a_post_preflight_asset_mutation_is_refused_before_launch(
    tmp_path: Path,
) -> None:
    placeholder = build_fixture(tmp_path)
    digest = write_source_asset(placeholder.workspace, "models/control.xml", b"control-model")
    realization = asset_realization(path="models/control.xml", sha256=digest)
    fixture = build_fixture(
        tmp_path,
        realization=realization,
        workspace=placeholder.workspace,
    )
    admission = preflight(fixture)
    assert admission.ready

    write_source_asset(placeholder.workspace, "models/control.xml", b"mutated-model")

    supervised = execute_preflighted(admission)

    assert supervised.result.state is RunLifecycleState.REFUSED
    assert {item.code for item in supervised.result.refusals} == {RefusalCode.ASSET_DIGEST_MISMATCH}
    assert not supervised.has_staging_bundle
    assert not _staging_root(fixture).exists()


def test_a_tampered_request_digest_is_refused_at_launch(
    execution_fixture: ExecutionFixture,
) -> None:
    admission = preflight(execution_fixture)
    assert admission.ready
    assert admission.request is not None
    tampered_request = admission.request.model_copy(update={"required_capabilities": ()})
    tampered = replace(admission, request=tampered_request)

    supervised = execute_preflighted(tampered)

    assert supervised.result.state is RunLifecycleState.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in {item.code for item in supervised.result.refusals}
    assert not supervised.has_staging_bundle
    assert not _staging_root(execution_fixture).exists()


def test_a_tampered_manifest_command_is_refused_at_launch(
    execution_fixture: ExecutionFixture,
) -> None:
    admission = preflight(execution_fixture)
    assert admission.ready
    tampered_manifest = admission.manifest.model_copy(
        update={"timeout_seconds": admission.manifest.timeout_seconds + 1.0}
    )
    tampered = replace(admission, manifest=tampered_manifest)

    supervised = execute_preflighted(tampered)

    assert supervised.result.state is RunLifecycleState.REFUSED
    assert RefusalCode.INVALID_RUN_SPEC in {item.code for item in supervised.result.refusals}
    assert not supervised.has_staging_bundle
    assert not _staging_root(execution_fixture).exists()


def test_a_tampered_manifest_adapter_is_refused_at_launch(
    execution_fixture: ExecutionFixture,
) -> None:
    admission = preflight(execution_fixture)
    assert admission.ready
    tampered_manifest = worker_manifest(
        execution_fixture,
        adapter=adapter_identity((Capability.STATE_SNAPSHOT,)),
    )
    tampered = replace(admission, manifest=tampered_manifest)

    supervised = execute_preflighted(tampered)

    assert supervised.result.state is RunLifecycleState.REFUSED
    codes = {item.code for item in supervised.result.refusals}
    assert RefusalCode.UNSUPPORTED_CAPABILITY in codes or (
        RefusalCode.ADAPTER_ENGINE_MISMATCH in codes
    )
    assert not supervised.has_staging_bundle
    assert not _staging_root(execution_fixture).exists()


def test_a_log_write_failure_persists_the_same_failed_state(
    execution_fixture: ExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = StagingBundle.write_payload

    def fail_log_write(self: StagingBundle, relative_path: str, data: bytes):
        if relative_path == "logs/worker.stderr.txt":
            raise BundleOperationError("injected log write failure")
        return original(self, relative_path, data)

    monkeypatch.setattr(StagingBundle, "write_payload", fail_log_write)
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("stderr",),
    )
    result = execute(execution_fixture, manifest).result

    assert result.state is RunLifecycleState.FAILED
    assert RefusalCode.EVIDENCE_WRITE_FAILED in {item.code for item in result.refusals}
    assert result.log_reference is None
    assert result.diagnostic_reference == "diagnostics.json"
    diagnostic = _diagnostic(execution_fixture)
    assert diagnostic.state is result.state
    assert {item.code for item in diagnostic.refusals} == {item.code for item in result.refusals}


def test_a_diagnostic_write_failure_returns_failed_and_persists_no_state(
    execution_fixture: ExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = StagingBundle.write_payload

    def fail_diagnostic_write(self: StagingBundle, relative_path: str, data: bytes):
        if relative_path == "diagnostics.json":
            raise BundleOperationError("injected diagnostic write failure")
        return original(self, relative_path, data)

    monkeypatch.setattr(StagingBundle, "write_payload", fail_diagnostic_write)
    manifest = worker_manifest(execution_fixture)
    supervised = execute(execution_fixture, manifest)
    result = supervised.result

    assert result.state is RunLifecycleState.FAILED
    assert RefusalCode.EVIDENCE_WRITE_FAILED in {item.code for item in result.refusals}
    assert result.diagnostic_reference is None
    assert not (_staging_root(execution_fixture) / "diagnostics.json").exists()
    assert supervised.result.seal_outcome is RunOutcome.FAILED
    with pytest.raises(ExecutionSealError):
        supervised.finalize(RunOutcome.SUCCEEDED)
    with pytest.raises(ExecutionSealError, match="diagnostics.json"):
        supervised.finalize()
    with pytest.raises(ExecutionSealError, match="diagnostics.json"):
        supervised.finalize(RunOutcome.FAILED)
    assert not _sealed_root(execution_fixture).exists()


def test_a_persisted_log_does_not_make_an_incomplete_failure_record_sealable(
    execution_fixture: ExecutionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = StagingBundle.write_payload

    def fail_diagnostic_write(self: StagingBundle, relative_path: str, data: bytes):
        if relative_path == "diagnostics.json":
            raise BundleOperationError("injected diagnostic write failure")
        return original(self, relative_path, data)

    monkeypatch.setattr(StagingBundle, "write_payload", fail_diagnostic_write)
    manifest = worker_manifest(
        execution_fixture,
        script=MISBEHAVING_WORKER,
        arguments=("stderr",),
    )
    supervised = execute(execution_fixture, manifest)
    result = supervised.result

    assert result.state is RunLifecycleState.FAILED
    assert result.log_reference == "logs/worker.stderr.txt"
    assert (_staging_root(execution_fixture) / "logs" / "worker.stderr.txt").is_file()
    assert result.diagnostic_reference is None
    assert not (_staging_root(execution_fixture) / "diagnostics.json").exists()

    with pytest.raises(ExecutionSealError, match="diagnostics.json"):
        supervised.finalize()
    with pytest.raises(ExecutionSealError, match="diagnostics.json"):
        supervised.finalize(RunOutcome.FAILED)
    assert not _sealed_root(execution_fixture).exists()


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
