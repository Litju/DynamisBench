"""Barbell back-squat model: a synthetic 75 kg, 1.75 m athlete with a 20 kg barbell in MuJoCo.

Module map (engine-free unless stated):

* :mod:`.anthropometry` - declared segment inertia (de Leva 1996), lengths, joint ranges,
  torque capacities, passive joint properties and barbell geometry, each with its source;
* :mod:`.mjcf` - deterministic MJCF rendering of that authority;
* :mod:`.stance` - stance, balance point and posture preferences (no trajectories);
* :mod:`.contract` - packaged asset identity (pinned SHA-256) and claim limit;
* :mod:`.control` - the postural and movement controller law (NumPy only);
* :mod:`.movement` - repetition plan, minimum-jerk intent, measured-state phase machine and
  phase detection (NumPy only; no joint states);
* :mod:`.analysis` - summary metrics of a recorded repetition (NumPy only);
* :mod:`.engine` - the **only** module of this package that imports MuJoCo;
* :mod:`.criteria` - the predeclared acceptance criteria of a repetition;
* :mod:`.case` - the study's authority: benchmark release (quantities, metrics), scenario,
  realization (configuration, asset, quantity mappings), system under test, environments and
  the configuration study, with their qualified factor domains;
* :mod:`.pins` - the pinned identities and semantic digests the worker admits;
* :mod:`.native` - the native output schema (Parquet samples and state, run record);
* :mod:`.identity` - the worker's implementation identity (files, engine, CPython, closure);
* :mod:`.worker` - the RunSpec worker entry point (protocol v1), run by the supervisor;
* ``python -I -m dynamisbench.adapters.mujoco.squat <mode>`` - fixed-mode observations.

Importing this package imports neither MuJoCo nor NumPy. The squat realization is executed
through the ``RunSpec -> preflight -> supervisor -> worker`` path by :mod:`.worker`; see
:mod:`.contract` for the two claims its outputs carry.
"""

from __future__ import annotations

from . import anthropometry, criteria

__all__ = ["anthropometry", "criteria"]
