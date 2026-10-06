"""The session's own security: one credential, one origin list, one refusal.

RES-375 (Architecture §13) puts the desktop session in charge of who may call the local API.
These gates cover the three decisions that follow from that, and each of them is checked
behaviourally — through the composed application or through the parser that produces it —
because the failure mode of all three is silence: a permissive allow-list, a comparison
that returns early, or a refusal that varies with its reason all keep serving correct
responses while giving up the property they exist to hold.

What is covered:

* **The credential representation.** 32 random bytes as unpadded URL-safe base64, 43 ASCII
  characters, is accepted; every other length, alphabet, encoding and padding is refused; and
  a refusal names the variable it is about and never the value it rejected.
* **The credential cannot be printed.** A refused value does not reach the message, and an
  admitted one does not survive in its own ``repr``.
* **Refusal is one answer.** Absent header, duplicated header, wrong scheme, empty bearer and
  wrong bearer produce the same status, the same body and the same ``WWW-Authenticate``
  header, so the endpoint cannot be used to test a guess. The duplicate case is exercised at
  the ASGI boundary rather than through a client, because a client would join the two headers
  into one value before the middleware ever saw them — which is the defect, not the absence
  of it, that has to be caught.
* **Comparison is constant time.** Every request, right or wrong, and however many
  ``Authorization`` headers it carries, goes through one ``hmac.compare_digest`` over two
  fixed-length digests.
* **Every route is authenticated.** The versioned routes, the OpenAPI document and the
  documentation routes all answer 401 without a credential, which is the property that stops
  a discovered localhost port from being readable by whatever found it.
* **CORS is exact, and it is not authentication.** A permitted origin's preflight succeeds
  without a credential — the one HTTP exception Architecture §13 allows — while the request
  that follows still needs the bearer header. A refused origin gets no grant at all.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dynamisbench.api.errors import ErrorCode
from dynamisbench.api.session import (
    CORS_HEADERS,
    CORS_METHODS,
    SESSION_CREDENTIAL_VARIABLE,
    UNAUTHORIZED_MESSAGE,
    SessionConfigurationError,
    parse_allowed_origins,
    parse_session_credential,
    presented_credential,
    secured_application,
)
from tests.api.factories import (
    ALLOWED_ORIGINS,
    CREDENTIAL,
    OTHER_ALLOWED_ORIGINS,
    session_configuration,
    session_environment,
)

UNAUTHORIZED_BODY = {"error": {"code": "unauthorized", "message": "Authentication required."}}
ALLOWED_ORIGIN = ALLOWED_ORIGINS[0]


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client on the application the session actually serves.

    The session configuration is threaded through rather than built inside a fixture, so a
    test that needs a different credential or a different origin list builds its own client
    rather than mutating this one.
    """
    configuration = session_configuration()
    with TestClient(secured_application(configuration.credential, configuration.origins)) as opened:
        yield opened


def _valid(length: int) -> str:
    """A correctly encoded credential of an incorrect length."""
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")[:length]
    return raw + "A" * (length - len(raw))


def _secured() -> ASGIApp:
    """The application the session serves, without a client wrapped around it."""
    configuration = session_configuration()
    return secured_application(configuration.credential, configuration.origins)


def _asgi_request(
    application: ASGIApp,
    headers: list[tuple[bytes, bytes]],
    path: str = "/api/v1/health",
) -> tuple[int, dict[bytes, bytes], bytes]:
    """One HTTP request driven straight into the application, with the headers as given.

    ``TestClient`` accepts a mapping of headers, and the client it is built on joins repeated
    names into a single comma-separated value before the request is spoken — so a request
    carrying two ``Authorization`` headers cannot be expressed through it at all. The scope is
    therefore assembled here, in the shape a server hands a middleware, and the application is
    called the way a server calls it. A higher-level client normalising duplicates away is
    precisely the failure these gates exist to catch, so nothing above the ASGI interface is
    allowed to sit between the headers and the refusal.
    """
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.5"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 51234),
        "server": ("127.0.0.1", 51273),
    }
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    async def call() -> None:
        await application(scope, receive, send)

    asyncio.run(call())

    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    return start["status"], dict(start["headers"]), body


