"""Predeclared acceptance criteria of the back-squat repetition, for the laboratory record.

Pure Python; no engine import. These criteria are declared before any observation and are
evaluated on each recording published to the laboratory, so the workbench can show, per
recording, which checks pass and which fail (the ablations are *meant* to fail some). They are
the same bounds the qualification tests apply; the tests keep their own independent constants
(``tests/execution/mujoco_squat``) so that a change here cannot silently relax the suite.

A criterion's outcome is a diagnostic statement about a model run. It is not sealed
DynamisBench evidence and not a scientific validation.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["CRITERIA", "CRITERIA_SCHEMA", "Criterion", "evaluate"]

CRITERIA_SCHEMA: Final = "dynamisbench.mujoco.squat.criteria/1"


@dataclass(frozen=True, slots=True)
class Criterion:
    """One declared check: how to read the value, and the bound it must satisfy."""

    criterion_id: str
    group: str
    label: str
    unit: str
    bound: str
    rationale: str
    value: Callable[[Mapping[str, Any]], float | None]
    passes: Callable[[float], bool]
    scale: float = 1.0
    """Display scale applied to the value (e.g. 1000 to show metres as millimetres)."""


def _extrema(key: str) -> Callable[[Mapping[str, Any]], float | None]:
    return lambda record: float(record["extrema"][key])


def _summary(*path: str) -> Callable[[Mapping[str, Any]], float | None]:
    def read(record: Mapping[str, Any]) -> float | None:
        value: Any = record["summary"]
        for key in path:
            value = value[key]
        return float(value)

    return read


def _numerics(key: str) -> Callable[[Mapping[str, Any]], float | None]:
    def read(record: Mapping[str, Any]) -> float | None:
        numerics = record.get("numerics")
        return None if numerics is None else float(numerics[key])

    return read


def _ledger_residual(record: Mapping[str, Any]) -> float | None:
    worst = 0.0
    for phase in record["work"].values():
        actuator = phase["positive_j"] + phase["negative_j"]
        residual = actuator - phase["damping_dissipation_j"] - phase["mechanical_energy_change_j"]
        allowance = 0.01 * abs(phase["mechanical_energy_change_j"]) + 1.0
        worst = max(worst, abs(residual) / allowance)
    return worst


CRITERIA: Final[tuple[Criterion, ...]] = (
    Criterion(
        "momentum",
        "Mechanics",
        "Impulse–momentum residual",
        "N·s",
        "< 0.05",
        "momentum change equals the external impulse at every step",
        _extrema("max_momentum_residual_n_s"),
        lambda v: v < 0.05,
    ),
    Criterion(
        "mean-grf",
        "Mechanics",
        "Mean vertical GRF / weight",
        "",
        "1 ± 0.001",
        "starting and ending at rest, the mean ground reaction is the weight",
        _summary("ground_reaction", "mean_vertical_over_weight"),
        lambda v: abs(v - 1.0) < 1e-3,
    ),
    Criterion(
        "ledger",
        "Mechanics",
        "Work–energy ledger residual",
        "of allowance",
        "< 1",
        "actuator work − damping = ΔE per phase, within 1 % + 1 J",
        _ledger_residual,
        lambda v: v < 1.0,
    ),
    Criterion(
        "plan-grf",
        "Mechanics",
        "Internal-model plan vs measured GRF",
        "% weight",
        "< 3",
        "the internal model predicts the simulated ground reaction",
        _summary("ground_reaction", "planned_minus_measured_rms_over_weight"),
        lambda v: v < 0.03,
        100.0,
    ),
    Criterion(
        "loaded",
        "Contact",
        "Loaded plantar contacts (min)",
        "of 10",
        "= 10",
        "every plantar point bears load (> 5 N) throughout",
        _extrema("min_loaded_sole_contacts"),
        lambda v: v == 10,
    ),
    Criterion(
        "point-load",
        "Contact",
        "Lightest contact-point load",
        "N",
        "> 10",
        "no plantar point unloads",
        _extrema("min_contact_point_load_n"),
        lambda v: v > 10.0,
    ),
    Criterion(
        "load-sum",
        "Contact",
        "Σ point loads − total GRF",
        "N",
        "< 1e-6",
        "the per-point loads account for the whole ground reaction",
        _extrema("max_contact_load_sum_error_n"),
        lambda v: v < 1e-6,
    ),
    Criterion(
        "heel",
        "Contact",
        "Heel load share, min foot",
        "%",
        "> 20",
        "the heels stay loaded on each foot: no heel rise",
        _extrema("min_heel_load_fraction_per_foot"),
        lambda v: v > 0.2,
        100.0,
    ),
    Criterion(
        "slip",
        "Contact",
        "Foot slip (contact point)",
        "mm",
        "< 2",
        "shod feet do not slide during a squat",
        _extrema("max_sole_point_slip_m"),
        lambda v: v < 0.002,
        1000.0,
    ),
    Criterion(
        "friction",
        "Contact",
        "Friction use per contact",
        "%",
        "< 50",
        "each contact stays inside its friction cone",
        _extrema("max_friction_utilization"),
        lambda v: v < 0.5,
        100.0,
    ),
    Criterion(
        "weld",
        "Coupling & joints",
        "Bar shelf weld error",
        "mm",
        "< 0.5",
        "the bar stays on the upper-trapezius shelf",
        _extrema("max_weld_position_error_m"),
        lambda v: v < 5e-4,
        1000.0,
    ),
    Criterion(
        "grip",
        "Coupling & joints",
        "Hand grip error",
        "mm",
        "< 0.5",
        "the hands stay on the bar",
        _extrema("max_grip_error_m"),
        lambda v: v < 5e-4,
        1000.0,
    ),
    Criterion(
        "range",
        "Coupling & joints",
        "Joint range violation",
        "°",
        "= 0",
        "no joint passes its anatomical stop",
        _extrema("max_range_violation_deg"),
        lambda v: v == 0.0,
    ),
    Criterion(
        "saturation",
        "Coupling & joints",
        "Actuator saturation",
        "% steps",
        "= 0",
        "no actuator reaches its capacity",
        _extrema("saturated_fraction"),
        lambda v: v == 0.0,
        100.0,
    ),
    Criterion(
        "depth",
        "Human-likeness",
        "Bottom knee flexion",
        "°",
        "118–122",
        "the measured bottom reaches the configured depth (120 deg is parallel here)",
        _summary("bottom", "knee_flexion_deg"),
        lambda v: 118.0 < v < 122.0,
    ),
    Criterion(
        "spine",
        "Human-likeness",
        "Lumbar excursion (neutral spine)",
        "°",
        "< 5",
        "no lumbar flexion at depth",
        _summary("ranges", "max_abs_lumbar_flexion_deg"),
        lambda v: v < 5.0,
    ),
    Criterion(
        "knee-moment",
        "Human-likeness",
        "Peak knee extensor moment",
        "N·m/kg",
        "1.0–2.2",
        "magnitude reported for light-load squats",
        _summary("torques", "knee_flexion_l", "peak_extensor_nm_per_kg"),
        lambda v: 1.0 < v < 2.2,
    ),
    Criterion(
        "cop",
        "Human-likeness",
        "CoP margin to loaded polygon",
        "mm",
        "> 30",
        "the centre of pressure stays well inside the loaded support polygon",
        _summary("balance", "min_cop_margin_m"),
        lambda v: v > 0.03,
        1000.0,
    ),
    Criterion(
        "com",
        "Human-likeness",
        "CoM offset from the mid-foot",
        "mm",
        "< 10",
        "the whole-system centre of mass stays over the mid-foot",
        lambda r: max(abs(x - 0.05) for x in r["summary"]["balance"]["com_x_range_m"]),
        lambda v: v < 0.01,
        1000.0,
    ),
    Criterion(
        "timestep",
        "Numerics",
        "Knee angle, dt 1 ms vs 0.5 ms",
        "°",
        "< 0.5",
        "the motion is insensitive to halving the timestep",
        _numerics("max_knee_angle_difference_deg"),
        lambda v: v < 0.5,
    ),
    Criterion(
        "convergence",
        "Numerics",
        "Momentum residual ratio, dt vs dt/2",
        "",
        "1.7–2.3",
        "what remains is first-order integration error",
        _numerics("momentum_residual_ratio"),
        lambda v: 1.7 < v < 2.3,
    ),
    Criterion(
        "tracking-invariance",
        "Numerics",
        "Tracking error change with dt",
        "°",
        "< 0.02",
        "a synchronized measurement does not depend on the timestep",
        _numerics("tracking_error_difference_deg"),
        lambda v: v < 0.02,
    ),
)


def _strictly_between(value: float, *, low: float, high: float) -> bool:
    return low < value < high


def evaluate(record: Mapping[str, Any], *, depth_target_deg: float = 120.0) -> list[dict[str, Any]]:
    """Evaluate every criterion on one recording; unavailable values are ``not evaluated``.

    ``depth_target_deg`` is the configured bottom knee flexion. The depth criterion is the one
    configuration-dependent bound: the measured bottom must be within 2 degrees of the target
    (118-122 for the nominal parallel squat).
    """
    results = []
    for criterion in CRITERIA:
        value = criterion.value(record)
        bound = criterion.bound
        passes: Callable[[float], bool] = criterion.passes
        if criterion.criterion_id == "depth":
            low, high = depth_target_deg - 2.0, depth_target_deg + 2.0
            bound = f"{low:g}–{high:g}"
            passes = functools.partial(_strictly_between, low=low, high=high)

        status = "not_evaluated" if value is None else ("pass" if passes(value) else "fail")
        results.append(
            {
                "criterion_id": criterion.criterion_id,
                "group": criterion.group,
                "label": criterion.label,
                "unit": criterion.unit,
                "bound": bound,
                "rationale": criterion.rationale,
                "value": None if value is None else value * criterion.scale,
                "status": status,
            }
        )
    return results
