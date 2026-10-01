"""Local application HTTP boundary.

Exposes application commands, read models, and events over a versioned local HTTP API.
It is an application boundary, not scientific authority (ADR-016), it never becomes the
scientific API for the desktop IPC channel (ADR-015), and it never executes simulations
itself (ADR-017).

FastAPI and Uvicorn arrive with the issue that implements this boundary; DB-1.1
provides the package only."""
