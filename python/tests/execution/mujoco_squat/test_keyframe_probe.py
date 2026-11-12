"""Synthetic tests of the RES-640 read-only probe; MuJoCo is never imported here."""

from __future__ import annotations

import math
import unittest

from tools.mujoco_squat_keyframe_probe import MAX_RUNS, SCHEMA, summarize_observations

from dynamisbench.adapters.mujoco.squat import reference


def _state(*, heading: float = 0.0, joint0: float = 0.0) -> list[float]:
    """A synthetic standing qpos: pelvis at mid-hip height, pitched 0.037 rad, bar on the shelf."""
    qpos = [0.0] * (reference.BAR_QPOS + 7)
    qpos[0:3] = [0.039, 0.0, 0.921]
    qpos[3] = math.cos(0.0183)
    qpos[5] = math.sin(0.0183)
    qpos[7] = joint0
    qpos[reference.BAR_QPOS : reference.BAR_QPOS + 3] = [0.046, 0.0, 1.469]
    qpos[reference.BAR_QPOS + 3 : reference.BAR_QPOS + 7] = qpos[3:7]
    return reference.rotate_world_frame(qpos, heading)


class KeyframeProbeTests(unittest.TestCase):
    @staticmethod
    def _obs(qpos: list[float], act: list[float], speed: float = 0.0, raw_heading=None) -> dict:
        return {
            "qpos": qpos,
            "act": act,
            "relaxation_final_max_speed": speed,
            "relaxation_heading_before_projection_rad": (
                reference.pelvis_heading_rad(qpos) if raw_heading is None else raw_heading
            ),
            "static_solution_qpos": list(qpos),
            "static_solution_act": list(act),
            "engine_version": "3.17.0",
            "python_version": "3.12.13",
        }

    def test_separates_the_world_heading_from_the_physical_state(self) -> None:
        # The protected-main failure: a regeneration whose *heading* differs by 7.66e-6 rad,
        # which is 3.829e-6 in a quaternion component, with every physical quantity identical.
        expected = _state()
        drifted = _state(heading=7.66e-6)
        results = summarize_observations(
            expected,
            [0.0],
            [self._obs(drifted, [0.0])],
            tolerance=1e-6,
            model_sha256="0" * 64,
        )
        self.assertEqual(results["schema"], SCHEMA)
        raw = results["runs"][0]["versus_packaged"]["qpos"]
        self.assertFalse(raw["within_tolerance"])
        self.assertAlmostEqual(raw["max_abs_difference"], 3.829e-6, delta=1e-9)
        self.assertEqual(raw["max_index"], 6)
        self.assertFalse(results["all_within_current_tolerance"])
        self.assertTrue(results["all_canonical_within_current_tolerance"])
        self.assertLess(
            results["runs"][0]["canonical_versus_packaged"]["qpos"]["max_abs_difference"], 1e-15
        )
        self.assertLess(results["runs"][0]["physical_versus_packaged"]["overall"], 1e-15)
        self.assertIn("diagnostic_only", results["claim"])

    def test_a_physical_difference_is_still_reported(self) -> None:
        expected = _state()
        moved = _state(joint0=3e-6)
        results = summarize_observations(
            expected,
            [0.0],
            [self._obs(moved, [0.0])],
            tolerance=1e-6,
            model_sha256="0" * 64,
        )
        self.assertFalse(results["all_canonical_within_current_tolerance"])
        self.assertAlmostEqual(
            results["runs"][0]["canonical_versus_packaged"]["qpos"]["max_abs_difference"],
            3e-6,
            delta=1e-12,
        )
        self.assertAlmostEqual(
            results["runs"][0]["physical_versus_packaged"]["joint_angles_rad"], 3e-6, delta=1e-12
        )

    def test_distinguishes_pinned_drift_from_repeatability(self) -> None:
        # Both fresh runs can be internally identical yet disagree with the pinned model.
        expected = _state()
        drifted = _state(heading=7.66e-6)
        results = summarize_observations(
            expected,
            [0.0],
            [self._obs(drifted, [0.0]), self._obs(drifted, [0.0])],
            tolerance=1e-6,
            model_sha256="0" * 64,
        )
        self.assertFalse(results["runs"][0]["versus_packaged"]["qpos"]["within_tolerance"])
        self.assertTrue(results["runs"][1]["versus_first_run"]["qpos"]["within_tolerance"])
        self.assertTrue(
            results["runs"][1]["canonical_versus_first_run"]["qpos"]["within_tolerance"]
        )

    def test_detects_between_run_drift_separately(self) -> None:
        expected = _state()
        results = summarize_observations(
            expected,
            [0.0],
            [self._obs(expected, [0.0]), self._obs(_state(heading=7.66e-6), [0.0])],
            tolerance=1e-6,
            model_sha256="a" * 64,
        )
        self.assertFalse(results["all_within_current_tolerance"])
        self.assertFalse(results["runs"][1]["versus_first_run"]["qpos"]["within_tolerance"])
        self.assertTrue(
            results["runs"][1]["canonical_versus_first_run"]["qpos"]["within_tolerance"]
        )
        self.assertTrue(results["runs"][1]["versus_packaged"]["act"]["within_tolerance"])

    def test_initial_static_drift_is_separate_from_relaxation_drift(self) -> None:
        first = self._obs(_state(), [0.25])
        next_run = self._obs(_state(), [0.25])
        next_run["static_solution_qpos"] = _state(heading=4e-6)
        result = summarize_observations(
            _state(),
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
        self.assertAlmostEqual(result["runs"][1]["static_solution_heading_rad"], 4e-6, delta=1e-9)
        self.assertEqual(result["first_run_static_solution"]["qpos"], _state())

    def test_rejects_missing_or_nonfinite_observations(self) -> None:
        with self.assertRaises(ValueError):
            summarize_observations(_state(), [0.0], [], tolerance=1e-6, model_sha256="a")
        with self.assertRaises(ValueError):
            summarize_observations(
                _state(),
                [0.0],
                [self._obs(_state(), [0.0], float("nan"))],
                tolerance=1e-6,
                model_sha256="a",
            )
        with self.assertRaises(ValueError):
            summarize_observations(
                _state(),
                [0.0],
                [self._obs(_state(), [0.0])] * (MAX_RUNS + 1),
                tolerance=1e-6,
                model_sha256="a",
            )
        with self.assertRaises(ValueError):
            summarize_observations(
                _state(),
                [0.0],
                [self._obs(_state(heading=1e-3), [0.0], raw_heading=float("inf"))],
                tolerance=1e-6,
                model_sha256="a",
            )


if __name__ == "__main__":
    unittest.main()
