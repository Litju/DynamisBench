"""Read-only comparisons for diagnostic numerical keyframe repeatability.

No simulator import or fixture mutation. Absolute differences are reported per *index*;
qpos mixes translations, quaternions, and joint coordinates, so do not assign one unit
or infer an anatomical joint from an index without checking the compiled model.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def vector_diagnostics(
    reference: Sequence[float],
    observed: Sequence[float],
    *,
    tolerance: float,
    top_n: int = 8,
) -> dict[str, Any]:
    """Rank deviations without changing a model, tolerance, or acceptance result."""
    if not (math.isfinite(tolerance) and tolerance >= 0):
        raise ValueError("tolerance must be finite and nonnegative")
    if top_n < 1 or top_n > 64:
        raise ValueError("top_n must be between 1 and 64")
    if len(reference) != len(observed) or not reference:
        raise ValueError("vectors must have equal, nonzero length")

    differences: list[tuple[int, float, float, float]] = []
    for index, (a, b) in enumerate(zip(reference, observed, strict=True)):
        a, b = float(a), float(b)
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError(f"vector entry {index} is non-finite")
        difference = abs(a - b)
        differences.append((index, a, b, difference))
    ordered = sorted(differences, key=lambda entry: (-entry[3], entry[0]))
    largest = ordered[0]
    return {
        "length": len(reference),
        "tolerance": tolerance,
        "max_abs_difference": largest[3],
        "max_index": largest[0],
        "exceeding_count": sum(x[3] > tolerance for x in differences),
        "within_tolerance": largest[3] <= tolerance,
        "largest": [
            {"index": i, "reference": a, "observed": b, "abs_difference": d}
            for i, a, b, d in ordered[:top_n]
        ],
    }
