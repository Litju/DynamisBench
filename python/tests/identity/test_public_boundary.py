"""Structural gates on the identity package's public boundary.

Three properties are checked here rather than trusted:

* **Simulator independence (ADR-001).** The canonical-identity path is part of the
  scientific core, so no engine-native library may be reachable from it. The repository
  -wide simulator isolation gate already walks every source file; this gate asserts the
  identity package specifically, so a regression names the boundary that broke.

* **No environment, clock, randomness or filesystem in semantic identity.** A semantic
  digest has to be a function of the validated meaning alone. If ``canonical.py`` or
  ``semantic.py`` could read the clock, a file, an environment variable or a random
  source, then two machines could compute different digests for identical authority and
  the Windows/Linux parity gate would be meaningless. The check is on the import graph,
  so it cannot be defeated by an indirect call.

  ``digests.py`` is exempt, and deliberately so: ``asset_sha256_of_file`` is *supposed*
  to touch the filesystem, because an asset's raw bytes are its identity. What must
  never happen is a *semantic* digest reading anything, and that is what the two modules
  the semantic path runs through are checked for.

* **A closed external surface.** ``pydantic`` and ``rfc8785`` are the entire third-party
  surface of semantic identity. A fourth dependency would change what the digest of
  every validated definition in the project depends on, and has to be a visible event.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import dynamisbench.identity as identity

IDENTITY_ROOT = Path(identity.__file__).resolve().parent

SEMANTIC_PATH_MODULES = ("canonical.py", "semantic.py")
"""The modules a semantic digest is computed through, end to end."""

IDENTITY_MODULES = tuple(sorted(path.name for path in IDENTITY_ROOT.glob("*.py")))

FORBIDDEN_IN_SEMANTIC_IDENTITY = frozenset(
    {
        "datetime",
        "getpass",
        "hashlib",
        "os",
        "pathlib",
        "platform",
        "random",
        "secrets",
        "socket",
        "subprocess",
        "tempfile",
        "time",
        "timeit",
        "uuid",
        "zoneinfo",
    }
)
"""Modules whose use would make a semantic digest depend on something but the meaning.

The filesystem, the clock, the environment, the network and every source of
non-determinism are here. ``locale`` is absent because neither Python's own formatting
nor RFC 8785 consults it; introducing a dependency on it would fail the gate below.
"""

FORBIDDEN_ENGINE_MODULES = frozenset(
    {"mujoco", "opensim", "simtk", "gym", "gymnasium", "pybullet", "brax", "dm_control"}
)

ALLOWED_SEMANTIC_IMPORT_ROOTS = frozenset(
    {
        "collections",
        "dynamisbench",
        "math",
        "typing",
        "pydantic",
        "rfc8785",
    }
)
"""Everything ``canonical.py`` and ``semantic.py`` are allowed to import.

Two of these are third-party: ``pydantic``, through the validated domain model, and
``rfc8785``, the canonical serialiser. The rest are the standard library or this
project. ``hashlib`` is deliberately *not* on this list: a semantic digest is taken over
canonical bytes by ``digests.py``, so the two modules that decide what those bytes are
must not be the ones that hash them.
"""

_IMPORT_PROBE = "\n".join(
    [
        "import sys",
        "import dynamisbench.identity",
        "print('\\n'.join(sorted(sys.modules)))",
    ]
)


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    roots.discard("__future__")
    return roots


@pytest.mark.parametrize("filename", SEMANTIC_PATH_MODULES)
def test_the_semantic_identity_path_imports_nothing_from_the_environment(filename: str) -> None:
    assert not _imported_roots(IDENTITY_ROOT / filename) & FORBIDDEN_IN_SEMANTIC_IDENTITY


@pytest.mark.parametrize("filename", IDENTITY_MODULES)
def test_the_identity_package_imports_no_simulator_library(filename: str) -> None:
    assert not _imported_roots(IDENTITY_ROOT / filename) & FORBIDDEN_ENGINE_MODULES


@pytest.mark.parametrize("filename", SEMANTIC_PATH_MODULES)
def test_the_semantic_identity_path_has_a_closed_external_surface(filename: str) -> None:
    unexpected = _imported_roots(IDENTITY_ROOT / filename) - ALLOWED_SEMANTIC_IMPORT_ROOTS
    assert not unexpected, f"{filename} imports {sorted(unexpected)}"


def test_importing_the_identity_package_loads_no_simulator_library() -> None:
    """A direct-import check is not enough: nothing may be smuggled in transitively
    either, so the package is imported in a fresh interpreter and inspected."""
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE], capture_output=True, text=True, check=True
    )
    loaded = {name.split(".")[0] for name in result.stdout.split()}
    assert not loaded & FORBIDDEN_ENGINE_MODULES


def test_every_advertised_name_exists_and_is_advertised_once() -> None:
    assert len(set(identity.__all__)) == len(identity.__all__)
    for name in identity.__all__:
        assert hasattr(identity, name), f"__all__ advertises {name}, which does not exist"


def test_no_exported_type_is_re_exported_from_another_module() -> None:
    """A class offered under ``dynamisbench.identity`` must be defined there, so its
    identity surface cannot drift into an unrelated module by accident."""
    for name in identity.__all__:
        value = getattr(identity, name)
        if isinstance(value, type):
            assert value.__module__.startswith("dynamisbench.identity"), (
                f"{name} is defined in {value.__module__}"
            )


def test_the_three_identity_modules_are_the_whole_package() -> None:
    """Named so that adding a module is a reviewed change rather than a silent one."""
    assert IDENTITY_MODULES == ("__init__.py", "canonical.py", "digests.py", "semantic.py")
