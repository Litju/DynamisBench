"""Smoke and surface gates for the ``dbench`` command line.

Qualifies that a fresh Windows-native or Linux checkout can install the locked environment and
run the CLI behaviourally, and that the surface DB-2.2 added is the whole of the surface it is
allowed to add.

The parser is inspected rather than the source, because the property is about what the program
accepts: ``--version`` still answers exactly as DB-1.1 left it, ``dbench api serve`` exists,
and the options that would hand a caller control of the bind address or the credential are
absent from every command. A supervisor that can pass ``--host`` can be pointed at the network,
and one that can pass ``--token`` has a credential in a process listing — so their absence is a
security property, not a preference.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from dynamisbench import __version__

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

RESERVED_OPTIONS = ("--host", "--port", "--token", "--workers", "--reload", "--log-level")
"""Options that would move a security decision out of the session and into the caller.

A host option would make the bind address a command-line choice; a token option would put the
credential in the process list. Neither is a convenience, so neither exists.
"""


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dynamisbench", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _commands(parser: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    """Every subparser, at every depth, as a flat list."""
    found = [parser]
    for action in parser._subparsers._group_actions if parser._subparsers else []:
        for choice in getattr(action, "choices", {}).values():
            found.extend(_commands(choice))
    return found


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


def test_the_api_serve_command_exists() -> None:
    result = run_cli("api", "serve", "--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: dbench api serve")


@pytest.mark.parametrize(
    "arguments",
    [
        ("--host",),
        ("--token",),
        ("--port", "8080"),
        ("api", "serve", "--workers"),
        ("api", "serve", "--host", "0.0.0.0"),
        ("api", "serve", "--token", "anything"),
        ("api", "serve", "--reload"),
    ],
)
def test_a_reserved_option_is_refused(arguments: tuple[str, ...]) -> None:
    """Ordinary argparse behaviour: a refusal, a non-zero exit, and nothing on stdout.

    Asserted as a refusal rather than as one exact message, because argparse's diagnosis
    depends on where the option lands - given at the root it may name the following value as an
    unknown command. What matters is that none of these is ever accepted, and that the refusal
    itself never reaches the channel the sidecar reserves for its handshake.
    """
    result = run_cli(*arguments)
    assert result.returncode != 0
    assert "error:" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("arguments", "refusal"),
    [
        (("api", "run"), "invalid choice"),
        (("serve",), "invalid choice"),
        (("api", "serve", "extra"), "unrecognized arguments"),
        (("api", "bind"), "invalid choice"),
    ],
)
def test_an_unknown_command_is_refused(arguments: tuple[str, ...], refusal: str) -> None:
    result = run_cli(*arguments)
    assert result.returncode == 2, result.stdout
    assert refusal in result.stderr


def test_the_command_line_has_no_reserved_options() -> None:
    """Inspected on the parser itself, so a new flag cannot appear without this failing."""
    from dynamisbench.cli import build_parser

    offered: set[str] = set()
    for parser in _commands(build_parser()):
        for action in parser._actions:
            offered.update(action.option_strings)

    assert not offered & set(RESERVED_OPTIONS)
    assert offered == {
        "-h",
        "--help",
        "--version",
        "--kind",
        "--study",
        "--benchmark",
        "--realization",
        "--sut",
        "--environment",
        "--factor-case",
    }


def test_bare_invocation_succeeds_and_prints_nothing() -> None:
    """DB-1.1's behaviour, unchanged: the program answers without a command."""
    result = run_cli()
    assert result.returncode == 0
    assert result.stdout == ""


def test_the_version_option_is_answered_without_loading_the_application_stack() -> None:
    """``dbench --version`` must not import the application stack or the scientific kernel.

    A sidecar's own entry point pulling the application stack into every invocation would make
    the cheapest command the slowest one, and the import it avoids is the same import that could
    one day have a side effect. The same argument applies to the M1 kernel: planning, domain,
    and identity are loaded by the commands that use them, never by a question about the
    program's own name.
    """
    probe = "\n".join(
        [
            "import contextlib, io, sys",
            "from dynamisbench.cli import main",
            "try:",
            "    with contextlib.redirect_stdout(io.StringIO()):",
            "        main(['--version'])",
            "except SystemExit:",
            "    pass",
            "forbidden = (",
            "    'fastapi',",
            "    'uvicorn',",
            "    'pydantic',",
            "    'dynamisbench.api',",
            "    'dynamisbench.domain',",
            "    'dynamisbench.identity',",
            "    'dynamisbench.planning',",
            ")",
            "loaded = {",
            "    name",
            "    for name in sys.modules",
            "    if any(name == item or name.startswith(item + '.') for item in forbidden)",
            "}",
            "print('loaded=' + ','.join(sorted(loaded)))",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "loaded=", f"--version loaded {result.stdout.strip()!r}"
