"""Pinned identities of the barbell back-squat realization: names, versions, digests, domains.

Pure Python; no engine import. This module is to the squat realization what
:mod:`dynamisbench.adapters.mujoco.reference` is to the reference pendulum: the reviewed
constants the isolated worker compares a request against. The definitions those digests are
taken over live in :mod:`.case`; ``python/tools/mujoco_squat_authority.py`` regenerates both
the workspace documents and these pins, and the qualification suite recomputes every digest
and compares it with the pin. A definition that keeps its identifier and version but changes
its meaning therefore never reaches the compiled physics.

The configuration domain — :data:`FACTOR_DOMAINS` — is the set of configurations this adapter
is qualified to execute. The study declares the same supports; the worker refuses a value
outside them rather than clipping it.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import Final

from dynamisbench.adapters.mujoco.squat import contract
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
    "ENVIRONMENT_SEMANTIC_DIGESTS",
    "ENVIRONMENT_VERSION",
    "FACTOR_DOMAINS",
    "IMPLEMENTATION_IDENTITY_SCHEMA",
    "MODEL_SOURCE_PATH",
    "OUTCOME",
    "PYTHON_SERIES",
    "REALIZATION_ID",
    "REALIZATION_SEMANTIC_DIGEST",
    "REALIZATION_VERSION",
    "SCENARIO_ID",
    "SCENARIO_SEMANTIC_DIGEST",
    "SCENARIO_VERSION",
    "SEED",
    "STUDY_ID",
    "STUDY_VERSION",
    "SUT_ID",
    "SUT_SEMANTIC_DIGEST",
    "SUT_VERSION",
    "FactorDomain",
    "SquatAuthorityError",
    "environment_id_for",
    "environment_semantic_digest_for",
    "platform_tag",
]

ADAPTER_ID: Final = "dynamisbench.mujoco.squat"
ADAPTER_VERSION: Final = "0.1.0"
CAPABILITIES: Final = (Capability.FORWARD_DYNAMICS,)

BENCHMARK_ID: Final = "db.squat.back-squat"
BENCHMARK_VERSION: Final = "1.0.0"
SCENARIO_ID: Final = "sc.squat.controlled-repetition"
SCENARIO_VERSION: Final = "1.0.0"
REALIZATION_ID: Final = "rl.mujoco.squat.torque-driven"
REALIZATION_VERSION: Final = "1.0.0"
SUT_ID: Final = "sut.squat.athlete-barbell"
SUT_VERSION: Final = "1.0.0"
ENVIRONMENT_VERSION: Final = "1.0.0"
STUDY_ID: Final = "st.squat.configuration"
STUDY_VERSION: Final = "1.0.0"
OUTCOME: Final = "repetition-record"
SEED: Final = 0
"""The physics is deterministic and consumes no randomness; the seed is recorded, not used."""

PYTHON_SERIES: Final = ("3.12.0", "3.13.0")
"""The CPython series the squat worker environment admits: ``>=3.12.0, <3.13.0``.

Unlike the reference pendulum (exact 3.12.13), the exact patch is not part of the
environment *definition*: it is observed at run time and bound into the adapter
implementation digest, which every sealed run records. Two runs therefore share an
implementation digest only on the same CPython patch; reproducibility is claimed per
implementation digest and never across patches."""

MODEL_SOURCE_PATH: Final = "models/squat/barbell_back_squat.xml"
"""The workspace-relative authority path of the realization's model asset."""

IMPLEMENTATION_IDENTITY_SCHEMA: Final = "dynamisbench.mujoco.squat.implementation-identity/1"

ADAPTER_SOURCE_FILES: Final = (
    "squat/__init__.py",
    "squat/analysis.py",
    "squat/anthropometry.py",
    "squat/case.py",
    "squat/contract.py",
    "squat/control.py",
    "squat/criteria.py",
    "squat/engine.py",
    "squat/identity.py",
    "squat/mjcf.py",
    "squat/movement.py",
    "squat/native.py",
    "squat/pins.py",
    "squat/stance.py",
    "squat/worker.py",
    "dependencies.py",
    f"squat/{contract.MODEL_ASSET_PATH}",
)
"""Every file (relative to ``dynamisbench.adapters.mujoco``) whose bytes are part of the squat
adapter's implementation identity. Explicit, so a new production file is a reviewed addition.
``__main__.py`` (fixed-mode observations) is not the worker and is deliberately absent."""


