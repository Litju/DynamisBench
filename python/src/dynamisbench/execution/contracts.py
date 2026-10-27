"""The versioned worker protocol, lifecycle vocabulary, and refusal reasons.

This module is the first engine-independent execution contract. It deliberately contains
no simulator import, no process launch, no filesystem operation and no clock: it is the
smallest set of values two processes must agree on before either of them can claim that a
:class:`~dynamisbench.planning.runspec.RunSpec` was handed to an isolated worker.

Four boundaries are fixed here, and each one is closed rather than extensible by a caller:

**The request carries meaning, not machinery.** A :class:`WorkerRequest` embeds the exact
``RunSpec`` and its :class:`~dynamisbench.planning.runspec.ExecutionFingerprint`, the
resolved environment identity, the adapter identity, and the capability sets both sides
agreed on. It carries one *logical* location — the staging locator — and no absolute path,
host, user, process id or timestamp. The worker command, working directory and environment
are operational resolution owned by the supervisor and the selected environment, never by
the request, so no run input can alter what executable is started.

**The protocol is one request, one response, one exit.** The request is canonical JSON on
stdin; the response is exactly one bounded JSON object on stdout; diagnostics go to
stderr; a successful worker exits zero. There is no ambient control channel and no
long-running RPC surface in v1. Cancellation and timeout are supervisor decisions that end
the process, not worker verbs that a compromised worker could ignore.

**Refusals are a closed vocabulary.** A caller that is refused receives a
:class:`RefusalCode` from a fixed set, not a sentence to parse. The reason a run was
refused is therefore comparable across releases, and adding one is a visible protocol
change.

**Lifecycle is a closed vocabulary, and completion is not a scientific claim.** The states
mirror what an operator can see: preflight ready, refused, starting, running, canceling,
canceled, timed out, failed, completed. ``COMPLETED`` means *the worker returned a valid
response and exited zero*. It does not mean the run is valid science, and it does not mean
sealed evidence exists. Sealing is a separate evidence transaction (ADR-008), and nothing
in the execution package performs it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, model_validator
from pydantic import ValidationError as PydanticValidationError

from dynamisbench.domain.spec.base import DomainModel, ShortText, unique_items
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.identifiers import Name, Sha256Hex, Version
from dynamisbench.evidence.bundle import (
    BundleNamingError,
    BundleRelativePath,
    RunId,
    RunOutcome,
    parse_run_id,
)
from dynamisbench.identity import SemanticDigest, canonical_semantic_bytes, semantic_sha256
from dynamisbench.planning.authority import ResolvedEnvironmentRef
from dynamisbench.planning.runspec import (
    ExecutionFingerprint,
    RunSpec,
    run_spec_fingerprint,
)
from dynamisbench.workspace.authority import (
    CLASS_LOCATION_SEGMENTS,
    PathScopeError,
    PersistenceClass,
)
from dynamisbench.workspace.paths import validate_logical_reference

__all__ = [
    "MAX_WORKER_LOG_BYTES",
    "MAX_WORKER_MESSAGE_BYTES",
    "MAX_WORKER_TIMEOUT_SECONDS",
    "MIN_WORKER_TIMEOUT_SECONDS",
    "WORKER_PROTOCOL_VERSION",
    "WORKER_REQUEST_SCHEMA_VERSION",
    "ExecutionDiagnostic",
    "ExecutionError",
    "ExecutionResult",
    "PreflightDecision",
    "PreflightReport",
    "Refusal",
    "RefusalCode",
    "RunLifecycleState",
    "WorkerAdapterIdentity",
    "WorkerProtocolError",
    "WorkerRequest",
    "WorkerResponse",
    "WorkerStatus",
    "canonical_preflight_bytes",
    "canonical_worker_request_bytes",
    "parse_worker_request",
    "parse_worker_response",
    "preflight_digest",
    "seal_outcome_for",
    "staging_locator_for",
    "worker_request_digest",
]

WORKER_PROTOCOL_VERSION: Final = 1
"""The worker wire protocol version.

A supervisor and a worker exchange this value in both directions. A future incompatible
change is a new version, not a new optional field: a v1 supervisor must refuse a v2
worker rather than partially understand it.
"""

WORKER_REQUEST_SCHEMA_VERSION: Final = 1
"""The request/response model version, separate from the wire protocol version.