def _recording_scope(application: ASGIApp) -> tuple[ASGIApp, list[Scope]]:
    """The application with the scope it was entered with kept alongside it."""

    observed: list[Scope] = []

    async def record(scope: Scope, receive: Receive, send: Send) -> None:
        observed.append(scope)
        await application(scope, receive, send)

    return record, observed


def _authorization(credential: str) -> tuple[bytes, bytes]:
    return (b"authorization", f"Bearer {credential}".encode())


INCORRECT_CREDENTIAL = _valid(43)
"""A correctly shaped credential that this session never issued."""

CORRECT_HEADER = _authorization(CREDENTIAL)
INCORRECT_HEADER = _authorization(INCORRECT_CREDENTIAL)


def test_a_valid_credential_is_accepted() -> None:
    """The exact representation the desktop session produces, and nothing stricter."""
    credential = parse_session_credential(CREDENTIAL)

    assert credential.admits(CREDENTIAL)
    assert CREDENTIAL not in repr(credential), "the credential must not survive in its repr"


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_credential_is_refused(value: str | None) -> None:
    with pytest.raises(SessionConfigurationError, match=SESSION_CREDENTIAL_VARIABLE):
        parse_session_credential(value)


@pytest.mark.parametrize("length", [1, 42, 44, 64])
def test_a_credential_of_the_wrong_length_is_refused(length: int) -> None:
    """43 is the only length 32 bytes can produce, so any other one is not our credential."""
    with pytest.raises(SessionConfigurationError, match="43"):
        parse_session_credential(_valid(length))


@pytest.mark.parametrize(
    "value",
    [
        _valid(43) + "=",
        "+" + _valid(42),
        "/" + _valid(42),
        "A" * 42 + "!",
        "héllo" + "A" * 38,
    ],
)
def test_a_malformed_credential_is_refused(value: str | None) -> None:
    """Padded, standard-alphabet, non-alphabet and non-ASCII values are all refused."""
    with pytest.raises(SessionConfigurationError):
        parse_session_credential(value)


def test_a_refusal_names_the_variable_and_never_the_value() -> None:
    """The rejected credential must not reach the message, which a supervisor will log."""
    rejected = "super-secret-not-even-valid" + "!"

    with pytest.raises(SessionConfigurationError) as refusal:
        parse_session_credential(rejected)

    assert SESSION_CREDENTIAL_VARIABLE in str(refusal.value)
    assert rejected not in str(refusal.value)
    assert "super-secret" not in repr(refusal.value)


def test_only_the_exact_credential_is_admitted() -> None:
    """Neighbouring values, not merely improbable ones: one character different, and one
    value of the right shape that was never issued."""
    credential = parse_session_credential(CREDENTIAL)
    flipped = ("A" if CREDENTIAL[0] != "A" else "B") + CREDENTIAL[1:]
    unissued = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    assert credential.admits(flipped) is False
    assert credential.admits(unissued) is False
    assert credential.admits("") is False


