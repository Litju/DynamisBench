"""The desktop session's own security: one credential, one origin allow-list, one refusal.

Architecture §13 and RES-375 do not let the application boundary decide who may call it. The
desktop session owns three decisions — who holds the credential, which browser origins may
present it, and what a refusal looks like — and this module is where they are made, so that
``create_app`` stays exactly what DB-2.1 made it: an unserved application. Importing this
module starts nothing either; it defines a credential that has already been validated
somewhere else, a list of origins somebody chose, and a middleware that refuses.

Four properties are load-bearing, and each is enforced where it can be rather than described:

* **The credential is validated, never generated.** The desktop session generates 32
  cryptographically random bytes and encodes them as unpadded URL-safe base64 — 43 ASCII
  characters. A sidecar that generated its own would be issuing and protecting the same
  value, and the supervisor would have no credential to hold. So this module only accepts.
* **The credential is not retained.** :class:`SessionCredential` keeps a SHA-256 digest and
  nothing else, so the secret cannot leave it through ``repr``, ``str``, a traceback, a
  debugger's locals view or a pickled exception. Comparison is a single constant-time
  comparison of two fixed-length digests, which is also why the presented value is never
  compared for equality against anything first: an early ``len`` or ``==`` test would tell
  an attacker whether the guess was the right *shape* before the comparison that matters.
* **Refusal is one answer.** A missing header, a duplicated header, a wrong scheme, a
  malformed token and an incorrect token all reach the same comparison, the same 401 status,
  the same envelope body and the same ``WWW-Authenticate`` header. Anything that
  distinguished them would turn this endpoint into an oracle for guessing a credential.
* **The origin list is exact or it is refused.** ``*``, ``null``, wildcard patterns,
  reflected origins, empty lists, embedded credentials and origins carrying a path, query
  or fragment are all rejected before a socket is opened, because a permissive CORS policy
  would hand the credential to whatever origin asked. CORS therefore never decides who may
  call the API — the bearer header does; it only decides which browser origins are allowed
  to make the attempt.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from dynamisbench.api.app import create_app
from dynamisbench.api.errors import ErrorCode, envelope

SESSION_CREDENTIAL_VARIABLE = "DYNAMISBENCH_SESSION_TOKEN"
"""Where the desktop session puts the credential.

An environment variable rather than an argument because a process's arguments are world
readable on Windows, appear in process listings and tools, and are routinely captured by
crash reports. The credential is out-of-band, per process, and never persisted.
"""

ALLOWED_ORIGINS_VARIABLE = "DYNAMISBENCH_ALLOWED_ORIGINS"
"""Where the desktop session puts the exact browser origins.

Not a secret — an origin is not a credential — but it *is* runtime configuration, because
the same build is loaded from ``tauri://``-style production origins on one platform and from
an explicit development origin on another, and a compiled-in default would be a guess
encoded in a binary.
"""

CREDENTIAL_BYTES = 32
"""The entropy of the session credential: 32 cryptographically random bytes."""

CREDENTIAL_LENGTH = 43
"""The encoded length of :data:`CREDENTIAL_BYTES` as unpadded URL-safe base64.

``ceil(32 / 3) * 4`` is 44; base64 pads to a multiple of four, and the trailing ``=`` is
dropped. 43 is therefore the only correct length, and any other length is a value the
desktop session did not produce.
"""

URL_SAFE_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_")
"""RFC 4648 §5. ``+`` and ``/`` are excluded because a credential travels in a header."""

UNAUTHORIZED_MESSAGE = "Authentication required."
"""The only text a refusal ever carries.

Fixed for the same reason :data:`dynamisbench.api.errors.SERVER_ERROR_MESSAGE` is fixed: a
message that varied with the reason would report the reason, and the reason is exactly what
must not be reported.
"""

NETWORK_ORIGIN_SCHEMES = ("http", "https")
"""The schemes a browser origin read over the network may use."""

TAURI_CUSTOM_PROTOCOL_ORIGIN = "tauri://localhost"
"""The one non-network origin the desktop WebView may occupy.

Tauri serves the bundled frontend over its own custom protocol on macOS and Linux, where the
WebView's origin is exactly ``tauri://localhost`` — Windows is the platform that uses
``http://tauri.localhost`` instead (RES-376). The scheme is non-network and only the Tauri
runtime serves it, so it is the exact Linux/macOS analogue of the trusted Windows origin and
is admitted by exact match alone: no other host under ``tauri:``, and no other custom scheme,
is this origin.
"""

CORS_METHODS = ("GET", "POST", "OPTIONS")
"""The methods the workbench's HTTP surface uses or needs.

Explicit rather than wildcarded. ``GET`` reads the read models, ``POST`` carries the
commands ADR-019 describes, and ``OPTIONS`` is what a browser's own preflight uses. A
wildcard would advertise capabilities the API has not decided to offer.
"""

CORS_HEADERS = ("Authorization", "Content-Type")
"""The request headers a browser origin may send.

