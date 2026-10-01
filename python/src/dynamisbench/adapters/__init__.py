"""Engine adapters.

The only place permitted to import simulator libraries. Adapters map DynamisBench
capability contracts to engine-native APIs; engine-native objects never cross into
the core public model (ADR-001). Realizations advertise capabilities and studies
declare requirements rather than sharing a universal reset/step abstraction (ADR-003).

No adapter is implemented in DB-1.1: MuJoCo is the first planned adapter, OpenSim/Moco
the second."""
