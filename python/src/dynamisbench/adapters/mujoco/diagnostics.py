"""The adapter-owned diagnostic emitted on stderr after a real MuJoCo run.

This is **not** NativeEvidence under the Evidence & Provenance Model. It is the reference
adapter's bounded process diagnostic, carried on the ordinary stderr channel the accepted
worker contract already defines and retained by the supervisor only as a bounded log. It is
not written to ``native/``, not sealed as native output, not normalized to a canonical
quantity, and not assessed. Its purpose is to let an operator and the qualification suite
observe what the real engine did without inventing an evidence-staging interface that
RES-550 is not authorized to add.

A later evidence-extraction gate may promote a reviewed subset of these fields into a
native artifact with its own schema and provenance. Nothing in this module claims that has
happened.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dynamisbench.adapters.mujoco.reference import REFERENCE_DIAGNOSTIC_SCHEMA

__all__ = ["ReferenceDiagnostic", "StateSample"]

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class StateSample(BaseModel):
    """One physical state and its analytically computed pendulum energy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    time_s: float = Field(ge=0, allow_inf_nan=False)
    angle_rad: float = Field(allow_inf_nan=False)
    angular_velocity_rad_s: float = Field(allow_inf_nan=False)
    energy_j: float = Field(allow_inf_nan=False)


class ReferenceDiagnostic(BaseModel):
    """The complete bounded diagnostic of one reference run.

    Every numeric field is finite by construction; the model refuses a non-finite value
    rather than serialising one. The fields are adapter-native observations, not canonical
    DynamisBench quantities.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["dynamisbench.mujoco.reference-diagnostic/1"] = REFERENCE_DIAGNOSTIC_SCHEMA
    adapter_id: str
    adapter_version: str
    engine: str
    engine_version: str
    implementation_digest: str = Field(pattern=_SHA256_PATTERN)
    model_sha256: str = Field(pattern=_SHA256_PATTERN)
    platform: str
    python_version: str
    run_id: str
    execution_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    benchmark: str
    scenario: str
    realization: str
    environment_id: str
    seed: int = Field(ge=0)
    outcomes: tuple[str, ...]
    control_policy: str
    integrator: str
    solver: str
    timestep_s: float = Field(gt=0, allow_inf_nan=False)
    duration_s: float = Field(gt=0, allow_inf_nan=False)
    steps: int = Field(gt=0)
    nq: int = Field(ge=0)
    nv: int = Field(ge=0)
    nu: int = Field(ge=0)
    njnt: int = Field(ge=0)
    ngeom: int = Field(ge=0)
    joint_constraints: str
    contact_policy: str
    solver_iterations: int = Field(gt=0)
    solver_tolerance: float = Field(gt=0, allow_inf_nan=False)
    precision: Literal["float64"] = "float64"
    randomness_policy: str
    gravity_m_s2: float = Field(gt=0, allow_inf_nan=False)
    mass_kg: float = Field(gt=0, allow_inf_nan=False)
    com_distance_m: float = Field(gt=0, allow_inf_nan=False)
    hinge_inertia_kg_m2: float = Field(gt=0, allow_inf_nan=False)
    initial: StateSample
    final: StateSample
    checkpoints: tuple[StateSample, ...]
    energy_initial_j: float = Field(allow_inf_nan=False)
    energy_final_j: float = Field(allow_inf_nan=False)
    energy_drift_j: float = Field(allow_inf_nan=False)
    max_relative_energy_drift: float = Field(ge=0, allow_inf_nan=False)
    trajectory_sha256: str = Field(pattern=_SHA256_PATTERN)
    all_finite: bool
    stochastic: Literal[False] = False
    native_state_layout: str
    claim: str
