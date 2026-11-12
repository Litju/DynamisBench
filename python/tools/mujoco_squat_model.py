"""Generate or check the packaged barbell back-squat MJCF asset.

The asset is not hand-written. It is the deterministic rendering of the declared anthropometry
(:mod:`dynamisbench.adapters.mujoco.squat.mjcf`) plus one standing keyframe that the isolated
MuJoCo worker computes from the declarations (posture solve, contact settle, minimum-effort
tonic torques, forward-dynamics relaxation to rest).

Run from ``python/`` with the isolated worker environment provisioned:

    uv run python tools/mujoco_squat_model.py --check
    uv run python tools/mujoco_squat_model.py --write

``--check`` fails (exit 1) when the packaged asset is not exactly the renderer's output for its
own keyframe, when its keyframe is not the freshly generated one within
:data:`KEYFRAME_TOLERANCE`, or when its SHA-256 is not the reviewed pin in
``squat/contract.py``. ``--write`` rewrites the asset and prints its digest; updating the pin is
a reviewed change made by hand, never by this tool. The application runtime never imports
MuJoCo: the keyframe is computed by running the worker interpreter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from dynamisbench.adapters.mujoco.squat import contract, mjcf, reference

__all__ = ["keyframe_of", "main"]

PYTHON_DIRECTORY: Final = Path(__file__).resolve().parents[1]
ASSET: Final = (
    PYTHON_DIRECTORY
    / "src"
    / "dynamisbench"
    / "adapters"
    / "mujoco"
    / "squat"
    / contract.MODEL_ASSET_PATH
)
KEYFRAME_TOLERANCE: Final = 1e-6
"""Absolute tolerance between a packaged and a regenerated keyframe value (m, rad or unitless
activation). The keyframe is the end state of a 30 s relaxation, so last-bit floating-point
differences between platforms are admitted; anything physical is not."""

CANONICAL_HEADING_TOLERANCE: Final = 1e-12
"""Structural bound on a regenerated reference's pelvis heading, radians. The generator
projects the relaxed state onto the declared representative, so its heading is zero to
machine precision on every platform; this only refuses a generator that stopped projecting."""


class SquatModelToolError(RuntimeError):
    """The asset could not be generated or checked."""


def worker_python() -> Path:
    configured = os.environ.get("DYNAMISBENCH_MUJOCO_PYTHON")
    candidate = (
        Path(configured)
        if configured
        else PYTHON_DIRECTORY
        / "worker-mujoco"
        / ".venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not candidate.is_file():
        raise SquatModelToolError(
            f"the isolated MuJoCo worker environment is not provisioned at {candidate}; "
            "run `uv sync --frozen --project worker-mujoco` in python/"
        )
    return candidate


def worker_environment(scratch: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The minimal worker environment, plus explicit diagnostic overrides.

    The whitelist is the production set. ``extra`` exists for the RES-640 stability receipt,
    which replays the generator under a different numeric-library dispatch; production
    callers pass nothing and the worker sees only the whitelisted variables.
    """
    environment = {"PYTHONHASHSEED": "0", "TMP": str(scratch), "TEMP": str(scratch)}
    for name in ("SYSTEMROOT", "WINDIR", "PATH", "HOME", "USERPROFILE", "LANG"):
        if name in os.environ:
            environment[name] = os.environ[name]
    if extra:
        environment.update({str(name): str(value) for name, value in extra.items()})
    return environment


