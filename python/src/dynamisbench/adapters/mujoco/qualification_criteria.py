"""Predeclared numerical acceptance criteria for the RES-550 MuJoCo qualification.

These constants are declared before an observation and are used by both the qualification
receipt generator and the independent receipt comparator. They are qualification-only: they
are not part of the worker's execution implementation and are deliberately excluded from the
adapter implementation identity.

The claim these criteria support is bounded: numerical solution verification of the fixed
planar-pendulum reference on the two qualified platforms. They say nothing about human
biomechanics, DB-LCMJ20, clinical validity, or a VVUQ PASS.
"""

from __future__ import annotations

from typing import Final

RECEIPT_SCHEMA: Final = "dynamisbench.mujoco.qualification-receipt/1"
COMPARISON_SCHEMA: Final = "dynamisbench.mujoco.receipt-comparison/1"

ANGLE_TOLERANCE_RAD: Final = 1e-8
ANGULAR_VELOCITY_TOLERANCE_RAD_S: Final = 1e-7
ENERGY_RELATIVE_TOLERANCE: Final = 1e-9
ENERGY_RECONSTRUCTION_TOLERANCE_J: Final = 1e-12
PERIOD_TOLERANCE_S: Final = 1e-4
VELOCITY_CONSISTENCY_TOLERANCE_RAD_S: Final = 1e-3
FINAL_TIME_TOLERANCE_S: Final = 1e-9
REFINEMENT_MIN_RATIO: Final = 8.0
REFINEMENT_FINAL_TOLERANCE_RAD: Final = 1e-8

# Comparison-only criterion, not part of the platform tolerances declared in a receipt. A
# receipt records its observed period, its analytical reference period and the error between
# them; the independent comparator subtracts the first two itself and requires the recorded
# error to agree. For an untampered receipt both are the same binary64 subtraction on the same
# two values, so agreement is exact; 1e-12 s admits representation noise only. It is eight
# orders below the 1e-4 s period acceptance and far above the roughly 2e-16 s spacing of
# doubles near this two-second period.
PERIOD_ERROR_REPORT_AGREEMENT_S: Final = 1e-12

CROSS_PLATFORM_FINAL_ANGLE_DIVERGENCE_RAD: Final = 1e-9
CROSS_PLATFORM_FINAL_ANGULAR_VELOCITY_DIVERGENCE_RAD_S: Final = 1e-8
CROSS_PLATFORM_PERIOD_DIVERGENCE_S: Final = 1e-5

CLAIM_LIMIT: Final = (
    "Numerical solution verification of the fixed MuJoCo planar-pendulum reference against "
    "an independent nonlinear pendulum solve and a finite-amplitude period. This is not "
    "human biomechanical validation, not a scientific benchmark acceptance, not VVUQ PASS, "
    "and not sealed native evidence."
)

TOLERANCES: Final = {
    "angle_rad": ANGLE_TOLERANCE_RAD,
    "angular_velocity_rad_s": ANGULAR_VELOCITY_TOLERANCE_RAD_S,
    "energy_relative": ENERGY_RELATIVE_TOLERANCE,
    "energy_reconstruction_j": ENERGY_RECONSTRUCTION_TOLERANCE_J,
    "period_s": PERIOD_TOLERANCE_S,
    "velocity_consistency_rad_s": VELOCITY_CONSISTENCY_TOLERANCE_RAD_S,
    "final_time_s": FINAL_TIME_TOLERANCE_S,
    "refinement_min_ratio": REFINEMENT_MIN_RATIO,
    "refinement_final_angle_rad": REFINEMENT_FINAL_TOLERANCE_RAD,
}
