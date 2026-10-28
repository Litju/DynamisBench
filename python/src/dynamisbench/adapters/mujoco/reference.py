"""The compiled physical and identity constants of the MuJoCo reference adapter.

Nothing here imports MuJoCo. The module is a pure description of the one reference case the
adapter executes, so the test suite, the preflight fixture and the worker can compare the
same constants without loading the engine in the core process.

The model is a single rigid body on a frictionless hinge. Its physical parameters are
stated here as constants *and* encoded in ``assets/reference_pendulum.xml``; the adapter
verifies the XML content digest and reports the model-derived mass, centre-of-mass distance
and hinge inertia, while the tests independently parse the XML and solve the corresponding
nonlinear pendulum equation. The constants are therefore a contract to be checked, not a
substitute for the model.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from importlib.resources import files
from typing import Final

from dynamisbench.domain.spec.capability import Capability

__all__ = [
    "ADAPTER_ID",
    "ADAPTER_SOURCE_FILES",
    "ADAPTER_VERSION",
    "BENCHMARK_ID",
    "BENCHMARK_VERSION",
    "CAPABILITIES",
    "CHECKPOINT_TIMES_S",
    "COM_INERTIA_KG_M2",
    "COM_DISTANCE_M",
    "CONTACT_POLICY",
    "CONTROL_POLICY",
    "DURATION_S",
    "ENGINE",
    "ENVIRONMENT_VERSION",
    "GRAVITY_M_S2",
    "GRAVITY_UNIT",
    "HINGE_INERTIA_KG_M2",
    "IMPLEMENTATION_IDENTITY_SCHEMA",
    "INITIAL_ANGLE_RAD",
    "INITIAL_ANGULAR_VELOCITY_RAD_S",
    "INTEGRATOR",
    "ITERATIONS",
    "JOINT_CONSTRAINTS",
    "MASS_KG",
    "MODEL_ASSET_PATH",
    "MODEL_SHA256",
    "NATIVE_STATE_LAYOUT",
    "OUTCOME",
    "QUALIFICATION_SCHEMA",
    "RANDOMNESS_POLICY",
    "REALIZATION_ID",
    "REALIZATION_VERSION",
    "REFERENCE_DIAGNOSTIC_SCHEMA",
    "SCENARIO_ID",
    "SCENARIO_VERSION",
    "SOLVER",
    "STEPS",
    "SUT_ID",
    "SUT_VERSION",
    "TIMESTEP_S",
    "TOLERANCE",
    "ReferenceAdapterError",
    "ReferenceModelError",
    "ReferencePlatformError",
    "expected_environment_id",
    "model_bytes",
    "platform_tag",
]

ADAPTER_ID: Final = "dynamisbench.mujoco.reference"
ADAPTER_VERSION: Final = "0.1.0"
ENGINE: Final = "mujoco"
CAPABILITIES: Final = (Capability.FORWARD_DYNAMICS,)
"""The only capability this adapter implements and has qualified."""

BENCHMARK_ID: Final = "db.reference.pendulum"
BENCHMARK_VERSION: Final = "1.0.0"
SCENARIO_ID: Final = "sc.reference.pendulum"
SCENARIO_VERSION: Final = "1.0.0"
REALIZATION_ID: Final = "rl.mujoco.reference-pendulum"
REALIZATION_VERSION: Final = "1.0.0"
SUT_ID: Final = "sut.reference.pendulum"
SUT_VERSION: Final = "1.0.0"
ENVIRONMENT_VERSION: Final = "1.0.0"
OUTCOME: Final = "reference-state"

MODEL_ASSET_PATH: Final = "assets/reference_pendulum.xml"
MODEL_SHA256: Final = "eac679a723ccfebb48ea5ee40692fa6ee38f965772b484b94b827be6b9dbfdfd"
"""Raw-byte SHA-256 of the reviewed reference model."""

ADAPTER_SOURCE_FILES: Final = (
    "__init__.py",
    "__main__.py",
    "diagnostics.py",
    "identity.py",
    "physics.py",
    "reference.py",
    "worker.py",
    MODEL_ASSET_PATH,
)
"""Every file whose bytes are part of the adapter implementation identity.