@pytest.mark.parametrize("origins", [ALLOWED_ORIGINS, OTHER_ALLOWED_ORIGINS])
def test_exact_origins_are_accepted(origins: tuple[str, ...]) -> None:
    assert parse_allowed_origins(json.dumps(list(origins))) == origins


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "is not set"),
        ("", "is not set"),
        ("   ", "is not set"),
        ("http://tauri.localhost", "JSON array"),
        ("[]", "non-empty"),
        ("{}", "non-empty"),
        ('"http://tauri.localhost"', "non-empty"),
        ("[null]", "strings"),
        ("[1]", "strings"),
        ('["*"]', "wildcard"),
        ('["null"]', "wildcard"),
        ('[""]', "wildcard"),
        ('["http://*.localhost"]', "wildcard"),
        ('["file:///tauri"]', "http or https"),
        ('["tauri://localhost"]', "http or https"),
        ('["http://user:pass@tauri.localhost"]', "no credentials"),
        ('["http://tauri.localhost/app"]', "no path"),
        ('["http://tauri.localhost/"]', "no path"),
        ('["http://tauri.localhost?x=1"]', "no path"),
        ('["http://tauri.localhost#f"]', "no path"),
        ('["HTTP://TAURI.LOCALHOST"]', "written exactly"),
        ('["http://tauri.localhost", "http://tauri.localhost"]', "repeats"),
        ('["http://[::1"]', "not a URL"),
    ],
)
def test_everything_other_than_an_exact_origin_is_refused(value: str | None, reason: str) -> None:
    """One gate over the whole permissive surface, because the failure is a wider allow-list.

    ``http://tauri.localhost/`` is in this list and is not a typo: it is the same origin with
    a path, and accepting it would teach the list that trailing slashes do not matter — which
    is the first step towards accepting something that does.
    """
    with pytest.raises(SessionConfigurationError, match=reason):
        parse_allowed_origins(value)


def test_a_no_such_host_is_not_a_configuration_error() -> None:
    """Names are not resolved and never looked up: an origin that no longer resolves is the
    supervisor's problem, and this process has no business reading DNS to find out."""
    assert parse_allowed_origins('["http://tauri.localhost.invalid"]') == (
        "http://tauri.localhost.invalid",
    )


@pytest.mark.parametrize(
    ("headers", "presented"),
    [
        ([], ""),
        ([(b"authorization", b"Bearer " + CREDENTIAL.encode())], CREDENTIAL),
        ([(b"Authorization", b"bearer " + CREDENTIAL.encode())], CREDENTIAL),
        ([(b"authorization", b"BEARER " + CREDENTIAL.encode())], CREDENTIAL),
        ([(b"authorization", b"Basic " + CREDENTIAL.encode())], ""),
        ([(b"authorization", CREDENTIAL.encode())], ""),
        ([(b"authorization", b"Bearer")], ""),
        ([(b"authorization", b"Bearer   ")], "  "),
        ([(b"cookie", b"session=abc")], ""),
    ],
)
def test_only_a_bearer_header_yields_a_credential(
    headers: list[tuple[bytes, bytes]], presented: str
) -> None:
    """Header shape is read here so that the comparison is the only thing that ever refuses.

    The scheme is case-insensitive per RFC 7235, and everything else — no header, no space,
    a different scheme, or a bearer value that is only whitespace — arrives at the
    comparison as a string that cannot be right, rather than as a branch that can be probed.
    """
    assert presented_credential(headers) == presented


@pytest.mark.parametrize(
    ("headers", "presented"),
    [
        ([], ""),
        ([CORRECT_HEADER], CREDENTIAL),
        ([(b"authorization", b"Basic " + CREDENTIAL.encode())], ""),
        ([(b"authorization", b"Bearer ")], ""),
        ([CORRECT_HEADER, INCORRECT_HEADER], ""),
        ([INCORRECT_HEADER, CORRECT_HEADER], ""),
        ([CORRECT_HEADER, CORRECT_HEADER], ""),
        ([CORRECT_HEADER, INCORRECT_HEADER, CORRECT_HEADER], ""),
        (
            [(b"Authorization", b"Bearer " + CREDENTIAL.encode()), CORRECT_HEADER],
            "",
        ),
        (
            [CORRECT_HEADER, (b"authorization", b"Bearer")],
            "",
        ),
    ],
)
def test_only_one_authorization_header_presents_a_proof(
    headers: list[tuple[bytes, bytes]], presented: str
) -> None:
    """The whole table, in one gate: what may present a credential, and what presents nothing.

    The duplicated rows are the point of this gate. ASGI preserves repeated header entries, so
    a request can carry two ``Authorization`` headers, and a parser that returned the first
    would admit a request because of where a header happened to sit in the list: correct first
    admitted, correct second refused. Admission that depends on header order is not a session
    proof. Duplicates therefore present nothing, in every order and any number, and they do it
    by returning the same empty string every other unusable header returns.
    """
    assert presented_credential(headers) == presented


