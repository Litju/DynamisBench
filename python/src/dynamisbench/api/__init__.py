"""Local application HTTP boundary.

Exposes application commands, read models, and events over a versioned local HTTP API. It
is an application boundary, not scientific authority (ADR-016), it never becomes the
scientific API for the desktop IPC channel (ADR-015), and it never executes simulations
itself (ADR-017).

Importing this package starts nothing. It defines a versioned namespace, typed read
models, one failure envelope, and a factory that builds an ASGI application; the desktop
session, not the library, decides whether and where to serve it (RES-375).
"""

from __future__ import annotations

from dynamisbench.api.app import create_app
from dynamisbench.api.errors import (
    INVALID_REQUEST_MESSAGE,
    SERVER_ERROR_MESSAGE,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    install_error_contract,
)
from dynamisbench.api.models import (
    ApiModel,
    ApplicationInfoResponse,
    HealthResponse,
    HealthStatus,
)
from dynamisbench.api.routing import (
    API_V1_PREFIX,
    API_VERSION,
    APPLICATION_NAME,
    read_health,
    read_info,
    v1_router,
)

__all__ = [
    "API_VERSION",
    "API_V1_PREFIX",
    "APPLICATION_NAME",
    "INVALID_REQUEST_MESSAGE",
    "SERVER_ERROR_MESSAGE",
    "ApiModel",
    "ApplicationInfoResponse",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "HealthStatus",
    "create_app",
    "install_error_contract",
    "read_health",
    "read_info",
    "v1_router",
]
