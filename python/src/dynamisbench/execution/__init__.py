"""Run preflight, isolated worker supervision, and run finalization.

This package is the first implemented M3 execution boundary. It is engine-independent by
construction: nothing here imports MuJoCo, OpenSim or any other simulator, and no
simulator-native object can cross into it. The first real MuJoCo adapter lives in
:mod:`dynamisbench.adapters.mujoco` and is launched, in its own locked execution environment,
through the same fixed worker contract. Version admission is evaluated by
:mod:`dynamisbench.execution.versions`; ``compatible`` constraints are refused because the
accepted authority does not define their semantics.

What the boundary owns:

* :mod:`dynamisbench.execution.contracts` — the versioned worker request/response, the
  closed refusal vocabulary, the operator-visible lifecycle, and the bounded diagnostic
  payload. It carries meaning and identities, never an absolute path or a shell command.
* :mod:`dynamisbench.execution.environment` — the explicitly selected, versioned worker
  environment: adapter identity, supported capabilities, fixed program/arguments, timeout,
  log bound and a rebuilt minimal process environment.
* :mod:`dynamisbench.execution.preflight` — fail-closed admission: fingerprint, resolved
  realization and environment identities, capability agreement, present and content-
  addressed assets, duplicate-run refusal, and worker-program resolution, all before any
  process starts.
* :mod:`dynamisbench.execution.supervisor` — one isolated subprocess, one bounded request,
  one bounded response, a deadline, a cancellation path, process-tree termination and
  reaping, and a bounded diagnostic written into mutable staging.

What it deliberately does not own: sealing (ADR-008 / :mod:`dynamisbench.evidence`),
native or canonical scientific evidence, numerical validity, a queue or scheduler, a
persistent run store, a remote control plane, or any product UI. ``COMPLETED`` means the
worker returned a valid response and exited zero; it is not a scientific claim and not a
sealed artifact.
"""

from dynamisbench.execution.contracts import (
    MAX_WORKER_LOG_BYTES,
    MAX_WORKER_MESSAGE_BYTES,
    MAX_WORKER_TIMEOUT_SECONDS,
    MIN_WORKER_TIMEOUT_SECONDS,
    WORKER_PROTOCOL_VERSION,
    WORKER_REQUEST_SCHEMA_VERSION,
    ExecutionDiagnostic,
    ExecutionError,
    ExecutionResult,
    PreflightDecision,
    PreflightReport,
    Refusal,
    RefusalCode,
    RunLifecycleState,
    WorkerAdapterIdentity,
    WorkerProtocolError,
    WorkerRequest,
    WorkerResponse,
    WorkerStatus,
    canonical_preflight_bytes,
    canonical_worker_request_bytes,
    parse_worker_request,
    parse_worker_response,
    preflight_digest,
    refusal,
    staging_locator_for,
    worker_request_digest,
)
from dynamisbench.execution.environment import (
    FORBIDDEN_WORKER_ENVIRONMENT_VARIABLES,
    WorkerCommand,
    WorkerEnvironmentError,
    WorkerEnvironmentManifest,
    WorkerEnvironmentVariable,
    resolved_worker_program,
    worker_environment,
)
from dynamisbench.execution.preflight import (
    PreflightedRun,
    PreflightRefusedError,
    admission_refusals,
    preflight_run,
    required_capabilities_of,
)
from dynamisbench.execution.supervisor import (
    ExecutionSealError,
    LifecycleObserver,
    SupervisedExecution,
    execute_preflighted,
)

__all__ = [
    "FORBIDDEN_WORKER_ENVIRONMENT_VARIABLES",
    "MAX_WORKER_LOG_BYTES",
    "MAX_WORKER_MESSAGE_BYTES",
    "MAX_WORKER_TIMEOUT_SECONDS",
    "MIN_WORKER_TIMEOUT_SECONDS",
    "WORKER_PROTOCOL_VERSION",
    "WORKER_REQUEST_SCHEMA_VERSION",
    "ExecutionDiagnostic",
    "ExecutionError",
    "ExecutionResult",
    "ExecutionSealError",
    "LifecycleObserver",
    "PreflightDecision",
    "PreflightRefusedError",
    "PreflightReport",
    "PreflightedRun",
    "Refusal",
    "RefusalCode",
    "RunLifecycleState",
    "SupervisedExecution",
    "WorkerAdapterIdentity",
    "WorkerCommand",
    "WorkerEnvironmentError",
    "WorkerEnvironmentManifest",
    "WorkerEnvironmentVariable",
    "WorkerProtocolError",
    "WorkerRequest",
    "WorkerResponse",
    "WorkerStatus",
    "admission_refusals",
    "canonical_preflight_bytes",
    "canonical_worker_request_bytes",
    "execute_preflighted",
    "parse_worker_request",
    "parse_worker_response",
    "preflight_digest",
    "preflight_run",
    "refusal",
    "required_capabilities_of",
    "resolved_worker_program",
    "staging_locator_for",
    "worker_environment",
    "worker_request_digest",
]