@pytest.mark.parametrize(
    "headers",
    [
        [CORRECT_HEADER, INCORRECT_HEADER],
        [INCORRECT_HEADER, CORRECT_HEADER],
        [CORRECT_HEADER, CORRECT_HEADER],
    ],
)
def test_a_duplicated_authorization_header_is_refused_in_either_order(
    headers: list[tuple[bytes, bytes]],
) -> None:
    """The same 401 as every other refusal, including when the credential is present twice.

    Driven straight into the ASGI application, because a client that joined repeated headers
    would make all three rows indistinguishable from one header and this gate would pass for
    the wrong reason. Correct-then-wrong, wrong-then-correct and correct-twice all reach the
    refusal, and all three reach it indistinguishably.
    """
    status, headers_out, body = _asgi_request(_secured(), headers)

    assert status == 401
    assert headers_out[b"www-authenticate"] == b"Bearer"
    assert json.loads(body) == UNAUTHORIZED_BODY


def test_a_duplicated_header_reaches_the_middleware_as_two_entries() -> None:
    """The raw representation itself, asserted rather than assumed.

    The gates above are only meaningful if the two ``Authorization`` entries survive the trip
    into the middleware, so the scope the application was entered with is inspected: two
    entries, in the order given. If a layer above ever joined them, this fails and says so
    rather than leaving the refusal looking as though it had been earned.
    """
    application, observed = _recording_scope(_secured())

    status, _, body = _asgi_request(application, [CORRECT_HEADER, INCORRECT_HEADER])

    presented = [name for name, _ in observed[0]["headers"] if name.lower() == b"authorization"]
    assert presented == [b"authorization", b"authorization"]
    assert len(observed[0]["headers"]) == 2
    assert status == 401
    assert json.loads(body) == UNAUTHORIZED_BODY


