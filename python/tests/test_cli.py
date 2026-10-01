"""Smoke gate for the ``dbench`` command line.

Qualifies that a fresh Windows-native or Linux checkout can install the locked
environment and run the CLI behaviourally.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from dynamisbench import __version__

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dynamisbench", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_module_entry_point_reports_the_package_version() -> None:
    result = run_cli("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"dbench {__version__}"


def test_help_succeeds_and_names_the_program() -> None:
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: dbench")


def test_console_script_is_declared() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["name"] == "dynamisbench"
    assert project["scripts"]["dbench"] == "dynamisbench.cli:main"
