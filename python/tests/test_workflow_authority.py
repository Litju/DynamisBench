"""ADR-024 CI authority and trust-boundary gates, enforced by the repository.

ADR-024 makes dedicated self-hosted runners the only authority for full DynamisBench
qualification. A GitHub-hosted success must never be readable as a qualification, an
unavailable self-hosted runner must not fall back to a hosted runner, and untrusted
fork pull-request code must never execute on a persistent self-hosted machine.

Those three properties are configuration invariants, so they are checked here rather
than left to code review. A change that routes an authoritative gate onto a hosted
runner, drops the explicit ``dynamisbench`` label, removes a pull-request trust
condition, or reintroduces ``pull_request_target`` fails this gate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

AUTHORITATIVE_WORKFLOW = "quality.yml"
NON_AUTHORITATIVE_WORKFLOW = "smoke-hosted.yml"

# An authoritative job may only name GitHub's self-hosted default labels plus the
# DynamisBench label. Anything else -- ``windows-latest``, ``ubuntu-24.04``, a bare
# ``self-hosted`` pool, a hypothetical hosted image -- is rejected, so a hosted
# fallback cannot be introduced by editing a label list.
ALLOWED_SELF_HOSTED_LABELS = frozenset(
    {"self-hosted", "linux", "windows", "macos", "x64", "arm", "arm64", "dynamisbench"}
)

HOSTED_LABEL_PATTERNS = (
    re.compile(r"^ubuntu(-|$)"),
    re.compile(r"^windows(-|$)"),
    re.compile(r"^macos(-|$)"),
)

NON_AUTHORITATIVE_MARKER = "NON-AUTHORITATIVE"

TRUST_EXPRESSION_FRAGMENTS = ("pull_request.head.repo.full_name", "github.repository")


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[Any, Any]:
    # PyYAML resolves the bare key ``on`` to the boolean ``True``.
    triggers = next((value for key, value in workflow.items() if key in ("on", True)), None)
    return triggers if isinstance(triggers, dict) else {}


def _labels_of(runs_on: Any) -> frozenset[str]:
    if isinstance(runs_on, str):
        return frozenset({runs_on})
    if isinstance(runs_on, list):
        return frozenset(runs_on)
    raise AssertionError(f"unsupported runs-on value: {runs_on!r}")


def _resolved_label_sets(workflow: dict[str, Any], job: dict[str, Any]) -> list[frozenset[str]]:
    """Every concrete label set a job can route to, with the matrix expanded.

    A job whose ``runs-on`` is a ``${{ matrix.* }}`` reference is resolved against the
    matrix so that a hosted entry smuggled into the matrix is inspected rather than
    hidden behind the expression.
    """
    runs_on = job["runs-on"]
    if not (isinstance(runs_on, str) and "matrix." in runs_on):
        return [_labels_of(runs_on)]
    match = re.search(r"matrix\.([A-Za-z0-9_-]+)", runs_on)
    assert match is not None, f"unresolvable matrix reference: {runs_on!r}"
    key = match.group(1)
    matrix = job.get("strategy", {}).get("matrix", {})
    overrides = [entry[key] for entry in matrix.get("include", []) if key in entry]
    if overrides:
        return [_labels_of(value) for value in overrides]
    axis = matrix.get(key)
    assert isinstance(axis, list), f"{runs_on!r} names no matrix axis or include entry"
    return [_labels_of(value) for value in axis]


def _authoritative_jobs() -> dict[str, dict[str, Any]]:
    workflow = _load(WORKFLOW_DIR / AUTHORITATIVE_WORKFLOW)
    return workflow["jobs"]


def test_repository_defines_both_workflows() -> None:
    assert AUTHORITATIVE_WORKFLOW in {p.name for p in WORKFLOW_DIR.glob("*.yml")}
    assert NON_AUTHORITATIVE_WORKFLOW in {p.name for p in WORKFLOW_DIR.glob("*.yml")}


def test_no_workflow_uses_pull_request_target_or_workflow_run() -> None:
    """``pull_request_target`` runs with a privileged token and is the documented way
    to execute untrusted fork code on a self-hosted runner. It is never acceptable."""
    offenders = {
        path.name: sorted(set(_triggers(_load(path))) & {"pull_request_target", "workflow_run"})
        for path in WORKFLOW_DIR.glob("*.yml")
    }
    assert not {name: events for name, events in offenders.items() if events}


def test_authoritative_workflow_routes_every_job_to_dedicated_self_hosted_runners() -> None:
    jobs = _authoritative_jobs()
    assert jobs, "the authoritative workflow must define qualification jobs"
    offenders: dict[str, list[str]] = {}
    for job_id, job in jobs.items():
        for labels in _resolved_label_sets({}, job):
            unknown = {label for label in labels if label.lower() not in ALLOWED_SELF_HOSTED_LABELS}
            missing = [
                required
                for required in ("self-hosted", "dynamisbench")
                if required not in {label.lower() for label in labels}
            ]
            if unknown or missing:
                offenders[f"{job_id} -> {sorted(labels)}"] = sorted(unknown) + sorted(
                    f"missing:{item}" for item in missing
                )
    assert not offenders, f"authoritative jobs left the dedicated runner set: {offenders}"


def test_authoritative_workflow_requires_both_platforms() -> None:
    labels = {
        label.lower()
        for job in _authoritative_jobs().values()
        for label_set in _resolved_label_sets({}, job)
        for label in label_set
    }
    assert "windows" in labels, "no Windows x64 self-hosted qualification gate"
    assert "linux" in labels, "no Linux x64 self-hosted qualification gate"
    assert "x64" in labels, "authoritative qualification must be x86-64"


def test_authoritative_workflow_is_reachable_only_from_trusted_refs() -> None:
    triggers = _triggers(_load(WORKFLOW_DIR / AUTHORITATIVE_WORKFLOW))
    assert triggers.get("push", {}).get("branches") == ["main"]
    assert "workflow_dispatch" in triggers
    assert "pull_request" in triggers, "the trust boundary is only meaningful for pull requests"

    ungated = {
        job_id
        for job_id, job in _authoritative_jobs().items()
        if not all(fragment in (job.get("if") or "") for fragment in TRUST_EXPRESSION_FRAGMENTS)
    }
    assert not ungated, f"pull-request-triggered authoritative jobs without a trust gate: {ungated}"


def test_authoritative_workflow_fails_closed_and_uses_read_only_permissions() -> None:
    workflow = _load(WORKFLOW_DIR / AUTHORITATIVE_WORKFLOW)
    assert workflow.get("permissions") == {"contents": "read"}
    tolerated = {job_id for job_id, job in workflow["jobs"].items() if job.get("continue-on-error")}
    assert not tolerated, f"authoritative gates may not tolerate failure: {tolerated}"
    persisted = [
        step.get("uses", "")
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout")
        and (step.get("with") or {}).get("persist-credentials") is not False
    ]
    assert not persisted, "checkouts on persistent runners must not persist the job token"


def test_authoritative_gates_emit_runner_identity_evidence() -> None:
    """ADR-024 requires the runner OS/architecture and relevant toolchain identity in
    qualification evidence. A dedicated identity gate publishes it as an artifact."""
    jobs = _authoritative_jobs()
    identity = jobs["platform-identity"]
    assert identity["runs-on"], "the identity gate must run on a dedicated runner"
    artifacts = [
        step
        for step in identity["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert artifacts, "the identity gate must publish its record as an artifact"
    assert not any(step.get("uses") == "actions/cache" for step in identity["steps"])


def test_non_authoritative_workflow_is_visibly_non_authoritative_and_hosted_only() -> None:
    workflow = _load(WORKFLOW_DIR / NON_AUTHORITATIVE_WORKFLOW)
    assert NON_AUTHORITATIVE_MARKER in str(workflow["name"])
    for job_id, job in workflow["jobs"].items():
        assert NON_AUTHORITATIVE_MARKER in str(job.get("name", job_id)), job_id
        for labels in _resolved_label_sets(workflow, job):
            lowered = {label.lower() for label in labels}
            assert "self-hosted" not in lowered, f"{job_id} must not touch a persistent runner"
            assert any(
                pattern.match(label) for pattern in HOSTED_LABEL_PATTERNS for label in labels
            ), f"{job_id} does not route to a recognised GitHub-hosted label: {sorted(labels)}"


def test_no_non_authoritative_job_can_shadow_an_authoritative_gate_name() -> None:
    """A hosted job sharing a required-check name with an authoritative gate would let
    a hosted result stand in for the qualification."""
    authoritative = {str(job.get("name", job_id)) for job_id, job in _authoritative_jobs().items()}
    hosted = _load(WORKFLOW_DIR / NON_AUTHORITATIVE_WORKFLOW)["jobs"]
    collisions = {str(job.get("name", job_id)) for job_id, job in hosted.items()} & authoritative
    assert not collisions, f"hosted smoke jobs collide with authoritative gate names: {collisions}"


def test_authoritative_workflow_has_no_gateway_step() -> None:
    """Only the identity gate records provenance; the qualification gates must not write
    scientific authority into runner-local state."""
    jobs = _authoritative_jobs()
    for job_id, job in jobs.items():
        if job_id == "platform-identity":
            continue
        assert not any("upload-artifact" in str(step.get("uses", "")) for step in job["steps"]), (
            job_id
        )