def test_a_single_authorization_header_is_still_the_whole_proof() -> None:
    """The rule refuses duplicates, not repeats of the same proof.

    Stated so that a future reader cannot mistake "exactly one header" for "a header that may
    not be sent again", and so the composed application's one-header path is covered at this
    level too rather than only through the client.
    """
    status, _, body = _asgi_request(_secured(), [CORRECT_HEADER])

    assert status == 200
    assert json.loads(body)["api_version"] == "v1"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [CORRECT_HEADER, INCORRECT_HEADER],
        [INCORRECT_HEADER, CORRECT_HEADER],
        [CORRECT_HEADER, CORRECT_HEADER],
        [(b"authorization", b"Basic " + CREDENTIAL.encode())],
        [(b"authorization", b"Bearer ")],
        [INCORRECT_HEADER],
    ],
)
def test_every_unusable_header_reaches_exactly_one_comparison(
    headers: list[tuple[bytes, bytes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicated header is refused the way every other one is: by the comparison itself.

    Each shape is driven through the same instrumented comparison, and each must produce
    exactly one call between two fixed-length digests. A parser that refused duplicates on a
    branch of its own — by returning before the credential was ever consulted, or by
    comparing something whose length depends on the request — would show up here as a
    different count or a different width.
    """
    observed: list[tuple[bytes, bytes]] = []
    compare = hmac.compare_digest

    def recorded(left: bytes, right: bytes) -> bool:
        observed.append((left, right))
        return compare(left, right)

    monkeypatch.setattr(hmac, "compare_digest", recorded)

    _asgi_request(_secured(), headers)

    assert len(observed) == 1, "every request must reach exactly one comparison"
    left, right = observed[0]
    assert len(left) == len(right) == hashlib.sha256().digest_size
    assert right == hashlib.sha256(CREDENTIAL.encode()).digest()


@pytest.mark.parametrize(
    "path", ["/api/v1/health", "/api/v1/info", "/openapi.json", "/docs", "/redoc"]
)
def test_no_route_is_reachable_without_a_credential(client: TestClient, path: str) -> None:
    """Every route the sidecar serves, including the ones that describe the application."""
    response = client.get(path)

    assert response.status_code == 401, path
    assert response.json() == UNAUTHORIZED_BODY


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        f"Bearer {CREDENTIAL}x",
        f"bearer {CREDENTIAL[:-1]}A" if CREDENTIAL[-1] != "A" else f"bearer {CREDENTIAL[:-1]}B",
        f"Bearer {_valid(43)}",
        f"Basic {CREDENTIAL}",
        f"Bearer {_valid(42)}",
    ],
)
def test_every_refusal_is_the_same_refusal(client: TestClient, authorization: str | None) -> None:
    """Nothing about the attempt survives into the answer.

    Absent, wrongly shaped, malformed and incorrect all have to be indistinguishable, or the
    endpoint is an oracle: a caller that can tell "the header was malformed" from "the token
    was wrong" learns which guesses to keep making.
    """
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.get("/api/v1/health", headers=headers)

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY
    assert response.headers["www-authenticate"] == "Bearer"


def test_the_refusal_uses_the_applications_error_vocabulary(client: TestClient) -> None:
    """One envelope, including for authentication — a client branches on ``error.code``."""
    response = client.get("/api/v1/health")

    assert ErrorCode.UNAUTHORIZED == "unauthorized"
    assert response.json() == {
        "error": {"code": ErrorCode.UNAUTHORIZED.value, "message": UNAUTHORIZED_MESSAGE}
    }


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/info"])
def test_the_credential_admits_the_versioned_routes(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Authorization": f"Bearer {CREDENTIAL}"})

    assert response.status_code == 200, path
    assert response.json()["api_version"] == "v1"


def test_the_credential_admits_the_openapi_document(client: TestClient) -> None:
    """The document is part of the boundary, and it describes a secured boundary."""
    response = client.get("/openapi.json", headers={"Authorization": f"Bearer {CREDENTIAL}"})

    assert response.status_code == 200


def test_the_credential_comparison_is_constant_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One comparison, over two digests, whatever was presented.

    Measured rather than read: patching ``hmac.compare_digest`` records the call that actually
    happens for a correct and for an incorrect credential. A future change that short-circuits
    on length, on a prefix or on an equality test would stop calling it, and this fails.
    """
    observed: list[tuple[bytes, bytes]] = []
    compare = hmac.compare_digest

    def recorded(left: bytes, right: bytes) -> bool:
        observed.append((left, right))
        return compare(left, right)

    monkeypatch.setattr(hmac, "compare_digest", recorded)

    refused = client.get("/api/v1/health")
    admitted = client.get("/api/v1/health", headers={"Authorization": f"Bearer {CREDENTIAL}"})

    assert refused.status_code == 401
    assert admitted.status_code == 200
    assert len(observed) == 2, "every request must reach exactly one comparison"
    for left, right in observed:
        assert len(left) == len(right) == hashlib.sha256().digest_size
    assert {right for _, right in observed} == {hashlib.sha256(CREDENTIAL.encode()).digest()}, (
        "both comparisons must be against the session credential's digest"
    )


def _preflight(client: TestClient, origin: str) -> Any:
    return client.options(
        "/api/v1/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_a_permitted_origin_may_preflight_without_a_credential(client: TestClient) -> None:
    """The one HTTP exception Architecture §13 allows, and the reason it is allowed.

    A browser must be able to discover that a request needs an ``Authorization`` header before
    it can send one, so the preflight cannot require the thing it is announcing.
    """
    response = _preflight(client, ALLOWED_ORIGIN)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_the_preflight_grants_nothing_wildcard(client: TestClient) -> None:
    """Every grant is explicit, and no grant is a cookie: the bearer header is the session."""
    response = _preflight(client, ALLOWED_ORIGIN)

    assert response.headers["access-control-allow-methods"].split(", ") == list(CORS_METHODS)
    allowed_headers = {
        header.lower() for header in response.headers["access-control-allow-headers"].split(", ")
    }
    assert {header.lower() for header in CORS_HEADERS} <= allowed_headers
    assert "*" not in allowed_headers
    assert "access-control-allow-credentials" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "https://tauri.localhost",
        "http://tauri.localhost.evil.example",
        "http://tauri.localhost:5173",
        "null",
        "*",
    ],
)
def test_a_refused_origin_receives_no_grant(client: TestClient, origin: str) -> None:
    """Including near-misses: a different scheme, a different port, and a subdomain of the
    permitted host are all different origins, and CORS compares origins exactly."""
    response = _preflight(client, origin)

    assert "access-control-allow-origin" not in response.headers
    assert response.status_code != 200 or "access-control-allow-origin" not in response.headers


def test_a_permitted_origin_still_needs_the_credential(client: TestClient) -> None:
    """Allowing an origin and allowing it to read a response are two separate decisions."""
    response = client.get(
        "/api/v1/health",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED_BODY


def test_a_permitted_origin_is_answered_once_the_credential_is_sent(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health",
        headers={"Origin": ALLOWED_ORIGIN, "Authorization": f"Bearer {CREDENTIAL}"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_no_response_ever_grants_a_wildcard_origin(client: TestClient) -> None:
    """Checked over every route and both outcomes, because ``*`` in a CORS header hands the
    response to whatever asked, which is the exact failure the allow-list exists to prevent."""
    headers = {"Origin": "http://evil.example", "Authorization": f"Bearer {CREDENTIAL}"}
    for path in ("/api/v1/health", "/api/v1/info", "/openapi.json", "/docs", "/api/v1/missing"):
        response = client.get(path, headers=headers)
        assert response.headers.get("access-control-allow-origin") != "*", path


def test_the_environment_is_the_only_way_to_supply_the_session() -> None:
    """The two variables this sidecar reads, and no third, are the whole configuration.

    Stated as a closed set rather than "at least these two exist", so a future environment
    variable cannot become a silent third input to a security decision.
    """
    configuration = session_configuration()

    assert configuration.origins == ALLOWED_ORIGINS
    assert configuration.credential.admits(CREDENTIAL)
    assert set(session_environment()) == {
        SESSION_CREDENTIAL_VARIABLE,
        "DYNAMISBENCH_ALLOWED_ORIGINS",
    }


def test_the_generation_recipe_produces_an_admitted_credential() -> None:
    """The recipe the desktop session will follow, pinned on this side of the contract.

    RES-375 validates the credential and does not generate it; RES-376 will. This is the one
    place that says what "will" means: 32 random bytes, unpadded URL-safe base64, exactly 43
    characters. Both halves of the contract live in this file, so the two cannot drift apart
    without this failing.
    """
    generated = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    assert len(generated) == 43
    assert generated.isascii()
    assert parse_session_credential(generated).admits(generated)


def test_the_preferred_base64_alphabet_is_the_url_safe_one() -> None:
    """``+`` and ``/`` are standard base64 and not URL-safe base64, and a credential travels
    in an ``Authorization`` header; admitting them would mean admitting two spellings of one
    credential and comparing bytes rather than the characters that were sent."""
    assert set("+/") & set(CREDENTIAL) == set()
    with pytest.raises(SessionConfigurationError):
        parse_session_credential("+" + CREDENTIAL[1:])
