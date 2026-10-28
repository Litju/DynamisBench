"""The first real MuJoCo capability adapter: a fixed forward-dynamics reference case.

This package is the authorized engine adapter boundary (ADR-001). It is deliberately
narrow: it implements one self-contained planar-pendulum reference case, advertises only
the ``forward_dynamics`` capability it actually executes, and refuses every other
realization, outcome, engine version, or adapter identity.

**Import boundary.** Importing this package imports no MuJoCo and no NumPy. The engine is
imported only by :mod:`dynamisbench.adapters.mujoco.physics`, which is imported only by the
isolated worker entry point. The engine-independent scientific core, planner, API and
desktop shell never import that module.

**Why the model is compiled into the adapter.** The accepted worker protocol carries the
resolved ``RunSpec`` identities — benchmark, scenario, realization, environment, seed and
outcomes — but not the definitions or asset bytes those identities name. A worker therefore
cannot resolve an arbitrary model path without a protocol field or an absolute path, and
neither is authorized in RES-550. The reference case is instead a *compiled* realization:
its model bytes, initial state, timestep, horizon, solver configuration and zero-control
policy are part of this implementation, and the adapter's implementation digest binds
them. The authoritative realization asset is verified byte-for-byte against the same
compiled model during preflight. That is sufficient for this fixed reference adapter and is
not a general arbitrary-model adapter; a later, separately authorized content-addressed
asset-materialization gate is required before a generic MuJoCo realization can run.

**Why the semantic digests are pinned.** An identifier and version name an artifact, not its
meaning. The reviewed definitions in :mod:`~dynamisbench.adapters.mujoco.reference_case` are
therefore bound by semantic digests pinned in
:mod:`~dynamisbench.adapters.mujoco.reference`, and the worker refuses any request whose
resolved digests differ before it advances physics. A re-authored benchmark, scenario,
realization, system under test or environment that keeps every visible name is still a
different experiment. The implementation identity additionally binds the installed worker
dependency closure; see :mod:`~dynamisbench.adapters.mujoco.dependencies`.
"""

from __future__ import annotations
