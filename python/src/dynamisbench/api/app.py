"""The application factory.

``create_app`` builds an ASGI application and returns it. It does not serve one.

That separation is the point: the desktop session owns the listening socket, the
ephemeral port and the session credential (Architecture §8/§13, ADR-017, RES-375), so
anything that started a server from here would either make importing the package a
side-effectful act or make the session's own security decisions inside a library call.
Construction therefore has exactly one output — an object — and no output at all on the
machine: no socket, no thread, no file, no directory.

**One empty registry, per application.** The workspace routes need somewhere to remember
which workspaces the application has opened, and the factory is where that memory is made.
It is created *empty*, and it is created in memory: constructing an application performs no
filesystem access, so an application built and never asked about a workspace has touched
nothing. A second application instance builds a second registry, which is what makes the
restart guarantee structural rather than documented — an identifier held by the first means
nothing to the second, because the second has never heard of it.
"""

from __future__ import annotations

from fastapi import FastAPI

from dynamisbench import __version__
from dynamisbench.api.errors import install_error_contract
from dynamisbench.api.routing import (
    API_V1_PREFIX,
    APPLICATION_NAME,
    v1_router,
)
from dynamisbench.api.workspace_registry import WorkspaceRegistry
from dynamisbench.api.workspaces import workspace_router

API_DESCRIPTION = (
    "The local DynamisBench application boundary. It is not scientific authority: "
    "restarting it neither erases nor redefines any scientific state (ADR-016), and it "
    "never executes a simulation itself (ADR-017)."
)

WORKSPACE_REGISTRY_ATTRIBUTE = "workspace_registry"
"""Where the application's registry of open workspaces is kept.

A named attribute on ``app.state`` rather than a module-level variable, because two
applications built in one process must not share one registry: a global would make the
second application accept the first application's identifiers, and every restart gate in the
qualification suite would be measuring nothing.
"""


def create_app() -> FastAPI:
    """Build the DynamisBench application.

    Deterministic and side-effect free. Two calls in one process produce two independent
    applications describing the same schema, with their own empty registries, and neither
    call reads the workspace, loads a simulator, touches the filesystem, or opens a socket.
    """
    app = FastAPI(
        title=f"{APPLICATION_NAME} API",
        description=API_DESCRIPTION,
        version=__version__,
    )
    app.include_router(v1_router)
    app.include_router(workspace_router, prefix=API_V1_PREFIX)
    # In-memory and empty. Creating a registry is object construction, so the factory's
    # own contract — one object out, nothing touched on the way — is unchanged by it.
    setattr(app.state, WORKSPACE_REGISTRY_ATTRIBUTE, WorkspaceRegistry())
    install_error_contract(app)
    return app


__all__ = ["WORKSPACE_REGISTRY_ATTRIBUTE", "create_app"]
