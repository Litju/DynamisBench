"""Deterministic compilation of validated definitions into study plans and run specs.

Planning is a compiler, not a scheduler: it is side-effect-free except for optional
plan artifacts, and it fails before execution when capability requirements cannot be
satisfied. Boundary only in DB-1.1."""
