"""Independent numerical and mechanical qualification of the real MuJoCo reference run.

These are verification checks, not validation. The reference is the nonlinear pendulum
equation implied by the model's own declared mass, geometry and inertia; agreement with it
demonstrates that the adapter integrated the intended mechanical system. It says nothing
about human biomechanics, DB-LCMJ20, or any scientific claim.

Tolerances are declared here, before observations, from the numerical method:

* MuJoCo RK4 at ``dt = 0.001 s`` over ``2 s`` has global truncation error of order four. For
  this smooth one-degree-of-freedom system the expected state error is on the order of
  ``1e-11``; the ``1e-8 rad`` angle and ``1e-7 rad/s`` velocity tolerances are deliberately
  generous margins over that estimate, not values fitted to an observed failure.
* A non-symplectic RK4 integration need not conserve energy exactly, but the drift over this
  short smooth horizon is expected near machine precision. ``1e-9`` relative drift is a
  conservative bound.
* The finite-amplitude period is computed from the complete elliptic integral and compared
  with four times the interpolated first zero crossing. The crossing interpolation and
  integration error are far below the declared ``1e-4 s`` tolerance.
* Timestep refinement must show the fourth-order signature. A ratio of at least eight per
  halving is a weak, conservative assertion (order three) against the expected ratio of
  sixteen.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.integrate import solve_ivp
from scipy.special import ellipk

from dynamisbench.adapters.mujoco import reference
from dynamisbench.adapters.mujoco.diagnostics import ReferenceDiagnostic
from dynamisbench.execution import RunLifecycleState
from tests.execution.mujoco.support import (
    COM_DISTANCE_M,
    COM_INERTIA_KG_M2,
    GRAVITY_M_S2,
    HINGE_INERTIA_KG_M2,
    INITIAL_ANGLE_RAD,
    MASS_KG,
    TIMESTEP_S,
    ExecutionFixture,
    execute_fixture,
    native_diagnostic,
)

ANGLE_TOLERANCE_RAD = 1e-8
ANGULAR_VELOCITY_TOLERANCE_RAD_S = 1e-7
ENERGY_RELATIVE_TOLERANCE = 1e-9
PERIOD_TOLERANCE_S = 1e-4
VELOCITY_CONSISTENCY_TOLERANCE_RAD_S = 1e-3
REFINEMENT_MIN_RATIO = 8.0
REFINEMENT_FINAL_TOLERANCE_RAD = 1e-8


def _reference_solution(times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Solve the independent nonlinear pendulum equation at the requested times.

    The equation is ``I theta'' + m g L sin(theta) = 0`` with the hinge inertia computed
    independently as centre-of-mass inertia plus the parallel-axis term.
    """
    spring = MASS_KG * GRAVITY_M_S2 * COM_DISTANCE_M / HINGE_INERTIA_KG_M2

    def derivative(_time: float, state: np.ndarray) -> tuple[float, float]:
        theta, omega = state
        return omega, -spring * math.sin(theta)

    solution = solve_ivp(
        derivative,
        (0.0, float(times[-1])),
        (INITIAL_ANGLE_RAD, 0.0),
        t_eval=times,
        method="DOP853",
        rtol=1e-12,
        atol=1e-14,
    )
    assert solution.success
    assert solution.y.shape[1] == len(times)
    return solution.y[0], solution.y[1]


def _energy(theta: np.ndarray, omega: np.ndarray) -> np.ndarray:
    return 0.5 * HINGE_INERTIA_KG_M2 * omega**2 + MASS_KG * GRAVITY_M_S2 * COM_DISTANCE_M * (
        1.0 - np.cos(theta)
    )


