"""``dbench`` command line.

DB-1.1 exposes the entry point only. Product commands arrive with the issues that
own them; command behaviour must stay engine-independent (ADR-001).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from dynamisbench import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Run the DynamisBench command line."""
    parser = argparse.ArgumentParser(
        prog="dbench",
        description="DynamisBench — scientific workbench command line.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
