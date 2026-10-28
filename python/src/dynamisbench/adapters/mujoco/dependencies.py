"""The reviewed dependency closure of the isolated MuJoCo worker environment.

The adapter implementation digest already binds source files, model bytes, native engine
release, Python release and platform. It did not bind the *installed third-party
distribution closure* that executes the run. This module closes that gap without adding a
field to the accepted worker protocol: the closure is folded into the existing
``implementation_digest``.

Three facts are kept apart deliberately:

* **The reviewed lock identity** — :data:`LOCKFILE_SHA256` is the raw-byte SHA-256 of
  ``python/worker-mujoco/uv.lock``. A repository test parses that lockfile, reconstructs the
  closure and compares both values. This is an attestation by the repository and its CI,
  not something the worker can prove from inside its own environment.
* **The approved closure** — :data:`APPROVED_DEPENDENCIES` is the exact
  ``(normalised name, version)`` set a qualified worker may import. It is generated from the
  reviewed lockfile by ``python/tools/mujoco_dependency_closure.py``.
* **The observed closure** — :func:`installed_closure` reads the distributions actually
  installed in the running interpreter with :mod:`importlib.metadata` and refuses a missing,
  extra or differently versioned distribution. This is a real runtime check of distribution
  versions, not a hash of the lockfile.

What runtime verification does **not** prove: it does not authenticate the bytes of an
installed wheel, the wheel's RECORD file, or the Python interpreter binary. A substituted
wheel that reports the approved version would pass this check. Those facts are attested by
the locked ``uv sync --frozen`` installation and the hosted runner identity recorded in the
qualification receipt; a future authority decision would be required to add file-level
attestation. This module never claims more than it checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import metadata
from typing import Final

from dynamisbench.adapters.mujoco import reference
from dynamisbench.identity import JsonValue, canonical_semantic_bytes

__all__ = [
    "APPROVED_DEPENDENCIES",
    "DEPENDENCY_CLOSURE_SCHEMA",
    "LOCKFILE_SHA256",
    "DependencyClosure",
    "DependencyClosureError",
    "closure_digest",
    "dependency_closure_payload",
    "installed_closure",
    "normalise_distribution_name",
    "verify_installed_closure",
]

DEPENDENCY_CLOSURE_SCHEMA: Final = "dynamisbench.mujoco.dependency-closure/1"

LOCKFILE_SHA256: Final = "f939e54b030cbd02c11a346867744340c1e1ccd8f9fbf74432640a0b0fcd4c99"
"""Raw-byte SHA-256 of the reviewed ``python/worker-mujoco/uv.lock``.

Changing the lockfile is a reviewed environment change: regenerate the approved closure and
this value with ``python/tools/mujoco_dependency_closure.py``.
"""

APPROVED_DEPENDENCIES: Final[tuple[tuple[str, str], ...]] = (
    ("absl-py", "2.5.1"),
    ("annotated-doc", "0.0.5"),
    ("annotated-types", "0.8.0"),
    ("anyio", "4.15.1"),
    ("click", "8.5.0"),
    ("dynamisbench", "0.0.0"),
    ("etils", "1.14.0"),
    ("fastapi", "0.162.0"),
    ("fsspec", "2026.9.0"),
    ("glfw", "2.11.0"),
    ("h11", "0.16.0"),
    ("idna", "3.20"),
    ("mujoco", "3.17.0"),
    ("numpy", "2.5.4"),
    ("opentelemetry-api", "1.45.1"),
    ("pyarrow", "26.0.0"),
    ("pydantic", "2.14.1"),
    ("pydantic-core", "2.50.1"),
    ("pyopengl", "3.1.10"),
    ("pyyaml", "6.0.3"),
    ("rfc8785", "0.1.4"),
    ("starlette", "1.10.0"),
    ("typing-extensions", "4.16.0"),
    ("typing-inspection", "0.4.4"),
    ("uvicorn", "0.54.0"),
    ("websockets", "17.3"),
    ("zipp", "4.1.2"),
)
"""The exact registry closure of the worker lockfile, plus the editable ``dynamisbench``.

