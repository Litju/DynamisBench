"""ADR-001 and ADR-004 gates for the DB-1.1 bootstrap.

Two independent guarantees are checked:

* no simulator library is imported by importing the core package or any module
  boundary;
* no simulator library or control-plane service is declared as a dependency.

A third check fails if a boundary required by the architecture authority is missing,
so the bootstrap cannot silently drop a module.
"""

from __future__ import annotations

import ast
import functools
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "dynamisbench"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

BOUNDARIES = (
    "domain.spec",
    "execution",
    "adapters",
    "planning",
    "normalization",
    "evaluation",
    "evidence",
    "query",
    "api",
)

FORBIDDEN_SIMULATOR_MODULES = frozenset(
    {"mujoco", "opensim", "simtk", "gym", "gymnasium", "pybullet", "brax", "dm_control"}
)
FORBIDDEN_SERVICE_DEPENDENCIES = frozenset(
    {
        "airflow",
        "celery",
        "dagster",
        "kafka",
        "mlflow",
        "postgres",
        "prefect",
        "ray",
        "redis",
        "sqlalchemy",
    }
)
FORBIDDEN_ROOT_MODULES = FORBIDDEN_SIMULATOR_MODULES | FORBIDDEN_SERVICE_DEPENDENCIES

_IMPORT_PROBE = "\n".join(
    [
        "import importlib",
        "import sys",
        "import dynamisbench",
        f"for name in {BOUNDARIES!r}:",
        "    importlib.import_module(f'dynamisbench.{name}')",
        "print('\\n'.join(sorted(sys.modules)))",
    ]
)


@functools.lru_cache(maxsize=1)
def loaded_modules_after_core_import() -> frozenset[str]:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(result.stdout.split())


def test_import_probe_covers_every_required_boundary() -> None:
    loaded = loaded_modules_after_core_import()
    assert "dynamisbench" in loaded
    missing = [boundary for boundary in BOUNDARIES if f"dynamisbench.{boundary}" not in loaded]
    assert not missing


@given(st.sampled_from(sorted(FORBIDDEN_SIMULATOR_MODULES)))
def test_importing_the_core_never_loads_a_simulator_library(module_name: str) -> None:
    assert module_name not in loaded_modules_after_core_import()


def test_source_files_contain_no_simulator_import_statements() -> None:
    offenders: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        forbidden = roots & FORBIDDEN_SIMULATOR_MODULES
        if forbidden:
            offenders[path.name] = forbidden
    assert not offenders


def test_declared_dependencies_exclude_simulators_and_control_plane_services() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    declared: set[str] = set()
    for requirement in project["dependencies"]:
        declared.update(re.split(r"[-_.]+", requirement.lower()))
    assert not declared & FORBIDDEN_ROOT_MODULES
