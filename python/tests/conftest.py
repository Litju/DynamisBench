"""Pytest/Hypothesis bootstrap.

Hypothesis profiles are registered here rather than in ``pyproject.toml`` so that
profile selection is explicit and identical on Windows and Linux. CI selects the
``ci`` profile through the ``HYPOTHESIS_PROFILE`` environment variable.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "default",
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("ci", max_examples=500, deadline=None, derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