Named in full because ``Authorization`` is the credential's header and ``Content-Type`` is
what a JSON command body carries. A wildcard would let any page ask for any header.
"""


class SessionConfigurationError(Exception):
    """The runtime configuration cannot produce a session, so no socket was opened.

    Raised before anything binds, which is why it can be a plain exception rather than a
    process outcome: nothing has been started and there is nothing to shut down.
    """


@dataclass(frozen=True)
class SessionCredential:
    """A validated session credential, held as a digest so it cannot be printed.

    ``secrets`` is not a field: there is no code path that can read the credential back out
    of one of these, and that is the property that lets the whole object appear in a log
    line, a traceback or a debugger without disclosing anything.
    """

    digest: bytes

    def admits(self, presented: str) -> bool:
        """Whether ``presented`` is this session's credential, in constant time.

        The presented value is hashed first so the comparison is between two 32-byte
        digests whatever the guess is. Comparing the strings directly would return early on
        the first differing byte *and* on a length mismatch, which is two oracles the
        desktop session would rather not publish.
        """
        return hmac.compare_digest(
            hashlib.sha256(presented.encode("utf-8")).digest(),
            self.digest,
        )


def parse_session_credential(value: str | None) -> SessionCredential:
    """Validate the credential representation the desktop session produced.

    Checks the shape and nothing else — there is no way to check that 43 characters are
    *random*, only that they are the encoding of 32 bytes. A value that fails any check is
    reported by naming the variable and the reason, never the value: a configuration error
    that echoed the rejected string would put the credential in the supervisor's log, which
    is one of the few places it was promised never to appear.
    """
    if value is None or not value:
        raise SessionConfigurationError(f"{SESSION_CREDENTIAL_VARIABLE} is not set.")

    if len(value) != CREDENTIAL_LENGTH or not value.isascii():
        raise SessionConfigurationError(
            f"{SESSION_CREDENTIAL_VARIABLE} must be exactly {CREDENTIAL_LENGTH} ASCII characters."
        )

    if not set(value) <= URL_SAFE_ALPHABET:
        raise SessionConfigurationError(
            f"{SESSION_CREDENTIAL_VARIABLE} must be unpadded URL-safe base64."
        )

    try:
        decoded = base64.b64decode(f"{value}=", altchars=b"-_", validate=True)
    except binascii.Error:
        decoded = b""

    if len(decoded) != CREDENTIAL_BYTES:
        raise SessionConfigurationError(
            f"{SESSION_CREDENTIAL_VARIABLE} must encode {CREDENTIAL_BYTES} random bytes."
        )

    return SessionCredential(digest=hashlib.sha256(value.encode("ascii")).digest())


def parse_allowed_origins(value: str | None) -> tuple[str, ...]:
    """Validate the exact origin allow-list the desktop session configured.

    A JSON array of origins, because that is unambiguous about being a list: a
    comma-separated string has to guess about origins that contain commas, and a
    space-separated one about spaces. Everything that would make the grant wider than the
    list is refused, because the failure this prevents is silent — a permissive allow-list
    serves correct responses to pages that were never meant to reach the desktop session.
    """
    if value is None or not value.strip():
        raise SessionConfigurationError(f"{ALLOWED_ORIGINS_VARIABLE} is not set.")

    try:
        parsed = json.loads(value)
    except ValueError:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} must be a JSON array of origins."
        ) from None

    if not isinstance(parsed, list) or not parsed:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} must be a non-empty JSON array of origins."
        )

    origins: list[str] = []
    for entry in parsed:
        origins.append(_exact_origin(entry))

    if len(set(origins)) != len(origins):
        raise SessionConfigurationError(f"{ALLOWED_ORIGINS_VARIABLE} repeats an origin.")

    return tuple(origins)


def _exact_origin(entry: object) -> str:
    """One origin, or a refusal that names which rule it broke."""
    if not isinstance(entry, str):
        raise SessionConfigurationError(f"{ALLOWED_ORIGINS_VARIABLE} entries must be strings.")

    if not entry or "*" in entry or entry.lower() == "null":
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} rejects wildcard, null and empty origins."
        )

    try:
        parts = urlsplit(entry)
    except ValueError:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} contains an origin that is not a URL."
        ) from None

    if parts.scheme == "tauri":
        if parts.netloc != "localhost":
            raise SessionConfigurationError(
                f"{ALLOWED_ORIGINS_VARIABLE} tauri origins must be exactly "
                f"{TAURI_CUSTOM_PROTOCOL_ORIGIN}."
            )
    elif parts.scheme not in NETWORK_ORIGIN_SCHEMES:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} origins must be http, https or "
            f"{TAURI_CUSTOM_PROTOCOL_ORIGIN}."
        )

    if not parts.netloc or parts.username is not None or parts.password is not None:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} origins must be a bare host, with no credentials."
        )

    if parts.path or parts.query or parts.fragment:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} origins carry no path, query or fragment."
        )

    canonical = f"{parts.scheme}://{parts.netloc}"
    if entry != canonical:
        raise SessionConfigurationError(
            f"{ALLOWED_ORIGINS_VARIABLE} origins must be written exactly as {canonical}."
        )

    return entry


def presented_credential(headers: Sequence[tuple[bytes, bytes]]) -> str:
    """The bearer value on a request, or the empty string when there is not one.

    Every failure of the *shape* of the header — absent, duplicated, no ``Bearer`` scheme,
    empty — returns the same empty string, so that the credential comparison is the only
    thing that ever rejects a request.

    **Exactly one** ``Authorization`` header counts as presenting a proof, and that is a count
    rather than a lookup. ASGI hands a middleware every header entry as it arrived, so a
    request may carry two of them; reading the first would make admission depend on their
    order — correct-then-anything admitted, anything-then-correct refused — and "which of these
    was meant" is not a question a server may answer by guessing. A duplicated header is
    malformed, so it presents nothing, and it presents nothing by the same route as every
    other malformed header rather than by a branch of its own.
    """
    authorization = [value for name, value in headers if name.lower() == b"authorization"]
    if len(authorization) != 1:
        return ""

    scheme, _, credential = authorization[0].partition(b" ")
    if scheme.lower() != b"bearer":
        return ""
    return credential.decode("utf-8", "replace")


class SessionAuthentication:
    """Refuse every HTTP request that does not present this session's credential.

    Pure ASGI rather than ``BaseHTTPMiddleware`` because it has to run *inside* the CORS
    middleware, ahead of the whole router, and because a middleware that never reads or
    rewrites the body cannot fail to read one. It answers nothing but a 401 and delegates
    everything else unchanged, which is what keeps ``/api/v1/health``, ``/openapi.json`` and
    the documentation routes from being reachable without a credential.
    """

    def __init__(self, application: ASGIApp, credential: SessionCredential) -> None:
        self.application = application
        self.credential = credential

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self.credential.admits(
            presented_credential(scope.get("headers") or ())
        ):
            response = envelope(ErrorCode.UNAUTHORIZED, UNAUTHORIZED_MESSAGE, 401)
            response.headers["WWW-Authenticate"] = "Bearer"
            await response(scope, receive, send)
            return
        await self.application(scope, receive, send)


def secured_application(credential: SessionCredential, origins: tuple[str, ...]) -> FastAPI:
    """The application the session serves: ``create_app()`` plus the session's own policy.

    ``create_app()`` is called and returned, unchanged and unserved — DB-2.1's factory is
    still the whole application, and this adds no route, no schema change and no second
    namespace.

    Order is the whole design. The two middlewares are registered authentication first and
    CORS second, which makes CORS the outer one: a *preflight* is answered by CORS itself and
    never reaches the authentication layer, which is what lets a permitted browser origin
    discover that it must send a credential. The actual request it then sends passes
    through CORS into authentication and must carry the bearer header, so allowing an origin
    and allowing it to read a response remain two separate decisions.

    ``allow_credentials=False`` because there is no cookie to allow: the bearer header is
    the whole session proof, and a cookie would be a second one that a browser sends without
    the page asking.
    """
    application = create_app()
    application.add_middleware(SessionAuthentication, credential=credential)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=list(CORS_METHODS),
        allow_headers=list(CORS_HEADERS),
        allow_credentials=False,
    )
    return application


@dataclass(frozen=True)
class RuntimeConfiguration:
    """Everything the session decided before the server was built."""

    credential: SessionCredential
    origins: tuple[str, ...]


def runtime_configuration(environment: Mapping[str, str]) -> RuntimeConfiguration:
    """Read the session's configuration out of the process environment.

    Two variables, both read here and nowhere else, and the credential first so that a
    process with neither set reports the credential — the one whose absence is a missing
    supervisor, not a missing configuration.
    """
    return RuntimeConfiguration(
        credential=parse_session_credential(environment.get(SESSION_CREDENTIAL_VARIABLE)),
        origins=parse_allowed_origins(environment.get(ALLOWED_ORIGINS_VARIABLE)),
    )


__all__ = [
    "ALLOWED_ORIGINS_VARIABLE",
    "CORS_HEADERS",
    "CORS_METHODS",
    "NETWORK_ORIGIN_SCHEMES",
    "SESSION_CREDENTIAL_VARIABLE",
    "TAURI_CUSTOM_PROTOCOL_ORIGIN",
    "UNAUTHORIZED_MESSAGE",
    "RuntimeConfiguration",
    "SessionAuthentication",
    "SessionConfigurationError",
    "SessionCredential",
    "parse_allowed_origins",
    "parse_session_credential",
    "presented_credential",
    "runtime_configuration",
    "secured_application",
]