def generate_keyframe(*, environment_extra: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Run the worker's ``--keyframe`` mode and return its observation.

    ``environment_extra`` is diagnostic only (see :func:`worker_environment`); the packaged
    reference is generated with the default environment.
    """
    with tempfile.TemporaryDirectory(prefix="dynamisbench-squat-keyframe-") as scratch:
        completed = subprocess.run(
            [str(worker_python()), "-I", "-m", "dynamisbench.adapters.mujoco.squat", "--keyframe"],
            cwd=scratch,
            env=worker_environment(Path(scratch), environment_extra),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    if completed.returncode != 0:
        raise SquatModelToolError(f"the keyframe worker failed: {completed.stderr[-2000:]}")
    payload = json.loads(completed.stdout)
    if payload.get("schema") != contract.OBSERVATION_SCHEMA or payload.get("mode") != "keyframe":
        raise SquatModelToolError("the keyframe worker did not emit a keyframe observation")
    return payload


def keyframe_of(content: bytes) -> tuple[list[float], list[float]]:
    """Parse the ``stand`` keyframe ``(qpos, act)`` of an MJCF document."""
    root = ElementTree.fromstring(content)
    keys = root.findall("./keyframe/key")
    if len(keys) != 1 or keys[0].attrib.get("name") != mjcf.KEYFRAME_NAME:
        raise SquatModelToolError("the asset does not have exactly one 'stand' keyframe")
    key = keys[0].attrib
    if key.get("act") != key.get("ctrl"):
        raise SquatModelToolError("the keyframe control is not its tonic activation")
    return (
        [float(value) for value in key["qpos"].split()],
        [float(value) for value in key.get("act", "").split()],
    )


def check() -> list[str]:
    """Return every way the packaged asset differs from its authority (empty when it agrees).

    The keyframe is compared as the *physical* standing state: both the packaged and the
    regenerated ``qpos`` are projected onto the declared representative of the model's exact
    world-frame gauge before the elementwise comparison. A whole-system heading is not a
    physical quantity of a model whose floor is an infinite plane (see
    :mod:`dynamisbench.adapters.mujoco.squat.reference`), and the generator's contact settle
    cannot determine it: it samples it from last-bit rounding at the 1e-6 rad level, which is
    the drift RES-640 diagnosed. Every other coordinate is compared exactly as before, with
    the same tolerance; nothing physical is excused.
    """
    problems: list[str] = []
    content = ASSET.read_bytes()
    qpos, act = keyframe_of(content)
    if mjcf.render_model_xml(qpos, act).encode("utf-8") != content:
        problems.append("the asset is not the renderer's output for its own keyframe")
    digest = hashlib.sha256(content).hexdigest()
    if digest != contract.MODEL_SHA256:
        problems.append(f"the asset digest {digest} is not the pinned {contract.MODEL_SHA256}")
    fresh = generate_keyframe()
    expected = reference.BAR_QPOS + 7
    if len(qpos) != expected or len(fresh["qpos"]) != expected:
        problems.append(f"the keyframe qpos length changed (expected {expected})")
        packaged_qpos = qpos
        regenerated_qpos = fresh["qpos"]
    else:
        heading = reference.pelvis_heading_rad(fresh["qpos"])
        if not abs(heading) <= CANONICAL_HEADING_TOLERANCE:
            problems.append(
                f"the regenerated keyframe is not in the declared world frame "
                f"(pelvis heading {heading:.3e} rad)"
            )
        packaged_qpos = reference.canonical_world_frame(qpos)
        regenerated_qpos = reference.canonical_world_frame(fresh["qpos"])
    for label, packaged, generated in (
        ("qpos", packaged_qpos, regenerated_qpos),
        ("act", act, fresh["act"]),
    ):
        if len(packaged) != len(generated):
            problems.append(f"the keyframe {label} length changed")
            continue
        if not all(math.isfinite(value) for value in (*packaged, *generated)):
            problems.append(f"the keyframe {label} contains non-finite values")
            continue
        worst = max(abs(a - b) for a, b in zip(packaged, generated, strict=True))
        if worst > KEYFRAME_TOLERANCE:
            problems.append(f"the keyframe {label} differs from the regenerated one by {worst:.3e}")
    return problems


def write() -> str:
    """Regenerate the asset and return its digest.

    The written keyframe is the generator's declared representative of the standing state
    (pelvis heading zero), not the raw relaxation end state.
    """
    fresh = generate_keyframe()
    content = mjcf.render_model_xml(fresh["qpos"], fresh["act"]).encode("utf-8")
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    ASSET.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="verify the packaged asset")
    group.add_argument("--write", action="store_true", help="regenerate the packaged asset")
    arguments = parser.parse_args(argv)
    try:
        if arguments.write:
            digest = write()
            sys.stdout.write(json.dumps({"asset": str(ASSET), "sha256": digest}, indent=2) + "\n")
            if digest != contract.MODEL_SHA256:
                sys.stderr.write(
                    "the asset changed: review it and pin MODEL_SHA256 in squat/contract.py\n"
                )
            return 0
        problems = check()
    except (SquatModelToolError, OSError, ValueError) as error:
        sys.stderr.write(f"mujoco_squat_model: {error}\n")
        return 1
    sys.stdout.write(json.dumps({"asset": str(ASSET), "problems": problems}, indent=2) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