They move separately because a field can be added to the JSON object without changing how
it is transported, and a transport can change without changing what a request means.
"""

MAX_WORKER_MESSAGE_BYTES: Final = 1024 * 1024
"""The largest request or single response this package will write or read.

A ``RunSpec`` is a small structured object, and a response is an identity echo plus a
short status. One mebibyte is already two orders of magnitude above both, and fixing the
bound here is what stops a corrupt or hostile peer from deciding how much memory the
supervisor allocates.
"""

MAX_WORKER_LOG_BYTES: Final = 256 * 1024
"""The largest stderr excerpt retained from one worker process."""

MIN_WORKER_TIMEOUT_SECONDS: Final = 0.05
"""The smallest accepted worker timeout, so a timeout is a real deadline."""

MAX_WORKER_TIMEOUT_SECONDS: Final = 3600.0
"""The largest accepted worker timeout, so no request can ask for an unbounded wait."""

MAX_REFUSAL_MESSAGE_LENGTH: Final = 256


class ExecutionError(Exception):
    """Base class for every refusal this package makes."""


class WorkerProtocolError(ExecutionError, ValueError):
    """A worker request or response is not in the versioned protocol language."""


class RefusalCode(StrEnum):
    """Every reason this package may refuse to start or continue a run.

    The vocabulary is closed because an operator and a later review both need to compare
    refusals. ``INVALID_RUN_ID`` is a caller mistake, the identity and capability codes
    are pre-execution judgements, the path and asset codes are workspace judgements, and
    the ``WORKER_*`` and ``EVIDENCE_*`` codes are runtime outcomes.
    """

    INVALID_RUN_ID = "invalid_run_id"
    INVALID_RUN_SPEC = "invalid_run_spec"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    REALIZATION_IDENTITY_MISMATCH = "realization_identity_mismatch"
    ENVIRONMENT_IDENTITY_MISMATCH = "environment_identity_mismatch"
    ADAPTER_ENGINE_MISMATCH = "adapter_engine_mismatch"
    UNKNOWN_CAPABILITY = "unknown_capability"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSTAGED_ASSET = "unstaged_asset"
    ASSET_DIGEST_MISMATCH = "asset_digest_mismatch"
    FORBIDDEN_PATH = "forbidden_path"
    DUPLICATE_EXECUTION = "duplicate_execution"
    WORKER_PROGRAM_UNRESOLVED = "worker_program_unresolved"
    WORKER_START_FAILED = "worker_start_failed"
    WORKER_PROTOCOL_VIOLATION = "worker_protocol_violation"
    WORKER_OUTPUT_TOO_LARGE = "worker_output_too_large"
    WORKER_TIMEOUT = "worker_timeout"
    WORKER_CANCELED = "worker_canceled"
    WORKER_ABNORMAL_EXIT = "worker_abnormal_exit"
    WORKER_FAILED = "worker_failed"
    EVIDENCE_WRITE_FAILED = "evidence_write_failed"


class Refusal(DomainModel):
    """One bounded, machine-comparable reason a run was refused or stopped.

    ``message`` is supervisor-authored and is deliberately not allowed to contain an
    absolute path. A refusal is operator-visible and may be logged; the resolved location
    of a workspace root is not part of the reason.
    """

    code: RefusalCode
    message: ShortText

    @model_validator(mode="after")
    def _message_is_bounded(self) -> Self:
        if len(self.message) > MAX_REFUSAL_MESSAGE_LENGTH:
            raise ValueError(
                f"a refusal message must be at most {MAX_REFUSAL_MESSAGE_LENGTH} characters"
            )
        return self


def refusal(code: RefusalCode, message: str) -> Refusal:
    """Build one refusal, truncating only the prose and never the code.

    Truncation is explicit rather than left to validation because a caller that produced a
    long diagnostic should still receive a comparable refusal code. The ellipsis marks
    that the message was shortened, so a reader is not told the quoted text was the whole
    reason.
    """

    if len(message) <= MAX_REFUSAL_MESSAGE_LENGTH:
        return Refusal(code=code, message=message)
    return Refusal(
        code=code,
        message=message[: MAX_REFUSAL_MESSAGE_LENGTH - 3].rstrip() + "...",
    )


class PreflightDecision(StrEnum):
    """Whether a run may be handed to a worker."""

    READY = "ready"
    REFUSED = "refused"


class RunLifecycleState(StrEnum):
    """The minimum operator-visible lifecycle of one execution.

    These are the states RES-548 can present without inventing a queue, a scheduler or a
    scientific verdict. ``PREFLIGHT_READY`` is a fact about admission, not a promise that
    execution will succeed. ``COMPLETED`` is a fact about the worker process, not a
    scientific result and not a sealed artifact.
    """

    PREFLIGHT_READY = "preflight_ready"
    REFUSED = "refused"
    STARTING = "starting"
    RUNNING = "running"
    CANCELING = "canceling"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    COMPLETED = "completed"

    @property
    def terminal(self) -> bool:
        """Whether a run in this state has stopped and will not continue."""
        return self in {
            RunLifecycleState.REFUSED,
            RunLifecycleState.CANCELED,
            RunLifecycleState.TIMED_OUT,
            RunLifecycleState.FAILED,
            RunLifecycleState.COMPLETED,
        }

    @property
    def successful(self) -> bool:
        """Whether the worker returned a valid response and exited zero.

        This is deliberately narrower than "the run is good": it says nothing about
        numerical validity, evidence completeness or a scientific claim.
        """
        return self is RunLifecycleState.COMPLETED


_STAGING_SEGMENTS: Final = CLASS_LOCATION_SEGMENTS[PersistenceClass.STAGING]


def staging_locator_for(run_id: RunId) -> str:
    """The portable staging locator for one run, e.g. ``.staging/run-1``.

    Derived from the workspace authority's declared staging segments rather than restated,
    so a layout change reaches this contract automatically and a request can never name a
    different location from the one the evidence layer will use.
    """
    return "/".join((*_STAGING_SEGMENTS, str(run_id)))


def _validate_staging_locator(value: str) -> str:
    """Accept only the canonical staging locator of one valid run id."""
    try:
        segments = validate_logical_reference(value, persistence_class=PersistenceClass.STAGING)
    except PathScopeError as error:
        raise ValueError(
            f"a staging locator is not a portable workspace reference: {error}"
        ) from error
    if segments[:-1] != _STAGING_SEGMENTS or len(segments) != len(_STAGING_SEGMENTS) + 1:
        raise ValueError(
            "a staging locator must name exactly one run beneath the declared staging location"
        )
    try:
        run = parse_run_id(segments[-1])
    except BundleNamingError as error:
        raise ValueError(f"a staging locator does not name a run id: {error}") from error
    if value != staging_locator_for(run):
        raise ValueError("a staging locator is not in its canonical form")
    return value


StagingLocator = Annotated[str, AfterValidator(_validate_staging_locator)]
"""The only location a worker request may carry: the logical staging directory of its run."""


class WorkerAdapterIdentity(DomainModel):
    """Which adapter implementation an environment offers, and what it claims to support.

    ``engine`` and ``engine_version`` describe the engine family for provenance. They are
    names and versions, never an engine object (ADR-001). ``implementation_digest`` is
    optional because an engine-independent control worker has no engine build to identify;
    a real engine adapter is expected to supply the digest of the adapter or environment
    that will run.
    """

    adapter_id: Name
    adapter_version: Version
    engine: Name
    engine_version: Version
    protocol_version: Literal[1] = WORKER_PROTOCOL_VERSION
    capabilities: Annotated[tuple[Capability, ...], unique_items()] = ()
    implementation_digest: Sha256Hex | None = None


class WorkerRequest(DomainModel):
    """The one message a supervisor writes to a worker's stdin.

    The ``RunSpec`` and fingerprint travel together because either alone is a weaker
    statement: the spec says what to execute, and the fingerprint is the identity the plan
    already published. The model re-computes the fingerprint and refuses a request whose
    two halves disagree, so a request that reaches a worker cannot assert an identity it
    did not derive from the spec it carries.
    """

    schema_version: Literal[1] = WORKER_REQUEST_SCHEMA_VERSION
    protocol_version: Literal[1] = WORKER_PROTOCOL_VERSION
    run_id: RunId
    run_spec: RunSpec
    execution_fingerprint: ExecutionFingerprint
    environment: ResolvedEnvironmentRef
    adapter: WorkerAdapterIdentity
    required_capabilities: Annotated[tuple[Capability, ...], unique_items()] = ()
    supported_capabilities: Annotated[tuple[Capability, ...], unique_items()] = ()
    staging_locator: StagingLocator

    @model_validator(mode="after")
    def _the_request_is_one_execution(self) -> Self:
        if self.execution_fingerprint != run_spec_fingerprint(self.run_spec):
            raise ValueError(
                "the execution fingerprint is not the SHA-256 of the RunSpec the request "
                "carries; a worker request may not assert an identity it did not derive"
            )
        if self.environment != self.run_spec.environment:
            raise ValueError(
                "the request environment is not the environment the RunSpec resolved; "
                "a run may not be launched in an environment it was not planned for"
            )
        if self.supported_capabilities != self.adapter.capabilities:
            raise ValueError(
                "the request's supported capabilities are not the adapter's advertised "
                "capabilities; there may be exactly one capability advertisement"
            )
        missing = sorted(
            capability.value
            for capability in set(self.required_capabilities) - set(self.supported_capabilities)
        )
        if missing:
            raise ValueError(
                f"the adapter does not advertise required capabilities {missing}, so this "
                "request must not be built"
            )
        if self.staging_locator != staging_locator_for(self.run_id):
            raise ValueError(
                "the staging locator is not the declared staging location of this run id"
            )
        return self


class WorkerStatus(StrEnum):
    """The worker's own terminal statement."""

    COMPLETED = "completed"
    FAILED = "failed"


