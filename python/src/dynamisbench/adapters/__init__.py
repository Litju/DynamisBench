"""Engine adapters.

The only place permitted to import simulator libraries. Adapters map DynamisBench
capability contracts to engine-native APIs; engine-native objects never cross into
the core public model (ADR-001). Realizations advertise capabilities and studies
declare requirements rather than sharing a universal reset/step abstraction (ADR-003).

:mod:`dynamisbench.adapters.mujoco` is the first implemented adapter (RES-550): one fixed,
self-contained planar-pendulum forward-dynamics reference case, advertised as
``forward_dynamics`` only. Its engine import is confined to ``physics.py`` and is loaded
only by the isolated worker. Importing this package or the adapter's pure reference and
identity modules does not import MuJoCo."""
