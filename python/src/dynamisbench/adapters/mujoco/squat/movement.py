"""Movement intent and phase logic of one back-squat repetition.

NumPy only; no engine import. Nothing in this module produces a joint state. It defines:

* :class:`RepetitionPlan` - the declared task of one repetition: depth and tempo;
* :func:`minimum_jerk` - the time course of the single scalar movement intent (knee-flexion
  depth), the minimum-jerk profile of planned human point-to-point movement (Flash & Hogan
  1985 J. Neurosci. 5:1688-1703);
* :class:`PhaseMachine` - the state machine that advances the intent. Its transitions after
  the start command are triggered by the *measured* state of the athlete, not by a clock;
* :class:`NaturalCubicSpline` - a C2 interpolant used to turn the discrete, statically solved
  posture synergy into a smooth reference with analytic first and second derivatives;
* :func:`detect_phases` - an independent, controller-agnostic segmentation of a recorded
  movement into standing, descent, bottom, ascent and standing again, from the measured hip
  height alone.

How the intent becomes motion is the engine's business: the intent selects a posture from the
balanced synergy, an internal inverse-dynamics model converts the plan into feedforward
torques, joint-impedance feedback corrects errors, and MuJoCo integrates the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "BOTTOM_SETTLE_SPEED_DEG_S",
    "REPETITION",
    "MeasuredPhase",
    "NaturalCubicSpline",
    "Phase",
    "PhaseMachine",
    "RepetitionPlan",
    "detect_phases",
    "minimum_jerk",
    "smoothstep",
]

FloatArray = NDArray[np.float64]


class Phase(StrEnum):
    """Commanded phase of the repetition."""

    STANDING = "standing"
    DESCENT = "descent"
    BOTTOM = "bottom"
    ASCENT = "ascent"
    RETURN = "return"


@dataclass(frozen=True, slots=True)
class RepetitionPlan:
    """The declared task of one controlled repetition.

    Durations are the *intended* durations of the intent profile; the measured phases are
    whatever forward dynamics produces, and are checked against these.
    """

    bottom_knee_flexion_deg: float
    standing_s: float
    descent_s: float
    bottom_pause_s: float
    ascent_s: float
    return_s: float
    blend_width_deg: float
    """Depth range over which the reference blends from the standing keyframe posture into the
    squat synergy (and back), so the reference and its derivatives are continuous. The standing
    keyframe differs from the synergy's first posture by ~4 deg of hip flexion; transferring
    that over 20 deg of depth put a visible ripple into the planned and measured ground reaction
    (peak GRF curvature 265 s^-2), over 40 deg it is a third of that with unchanged extremes."""

    def __post_init__(self) -> None:
        for name in ("standing_s", "descent_s", "bottom_pause_s", "ascent_s", "return_s"):
            value = getattr(self, name)
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be a finite non-negative duration")
        if self.descent_s <= 0.0 or self.ascent_s <= 0.0:
            raise ValueError("descent and ascent must take time")
        if not 0.0 < self.blend_width_deg < self.bottom_knee_flexion_deg:
            raise ValueError("the blend must be a positive part of the depth")


REPETITION: Final = RepetitionPlan(
    bottom_knee_flexion_deg=120.0,
    standing_s=1.0,
    descent_s=1.5,
    bottom_pause_s=0.3,
    ascent_s=1.2,
    return_s=1.5,
    blend_width_deg=40.0,
)
"""A controlled parallel-depth repetition: 120 deg knee flexion is where this model's thigh
reaches horizontal. A 1.5 s eccentric, a brief 0.3 s pause and a 1.2 s concentric phase are a
typical controlled tempo for resistance training (e.g. a "2-0-1"-style prescription; controlled
eccentric durations of 1-2 s and concentric durations of ~1 s are usual for light loads)."""

BOTTOM_SETTLE_SPEED_DEG_S: Final = 3.0
"""The bottom is reached when the intent has arrived and the measured knee flexion speed has
fallen below this."""
RETURN_TOLERANCE_DEG: Final = 3.0
"""Standing is regained when every measured sagittal joint is within this of standing."""
TRANSITION_TIMEOUT_S: Final = 1.0
"""How long past the intended end of descent or ascent the measured state may take to satisfy
a transition before the repetition is declared failed."""


def smoothstep(x: float) -> tuple[float, float, float]:
    """Quintic 0-to-1 step ``10x^3 - 15x^4 + 6x^5`` and its first two derivatives, clamped."""
    if x <= 0.0:
        return 0.0, 0.0, 0.0
    if x >= 1.0:
        return 1.0, 0.0, 0.0
    return (
        x**3 * (10.0 - 15.0 * x + 6.0 * x * x),
        30.0 * x * x * (1.0 - x) ** 2,
        60.0 * x * (1.0 - x) * (1.0 - 2.0 * x),
    )


def minimum_jerk(start: float, end: float, duration: float, t: float) -> tuple[float, float, float]:
    """Position, velocity and acceleration of the minimum-jerk path at time ``t``."""
    if duration <= 0.0:
        raise ValueError("a minimum-jerk movement needs a positive duration")
    shape, rate, curvature = smoothstep(t / duration)
    span = end - start
    return start + span * shape, span * rate / duration, span * curvature / duration**2


class NaturalCubicSpline:
    """C2 natural cubic spline through ``(knots, values)``, one curve per column."""

    def __init__(self, knots: FloatArray, values: FloatArray) -> None:
        knots = np.asarray(knots, dtype=np.float64)
        values = np.asarray(values, dtype=np.float64)
        if knots.ndim != 1 or len(knots) < 3 or values.shape[0] != len(knots):
            raise ValueError("a spline needs at least three knots and one value row per knot")
        if not bool(np.all(np.diff(knots) > 0.0)):
            raise ValueError("spline knots must increase strictly")
        h = np.diff(knots)
        n = len(knots)
        system = np.zeros((n, n))
        rhs = np.zeros((n, values.shape[1]))
        system[0, 0] = system[-1, -1] = 1.0
        for i in range(1, n - 1):
            system[i, i - 1] = h[i - 1]
            system[i, i] = 2.0 * (h[i - 1] + h[i])
            system[i, i + 1] = h[i]
            rhs[i] = 3.0 * (
                (values[i + 1] - values[i]) / h[i] - (values[i] - values[i - 1]) / h[i - 1]
            )
        c = np.linalg.solve(system, rhs)
        self._knots = knots
        self._a = values[:-1]
        self._b = (values[1:] - values[:-1]) / h[:, None] - h[:, None] * (
            2.0 * c[:-1] + c[1:]
        ) / 3.0
        self._c = c[:-1]
        self._d = (c[1:] - c[:-1]) / (3.0 * h[:, None])

    @property
    def domain(self) -> tuple[float, float]:
        return float(self._knots[0]), float(self._knots[-1])

    def __call__(self, x: float) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Value, first and second derivative at ``x`` (which must lie in the domain)."""
        low, high = self.domain
        if not low - 1e-9 <= x <= high + 1e-9:
            raise ValueError(f"{x} is outside the spline domain [{low}, {high}]")
        x = min(max(x, low), high)
        index = int(
            min(max(np.searchsorted(self._knots, x, side="right") - 1, 0), len(self._a) - 1)
        )
        u = x - float(self._knots[index])
        b, c, d = self._b[index], self._c[index], self._d[index]
        return (
            self._a[index] + b * u + c * u * u + d * u**3,
            b + 2.0 * c * u + 3.0 * d * u * u,
            2.0 * c + 6.0 * d * u,
        )


