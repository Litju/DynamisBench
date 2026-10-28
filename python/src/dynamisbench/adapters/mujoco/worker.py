"""The isolated MuJoCo reference worker.

The worker is launched by the engine-independent supervisor with a fixed executable and
argument vector, one canonical request on stdin, a rebuilt minimal environment, a deadline
and a process tree it does not own. It does exactly one thing:

    parse one v1 request
    -> prove the request names this adapter, this reference case and this platform
    -> prove the running engine and installed implementation are the request's identity
    -> load the reviewed model and integrate it with real MuJoCo
    -> emit one bounded native diagnostic on stderr
    -> emit one valid v1 response on stdout
    -> exit zero

Any failure after the request is understood is a protocol-valid ``failed`` response with a
bounded message, so the supervisor records ``WORKER_FAILED`` rather than treating a
scientific refusal as a successful process. A malformed request is not answered at all; it
exits non-zero with a bounded stderr line.

The diagnostic on stderr is an adapter diagnostic, not sealed native evidence. The accepted
worker contract already gives stderr a bounded diagnostics channel; RES-550 does not add a
native-output field, a staging path, or an absolute model path.
"""

from __future__ import annotations

import sys
from typing import Final, NoReturn

from dynamisbench.adapters.mujoco import physics, reference
from dynamisbench.adapters.mujoco.diagnostics import ReferenceDiagnostic
from dynamisbench.adapters.mujoco.identity import (
    ImplementationIdentity,
    build_implementation_identity,
)
from dynamisbench.execution.contracts import (
    MAX_WORKER_MESSAGE_BYTES,
    WORKER_PROTOCOL_VERSION,
    WorkerProtocolError,
    WorkerRequest,
    WorkerResponse,
    WorkerStatus,
    parse_worker_request,
)
from dynamisbench.identity import canonical_semantic_bytes

__all__ = ["DIAGNOSTIC_PREFIX", "main"]

DIAGNOSTIC_PREFIX: Final = "DYNAMISBENCH_MUJOCO_DIAGNOSTIC "
"""The unmistakable prefix of the adapter's bounded stderr diagnostic."""

_MAX_FAILURE_MESSAGE: Final = 200


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _identity() -> ImplementationIdentity:
    """Compute the installed implementation identity after proving the model loads."""
    physics.load_model()
    return build_implementation_identity(
        engine_version=physics.engine_version(),
        python_version=_python_version(),
        platform_tag=reference.platform_tag(),
    )


def _write_stdout(payload: bytes) -> None:
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _write_stderr(line: str) -> None:
    sys.stderr.write(line.rstrip("\n") + "\n")
    sys.stderr.flush()


def _refuse_process(message: str) -> NoReturn:
    """Refuse a request that cannot be answered with a valid protocol response."""
    _write_stderr(f"dynamisbench mujoco worker: {message}")
    raise SystemExit(2)


def _response(
    request: WorkerRequest,
    *,
    status: WorkerStatus,
    message: str | None = None,
) -> WorkerResponse:
    return WorkerResponse(
        run_id=request.run_id,
        execution_fingerprint=request.execution_fingerprint,
        environment=request.environment,
        adapter=request.adapter,
        status=status,
        message=message,
    )


def _write_response(response: WorkerResponse) -> None:
    _write_stdout(canonical_semantic_bytes(response) + b"\n")


def _read_request() -> WorkerRequest:
    raw = sys.stdin.buffer.read(MAX_WORKER_MESSAGE_BYTES + 1)
    if len(raw) > MAX_WORKER_MESSAGE_BYTES:
        raise WorkerProtocolError("the request exceeds the worker protocol message bound")
    return parse_worker_request(raw)


