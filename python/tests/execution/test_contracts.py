"""The versioned worker protocol is closed, bounded and deterministic."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from dynamisbench.execution import (
    MAX_WORKER_MESSAGE_BYTES,
    RefusalCode,
    RunLifecycleState,
    WorkerEnvironmentError,
    WorkerEnvironmentManifest,
    WorkerEnvironmentVariable,
    WorkerProtocolError,
    WorkerRequest,
    WorkerResponse,
    WorkerStatus,
    canonical_worker_request_bytes,
    parse_worker_request,
    parse_worker_response,
    refusal,
    staging_locator_for,
    worker_environment,
    worker_request_digest,
)
from tests.execution.support import ExecutionFixture, preflight, worker_manifest


def _ready_request(fixture: ExecutionFixture) -> WorkerRequest:
    admission = preflight(fixture)
    assert admission.ready
    assert admission.request is not None
    return admission.request


def test_request_round_trips_through_its_canonical_bytes(
    execution_fixture: ExecutionFixture,
) -> None:
    request = _ready_request(execution_fixture)

    canonical = canonical_worker_request_bytes(request)
    parsed = parse_worker_request(canonical + b"\n")

    assert parsed == request
    assert canonical_worker_request_bytes(parsed) == canonical
    assert worker_request_digest(parsed) == worker_request_digest(request)
    assert request.staging_locator == staging_locator_for(request.run_id)
    assert request.execution_fingerprint == execution_fixture.run.fingerprint


def test_request_refuses_a_fingerprint_it_did_not_derive(
    execution_fixture: ExecutionFixture,
) -> None:
    request = _ready_request(execution_fixture)
    tampered = request.model_dump()
    tampered["execution_fingerprint"] = {"algorithm": "sha256", "hex": "0" * 64}

    with pytest.raises(ValidationError, match="fingerprint"):
        WorkerRequest.model_validate(tampered)


def test_request_refuses_a_capability_the_adapter_does_not_advertise(
    execution_fixture: ExecutionFixture,
) -> None:
    request = _ready_request(execution_fixture)
    tampered = request.model_dump()
    tampered["supported_capabilities"] = []

    with pytest.raises(ValidationError, match="capabilities"):
        WorkerRequest.model_validate(tampered)


@pytest.mark.parametrize(
    "locator",
    [
        "/tmp/run-0000",
        "../run-0000",
        "C:\\Windows\\run-0000",
        ".staging/../run-0000",
        ".staging/run-other",
        ".staging/",
    ],
)
def test_request_refuses_a_locator_outside_the_declared_staging_location(
    execution_fixture: ExecutionFixture, locator: str
) -> None:
    request = _ready_request(execution_fixture)
    tampered = request.model_dump()
    tampered["staging_locator"] = locator

    with pytest.raises(ValidationError):
        WorkerRequest.model_validate(tampered)


def test_response_round_trips_and_refuses_malformed_frames(
    execution_fixture: ExecutionFixture,
) -> None:
    request = _ready_request(execution_fixture)
    response = WorkerResponse(
        run_id=request.run_id,
        execution_fingerprint=request.execution_fingerprint,
        environment=request.environment,
        adapter=request.adapter,
        status=WorkerStatus.COMPLETED,
        message="engine-free control case; no scientific result",
    )

    raw = response.model_dump_json().encode("utf-8")
    assert parse_worker_response(raw + b"\n") == response

    with pytest.raises(WorkerProtocolError):
        parse_worker_response(b"{}\n{}\n")
    with pytest.raises(WorkerProtocolError):
        parse_worker_response(b"not-json")
    with pytest.raises(WorkerProtocolError):
        parse_worker_response(b"x" * (MAX_WORKER_MESSAGE_BYTES + 1))


def test_a_failed_response_must_state_a_reason(execution_fixture: ExecutionFixture) -> None:
    request = _ready_request(execution_fixture)
    with pytest.raises(ValidationError, match="bounded message"):
        WorkerResponse(
            run_id=request.run_id,
            execution_fingerprint=request.execution_fingerprint,
            environment=request.environment,
            adapter=request.adapter,
            status=WorkerStatus.FAILED,
        )


def test_lifecycle_terminality_and_success_are_separate_vocabularies() -> None:
    terminal = {
        RunLifecycleState.REFUSED,
        RunLifecycleState.CANCELED,
        RunLifecycleState.TIMED_OUT,
        RunLifecycleState.FAILED,
        RunLifecycleState.COMPLETED,
    }
    for state in RunLifecycleState:
        assert state.terminal is (state in terminal)

    assert RunLifecycleState.COMPLETED.successful
    for state in RunLifecycleState:
        if state is not RunLifecycleState.COMPLETED:
            assert not state.successful


def test_a_refusal_message_is_bounded_without_changing_its_code() -> None:
    long = refusal(RefusalCode.WORKER_FAILED, "x" * 1000)
    assert long.code is RefusalCode.WORKER_FAILED
    assert len(long.message) <= 256
    assert long.message.endswith("...")


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "Path",
        "pAtH",
        "PYTHONPATH",
        "PythonPath",
        "PYTHONHOME",
        "PYTHONWARNINGS",
        "LANG",
        "LC_ALL",
        "TZ",
        "tz",
        "SYSTEMROOT",
        "DYNAMISBENCH_MODE",
        "dynamisbench_mode",
        "LD_PRELOAD",
        "Ld_Preload",
        "ld_audit",
        "DYLD_INSERT_LIBRARIES",
        "dYlD_iNsErT_lIbRaRiEs",
        "DOTNET_STARTUP_HOOKS",
        "dotnet_startup_hooks",
        "NODE_OPTIONS",
        "Node_Options",
        "JAVA_TOOL_OPTIONS",
        "__COMPAT_LAYER",
        "__PYVENV_LAUNCHER__",
        "GCONV_PATH",
        "GLIBC_TUNABLES",
        "BASH_FUNC_echo",
    ],
)
def test_the_worker_environment_refuses_a_reserved_variable(name: str) -> None:
    with pytest.raises(ValidationError):
        WorkerEnvironmentVariable(name=name, value="override")


def test_the_worker_environment_is_rebuilt_not_inherited(
    execution_fixture: ExecutionFixture, tmp_path
) -> None:
    manifest = worker_manifest(execution_fixture)
    environment = worker_environment(
        manifest,
        temporary_directory=tmp_path,
        inherited={
            "PATH": "C:\\hostile",
            "PYTHONPATH": "C:\\hostile",
            "SYSTEMROOT": "C:\\Windows",
            "WINDIR": "C:\\Windows",
            "UNRELATED_SECRET": "must-not-be-inherited",
        },
    )

    assert "PATH" not in environment
    assert "PYTHONPATH" not in environment
    assert "UNRELATED_SECRET" not in environment
    assert environment["PYTHONHASHSEED"] == "0"
    assert environment["DYNAMISBENCH_WORKER_PROTOCOL"] == "1"
    if os.name == "nt":
        assert environment["TEMP"] == str(tmp_path)
        assert environment["TMP"] == str(tmp_path)
    else:
        assert environment["TMPDIR"] == str(tmp_path)


def test_the_manifest_refuses_case_alias_environment_variables(
    execution_fixture: ExecutionFixture,
) -> None:
    base = worker_manifest(execution_fixture)
    with pytest.raises(ValidationError, match="differ only by case"):
        WorkerEnvironmentManifest(
            environment=base.environment,
            adapter=base.adapter,
            command=base.command,
            timeout_seconds=base.timeout_seconds,
            environment_variables=(
                WorkerEnvironmentVariable(name="CONTROL_MODE", value="one"),
                WorkerEnvironmentVariable(name="control_mode", value="two"),
            ),
        )


def test_worker_environment_refuses_a_case_alias_of_a_supervisor_value(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    manifest = worker_manifest(execution_fixture)
    tampered = manifest.model_copy(
        update={
            "environment_variables": (
                WorkerEnvironmentVariable.model_construct(name="tz", value="hostile"),
            )
        }
    )

    with pytest.raises(WorkerEnvironmentError):
        worker_environment(tampered, temporary_directory=tmp_path)


def test_worker_environment_refuses_a_loader_name_that_skipped_validation(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    manifest = worker_manifest(execution_fixture)
    tampered = manifest.model_copy(
        update={
            "environment_variables": (
                WorkerEnvironmentVariable.model_construct(name="Ld_Preload", value="hostile.so"),
            )
        }
    )

    with pytest.raises(WorkerEnvironmentError, match="not admissible"):
        worker_environment(tampered, temporary_directory=tmp_path)


def test_worker_environment_refuses_case_aliases_that_skipped_validation(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    manifest = worker_manifest(execution_fixture)
    tampered = manifest.model_copy(
        update={
            "environment_variables": (
                WorkerEnvironmentVariable.model_construct(name="CONTROL_MODE", value="one"),
                WorkerEnvironmentVariable.model_construct(name="control_mode", value="two"),
            )
        }
    )

    with pytest.raises(WorkerEnvironmentError, match="aliases another declaration"):
        worker_environment(tampered, temporary_directory=tmp_path)


def test_windows_platform_variables_are_read_case_insensitively(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    manifest = worker_manifest(execution_fixture)
    environment = worker_environment(
        manifest,
        temporary_directory=tmp_path,
        inherited={"systemroot": r"C:\Windows", "WiNdIr": r"C:\Windows"},
    )
    if os.name == "nt":
        assert environment["SYSTEMROOT"] == r"C:\Windows"
        assert environment["WINDIR"] == r"C:\Windows"


def test_conflicting_case_aliases_of_a_platform_variable_are_refused(
    execution_fixture: ExecutionFixture, tmp_path: Path
) -> None:
    if os.name != "nt":
        pytest.skip("Windows environment-block case aliases only exist on Windows")
    manifest = worker_manifest(execution_fixture)
    with pytest.raises(WorkerEnvironmentError, match="conflicting case aliases"):
        worker_environment(
            manifest,
            temporary_directory=tmp_path,
            inherited={"SYSTEMROOT": r"C:\Windows", "systemroot": r"C:\Elsewhere"},
        )