The virtual ``dynamisbench-mujoco-environment`` project is not an installed distribution and
is deliberately absent. Names are normalised with :pep:`503` rules so a metadata spelling
such as ``PyOpenGL`` and a lockfile spelling such as ``pyopengl`` are one package.
"""


class DependencyClosureError(reference.ReferenceAdapterError):
    """The running interpreter does not contain the approved dependency closure."""


_DISTRIBUTION_NAME = re.compile(r"[-_.]+")


def normalise_distribution_name(name: str) -> str:
    """Return the :pep:`503` normalised distribution name."""
    return _DISTRIBUTION_NAME.sub("-", name).lower()


def _approved_map() -> dict[str, str]:
    return {normalise_distribution_name(name): version for name, version in APPROVED_DEPENDENCIES}


def dependency_closure_payload(
    packages: tuple[tuple[str, str], ...],
) -> dict[str, JsonValue]:
    """The canonical payload whose SHA-256 names one installed closure."""
    return {
        "schema": DEPENDENCY_CLOSURE_SCHEMA,
        "lockfile_sha256": LOCKFILE_SHA256,
        "packages": [[name, version] for name, version in packages],
    }


def closure_digest(packages: tuple[tuple[str, str], ...]) -> str:
    """The SHA-256 of the reviewed lock identity and the exact package versions."""
    import hashlib

    return hashlib.sha256(
        canonical_semantic_bytes(dependency_closure_payload(packages))
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class DependencyClosure:
    """One verified closure and the canonical payload that identifies it."""

    packages: tuple[tuple[str, str], ...]

    @property
    def digest(self) -> str:
        return closure_digest(self.packages)

    def as_json_object(self) -> dict[str, object]:
        return {
            **dependency_closure_payload(self.packages),
            "digest": self.digest,
        }


def _observed_versions() -> dict[str, str]:
    """Every installed distribution in the running interpreter, normalised and bounded."""
    observed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            raise DependencyClosureError(
                "an installed distribution has no Name metadata, so the dependency closure "
                "cannot be established"
            )
        normalised = normalise_distribution_name(name)
        previous = observed.get(normalised)
        if previous is not None and previous != distribution.version:
            raise DependencyClosureError(
                f"two installed distributions normalise to {normalised!r} with different "
                "versions; the dependency closure is ambiguous"
            )
        observed[normalised] = distribution.version
    return observed


def verify_installed_closure(
    versions: dict[str, str] | None = None,
) -> DependencyClosure:
    """Verify that the installed distributions are exactly the approved closure.

    ``versions`` is an injection point for the engine-independent qualification suite. In a
    worker it is omitted and the running interpreter is inspected with
    :mod:`importlib.metadata`.

    :raises DependencyClosureError: if any approved distribution is missing, any installed
        distribution is not approved, or an approved distribution has another version.
    """
    observed = (
        _observed_versions()
        if versions is None
        else {normalise_distribution_name(name): version for name, version in versions.items()}
    )
    approved = _approved_map()
    missing = sorted(set(approved) - set(observed))
    extra = sorted(set(observed) - set(approved))
    mismatched = sorted(
        name for name in set(approved) & set(observed) if approved[name] != observed[name]
    )
    if missing or extra or mismatched:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unapproved {extra}")
        if mismatched:
            details.append(
                "version mismatch "
                + ", ".join(
                    f"{name}=={observed[name]} (approved {approved[name]})" for name in mismatched
                )
            )
        raise DependencyClosureError(
            "the installed dependency closure is not the qualified worker environment: "
            + "; ".join(details)
        )
    return DependencyClosure(packages=APPROVED_DEPENDENCIES)


def installed_closure() -> DependencyClosure:
    """Return the verified installed closure, or refuse."""
    return verify_installed_closure()
