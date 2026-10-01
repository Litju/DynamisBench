"""DynamisBench scientific core and application package root.

DB-1.1 (RES-227) establishes this package and its module boundaries only; no
scientific implementation exists yet. Scientific and architectural authority is
the Linear project P-RES-35, not this docstring.

Engine-native simulator libraries must never be imported from this package
(ADR-001). ``tests/test_simulator_isolation.py`` enforces that invariant.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dynamisbench")
except PackageNotFoundError:  # pragma: no cover - only reachable outside an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