def _nominal_arrays(qualification: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    nominal = qualification["nominal"]
    samples = np.asarray(nominal["samples"], dtype=float)
    assert samples.ndim == 2
    assert samples.shape[1] == 4
    return samples[:, 0], samples[:, 1], samples[:, 2], samples[:, 3]


def test_the_nominal_real_run_matches_an_independent_nonlinear_reference(
    mujoco_qualification: dict,
) -> None:
    times, theta, omega, _energy_observed = _nominal_arrays(mujoco_qualification)
    theta_reference, omega_reference = _reference_solution(times)

    angle_error = np.max(np.abs(theta - theta_reference))
    velocity_error = np.max(np.abs(omega - omega_reference))

    assert angle_error <= ANGLE_TOLERANCE_RAD, f"max angle error {angle_error!r} rad"
    assert velocity_error <= ANGULAR_VELOCITY_TOLERANCE_RAD_S, (
        f"max angular velocity error {velocity_error!r} rad/s"
    )


def test_the_nominal_real_run_is_finite_monotonic_and_velocity_consistent(
    mujoco_qualification: dict,
) -> None:
    times, theta, omega, observed_energy = _nominal_arrays(mujoco_qualification)

    assert np.all(np.isfinite(times))
    assert np.all(np.isfinite(theta))
    assert np.all(np.isfinite(omega))
    assert np.all(np.isfinite(observed_energy))
    assert np.all(np.diff(times) > 0.0)
    assert np.allclose(np.diff(times), TIMESTEP_S, rtol=0.0, atol=1e-9)

    finite_difference = np.gradient(theta, times)
    interior = slice(2, -2)
    consistency_error = np.max(np.abs(finite_difference[interior] - omega[interior]))
    assert consistency_error <= VELOCITY_CONSISTENCY_TOLERANCE_RAD_S


def test_the_nominal_real_run_has_the_expected_initial_state(
    mujoco_qualification: dict,
) -> None:
    diagnostic = ReferenceDiagnostic.model_validate(mujoco_qualification["nominal"]["diagnostic"])
    assert diagnostic.initial.time_s == 0.0
    assert diagnostic.initial.angle_rad == INITIAL_ANGLE_RAD
    assert diagnostic.initial.angular_velocity_rad_s == 0.0
    assert (diagnostic.nq, diagnostic.nv, diagnostic.nu, diagnostic.njnt, diagnostic.ngeom) == (
        1,
        1,
        0,
        1,
        0,
    )
    assert diagnostic.precision == "float64"
    assert diagnostic.solver_iterations == 100
    assert diagnostic.solver_tolerance == 1e-12
    assert diagnostic.stochastic is False
    assert diagnostic.mass_kg == MASS_KG
    assert diagnostic.com_distance_m == COM_DISTANCE_M
    assert math.isclose(
        diagnostic.hinge_inertia_kg_m2,
        HINGE_INERTIA_KG_M2,
        rel_tol=0.0,
        abs_tol=1e-15,
    )
    assert math.isclose(
        diagnostic.gravity_m_s2,
        GRAVITY_M_S2,
        rel_tol=0.0,
        abs_tol=1e-15,
    )
    assert math.isclose(
        diagnostic.hinge_inertia_kg_m2,
        COM_INERTIA_KG_M2 + MASS_KG * COM_DISTANCE_M**2,
        rel_tol=0.0,
        abs_tol=1e-15,
    )


def test_the_nominal_real_run_conserves_energy_within_the_declared_tolerance(
    mujoco_qualification: dict,
) -> None:
    times, theta, omega, observed_energy = _nominal_arrays(mujoco_qualification)
    independent_energy = _energy(theta, omega)
    assert np.allclose(independent_energy, observed_energy, rtol=0.0, atol=1e-12)

    initial = independent_energy[0]
    relative_drift = np.max(np.abs(independent_energy - initial)) / abs(initial)
    assert relative_drift <= ENERGY_RELATIVE_TOLERANCE

    diagnostic = ReferenceDiagnostic.model_validate(mujoco_qualification["nominal"]["diagnostic"])
    assert math.isclose(
        diagnostic.energy_initial_j,
        float(initial),
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert math.isclose(
        diagnostic.max_relative_energy_drift,
        float(relative_drift),
        rel_tol=1e-9,
        abs_tol=1e-15,
    )
    assert np.all(np.diff(times) > 0.0)


def test_the_finite_amplitude_period_matches_the_elliptic_integral(
    mujoco_qualification: dict,
) -> None:
    crossing = mujoco_qualification["nominal"]["first_zero_crossing_s"]
    assert crossing is not None
    measured_period = 4.0 * float(crossing)

    elliptic_parameter = math.sin(INITIAL_ANGLE_RAD / 2.0) ** 2
    analytical_period = (
        4.0
        * math.sqrt(HINGE_INERTIA_KG_M2 / (MASS_KG * GRAVITY_M_S2 * COM_DISTANCE_M))
        * float(ellipk(elliptic_parameter))
    )

    assert abs(measured_period - analytical_period) <= PERIOD_TOLERANCE_S
    assert measured_period > 2.0 * math.pi * math.sqrt(
        HINGE_INERTIA_KG_M2 / (MASS_KG * GRAVITY_M_S2 * COM_DISTANCE_M)
    )


def test_timestep_refinement_shows_the_expected_convergence(
    mujoco_qualification: dict,
) -> None:
    refinement = mujoco_qualification["refinement"]
    assert len(refinement) >= 4
    errors: list[float] = []
    for entry in refinement:
        final_time, final_theta, _final_omega = entry["final"]
        theta_reference, _omega_reference = _reference_solution(
            np.asarray([0.0, float(final_time)])
        )
        errors.append(abs(float(final_theta) - float(theta_reference[-1])))

    assert errors[-1] <= REFINEMENT_FINAL_TOLERANCE_RAD
    for coarser, finer in zip(errors, errors[1:], strict=False):
        assert finer < coarser
        assert coarser / finer >= REFINEMENT_MIN_RATIO


def test_the_supervised_worker_and_the_qualification_tool_agree(
    mujoco_fixture: ExecutionFixture,
    mujoco_identity: dict,
    mujoco_qualification: dict,
) -> None:
    supervised = execute_fixture(mujoco_fixture, mujoco_identity)
    assert supervised.result.state is RunLifecycleState.COMPLETED
    supervised_diagnostic = native_diagnostic(mujoco_fixture.workspace, mujoco_fixture.run_id)
    tool_diagnostic = ReferenceDiagnostic.model_validate(
        mujoco_qualification["nominal"]["diagnostic"]
    )

    assert supervised_diagnostic.trajectory_sha256 == tool_diagnostic.trajectory_sha256
    assert supervised_diagnostic.initial == tool_diagnostic.initial
    assert supervised_diagnostic.final == tool_diagnostic.final
    assert supervised_diagnostic.checkpoints == tool_diagnostic.checkpoints
    assert supervised_diagnostic.energy_initial_j == tool_diagnostic.energy_initial_j
    assert supervised_diagnostic.energy_final_j == tool_diagnostic.energy_final_j
    assert supervised_diagnostic.implementation_digest == mujoco_identity["implementation_digest"]
    assert tool_diagnostic.model_sha256 == reference.MODEL_SHA256


def test_a_real_nonfinite_mujoco_state_is_refused(
    mujoco_nonfinite_probe: dict,
) -> None:
    assert mujoco_nonfinite_probe["guard_refused"] is True
    assert "not finite" in mujoco_nonfinite_probe["message"]
