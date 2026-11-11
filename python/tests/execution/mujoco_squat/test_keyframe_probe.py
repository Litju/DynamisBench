"""Synthetic tests of the RES-640 read-only probe; MuJoCo is never imported here."""

from __future__ import annotations

import unittest

from tools.mujoco_squat_keyframe_probe import MAX_RUNS, SCHEMA, summarize_observations


class KeyframeProbeTests(unittest.TestCase):
    @staticmethod
    def _obs(qpos: list[float], act: list[float], speed: float = 0.0) -> dict:
        return {
            "qpos": qpos,
            "act": act,
            "relaxation_final_max_speed": speed,
            "static_solution_qpos": list(qpos),
            "static_solution_act": list(act),
            "engine_version": "3.17.0",
            "python_version": "3.12.13",
        }

    def test_distinguishes_pinned_drift_from_repeatability(self) -> None:
        # Both fresh runs can be internally identical yet disagree with the pinned model.
        reference = [0.0, 0.0]
        results = summarize_observations(
            reference,
            [0.0],
            [self._obs([0.0, 3.829e-6], [0.0]), self._obs([0.0, 3.829e-6], [0.0])],
            tolerance=1e-6,
            model_sha256="0" * 64,
        )
        self.assertEqual(results["schema"], SCHEMA)
        self.assertFalse(results["all_within_current_tolerance"])
        self.assertFalse(results["runs"][0]["versus_packaged"]["qpos"]["within_tolerance"])
        self.assertTrue(results["runs"][1]["versus_first_run"]["qpos"]["within_tolerance"])
        self.assertEqual(results["runs"][0]["versus_packaged"]["qpos"]["max_index"], 1)
        self.assertIn("diagnostic_only", results["claim"])

    def test_detects_between_run_drift_separately(self) -> None:
        results = summarize_observations(
            [0.0],
            [0.0],
            [self._obs([0.0], [0.0]), self._obs([0.000002], [0.0])],
            tolerance=0.000001,
            model_sha256="a" * 64,
        )
        self.assertFalse(results["all_within_current_tolerance"])
        self.assertFalse(results["runs"][1]["versus_first_run"]["qpos"]["within_tolerance"])
        self.assertTrue(results["runs"][1]["versus_packaged"]["act"]["within_tolerance"])

    def test_initial_static_drift_is_separate_from_relaxation_drift(self) -> None:
        first = self._obs([1.0], [0.25])
        next_run = self._obs([1.0], [0.25])
        next_run["static_solution_qpos"] = [1.000004]
        result = summarize_observations(
            [1.0],
            [0.25],
            [first, next_run],
            tolerance=1e-6,
            model_sha256="f" * 64,
        )
        self.assertTrue(result["all_within_current_tolerance"])
        self.assertEqual(result["runs"][1]["versus_first_run"]["qpos"]["max_abs_difference"], 0.0)
        self.assertFalse(
            result["runs"][1]["static_solution_versus_first"]["qpos"]["within_tolerance"]
        )
        self.assertEqual(result["first_run_static_solution"]["qpos"], [1.0])

    def test_rejects_missing_or_nonfinite_observations(self) -> None:
        with self.assertRaises(ValueError):
            summarize_observations([0.0], [0.0], [], tolerance=1e-6, model_sha256="a")
        with self.assertRaises(ValueError):
            summarize_observations(
                [0.0],
                [0.0],
                [self._obs([0.0], [0.0], float("nan"))],
                tolerance=1e-6,
                model_sha256="a",
            )
        with self.assertRaises(ValueError):
            summarize_observations(
                [0.0],
                [0.0],
                [self._obs([0.0], [0.0])] * (MAX_RUNS + 1),
                tolerance=1e-6,
                model_sha256="a",
            )


if __name__ == "__main__":
    unittest.main()