def _verify_request(request: WorkerRequest, identity: ImplementationIdentity) -> None:
    """Prove the request and the running implementation are the same execution.

    Every comparison is against the installed implementation or the reviewed reference
    constants, never against a value the request supplies about itself. A caller can
    therefore substitute an adapter version, engine version, realization, environment,
    benchmark, scenario or outcome in the request and be refused here even if a broken
    upstream admitted it.
    """
    adapter = request.adapter
    expected_pairs = (
        ("adapter id", adapter.adapter_id, reference.ADAPTER_ID),
        ("adapter version", adapter.adapter_version, reference.ADAPTER_VERSION),
        ("engine", adapter.engine, reference.ENGINE),
        ("engine version", adapter.engine_version, physics.engine_version()),
        ("protocol version", adapter.protocol_version, WORKER_PROTOCOL_VERSION),
        ("implementation digest", adapter.implementation_digest, identity.digest),
    )
    for label, observed, expected in expected_pairs:
        if observed != expected:
            raise reference.ReferenceAdapterError(
                f"the request's {label} is not the installed implementation identity"
            )
    if tuple(adapter.capabilities) != tuple(reference.CAPABILITIES):
        raise reference.ReferenceAdapterError(
            "the request's adapter capability advertisement is not this adapter's "
            "implemented capability set"
        )
    if tuple(request.required_capabilities) != tuple(reference.CAPABILITIES):
        raise reference.ReferenceAdapterError(
            "the request does not require the single forward-dynamics capability this "
            "reference adapter implements"
        )

    spec = request.run_spec
    identities = (
        ("benchmark", spec.benchmark.identifier, reference.BENCHMARK_ID),
        ("benchmark version", spec.benchmark.version, reference.BENCHMARK_VERSION),
        ("scenario", spec.scenario.identifier, reference.SCENARIO_ID),
        ("scenario version", spec.scenario.version, reference.SCENARIO_VERSION),
        ("realization", spec.realization.identifier, reference.REALIZATION_ID),
        ("realization version", spec.realization.version, reference.REALIZATION_VERSION),
        ("system under test", spec.system_under_test.identifier, reference.SUT_ID),
        ("system under test version", spec.system_under_test.version, reference.SUT_VERSION),
        ("environment", spec.environment.identifier, reference.expected_environment_id()),
        ("environment version", spec.environment.version, reference.ENVIRONMENT_VERSION),
    )
    for label, observed, expected in identities:
        if str(observed) != str(expected):
            raise reference.ReferenceAdapterError(
                f"the request's {label} is not the compiled reference case"
            )
    if tuple(spec.outcomes) != (reference.OUTCOME,):
        raise reference.ReferenceAdapterError(
            f"the request asks for outcomes {tuple(spec.outcomes)!r}; this adapter produces "
            f"only {reference.OUTCOME!r}"
        )

    if len(spec.factors) != 1:
        raise reference.ReferenceAdapterError(
            "the reference adapter requires exactly one controlled gravity factor and no "
            "other factor assignments"
        )
    gravity = spec.factors[0]
    if gravity.target.parameter != "gravity":
        raise reference.ReferenceAdapterError(
            "the request's single factor is not the compiled gravity control"
        )
    if (
        gravity.target.kind.value != "realization"
        or str(gravity.target.identifier) != reference.REALIZATION_ID
        or str(gravity.quantity) != "q.pendulum.gravity"
        or gravity.unit.expression != reference.GRAVITY_UNIT
        or gravity.value != reference.GRAVITY_M_S2
    ):
        raise reference.ReferenceAdapterError(
            "the request's gravity factor is not the compiled standard-gravity reference value"
        )


def _context(request: WorkerRequest, identity: ImplementationIdentity) -> physics.RunContext:
    spec = request.run_spec
    return physics.RunContext(
        run_id=str(request.run_id),
        execution_fingerprint=request.execution_fingerprint.hex,
        benchmark=str(spec.benchmark.identifier),
        scenario=str(spec.scenario.identifier),
        realization=str(spec.realization.identifier),
        environment_id=str(spec.environment.identifier),
        seed=spec.seed,
        outcomes=tuple(str(outcome) for outcome in spec.outcomes),
        adapter_version=str(request.adapter.adapter_version),
        engine_version=str(request.adapter.engine_version),
        implementation_digest=str(request.adapter.implementation_digest),
    )


def _emit_native_diagnostic(diagnostic: ReferenceDiagnostic) -> None:
    """Write one canonical diagnostic line to the bounded stderr channel."""
    encoded = canonical_semantic_bytes(diagnostic.model_dump(mode="json"))
    _write_stderr(DIAGNOSTIC_PREFIX + encoded.decode("utf-8"))


def _failure_message(error: BaseException) -> str:
    text = str(error).strip() or type(error).__name__
    return text[:_MAX_FAILURE_MESSAGE]


def _run_protocol() -> int:
    try:
        request = _read_request()
    except WorkerProtocolError as error:
        _refuse_process(f"request is not valid protocol v1: {error}")

    try:
        identity = _identity()
        _verify_request(request, identity)
        context = _context(request, identity)
        run = physics.run_reference(context)
    except reference.ReferenceAdapterError as error:
        message = _failure_message(error)
        _write_stderr(f"dynamisbench mujoco worker: {message}")
        _write_response(_response(request, status=WorkerStatus.FAILED, message=message))
        return 0
    except Exception as error:  # noqa: BLE001 - fail closed without leaking a traceback
        message = f"the reference run failed ({type(error).__name__})"
        _write_stderr(f"dynamisbench mujoco worker: {message}")
        _write_response(_response(request, status=WorkerStatus.FAILED, message=message))
        return 0

    _emit_native_diagnostic(run.diagnostic)
    _write_response(
        _response(
            request,
            status=WorkerStatus.COMPLETED,
            message=("reference pendulum forward dynamics completed; native diagnostic on stderr"),
        )
    )
    return 0


def _print_identity() -> int:
    try:
        identity = _identity()
    except reference.ReferenceAdapterError as error:
        _write_stderr(f"dynamisbench mujoco worker: {_failure_message(error)}")
        return 2
    _write_stdout(canonical_semantic_bytes(identity.as_json_object()) + b"\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """The fixed entry point. Only ``--identity`` is a qualification interface."""
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--identity"]:
        return _print_identity()
    if arguments:
        _write_stderr(
            "dynamisbench mujoco worker: the worker accepts no arguments except --identity"
        )
        return 2
    return _run_protocol()
