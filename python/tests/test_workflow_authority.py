"""ADR-025 portable-qualification CI authority, enforced by the repository.

ADR-025 makes ephemeral GitHub-hosted runners authoritative for portable software
qualification: Windows x64 and Linux x64 stay distinct qualification targets, each on
an explicitly pinned image, each resolving its own platform environment. Self-hosted
runners are not a higher-authority tier; they exist only for a claim that needs an
environment GitHub cannot represent.

Because these runners are ephemeral and isolated, pull-request code — including code
from a public fork — executes here. Every property that follows from that is a
configuration invariant rather than a review convention, so it is checked here: one
portable qualification workflow, every gate on an approved explicit hosted image,
both platforms present in every gate, nothing routed to a persistent self-hosted
runner, least privilege with no tolerated failures, and published runner-image and
toolchain identity.

These are the gates that stop the ADR-024 model from returning quietly. Re-adding
``self-hosted``, a floating ``-latest`` image, ``pull_request_target``, a write
scope, a secret, ``continue-on-error``, or a second overlapping hosted workflow fails
here rather than waiting to be noticed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

QUALIFICATION_WORKFLOW = "quality.yml"
IDENTITY_JOB = "platform-identity"

# Pinned images, deliberately never ``-latest``: a qualification result has to be
# interpretable against a named runner image. ``self-hosted`` is not a portable
# target under ADR-025, so it cannot be added to this set.
APPROVED_HOSTED_IMAGES = frozenset({"windows-2025", "ubuntu-24.04"})
PORTABLE_TARGETS = frozenset(APPROVED_HOSTED_IMAGES)

# Every one of these must appear in the identity record; the set is what makes a
# hosted result interpretable without asking the runner for anything.
REQUIRED_IDENTITY_KEYS = (
    "github_sha",
    "runner_os",
    "runner_arch",
    "image_os",
    "image_version",
    "python",
    "uv",
    "node",
    "pnpm",
    "rustc",
    "cargo",
)

# Sniffing that existed only to tell the old self-hosted Linux target apart from
# WSL. The Linux qualification target is now a real VM, so none of it is evidence.
OBSOLETE_IDENTITY_PROBES = ("uname", "WSL", "/proc/version", "RUNNER_TEMP")

FORBIDDEN_TRIGGERS = frozenset({"pull_request_target", "workflow_run"})


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[Any, Any]:
    # PyYAML resolves the bare key ``on`` to the boolean ``True``.
    triggers = next((value for key, value in workflow.items() if key in ("on", True)), None)
    return triggers if isinstance(triggers, dict) else {}


def _resolved_images(job: dict[str, Any]) -> list[str]:
    """Every concrete runner image a job can reach, with its matrix expanded.

    Resolving the matrix is the point: an unknown, self-hosted, or floating image
    smuggled into a matrix entry is inspected rather than hidden behind the
    ``${{ matrix.* }}`` expression that names it.
    """
    runs_on = job["runs-on"]
    if isinstance(runs_on, str) and "matrix." in runs_on:
        match = re.search(r"matrix\.([A-Za-z0-9_-]+)", runs_on)
        assert match is not None, f"unresolvable matrix reference: {runs_on!r}"
        axis = match.group(1)
        matrix = job.get("strategy", {}).get("matrix", {})
        included = [entry[axis] for entry in matrix.get("include", []) if axis in entry]
        if included:
            return [str(image) for image in included]
        values = matrix.get(axis)
        assert isinstance(values, list), f"{runs_on!r} names no matrix axis or include entry"
        return [str(image) for image in values]
    labels = [runs_on] if isinstance(runs_on, str) else runs_on
    return [str(label) for label in labels]


def _qualification() -> dict[str, Any]:
    return _load(WORKFLOW_DIR / QUALIFICATION_WORKFLOW)


def _gates() -> dict[str, dict[str, Any]]:
    gates = _qualification()["jobs"]
    assert gates, "the qualification workflow must define portable gates"
    return gates


def test_portable_qualification_is_exactly_one_workflow() -> None:
    """ADR-025 retired the authoritative/self-hosted split.

    The old model needed a second, visibly non-authoritative hosted workflow because
    the authoritative one could not run fork code. Ephemeral runners remove that
    constraint, so a second overlapping hosted workflow would only be a second place
    for the qualification contract to drift.
    """
    workflows = sorted(path.name for path in WORKFLOW_DIR.glob("*.yml"))
    assert workflows == [QUALIFICATION_WORKFLOW]


def test_no_workflow_uses_a_privileged_pull_request_trigger() -> None:
    """``pull_request_target`` runs with a privileged token against untrusted head code."""
    offenders = {
        path.name: sorted(set(_triggers(_load(path))) & FORBIDDEN_TRIGGERS)
        for path in WORKFLOW_DIR.glob("*.yml")
    }
    assert not {name: events for name, events in offenders.items() if events}


def test_every_gate_runs_on_an_approved_explicit_hosted_image() -> None:
    """Portable gates run on GitHub-hosted runners, and nothing else.

    A gate routed to ``self-hosted`` is exactly the ADR-024 model ADR-025 superseded,
    so it is rejected here along with floating ``-latest`` labels and any image that
    is not one this project deliberately pinned.
    """
    unapproved = {
        f"{job_id} -> {image}"
        for job_id, job in _gates().items()
        for image in _resolved_images(job)
        if image not in APPROVED_HOSTED_IMAGES
    }
    assert not unapproved, (
        f"portable gates must name an approved hosted image {sorted(APPROVED_HOSTED_IMAGES)}; "
        f"self-hosted runners are not a portable qualification target: {sorted(unapproved)}"
    )


def test_every_gate_qualifies_on_windows_x64_and_linux_x64() -> None:
    """Cross-platform claims need both platforms, in every gate, not somewhere."""
    partial = {
        job_id: sorted(set(_resolved_images(job)))
        for job_id, job in _gates().items()
        if set(_resolved_images(job)) != PORTABLE_TARGETS
    }
    assert not partial, f"each portable gate must run on {sorted(PORTABLE_TARGETS)}: {partial}"


def test_workflow_permissions_stay_read_only_and_no_gate_tolerates_failure() -> None:
    assert _qualification().get("permissions") == {"contents": "read"}
    tolerated = {job_id for job_id, job in _gates().items() if job.get("continue-on-error")}
    assert not tolerated, f"a qualification gate may not tolerate failure: {tolerated}"
    # Fork code now executes here, so no step may hand the job token to a later step
    # or reach for a secret that fork code could read.
    leaking = [
        f"{job_id} / {step.get('name', step.get('uses'))}"
        for job_id, job in _gates().items()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout")
        and (step.get("with") or {}).get("persist-credentials") is not False
    ]
    assert not leaking, f"checkouts must not persist the job token: {leaking}"
    secret_use = [
        line
        for line in (WORKFLOW_DIR / QUALIFICATION_WORKFLOW).read_text(encoding="utf-8").splitlines()
        if "secrets." in line
    ]
    assert not secret_use, f"hosted qualification must not consume secrets: {secret_use}"


def test_pull_requests_reach_the_matrix_without_a_fork_trust_gate() -> None:
    """Hosted runners are ephemeral, so the ADR-024 fork trust condition is obsolete.

    Gating jobs on ``pull_request.head.repo.full_name == github.repository`` would
    silently drop every fork contribution out of qualification while looking
    deliberate. Pull requests from any repository run the same matrix.
    """
    triggers = _triggers(_qualification())
    assert triggers.get("push", {}).get("branches") == ["main"]
    assert triggers.get("pull_request", {}).get("branches") == ["main"]
    assert "workflow_dispatch" in triggers
    gated = {job_id: job["if"] for job_id, job in _gates().items() if job.get("if")}
    assert not gated, f"hosted ephemeral runners need no fork trust gate: {gated}"


def test_platform_identity_publishes_image_and_toolchain_evidence() -> None:
    """The run must be interpretable after the fact, from the record it left behind."""
    identity = _gates()[IDENTITY_JOB]
    assert set(_resolved_images(identity)) == PORTABLE_TARGETS
    published = [
        step
        for step in identity["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert published, "the identity gate must publish its record as an artifact"
    assert all((step.get("with") or {}).get("if-no-files-found") == "error" for step in published)

    scripts = [
        str(step["run"])
        for step in identity["steps"]
        if step.get("run") and "platform-identity" in str(step["run"])
    ]
    assert scripts, "the identity gate must run the recorder that builds the record"
    recorded = "\n".join(scripts)
    missing = [key for key in REQUIRED_IDENTITY_KEYS if f'"{key}"' not in recorded]
    assert not missing, f"the identity record omits required evidence: {missing}"
    stale = [probe for probe in OBSOLETE_IDENTITY_PROBES if probe in recorded]
    assert not stale, f"hosted Linux is a real VM; obsolete runner probing: {stale}"

    # Runner-local state is not scientific authority: only the identity gate writes
    # a qualification artifact, so no other gate can quietly publish one.
    extra = {
        job_id
        for job_id, job in _gates().items()
        if job_id != IDENTITY_JOB
        and any("upload-artifact" in str(step.get("uses", "")) for step in job["steps"])
    }
    assert not extra, f"only the identity gate may publish qualification artifacts: {extra}"


def test_no_gate_is_marked_non_authoritative() -> None:
    """The hosted/self-hosted authority split is gone, including its vocabulary."""
    workflow = _qualification()
    names = [str(workflow["name"])] + [
        str(job.get("name", job_id)) for job_id, job in _gates().items()
    ]
    marked = [name for name in names if "NON-AUTHORITATIVE" in name]
    assert not marked, f"every gate here is authoritative: {marked}"