@dataclass(slots=True)
class PhaseMachine:
    """Advances the depth intent; transitions after the start are decided by measured state.

    ``standing_depth_deg`` is the measured knee flexion of the standing keyframe, so the
    intent starts and ends exactly where the athlete stands.
    """

    plan: RepetitionPlan
    standing_depth_deg: float
    phase: Phase = Phase.STANDING
    phase_start_s: float = 0.0
    failed: str | None = None

    def intent(self, time_s: float) -> tuple[float, float, float]:
        """Depth intent (deg) and its first two time derivatives for the current phase."""
        plan = self.plan
        elapsed = time_s - self.phase_start_s
        if self.phase is Phase.DESCENT:
            return minimum_jerk(
                self.standing_depth_deg, plan.bottom_knee_flexion_deg, plan.descent_s, elapsed
            )
        if self.phase is Phase.ASCENT:
            return minimum_jerk(
                plan.bottom_knee_flexion_deg, self.standing_depth_deg, plan.ascent_s, elapsed
            )
        if self.phase is Phase.BOTTOM:
            return plan.bottom_knee_flexion_deg, 0.0, 0.0
        return self.standing_depth_deg, 0.0, 0.0

    def update(
        self,
        time_s: float,
        *,
        knee_flexion_deg: float,
        knee_speed_deg_s: float,
        sagittal_error_deg: float,
    ) -> Phase:
        """Advance on the measured state; return the (possibly new) phase."""
        plan = self.plan
        elapsed = time_s - self.phase_start_s
        if self.phase is Phase.STANDING and time_s >= plan.standing_s - 1e-12:
            self._enter(Phase.DESCENT, time_s)
        elif self.phase is Phase.DESCENT and elapsed >= plan.descent_s - 1e-12:
            arrived = abs(knee_flexion_deg - plan.bottom_knee_flexion_deg) < RETURN_TOLERANCE_DEG
            if arrived and abs(knee_speed_deg_s) < BOTTOM_SETTLE_SPEED_DEG_S:
                self._enter(Phase.BOTTOM, time_s)
            elif elapsed > plan.descent_s + TRANSITION_TIMEOUT_S:
                self.failed = "the athlete did not reach and settle at the bottom"
        elif self.phase is Phase.BOTTOM and elapsed >= plan.bottom_pause_s - 1e-12:
            self._enter(Phase.ASCENT, time_s)
        elif self.phase is Phase.ASCENT and elapsed >= plan.ascent_s - 1e-12:
            if sagittal_error_deg < RETURN_TOLERANCE_DEG:
                self._enter(Phase.RETURN, time_s)
            elif elapsed > plan.ascent_s + TRANSITION_TIMEOUT_S:
                self.failed = "the athlete did not regain the standing posture"
        return self.phase

    def _enter(self, phase: Phase, time_s: float) -> None:
        self.phase = phase
        self.phase_start_s = time_s


