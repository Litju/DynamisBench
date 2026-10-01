"""Manifests, hashing, sealed run bundles, provenance, and evidence verification.

A run becomes authoritative only after outcome capture, schema validation, manifest
construction, complete SHA-256 verification, and atomic promotion; sealed bundles are
never overwritten (ADR-008). Scientific authority is Git, specs, Parquet, and SHA-256
rather than a mutable service database (ADR-004). Boundary only in DB-1.1."""
