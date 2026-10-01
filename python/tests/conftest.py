"""Pytest/Hypothesis bootstrap.

Hypothesis profiles are registered here rather than in ``pyproject.toml`` so that
profile selection is explicit and identical on Windows and Linux. CI selects the
``ci`` profile through the ``HYPOTHESIS_PROFILE`` environment variable.

``--update-golden`` is declared here because the canonical-identity golden corpus is
committed authority: regenerating it is a deliberate act with a reviewable diff, never
something a test does silently to make itself pass.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "default",
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("ci", max_examples=500, deadline=None, derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "rewrite the committed canonical-identity golden corpus from the current code. "
            "Run it, then read the diff: a changed digest is a changed scientific identity."
        ),
    )
