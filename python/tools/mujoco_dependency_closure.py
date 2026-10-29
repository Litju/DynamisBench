"""Verify the approved worker dependency closure against ``worker-mujoco/uv.lock``.

The worker verifies installed distribution versions at runtime; this tool verifies the next
link: that the approved closure and lockfile hash in
:mod:`dynamisbench.adapters.mujoco.dependencies` are the ones the reviewed lockfile defines.

Run from ``python/``:

    uv run python tools/mujoco_dependency_closure.py
    uv run python tools/mujoco_dependency_closure.py --check

The tool reads only the committed lockfile. It never installs, downloads or mutates an
environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

from dynamisbench.adapters.mujoco import dependencies

__all__ = ["main"]

LOCKFILE: Final = Path(__file__).resolve().parents[1] / "worker-mujoco" / "uv.lock"


def _lock_closure() -> tuple[str, tuple[tuple[str, str], ...]]:
    raw = LOCKFILE.read_bytes()
    document: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    packages: list[tuple[str, str]] = []
    for package in document["package"]:
        source = package.get("source") or {}
        if "virtual" in source:
            continue
        packages.append(
            (
                dependencies.normalise_distribution_name(str(package["name"])),
                str(package["version"]),
            )
        )
    return hashlib.sha256(raw).hexdigest(), tuple(sorted(packages))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the approved closure or lockfile hash is stale",
    )
    arguments = parser.parse_args(argv)
    lockfile_sha256, packages = _lock_closure()
    approved = tuple(
        sorted(
            (
                dependencies.normalise_distribution_name(name),
                version,
            )
            for name, version in dependencies.APPROVED_DEPENDENCIES
        )
    )
    payload = {
        "schema": "dynamisbench.mujoco.lock-closure-verification/1",
        "lockfile": LOCKFILE.as_posix(),
        "lockfile_sha256": lockfile_sha256,
        "approved_lockfile_sha256": dependencies.LOCKFILE_SHA256,
        "packages": [[name, version] for name, version in packages],
        "approved_packages": [[name, version] for name, version in approved],
        "matches": lockfile_sha256 == dependencies.LOCKFILE_SHA256 and packages == approved,
        "closure_digest": dependencies.closure_digest(approved),
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if arguments.check and not payload["matches"]:
        sys.stderr.write(
            "the approved worker dependency closure is stale against worker-mujoco/uv.lock\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