``qualification.py`` is deliberately absent: it is a qualification-only observation tool,
not part of the execution implementation. The list is explicit rather than a directory walk
so a new production file is a reviewed addition to the identity.
"""

MASS_KG: Final = 1.0
COM_DISTANCE_M: Final = 1.0
COM_INERTIA_KG_M2: Final = 0.001
HINGE_INERTIA_KG_M2: Final = COM_INERTIA_KG_M2 + MASS_KG * COM_DISTANCE_M**2
"""Inertia about the hinge axis: centre-of-mass inertia plus the parallel-axis term."""

GRAVITY_M_S2: Final = 9.80665
GRAVITY_UNIT: Final = "m*s^-2"
"""The domain's canonical SI spelling of acceleration (``m/s^2`` canonicalises to this)."""
INITIAL_ANGLE_RAD: Final = 0.5235987755982988
"""Thirty degrees, the exact initial condition of the reference scenario."""
INITIAL_ANGULAR_VELOCITY_RAD_S: Final = 0.0
TIMESTEP_S: Final = 0.001
DURATION_S: Final = 2.0
STEPS: Final = 2000
INTEGRATOR: Final = "RK4"
SOLVER: Final = "Newton"
ITERATIONS: Final = 100
TOLERANCE: Final = 1e-12
CHECKPOINT_TIMES_S: Final = (0.0, 0.5, 1.0, 1.5, 2.0)
CONTROL_POLICY: Final = "zero control; the model has no actuators"
JOINT_CONSTRAINTS: Final = "none; one unconstrained hinge"
CONTACT_POLICY: Final = "no geoms; no contacts"
RANDOMNESS_POLICY: Final = "no stochastic process; the RunSpec seed is recorded, not consumed"
NATIVE_STATE_LAYOUT: Final = "qpos[0]=hinge angle (rad); qvel[0]=hinge angular velocity (rad/s)"

REFERENCE_DIAGNOSTIC_SCHEMA: Final = "dynamisbench.mujoco.reference-diagnostic/1"
IMPLEMENTATION_IDENTITY_SCHEMA: Final = "dynamisbench.mujoco.implementation-identity/1"
QUALIFICATION_SCHEMA: Final = "dynamisbench.mujoco.qualification/1"


class ReferenceAdapterError(Exception):
    """Base class for a fixed-reference adapter refusal."""


class ReferenceModelError(ReferenceAdapterError):
    """The packaged model is absent, unreadable, or not the reviewed bytes."""


class ReferencePlatformError(ReferenceAdapterError):
    """The host is not one of the two qualified reference platforms."""


def model_bytes() -> bytes:
    """Return the reviewed model bytes, or refuse if the packaged content changed.

    The model is read from package resources and hashed every time it is needed. A model
    that differs from :data:`MODEL_SHA256` is not silently executed: the adapter refuses,
    whether the change came from a modified installation, a substituted package, or a bad
    build.
    """
    try:
        content = files("dynamisbench.adapters.mujoco").joinpath(MODEL_ASSET_PATH).read_bytes()
    except (FileNotFoundError, OSError) as error:
        raise ReferenceModelError(
            "the packaged reference model could not be read from the adapter installation"
        ) from error
    digest = hashlib.sha256(content).hexdigest()
    if digest != MODEL_SHA256:
        raise ReferenceModelError(
            "the packaged reference model is not the reviewed model: "
            f"expected {MODEL_SHA256}, observed {digest}"
        )
    return content


def platform_tag() -> str:
    """Return the qualified platform identity used in the environment identifier.

    Only the two platforms required by the issue are qualified. A different host is a
    refusal rather than an unlabelled execution, because the environment identity and the
    adapter implementation digest both name this tag.
    """
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64", "x64"}:
        return "windows-x86-64"
    if sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        return "linux-x86-64"
    raise ReferencePlatformError(
        f"the reference adapter is qualified on Windows x86-64 and Linux x86-64 only; "
        f"observed sys.platform={sys.platform!r}, machine={platform.machine()!r}"
    )


def expected_environment_id() -> str:
    """The platform-specific environment identifier this adapter is compiled for."""
    return f"env.mujoco.reference.{platform_tag()}"