class WorkerResponse(DomainModel):
    """The one message a worker writes to stdout before exiting.

    The response echoes the identities the request supplied. A mismatch is a protocol
    violation, not a warning: a worker that answered about another run, environment or
    adapter did not execute the request it was given.
    """

    schema_version: Literal[1] = WORKER_REQUEST_SCHEMA_VERSION
    protocol_version: Literal[1] = WORKER_PROTOCOL_VERSION
    run_id: RunId
    execution_fingerprint: ExecutionFingerprint
    environment: ResolvedEnvironmentRef
    adapter: WorkerAdapterIdentity
    status: WorkerStatus
    message: ShortText | None = None

    @model_validator(mode="after")
    def _failure_states_a_reason(self) -> Self:
        if self.status is WorkerStatus.FAILED and self.message is None:
            raise ValueError("a failed worker response must state a bounded message")
        return self


class PreflightReport(DomainModel):
    """The operator-visible result of deciding whether a run may start.

    It contains no absolute path, host name, timestamp, process id or scientific verdict.
    ``staging_locator`` is present only when the decision is ``READY``: a refused run has no
    evidence location, because no staging bundle was created for it. ``request_digest`` is
    the semantic digest of the exact canonical request that would be written, so two equal
    admissions produce one identity and a later reader can tie a worker request to the
    preflight that admitted it.
    """

    schema_version: Literal[1] = WORKER_REQUEST_SCHEMA_VERSION
    protocol_version: Literal[1] = WORKER_PROTOCOL_VERSION
    run_id: RunId
    execution_fingerprint: ExecutionFingerprint
    environment: ResolvedEnvironmentRef
    adapter: WorkerAdapterIdentity
    required_capabilities: Annotated[tuple[Capability, ...], unique_items()] = ()
    supported_capabilities: Annotated[tuple[Capability, ...], unique_items()] = ()
    decision: PreflightDecision
    refusals: tuple[Refusal, ...] = ()
    staging_locator: StagingLocator | None = None
    request_digest: SemanticDigest | None = None

    @model_validator(mode="after")
    def _the_decision_is_complete(self) -> Self:
        if self.supported_capabilities != self.adapter.capabilities:
            raise ValueError(
                "the report's supported capabilities are not the adapter's advertised capabilities"
            )
        if self.decision is PreflightDecision.READY:
            if self.refusals:
                raise ValueError("a ready preflight report must not carry refusals")
            if self.staging_locator is None or self.request_digest is None:
                raise ValueError(
                    "a ready preflight report must state its staging locator and request digest"
                )
        else:
            if not self.refusals:
                raise ValueError("a refused preflight report must state at least one reason")
            if self.request_digest is not None:
                raise ValueError("a refused preflight report must not claim a request identity")
        return self


