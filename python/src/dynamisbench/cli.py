"""``dbench`` command line.

DB-1.1 exposes the entry point only. Product commands arrive with the issues that
own them; command behaviour must stay engine-independent (ADR-001).

One command exists, and it has no options. ``dbench api serve`` starts the session-secured
localhost sidecar (RES-375) and takes its credential and its origin list from the process
environment, so there is nothing to pass on the command line: no ``--host`` to widen the
bind, no ``--token`` to leak the credential into the process list, no ``--workers`` or
``--reload`` to turn a supervised sidecar into a fleet. Every one of those is a decision
that belongs to the desktop session, and a flag would be a way to make it in the wrong place.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from dynamisbench import __version__


def build_parser() -> argparse.ArgumentParser:
    """The command line, described."""
    parser = argparse.ArgumentParser(
        prog="dbench",
        description="DynamisBench — scientific workbench command line.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    commands = parser.add_subparsers(dest="command")
    api = commands.add_parser("api", help="Local application API.")
    api_commands = api.add_subparsers(dest="api_command")
    api_commands.add_parser(
        "serve",
        help="Serve the session-secured localhost API sidecar.",
        description=(
            "Serve the local API on one ephemeral 127.0.0.1 port. The session credential and "
            "the allowed origins are read from the environment; there is no command line option "
            "for either, and no option to change the bind address."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the DynamisBench command line."""
    arguments = build_parser().parse_args(argv)

    if getattr(arguments, "api_command", None) == "serve":
        # Imported here so that `dbench --version` and `dbench --help` do not load the
        # application stack to answer a question about the program's own name.
        from dynamisbench.api.server import serve

        return serve()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
