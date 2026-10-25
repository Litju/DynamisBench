"""Fail-closed admission of one RunSpec to one explicitly selected worker environment.

Preflight is the last point at which a run can be refused without side effects. It reads
the exact definitions the RunSpec resolved, re-derives the execution fingerprint, checks
that the selected environment is the environment the plan named, checks that the adapter
advertises every capability the plan required, checks that the realization's declared
assets are present and content-addressed, checks that the run id is not already in use,
and checks that the fixed worker program exists. Only then does it build a
:class:`~dynamisbench.execution.contracts.WorkerRequest`.

Three properties are deliberate.

**It is read-only.** Preflight creates no staging directory, writes no file, starts no
process, reads no clock and reaches no network. A refused run therefore leaves the
workspace exactly as it found it, and a caller can preflight speculatively.

**It re-checks authority rather than trusting the planner.** Planning already refused an
unsupported capability, but preflight is a separate process boundary and receives its
inputs again. Re-deriving the fingerprint and re-comparing the realization and environment
semantic digests means a tampered or accidentally substituted definition cannot ride on a
plan that was computed from different content.

**It reports every independent refusal it can.** An operator diagnosing an unrunnable
configuration wants to see that the environment is wrong *and* that an asset is missing,
not to fix one problem, retry, and discover the next. Checks that depend on an earlier
failure — building the request, for example — are skipped because their result would be
meaningless.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError

from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.evidence.bundle import RunId, parse_run_id
from dynamisbench.execution.contracts import (
    ExecutionError,
    PreflightDecision,
    PreflightReport,
    Refusal,
    RefusalCode,
    WorkerRequest,
    refusal,
    staging_locator_for,
    worker_request_digest,
)
from dynamisbench.execution.environment import (
    WorkerEnvironmentError,
    WorkerEnvironmentManifest,
    resolved_worker_program,
)
from dynamisbench.identity import AssetAccessError, asset_sha256_of_file, semantic_sha256
from dynamisbench.planning.runspec import ExecutionFingerprint, RunSpec, run_spec_fingerprint
from dynamisbench.workspace.authority import PathScopeError, PersistenceClass
from dynamisbench.workspace.paths import resolve_within
from dynamisbench.workspace.workspace import Workspace

__all__ = [
    "PreflightRefusedError",
    "PreflightedRun",
    "preflight_run",
]


class PreflightRefusedError(ExecutionError):
    """A caller tried to execute a run that preflight did not admit.

    The report is carried on the error so an operator can read every refusal, rather than a
    single sentence that names whichever check happened first.
    """

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        reasons = "; ".join(item.message for item in report.refusals)
        super().__init__(
            f"run {report.run_id!r} was refused by preflight" + (f": {reasons}" if reasons else "")
        )


@dataclass(frozen=True, slots=True)
class PreflightedRun:
    """A ready admission together with the exact request it would write.

    The request is ``None`` for a refused admission, and the supervisor refuses to execute
    one. Keeping the report and the request together means the bytes that will be written
    are the bytes whose digest the report published.
    """

    report: PreflightReport
    request: WorkerRequest | None
    manifest: WorkerEnvironmentManifest
    workspace: Workspace

    @property
    def ready(self) -> bool:
        """Whether this admission may be handed to the supervisor."""
        return self.report.decision is PreflightDecision.READY and self.request is not None


def _identity_refusals(
    run_spec: RunSpec,
    realization: RealizationDefinition,
    environment: EnvironmentDefinition,
    manifest: WorkerEnvironmentManifest,
) -> list[Refusal]:
    """Compare every resolved identity the RunSpec carries with the definitions supplied."""
    refusals: list[Refusal] = []
    expected_realization = run_spec.realization
    if (
        str(realization.realization_id) != str(expected_realization.identifier)
        or realization.version != expected_realization.version
        or semantic_sha256(realization) != expected_realization.semantic_digest
    ):
        refusals.append(
            refusal(
                RefusalCode.REALIZATION_IDENTITY_MISMATCH,
                "the supplied realization is not the realization this RunSpec resolved",
            )
        )

    expected_environment = run_spec.environment
    if (
        str(environment.environment_id) != str(expected_environment.identifier)
        or environment.version != expected_environment.version
        or semantic_sha256(environment) != expected_environment.semantic_digest
    ):
        refusals.append(
            refusal(
                RefusalCode.ENVIRONMENT_IDENTITY_MISMATCH,
                "the supplied environment definition is not the environment this RunSpec resolved",
            )
        )
    if manifest.environment != expected_environment:
        refusals.append(
            refusal(
                RefusalCode.ENVIRONMENT_IDENTITY_MISMATCH,
                "the selected worker environment manifest is not the environment this "
                "RunSpec resolved",
            )
        )
    if manifest.adapter.engine != realization.engine.engine:
        refusals.append(
            refusal(
                RefusalCode.ADAPTER_ENGINE_MISMATCH,
                "the selected worker adapter is for a different engine than the realization binds",
            )
        )
    return refusals


def _normalise_required_capabilities(
    required: Iterable[Capability | str],
) -> tuple[tuple[Capability, ...], list[Refusal]]:
    """Coerce the plan's requirements to the closed capability vocabulary, or refuse."""
    normalised: dict[str, Capability] = {}
    refusals: list[Refusal] = []
    for item in required:
        if isinstance(item, Capability):
            normalised[item.value] = item
            continue
        try:
            capability = Capability(item)
        except ValueError:
            refusals.append(
                refusal(
                    RefusalCode.UNKNOWN_CAPABILITY,
                    "a required capability is not in the closed engine-independent vocabulary",
                )
            )
            continue
        normalised[capability.value] = capability
    return tuple(normalised[key] for key in sorted(normalised)), refusals


