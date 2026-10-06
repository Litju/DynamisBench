"""The application factory.

``create_app`` builds an ASGI application and returns it. It does not serve one.

That separation is the point: the desktop session owns the listening socket, the
ephemeral port and the session credential (Architecture §8/§13, ADR-017, RES-375), so
anything that started a server from here would either make importing the package a
side-effectful act or make the session's own security decisions inside a library call.
Construction therefore has exactly one output — an object — and no output at all on the
machine: no socket, no thread, no file, no directory.
"""

from __future__ import annotations

from fastapi import FastAPI

from dynamisbench import __version__
from dynamisbench.api.errors import install_error_contract
from dynamisbench.api.routing import APPLICATION_NAME, v1_router

API_DESCRIPTION = (
    "The local DynamisBench application boundary. It is not scientific authority: "
    "restarting it neither erases nor redefines any scientific state (ADR-016), and it "
    "never executes a simulation itself (ADR-017)."
)


def create_app() -> FastAPI:
    """Build the DynamisBench application.

    Deterministic and side-effect free. Two calls in one process produce two independent
    applications describing the same schema, and neither call reads the workspace, loads
    a simulator, touches the filesystem, or opens a socket.
    """
    app = FastAPI(
        title=f"{APPLICATION_NAME} API",
        description=API_DESCRIPTION,
        version=__version__,
    )
    app.include_router(v1_router)
    install_error_contract(app)
    return app


__all__ = ["create_app"]