@dataclass(frozen=True, slots=True)
class FactorDomain:
    """One configurable parameter: its factor, canonical quantity, unit and qualified range."""

    factor_id: str
    quantity_id: str
    unit: str
    parameter: str
    label: str
    lower: float
    upper: float
    nominal: float


FACTOR_DOMAINS: Final[tuple[FactorDomain, ...]] = (
    FactorDomain(
        "f.squat.bottom-knee-flexion",
        "q.squat.bottom-knee-flexion-target",
        "1",
        "bottom-knee-flexion",
        "Target knee flexion at the bottom",
        1.5707963267948966,  # 90 deg
        2.0943951023931953,  # 120 deg (parallel depth for this model)
        2.0943951023931953,
    ),
    FactorDomain(
        "f.squat.descent-duration",
        "q.squat.descent-duration",
        "s",
        "descent-duration",
        "Intended descent duration",
        1.0,
        2.0,
        1.5,
    ),
    FactorDomain(
        "f.squat.ascent-duration",
        "q.squat.ascent-duration",
        "s",
        "ascent-duration",
        "Intended ascent duration",
        0.8,
        1.6,
        1.2,
    ),
    FactorDomain(
        "f.squat.integration-timestep",
        "q.squat.integration-timestep",
        "s",
        "timestep",
        "Integration timestep",
        0.00025,
        0.001,
        0.001,
    ),
    FactorDomain(
        "f.squat.internal-model-gain",
        "q.squat.internal-model-gain",
        "1",
        "internal-model-gain",
        "Internal-model dynamics gain",
        0.0,
        1.0,
        1.0,
    ),
    FactorDomain(
        "f.squat.sole-friction-time-constant",
        "q.squat.sole-friction-time-constant",
        "s",
        "sole-friction-time-constant",
        "Sole friction time constant",
        0.002,
        0.015,
        0.002,
    ),
)
"""The qualified configuration domain, in canonical SI units. Angles are radians."""

# --- pinned semantic digests (regenerate with python/tools/mujoco_squat_authority.py) ------

BENCHMARK_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="8b581aa2814283d58e291494f593e0be570b5f2e10d7860b794464d199667201"
)
SCENARIO_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="02ea513eca7770742ebac0c5b41d3c3588b869b123616b42b0061fbef0c9088e"
)
REALIZATION_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="60183b7353ef442da1f808f515643ac61b6bba5df4db2883550ebaf7292bc4de"
)
SUT_SEMANTIC_DIGEST: Final = SemanticDigest(
    hex="bf50027c197775b8c56492b397f51a048f1eadca243dba83a78bb57bb67fbb9b"
)
ENVIRONMENT_SEMANTIC_DIGESTS: Final = {
    "windows-x86-64": SemanticDigest(
        hex="2880abe8add283aa60226691888d693421463a3a768af83909ea78aa7e46f4fc"
    ),
    "linux-x86-64": SemanticDigest(
        hex="8a8c34161f79d530d1eb279769603c9133029547e55c724c322b21c74f4fb42b"
    ),
}


class SquatAuthorityError(Exception):
    """A request or host is not the compiled squat realization's authority."""


def platform_tag() -> str:
    """The qualified platform identity: Windows x86-64 or Linux x86-64, nothing else."""
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64", "x64"}:
        return "windows-x86-64"
    if sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        return "linux-x86-64"
    raise SquatAuthorityError(
        "the squat adapter is qualified on Windows x86-64 and Linux x86-64 only; "
        f"observed sys.platform={sys.platform!r}, machine={platform.machine()!r}"
    )


def environment_id_for(platform_name: str) -> str:
    """The environment identifier of one qualified platform."""
    if platform_name not in ENVIRONMENT_SEMANTIC_DIGESTS:
        raise SquatAuthorityError(f"no squat environment authority for platform {platform_name!r}")
    return f"env.mujoco.squat.{platform_name}"


def environment_semantic_digest_for(platform_name: str) -> SemanticDigest:
    """The reviewed semantic digest of the environment on one qualified platform."""
    try:
        return ENVIRONMENT_SEMANTIC_DIGESTS[platform_name]
    except KeyError as error:
        raise SquatAuthorityError(
            f"no squat environment authority for platform {platform_name!r}"
        ) from error
