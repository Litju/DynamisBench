"""Run preflight, isolated worker supervision, and run finalization.

Owns worker spawning, bounded concurrency, cancellation, timeout and failure
handling, staging, outcome capture, and finalization. Native simulations execute
only in worker subprocesses, never in the API process (ADR-017), and scientific
execution environments stay separate from the application runtime (ADR-018).
Boundary only in DB-1.1."""