@dataclass(frozen=True, slots=True)
class MeasuredPhase:
    """One contiguous phase segmented from the measured hip-height trace."""

    phase: str
    start_s: float
    end_s: float


def detect_phases(
    time_s: FloatArray,
    hip_height_m: FloatArray,
    *,
    speed_threshold_m_s: float = 0.05,
) -> list[MeasuredPhase]:
    """Segment a recorded repetition from the hip (pelvis origin) height alone.

    Descent is where the hip moves down faster than ``speed_threshold_m_s``, ascent where it
    moves up faster than that, the bottom is the interval between them (around the lowest
    point), and standing is before the descent and after the ascent. The result is
    independent of the controller's own phase bookkeeping, so a test can compare the two.
    """
    time_s = np.asarray(time_s, dtype=np.float64)
    height = np.asarray(hip_height_m, dtype=np.float64)
    if len(time_s) < 5 or time_s.shape != height.shape:
        raise ValueError("phase detection needs matching time and height samples")
    velocity = np.gradient(height, time_s)
    down = np.flatnonzero(velocity < -speed_threshold_m_s)
    up = np.flatnonzero(velocity > speed_threshold_m_s)
    if len(down) == 0 or len(up) == 0:
        return [MeasuredPhase("standing", float(time_s[0]), float(time_s[-1]))]
    lowest = int(np.argmin(height))
    descent_start = int(down[0])
    descent_end = int(down[down < lowest][-1]) if np.any(down < lowest) else descent_start
    ascent_start = int(up[up > lowest][0]) if np.any(up > lowest) else lowest
    ascent_end = int(up[-1])
    return [
        MeasuredPhase("standing", float(time_s[0]), float(time_s[descent_start])),
        MeasuredPhase("descent", float(time_s[descent_start]), float(time_s[descent_end])),
        MeasuredPhase("bottom", float(time_s[descent_end]), float(time_s[ascent_start])),
        MeasuredPhase("ascent", float(time_s[ascent_start]), float(time_s[ascent_end])),
        MeasuredPhase("standing", float(time_s[ascent_end]), float(time_s[-1])),
    ]
