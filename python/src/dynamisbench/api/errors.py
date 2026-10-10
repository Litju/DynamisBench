"""One stable JSON envelope for every application/API failure.

Every client of this API — today's local workbench, tomorrow's remote browser — has to be
able to tell "the request was refused" from "the response is malformed" from "the
application broke" without parsing prose and without knowing which handler produced the
answer. One envelope does that: a single ``error`` object carrying a closed-vocabulary
``code`` for the machine and a short ``message`` for whoever reads the log.

It is deliberately small. No request id, no timestamp, no nested detail tree, no stack
trace, no filesystem path, no echoed input. A local API on 127.0.0.1 is still an API a
future remote deployment will reuse (ADR-022), and every one of those fields is something
that would have to be redacted, bounded or trusted before this envelope could be served
off-machine.

What the envelope withholds is the load-bearing decision here. A 5xx reports a fixed
message and nothing else, so an exception's text — which may quote a filesystem path, a
query fragment, an environment variable or a credential — cannot reach a response by
being passed through. Pydantic's validation detail is withheld for the same reason: it
names each offending field and echoes the value it rejected, which on a machine holding a
local repository is workspace and configuration detail the client did not ask for. A
client error reports the detail the application itself wrote, which is the one string the
API is genuinely entitled to explain.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from dynamisbench.api.models import ApiModel

SERVER_ERROR_MESSAGE = "The application could not complete the request."
"""The only text a 5xx ever reports.

Not a default an exception could overwrite, and not a template: a fixed string is the
only way to guarantee that a traceback cannot leak through the message field.
"""

INVALID_REQUEST_MESSAGE = "The request could not be understood."
"""The only text a request-validation failure ever reports."""


class ErrorCode(StrEnum):
    """The closed vocabulary of application/API failures.

    Closed on purpose. A client branches on these values, so the set grows only by a
    decision recorded here, and every member describes what happened to the request
    rather than anything scientific.
    """

    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INVALID_REQUEST = "invalid_request"
    HTTP_ERROR = "http_error"
    UNAUTHORIZED = "unauthorized"
    INTERNAL_ERROR = "internal_error"


_STATUS_CODES: dict[int, ErrorCode] = {
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    422: ErrorCode.INVALID_REQUEST,
}
"""The statuses this application can raise with a meaning worth naming.

Small on purpose. A status with no entry still produces a valid envelope; it is simply
described as a generic HTTP failure rather than given a second name to keep in step.
"""


class ErrorDetail(ApiModel):
    """The machine-readable code, and a message safe to show."""

    code: ErrorCode
    message: str


class ErrorResponse(ApiModel):
    """The body of every failed application/API response.

    A single top-level key, so a client reads ``body["error"]["code"]`` and never has to
    ask where in the payload the failure went.
    """

    error: ErrorDetail


ROUTE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    405: {"model": ErrorResponse, "description": "The route exists, but not for this method."},
    500: {"model": ErrorResponse, "description": "The application could not complete the request."},
}
"""Declared on every route, so a generated client learns the envelope shape from OpenAPI.

Only the two failures a client can provoke or observe on an existing route. A 404 belongs
to the path that did not match, not to the routes that were. A route with a failure of its
own — the workspace routes' ``404`` for an unknown identifier, ``400`` for a root that will
not open — declares it *in addition* to these, through :data:`ROUTE_REFUSAL_RESPONSES`: it is
a spread, not a replacement, and a route that shadowed these would publish a document whose
typings disagree about how the application answers a wrong verb.
"""


def refusal_responses(
    declarations: Mapping[int | str, dict[str, Any]],
) -> dict[int | str, dict[str, Any]]:
    """The shared envelope declarations plus a route's own failures, as one mapping.

    A mapping rather than keyword arguments, because a refusal's status is an integer and
    ``404=...`` is not a valid keyword — and rather than a replacement, because every failure
    a route documents is typed as :class:`ErrorResponse`: a client cannot be expected to learn
    a second body shape from a prose description. Merging rather than dict-literal allows the
    ``**responses`` spread a route would otherwise hand-write.
    """
    return {**ROUTE_ERROR_RESPONSES, **dict(declarations)}


def envelope(code: ErrorCode, message: str, status_code: int) -> JSONResponse:
    """Build the one response body this application ever returns for a failure."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def classify(exc: Exception) -> tuple[ErrorCode, str, int]:
    """Decide what a failure is called, what it may say, and with which status.

    One function rather than one per failure shape, because the three cases differ only
    in what they are permitted to disclose. An HTTP failure below 500 carries the detail
    the application wrote; anything at or above 500, and anything unrecognised, carries
    the fixed message; a request that could not be parsed carries its own fixed message
    and never the rejected input.
    """
    if isinstance(exc, HTTPException):
        if exc.status_code >= 500:
            return ErrorCode.INTERNAL_ERROR, SERVER_ERROR_MESSAGE, exc.status_code
        code = _STATUS_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)
        return code, str(exc.detail), exc.status_code
    if isinstance(exc, RequestValidationError):
        return ErrorCode.INVALID_REQUEST, INVALID_REQUEST_MESSAGE, 422
    return ErrorCode.INTERNAL_ERROR, SERVER_ERROR_MESSAGE, 500


async def error_envelope(_request: Request, exc: Exception) -> JSONResponse:
    """Answer any registered failure in the declared envelope.

    Declared for the broad ``Exception`` the framework's callback shape requires, and
    ``async`` so the framework runs it on the event loop instead of in a worker thread.
    The raised exception is never read, formatted, interpolated or logged here: doing
    any of those in the response path is how a path or a secret reaches a client, and the
    operator's copy of the failure is the server log rather than the response body.
    """
    return envelope(*classify(exc))


def install_error_contract(app: FastAPI) -> None:
    """Install the envelope as the application's only failure representation.

    Three registrations and one handler. Starlette resolves a raised exception by walking
    its base classes, so registering the same handler for a failure and for ``Exception``
    is what puts each one in the layer that can answer it — and registering only
    ``Exception`` would route a 404 through the 500 handler and re-raise it.

    ``HTTPException`` is imported from ``starlette``, not from ``fastapi``, and that is
    not a style choice. ``fastapi.HTTPException`` is a *subclass* of the class the
    framework actually raises for an unmatched path or a wrong method, so registering the
    subclass would leave every 404 and 405 answering with Starlette's default
    ``{"detail": ...}`` while looking correctly installed.

    There is no shared base class, no registry, no per-code exception hierarchy and no
    global mutable state: the boundary has three failure shapes, each answered in three
    lines, and a fourth would be an exception framework.
    """
    app.add_exception_handler(HTTPException, error_envelope)
    app.add_exception_handler(RequestValidationError, error_envelope)
    app.add_exception_handler(Exception, error_envelope)


__all__ = [
    "INVALID_REQUEST_MESSAGE",
    "ROUTE_ERROR_RESPONSES",
    "SERVER_ERROR_MESSAGE",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "classify",
    "envelope",
    "error_envelope",
    "install_error_contract",
    "refusal_responses",
]
