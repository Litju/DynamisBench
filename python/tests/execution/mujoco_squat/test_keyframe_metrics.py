"""Scientific-authority-neutral tests of RES-640 numerical diagnostics."""

from __future__ import annotations

import math
import unittest

from tools.keyframe_metrics import vector_diagnostics


class KeyframeMetricsTests(unittest.TestCase):
    def test_identical_vectors_pass_with_exact_zero_delta(self) -> None:
        actual = vector_diagnostics([0.0, 1.0], [0.0, 1.0], tolerance=1e-6)
        self.assertTrue(actual["within_tolerance"])
        self.assertEqual(actual["max_abs_difference"], 0.0)
        self.assertEqual(actual["exceeding_count"], 0)
        self.assertEqual(actual["max_index"], 0)

    def test_ranked_coordinates_and_failure_are_not_masked(self) -> None:
        actual = vector_diagnostics(
            [0.0, 0.0, 0.0, 0.0], [0.0, 2e-6, -3.829e-6, 1e-7],
            tolerance=1e-6, top_n=3,
        )
        self.assertFalse(actual["within_tolerance"])
        self.assertEqual(actual["exceeding_count"], 2)
        self.assertEqual(actual["max_index"], 2)
        self.assertAlmostEqual(actual["max_abs_difference"], 3.829e-6)
        self.assertEqual([x["index"] for x in actual["largest"]], [2, 1, 3])
        self.assertEqual(actual["largest"][0]["reference"], 0.0)
        self.assertAlmostEqual(actual["largest"][0]["observed"], -3.829e-6)

    def test_equal_to_tolerance_passes(self) -> None:
        actual = vector_diagnostics([0.0], [1e-6], tolerance=1e-6)
        self.assertTrue(actual["within_tolerance"])
        self.assertEqual(actual["exceeding_count"], 0)

    def test_ties_use_stable_index_order(self) -> None:
        actual = vector_diagnostics([0.0, 0.0], [0.25, -0.25], tolerance=1.0)
        self.assertEqual([x["index"] for x in actual["largest"]], [0, 1])

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            vector_diagnostics([], [], tolerance=1e-6)
        with self.assertRaises(ValueError):
            vector_diagnostics([1.0], [1.0, 2.0], tolerance=1e-6)
        with self.assertRaises(ValueError):
            vector_diagnostics([math.nan], [0.0], tolerance=1e-6)
        with self.assertRaises(ValueError):
            vector_diagnostics([0.0], [math.inf], tolerance=1e-6)
        with self.assertRaises(ValueError):
            vector_diagnostics([0.0], [0.0], tolerance=-1)
        with self.assertRaises(ValueError):
            vector_diagnostics([0.0], [0.0], tolerance=math.nan)
        with self.assertRaises(ValueError):
            vector_diagnostics([0.0], [0.0], tolerance=0, top_n=65)


if __name__ == "__main__":
    unittest.main()
