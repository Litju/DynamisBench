"""Reproduce the pinned RES-550 reference-authority digests, or check the checked-in pins.

The worker admits only the exact benchmark, scenario, realization, system-under-test and
environment meaning it was compiled for. Those meanings are reviewed constants in
:mod:`dynamisbench.adapters.mujoco.reference`; this tool recomputes them from the canonical
definitions in :mod:`dynamisbench.adapters.mujoco.reference_case`.

It exists so the pins are reproducible outside the test suite and independent of any worker
request. Run it from ``python/``:

    uv run python tools/mujoco_reference_authority.py
    uv run python tools/mujoco_reference_authority.py --check

Exit status is 1 when ``--check`` finds a stale pin. A stale pin is a reviewed decision: the
definition changed, so the reference experiment changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Final

from dynamisbench.adapters.mujoco import reference, reference_case

__all__ = ["main"]

_PINNED: Final = {
    "benchmark": reference.BENCHMARK_SEMANTIC_DIGEST.hex,
    "scenario": reference.SCENARIO_SEMANTIC_DIGEST.hex,
    "realization": reference.REALIZATION_SEMANTIC_DIGEST.hex,
    "system_under_test": reference.SUT_SEMANTIC_DIGEST.hex,
    "environment_windows_x86_64": reference.ENVIRONMENT_SEMANTIC_DIGESTS["windows-x86-64"].hex,
    "environment_linux_x86_64": reference.ENVIRONMENT_SEMANTIC_DIGESTS["linux-x86-64"].hex,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the checked-in pins and fail on any stale value",
    )
    arguments = parser.parse_args(argv)
    observed = reference_case.reference_authority_matches_definitions()
    payload = {
        "schema": "dynamisbench.mujoco.reference-authority/1",
        "pinned": _PINNED,
        "observed": observed,
        "matches": observed == _PINNED,
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if arguments.check and observed != _PINNED:
        stale = sorted(key for key, value in observed.items() if _PINNED.get(key) != value)
        sys.stderr.write("the reference-authority pins are stale for: " + ", ".join(stale) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
