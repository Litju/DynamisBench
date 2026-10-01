"""Rebuildable query projections over sealed manifests and Parquet evidence.

The projection is disposable derived state: deleting it must not destroy scientific
meaning, and rebuilding it from sealed evidence must recover all of it (ADR-010).
Boundary only in DB-1.1."""