def _capability_refusals(
    required: tuple[Capability, ...],
    manifest: WorkerEnvironmentManifest,
    realization: RealizationDefinition,
) -> list[Refusal]:
    """Require both the adapter and the realization to advertise every essential capability.

    Planning already checked the realization advertisement. This second check is not
    redundant: preflight receives the definition again, and a realization swapped after
    planning would otherwise be admitted on the strength of the earlier object.
    """
    supported = set(manifest.adapter.capabilities)
    advertised = {declaration.capability for declaration in realization.capabilities}
    missing_from_adapter = sorted(capability.value for capability in set(required) - supported)
    missing_from_realization = sorted(capability.value for capability in set(required) - advertised)
    refusals: list[Refusal] = []
    if missing_from_adapter:
        refusals.append(
            refusal(
                RefusalCode.UNSUPPORTED_CAPABILITY,
                "the selected worker environment does not advertise required capabilities "
                + ", ".join(missing_from_adapter),
            )
        )
    if missing_from_realization:
        refusals.append(
            refusal(
                RefusalCode.UNSUPPORTED_CAPABILITY,
                "the realization does not advertise required capabilities "
                + ", ".join(missing_from_realization),
            )
        )
    return refusals


def _asset_refusals(workspace: Workspace, realization: RealizationDefinition) -> list[Refusal]:
    """Require every declared realization asset to be a present, content-addressed file.

    The asset path is workspace-relative authority, so it is resolved through the one
    workspace containment function rather than joined by hand. A missing asset is refused
    before a worker starts, which is the difference between an admission decision and a
    simulator crash halfway through a run.
    """
    refusals: list[Refusal] = []
    for asset in realization.assets:
        try:
            path = resolve_within(
                workspace.source_root,
                asset.path,
                authorized_roots=(workspace.source_root,),
                persistence_class=PersistenceClass.SOURCE_AUTHORITY,
            )
        except PathScopeError:
            refusals.append(
                refusal(
                    RefusalCode.FORBIDDEN_PATH,
                    f"asset {asset.asset_id!r} resolves outside the source root",
                )
            )
            continue
        if not path.is_file():
            refusals.append(
                refusal(
                    RefusalCode.UNSTAGED_ASSET,
                    f"asset {asset.asset_id!r} is not present in the source root",
                )
            )
            continue
        if asset.sha256 is None:
            continue
        try:
            digest = asset_sha256_of_file(path)
        except AssetAccessError:
            refusals.append(
                refusal(
                    RefusalCode.UNSTAGED_ASSET,
                    f"asset {asset.asset_id!r} could not be read to establish its identity",
                )
            )
            continue
        if digest.hex != asset.sha256:
            refusals.append(
                refusal(
                    RefusalCode.ASSET_DIGEST_MISMATCH,
                    f"asset {asset.asset_id!r} does not match the digest its realization declares",
                )
            )
    return refusals