class ExecutionDiagnostic(DomainModel):
    """The bounded payload the supervisor writes as ``diagnostics.json``.

    It records what the supervisor observed about the *process*, not a scientific result.
    There is no numeric output, no native evidence, no canonical quantity, no assessment
    and no claim. A real adapter's native evidence is a later, separately owned concern.
    """

    schema_version: Literal[1] = WORKER_REQUEST_SCHEMA_VERSION
    protocol_version: Literal[1] = WORKER_PROTOCOL_VERSION
    run_id: RunId
    execution_fingerprint: ExecutionFingerprint
    environment: ResolvedEnvironmentRef
    adapter: WorkerAdapterIdentity
    state: RunLifecycleState
    refusals: tuple[Refusal, ...] = ()
    worker_exit_code: int | None = None
    stdin_delivered: bool = False
    process_tree_cleaned: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    log_reference: BundleRelativePath | None = None

    @model_validator(mode="after")
    def _a_diagnostic_is_terminal(self) -> Self:
        if not self.state.terminal:
            raise ValueError("an execution diagnostic records a terminal state only")
        return self


def seal_outcome_for(state: RunLifecycleState, refusals: tuple[Refusal, ...]) -> RunOutcome:
    """The only evidence outcome a terminal observation may be sealed as.

    This is the single definition of the success rule for both an in-process
    :class:`ExecutionResult` and the supervisor's persisted
    :class:`ExecutionDiagnostic`. Keeping it in one place is what stops the returned value
    and the durable record from developing two different notions of success. ``SUCCEEDED``
    requires the narrow process fact — the worker returned a valid response and exited
    zero — and no refusal at all; every other terminal state is evidence of failure.
    """
    if state is RunLifecycleState.COMPLETED and not refusals:
        return RunOutcome.SUCCEEDED
    return RunOutcome.FAILED


