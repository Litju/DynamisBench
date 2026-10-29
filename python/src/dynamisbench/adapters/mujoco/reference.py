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
from dynamisbench.identity import SemanticDigest

__all__ = [
    "ADAPTER_ID",
    "ADAPTER_SOURCE_FILES",
    "ADAPTER_VERSION",
    "BENCHMARK_ID",
    "BENCHMARK_SEMANTIC_DIGEST",
    "BENCHMARK_VERSION",
    "CAPABILITIES",
    "CHECKPOINT_TIMES_S",
    "COM_INERTIA_KG_M2",
    "COM_DISTANCE_M",
    "CONTACT_POLICY",
    "CONTROL_POLICY",
    "DURATION_S",
    "ENGINE",
    "ENGINE_VERSION",
    "ENVIRONMENT_SEMANTIC_DIGESTS",
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
    "MODEL_SOURCE_PATH",
    "NATIVE_STATE_LAYOUT",
    "OUTCOME",
    "PYTHON_VERSION",
    "QUALIFICATION_SCHEMA",
    "RANDOMNESS_POLICY",
    "REALIZATION_ID",
    "REALIZATION_SEMANTIC_DIGEST",
    "REALIZATION_VERSION",
    "REFERENCE_DIAGNOSTIC_SCHEMA",
    "SCENARIO_ID",
    "SCENARIO_SEMANTIC_DIGEST",
    "SCENARIO_VERSION",
    "SEED",
    "SOLVER",
    "STEPS",
    "SUT_ID",
    "SUT_SEMANTIC_DIGEST",
    "SUT_VERSION",
    "TIMESTEP_S",
    "TOLERANCE",
    "ReferenceAdapterError",
    "ReferenceModelError",
    "ReferencePlatformError",
    "environment_semantic_digest_for",
    "expected_environment_id",
    "expected_environment_id_for",
    "model_bytes",
    "platform_tag",
]

ADAPTER_ID: Final = "dynamisbench.mujoco.reference"
ADAPTER_VERSION: Final = "0.1.0"
ENGINE: Final = "mujoco"
ENGINE_VERSION: Final = "3.17.0"
"""The one native engine release the qualified reference adapter is compiled for."""
PYTHON_VERSION: Final = "3.12.13"
"""The exact CPython patch release of the isolated worker environment."""
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
SEED: Final = 0
"""The declared seed of the reference run. The physics is deterministic and does not consume
randomness, but the seed remains execution-defining: the compiled reference supports exactly
this value, so a request carrying another seed is a different requested execution."""

MODEL_ASSET_PATH: Final = "assets/reference_pendulum.xml"
MODEL_SOURCE_PATH: Final = "models/reference/pendulum.xml"
"""The workspace-relative authority path of the realization's model asset."""
MODEL_SHA256: Final = "eac679a723ccfebb48ea5ee40692fa6ee38f965772b484b94b827be6b9dbfdfd"
"""Raw-byte SHA-256 of the reviewed reference model."""

BENCHMARK_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="7998fdd62b5d3b29fa5c04a50d9dce9daf506703777e2cc3b51b3ca69f88f7bd"
)
SCENARIO_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="ef31253d815a43b7893e9628e03be6632f385dbd75b568ce816a561261057ccb"
)
REALIZATION_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="f31340c60166f8f37b6a4609929ef7ccf23554b294fb57889e4644d04c86d8cb"
)
SUT_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="7dd9bb16f04c8b15bc012b87660b55d24bd7e6108daffafeaf84f62c719a51ee"
)
ENVIRONMENT_SEMANTIC_DIGESTS: Final = {
    "windows-x86-64": SemanticDigest(
        hex="5391e3ba772aa7fa3b7d01f42a56585f24a4525527e6cd0ba5e672f447ae5231"
    ),
    "linux-x86-64": SemanticDigest(
        hex="8652ad6cc054383eb301183f3036e01f673ccbe8e93b807e4c0968ffa5a73963"
    ),
}
"""Reviewed semantic digests of the exact definitions the adapter is compiled for.

These are not derived from a request. They are generated from
:mod:`dynamisbench.adapters.mujoco.reference_case` by
``python/tools/mujoco_reference_authority.py`` and verified by the qualification suite. A
different definition that keeps the same identifier and version therefore cannot reach the
compiled reference physics.
"""

ADAPTER_SOURCE_FILES: Final = (
    "__init__.py",
    "__main__.py",
    "dependencies.py",
    "diagnostics.py",
    "identity.py",
    "physics.py",
    "reference_case.py",
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


def expected_environment_id_for(platform: str) -> str:
    """The environment identifier of one of the two qualified platforms."""
    if platform not in ENVIRONMENT_SEMANTIC_DIGESTS:
        raise ReferencePlatformError(
            f"the reference adapter has no environment authority for platform {platform!r}; "
            "only Windows x86-64 and Linux x86-64 are qualified"
        )
    return f"env.mujoco.reference.{platform}"


def expected_environment_id() -> str:
    """The platform-specific environment identifier this adapter is compiled for."""
    return expected_environment_id_for(platform_tag())


def environment_semantic_digest_for(platform: str) -> SemanticDigest:
    """The reviewed semantic digest of the environment on one qualified platform."""
    try:
        return ENVIRONMENT_SEMANTIC_DIGESTS[platform]
    except KeyError as error:
        raise ReferencePlatformError(
            f"the reference adapter has no environment authority for platform {platform!r}; "
            "only Windows x86-64 and Linux x86-64 are qualified"
        ) from error