def _duplicate_refusals(workspace: Workspace, run: RunId) -> list[Refusal]:
    """Refuse a run id that already has staging or sealed evidence.

    Checked without creating anything. The check is repeated by the supervisor when it
    creates the staging bundle, because preflight is read-only and the two calls are not
    one transaction.
    """
    for persistence_class, description in (
        (PersistenceClass.STAGING, "staging"),
        (PersistenceClass.SEALED_EVIDENCE, "sealed evidence"),
    ):
        path = workspace.resolve(persistence_class, run)
        if path.exists() or path.is_symlink():
            return [
                refusal(
                    RefusalCode.DUPLICATE_EXECUTION,
                    f"run {run!r} already has a {description} directory; one run id is one "
                    "execution and is never reused",
                )
            ]
    return []


def preflight_run(
    run_id: RunId,
    run_spec: RunSpec,
    fingerprint: ExecutionFingerprint,
    *,
    realization: RealizationDefinition,
    environment: EnvironmentDefinition,
    manifest: WorkerEnvironmentManifest,
    workspace: Workspace,
    required_capabilities: Iterable[Capability | str],
) -> PreflightedRun:
    """Decide whether one exact run may be handed to one exact worker environment.

    :param run_id: the human/logical identity of this execution. It must not already name
        a staging or sealed directory.
    :param run_spec: the exact planned inputs.
    :param fingerprint: the execution identity the plan published for ``run_spec``.
    :param realization: the validated realization the RunSpec resolved. Its semantic
        digest must equal the RunSpec's.
    :param environment: the validated environment the RunSpec resolved.
    :param manifest: the operational environment selection: adapter identity, capabilities,
        fixed command, timeout, log bound and explicit environment variables.
    :param workspace: the workspace whose source root holds the realization's assets and
        whose staging and sealed locations decide duplicate-run refusal.
    :param required_capabilities: the effective essential capabilities planning derived
        for this candidate. Preflight re-checks them against both the adapter and the
        realization.

    :raises BundleNamingError: if ``run_id`` is not a run id.
    """
    run = parse_run_id(run_id)
    required, refusals = _normalise_required_capabilities(required_capabilities)

    if fingerprint != run_spec_fingerprint(run_spec):
        refusals.append(
            refusal(
                RefusalCode.FINGERPRINT_MISMATCH,
                "the supplied execution fingerprint is not the SHA-256 of the RunSpec meaning",
            )
        )
    refusals.extend(_identity_refusals(run_spec, realization, environment, manifest))
    refusals.extend(_capability_refusals(required, manifest, realization))
    refusals.extend(_asset_refusals(workspace, realization))
    refusals.extend(_duplicate_refusals(workspace, run))

    try:
        resolved_worker_program(manifest)
    except WorkerEnvironmentError:
        refusals.append(
            refusal(
                RefusalCode.WORKER_PROGRAM_UNRESOLVED,
                "the selected worker program is not an existing executable file; no fallback "
                "program is attempted",
            )
        )

    request: WorkerRequest | None = None
    if not refusals:
        try:
            request = WorkerRequest(
                run_id=run,
                run_spec=run_spec,
                execution_fingerprint=fingerprint,
                environment=run_spec.environment,
                adapter=manifest.adapter,
                required_capabilities=required,
                supported_capabilities=manifest.adapter.capabilities,
                staging_locator=staging_locator_for(run),
            )
        except PydanticValidationError as error:
            refusals.append(
                refusal(
                    RefusalCode.INVALID_RUN_SPEC,
                    f"the run cannot be expressed as a worker request: {error}",
                )
            )

    decision = PreflightDecision.REFUSED if refusals else PreflightDecision.READY
    report = PreflightReport(
        run_id=run,
        execution_fingerprint=fingerprint,
        environment=run_spec.environment,
        adapter=manifest.adapter,
        required_capabilities=required,
        supported_capabilities=manifest.adapter.capabilities,
        decision=decision,
        refusals=tuple(refusals),
        staging_locator=staging_locator_for(run) if request is not None else None,
        request_digest=worker_request_digest(request) if request is not None else None,
    )
    return PreflightedRun(
        report=report,
        request=request,
        manifest=manifest,
        workspace=workspace,
    )