class ExecutionResult:
    """What one supervised execution produced, in portable operator terms.

    A frozen value, not a domain model: most of it is runtime observation. It carries a
    staging locator and never a sealed evidence digest, because the supervisor does not
    seal. ``sealed`` is therefore absent rather than false, which is the stronger
    statement: this object cannot be mistaken for a claim that a run is authoritative.

    Immutability is part of the seal boundary rather than a style choice. The terminal state
    and the refusal list are the supervisor's observation, and :attr:`seal_outcome` derives
    the only admissible evidence outcome from them. If a caller could assign
    ``COMPLETED`` or erase a refusal after a failed run, a downstream finalizer would receive
    an object claiming success. Both assignment and deletion are therefore refused.

    This class is a value, not a capability: a caller can construct another one, because
    there is no secret here with which to authenticate it. The sealable authority is the
    supervisor's handle, which privately binds one of these values to the staging bundle it
    was written into and re-verifies the persisted diagnostic before sealing. That
    in-process trust boundary is documented on
    :class:`~dynamisbench.execution.supervisor.SupervisedExecution`.
    """

    __slots__ = (
        "adapter",
        "diagnostic_reference",
        "environment",
        "execution_fingerprint",
        "log_reference",
        "process_tree_cleaned",
        "refusals",
        "run_id",
        "staging",
        "state",
        "stderr_truncated",
        "stdin_delivered",
        "stdout_truncated",
        "worker_exit_code",
        "worker_pid",
        "worker_reaped",
    )

    def __init__(
        self,
        *,
        run_id: RunId,
        execution_fingerprint: ExecutionFingerprint,
        environment: ResolvedEnvironmentRef,
        adapter: WorkerAdapterIdentity,
        state: RunLifecycleState,
        staging: str,
        refusals: tuple[Refusal, ...] = (),
        diagnostic_reference: str | None = None,
        log_reference: str | None = None,
        worker_exit_code: int | None = None,
        worker_pid: int | None = None,
        worker_reaped: bool = False,
        stdin_delivered: bool = False,
        process_tree_cleaned: bool = False,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> None:
        if not state.terminal:
            raise ValueError("an execution result records a terminal state only")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "execution_fingerprint", execution_fingerprint)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "staging", staging)
        object.__setattr__(self, "refusals", tuple(refusals))
        object.__setattr__(self, "diagnostic_reference", diagnostic_reference)
        object.__setattr__(self, "log_reference", log_reference)
        object.__setattr__(self, "worker_exit_code", worker_exit_code)
        object.__setattr__(self, "worker_pid", worker_pid)
        object.__setattr__(self, "worker_reaped", worker_reaped)
        object.__setattr__(self, "stdin_delivered", stdin_delivered)
        object.__setattr__(self, "process_tree_cleaned", process_tree_cleaned)
        object.__setattr__(self, "stdout_truncated", stdout_truncated)
        object.__setattr__(self, "stderr_truncated", stderr_truncated)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(
            "ExecutionResult is immutable: the terminal state and its refusals are the "
            "supervisor's observation and cannot be rewritten"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ExecutionResult is immutable: its terminal facts cannot be deleted")

    @property
    def successful(self) -> bool:
        """Whether the worker returned a valid response and exited zero.

        The same narrow meaning as :attr:`RunLifecycleState.successful`; this is not a
        scientific result and not a sealed artifact.
        """
        return self.state is RunLifecycleState.COMPLETED

    @property
    def seal_outcome(self) -> RunOutcome:
        """The only evidence outcome this execution may be sealed as.

        The supervisor knows whether it observed a completed process; a caller does not
        get to reinterpret a cancelled, timed-out or failed run as a success because the
        staging directory is still mutable. ``SUCCEEDED`` is therefore derived from the
        terminal state and refusals, never supplied by the caller (ADR-008 still owns the
        sealing transaction itself).
        """
        return seal_outcome_for(self.state, self.refusals)

    @property
    def evidence_locator(self) -> str:
        """The portable staging locator an operator can inspect after this result."""
        return self.staging

    def __repr__(self) -> str:
        return (
            f"<ExecutionResult {self.run_id!r} {self.state.value} "
            f"refusals={[item.code.value for item in self.refusals]}>"
        )


def canonical_worker_request_bytes(request: WorkerRequest) -> bytes:
    """The RFC 8785 canonical bytes of one worker request, without the trailing newline.

    The same canonical identity boundary the rest of the project uses is applied to the
    request, so the digest of a request cannot depend on field order, whitespace or the
    serialiser. The supervisor appends exactly one newline when it writes the bytes.
    """
    return canonical_semantic_bytes(request)


def worker_request_digest(request: WorkerRequest) -> SemanticDigest:
    """The semantic digest of the exact request a worker would receive."""
    return semantic_sha256(request)


def canonical_preflight_bytes(report: PreflightReport) -> bytes:
    """The canonical bytes of a preflight report, so two admissions are comparable."""
    return canonical_semantic_bytes(report)


def preflight_digest(report: PreflightReport) -> SemanticDigest:
    """The semantic digest of a preflight report's meaning."""
    return semantic_sha256(report)


def parse_worker_request(raw: bytes) -> WorkerRequest:
    """Parse exactly one bounded request object, or refuse it.

    :raises WorkerProtocolError: if the bytes exceed the message bound, are not UTF-8, are
        not one JSON object, or do not validate as a v1 request.
    """
    return _parse_one_message(raw, WorkerRequest, "request")


def parse_worker_response(raw: bytes) -> WorkerResponse:
    """Parse exactly one bounded response object, or refuse it.

    One trailing newline is accepted because a line-oriented stdout is the normal way a
    worker writes it. Any second line is a protocol violation rather than something to
    ignore, because ignoring one is how a supervisor ends up reading a different message
    from the one the worker meant to send.
    """
    return _parse_one_message(raw, WorkerResponse, "response")


def _parse_one_message[MessageT: (WorkerRequest, WorkerResponse)](
    raw: bytes, model: type[MessageT], what: str
) -> MessageT:
    if len(raw) > MAX_WORKER_MESSAGE_BYTES:
        raise WorkerProtocolError(
            f"the worker {what} is {len(raw)} bytes, larger than the "
            f"{MAX_WORKER_MESSAGE_BYTES}-byte protocol bound"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkerProtocolError(f"the worker {what} is not valid UTF-8: {error}") from error
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if "\n" in text or "\r" in text:
        raise WorkerProtocolError(f"the worker {what} contains more than one line")
    try:
        return model.model_validate_json(text)
    except PydanticValidationError as error:
        raise WorkerProtocolError(
            f"the worker {what} is not valid for protocol v1: {error}"
        ) from error
    except ValueError as error:
        raise WorkerProtocolError(f"the worker {what} is not valid JSON: {error}") from error
