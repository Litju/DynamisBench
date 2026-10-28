"""Dependency-closure qualification for the isolated MuJoCo worker environment."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any

import pytest

from dynamisbench.adapters.mujoco import dependencies
from dynamisbench.adapters.mujoco.dependencies import (
    DependencyClosureError,
    closure_digest,
    verify_installed_closure,
)

WORKER_PROJECT = Path(__file__).resolve().parents[3] / "worker-mujoco"


def _lock_closure() -> tuple[str, tuple[tuple[str, str], ...]]:
    raw = (WORKER_PROJECT / "uv.lock").read_bytes()
    document: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    packages = tuple(
        sorted(
            (
                dependencies.normalise_distribution_name(str(package["name"])),
                str(package["version"]),
            )
            for package in document["package"]
            if "virtual" not in (package.get("source") or {})
        )
    )
    return hashlib.sha256(raw).hexdigest(), packages


def _approved() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                dependencies.normalise_distribution_name(name),
                version,
            )
            for name, version in dependencies.APPROVED_DEPENDENCIES
        )
    )


def test_the_approved_closure_is_the_reviewed_lockfile() -> None:
    lockfile_sha256, packages = _lock_closure()

    assert lockfile_sha256 == dependencies.LOCKFILE_SHA256
    assert packages == _approved()


def test_the_worker_identity_reports_the_approved_closure(mujoco_identity: dict) -> None:
    closure = mujoco_identity["dependency_closure"]

    assert closure["schema"] == dependencies.DEPENDENCY_CLOSURE_SCHEMA
    assert closure["lockfile_sha256"] == dependencies.LOCKFILE_SHA256
    assert tuple(tuple(item) for item in closure["packages"]) == _approved()
    assert closure["digest"] == closure_digest(_approved())


def test_the_approved_closure_is_accepted() -> None:
    """The success path is injected; the app runtime is not the worker environment.

    The real installed-environment check runs inside the worker when it computes its
    identity, and ``test_the_worker_identity_reports_the_approved_closure`` proves that the
    reported closure is the approved one.
    """
    versions = {
        dependencies.normalise_distribution_name(name): version
        for name, version in dependencies.APPROVED_DEPENDENCIES
    }
    closure = verify_installed_closure(versions)

    assert closure.packages == dependencies.APPROVED_DEPENDENCIES
    assert closure.digest == closure_digest(dependencies.APPROVED_DEPENDENCIES)


def test_a_missing_distribution_is_refused() -> None:
    versions = {
        dependencies.normalise_distribution_name(name): version
        for name, version in dependencies.APPROVED_DEPENDENCIES
        if name != "numpy"
    }
    with pytest.raises(DependencyClosureError, match="missing"):
        verify_installed_closure(versions)


def test_an_extra_distribution_is_refused() -> None:
    versions = {
        dependencies.normalise_distribution_name(name): version
        for name, version in dependencies.APPROVED_DEPENDENCIES
    }
    versions["unapproved-package"] = "1.0.0"
    with pytest.raises(DependencyClosureError, match="unapproved"):
        verify_installed_closure(versions)


def test_a_different_installed_version_is_refused() -> None:
    versions = {
        dependencies.normalise_distribution_name(name): version
        for name, version in dependencies.APPROVED_DEPENDENCIES
    }
    versions["mujoco"] = "3.17.1"
    with pytest.raises(DependencyClosureError, match="version mismatch"):
        verify_installed_closure(versions)


def test_a_case_or_separator_spelling_is_one_distribution() -> None:
    assert dependencies.normalise_distribution_name("PyOpenGL") == "pyopengl"
    assert dependencies.normalise_distribution_name("pydantic_core") == "pydantic-core"
    assert dependencies.normalise_distribution_name("typing_extensions") == "typing-extensions"
    assert dependencies.normalise_distribution_name("PyYAML") == "pyyaml"


def test_the_closure_digest_binds_lock_identity_and_every_version() -> None:
    approved = _approved()
    changed = tuple(
        ("numpy", "9.9.9") if name == "numpy" else (name, version) for name, version in approved
    )

    assert closure_digest(changed) != closure_digest(approved)
