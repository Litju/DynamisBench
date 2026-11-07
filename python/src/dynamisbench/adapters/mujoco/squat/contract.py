"""Identity, asset and claim contract of the barbell back-squat model.

Pure Python; no engine import. The packaged MJCF asset is verified byte-for-byte against
:data:`MODEL_SHA256` every time it is read, exactly as the reference pendulum adapter does, so
a modified installation is refused rather than simulated.

Scope of this contract. The squat model runs only in the isolated worker environment, in two
ways: the fixed-mode qualification entry points (``python -I -m
dynamisbench.adapters.mujoco.squat <mode>``), whose observations are diagnostic and carry
:data:`CLAIM_LIMIT`; and the reviewed RunSpec worker (:mod:`.worker`), admitted through
``RunSpec -> preflight -> supervisor`` against the pinned authority of :mod:`.pins`, whose native
output is sealed as execution evidence and carries :data:`EXECUTION_CLAIM`. Neither changes the
reference pendulum adapter, its identity or the worker protocol.
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import Final

__all__ = [
    "CLAIM_LIMIT",
    "ENGINE",
    "EXECUTION_CLAIM",
    "ENGINE_VERSION",
    "MODEL_ASSET_PATH",
    "MODEL_SHA256",
    "OBSERVATION_SCHEMA",
    "SquatModelError",
    "model_bytes",
]

ENGINE: Final = "mujoco"
ENGINE_VERSION: Final = "3.17.0"
"""The engine release the model was generated and qualified with (the worker lock pin)."""

MODEL_ASSET_PATH: Final = "assets/barbell_back_squat.xml"
"""Package-relative path of the generated MJCF asset."""
MODEL_SHA256: Final = "c91b2fa2ca1e04f920f4685bc23be2a99a64ad697dcd6a40cf5699dc5761a947"
"""Raw-byte SHA-256 of the reviewed asset. Regenerate with
``python/tools/mujoco_squat_model.py --write``; a changed pin is a reviewed model change."""

OBSERVATION_SCHEMA: Final = "dynamisbench.mujoco.squat.observation/1"

CLAIM_LIMIT: Final = (
    "Mechanical consistency and closed-loop forward-dynamics behaviour of a synthetic, "
    "population-scaled athlete-barbell model in MuJoCo. Not validated against measured "
    "human motion, not subject-specific, not native/canonical/assessment evidence, and not "
    "a DynamisBench benchmark execution."
)
"""The claim of the fixed-mode qualification observations (diagnostic, never sealed)."""


EXECUTION_CLAIM: Final = (
    "Native output of one admitted execution of the squat realization (RunSpec, preflight, "
    "isolated worker), sealed as execution evidence. A forward-dynamics simulation of a "
    "synthetic, population-scaled athlete-barbell model: not validated against measured human "
    "motion and not subject-specific."
)
"""The claim the RunSpec worker's run record carries (the fixed modes carry CLAIM_LIMIT)."""


class SquatModelError(Exception):
    """The squat model asset or a squat-model computation could not be established."""


def model_bytes() -> bytes:
    """Return the reviewed asset bytes, or refuse if they are absent or not the pinned bytes."""
    try:
        content = (
            files("dynamisbench.adapters.mujoco.squat").joinpath(MODEL_ASSET_PATH).read_bytes()
        )
    except (FileNotFoundError, OSError) as error:
        raise SquatModelError(f"the squat model asset is unavailable: {error}") from error
    digest = hashlib.sha256(content).hexdigest()
    if digest != MODEL_SHA256:
        raise SquatModelError(
            f"the squat model asset digest {digest} is not the reviewed {MODEL_SHA256}"
        )
    return content
