"""Fixed module entry point for the isolated MuJoCo reference worker."""

from __future__ import annotations

from dynamisbench.adapters.mujoco.worker import main

if __name__ == "__main__":
    raise SystemExit(main())
