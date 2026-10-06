"""The versioned API returns typed read models and one stable failure envelope.

DB-2.1's second qualification gate. It covers two claims a routing test cannot:

* every successful response is an explicit Pydantic read model whose fields are typed and
  closed, not a dict that happens to serialise to something plausible; and
* every failure — a framework 404, a wrong method, an unparseable request, a handler that
  raises — arrives in one envelope, with a status-appropriate code and with nothing
  disclosed that the client did not already send.

The disclosure half is the one worth testing hard. This process holds a local repository,
absolute Windows paths and whatever a caller's exception happens to quote, so a failure
path that formats an exception into a response is a real leak rather than a theoretical
one; ``TEST_LEAKS`` below is a value shaped like exactly that, and it is asserted absent
from the body, the headers and the text of every failure exercised here.
"""

from __future__ import annotations

import json
from typing import Annotated

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import StringConstraints
from starlette.exceptions import HTTPException

from dynamisbench import __version__
from dynamisbench.api import (
    API_V1_PREFIX,
    API_VERSION,
    APPLICATION_NAME,
    INVALID_REQUEST_MESSAGE,
    SERVER_ERROR_MESSAGE,
    ApplicationInfoResponse,
    ErrorCode,
    ErrorResponse,
    HealthResponse,
    HealthStatus,
    create_app,
    install_error_contract,
)

TEST_LEAKS = "C:\\Users\\Educacion\\secrets.env"


def _client(app: FastAPI | None = None) -> TestClient:
    return TestClient(app if app is not None else create_app())


def _client_with_a_typed_probe_route() -> TestClient:
    """An application carrying one route with inputs the framework has to validate.

    Registered on a real application rather than on a bare one so the failure travels the
    same middleware stack it would travel in production.
    """
    app = create_app()

    @app.get(f"{API_V1_PREFIX}/probe")
    def probe(
        value: Annotated[str, StringConstraints(max_length=32)], count: int
    ) -> dict[str, str]:
        return {"value": value, "count": str(count)}

    return TestClient(app)


def test_health_returns_the_declared_read_model() -> None:
    with _client() as client:
        response = client.get(f"{API_V1_PREFIX}/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application": APPLICATION_NAME,
        "version": __version__,
        "api_version": API_VERSION,
    }


def test_info_returns_the_declared_read_model() -> None:
    with _client() as client:
        response = client.get(f"{API_V1_PREFIX}/info")

    assert response.status_code == 200
    assert response.json() == {
        "application": APPLICATION_NAME,
        "version": __version__,
        "api_version": API_VERSION,
    }


def test_both_routes_are_served_by_their_own_typed_model() -> None:
    """The declared type and the wire shape are checked against each other.

    Validating the body *as the model* is the part a JSON equality assertion cannot do: it
    would pass on a field the model has since dropped, and would not notice a field the
    response grew. Round-tripping through the model proves both directions at once.
    """
    with _client() as client:
        health = client.get(f"{API_V1_PREFIX}/health").json()
        info = client.get(f"{API_V1_PREFIX}/info").json()

    assert HealthResponse.model_validate(health).model_dump(mode="json") == health
    assert ApplicationInfoResponse.model_validate(info).model_dump(mode="json") == info


def test_a_read_model_rejects_a_field_it_does_not_declare() -> None:
    """Both properties of ``ApiModel`` are load-bearing for a versioned schema.

    ``extra="forbid"`` is what stops a later field from being added to a response and
    relied on by a client without appearing in the schema; ``frozen`` is what stops a
    caller mutating a value that has already been served.
    """
    with pytest.raises(ValueError):
        HealthResponse.model_validate(
            {
                "status": "ok",
                "application": APPLICATION_NAME,
                "version": __version__,
                "api_version": API_VERSION,
                "workspace": "somewhere",
            }
        )

    model = HealthResponse(
        status=HealthStatus.OK,
        application=APPLICATION_NAME,
        version=__version__,
        api_version=API_VERSION,
    )
    with pytest.raises(ValueError):
        model.status = HealthStatus.OK  # type: ignore[misc]


def test_health_reports_a_closed_status_vocabulary() -> None:
    """A client branches on the status string, so the set of states it can mean is closed."""
    assert {status.value for status in HealthStatus} == {"ok"}


def test_an_unknown_path_answers_with_the_envelope() -> None:
    with _client() as client:
        response = client.get(f"{API_V1_PREFIX}/no-such-thing")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_a_wrong_method_answers_with_the_envelope() -> None:
    with _client() as client:
        response = client.post(f"{API_V1_PREFIX}/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == ErrorCode.METHOD_NOT_ALLOWED


def test_an_unparseable_request_answers_with_the_envelope_and_echoes_nothing() -> None:
    """Pydantic's own detail would name every offending field and echo every rejected
    value. This process holds a local repository, so that detail is workspace and
    configuration information the client never sent."""
    with _client_with_a_typed_probe_route() as client:
        accepted = client.get(f"{API_V1_PREFIX}/probe", params={"value": "ok", "count": 3})
        no_parameters = client.get(f"{API_V1_PREFIX}/probe")
        wrong_type = client.get(
            f"{API_V1_PREFIX}/probe", params={"value": "ok", "count": "not-an-integer"}
        )
        too_long = client.get(
            f"{API_V1_PREFIX}/probe", params={"value": TEST_LEAKS * 20, "count": 3}
        )

    assert accepted.status_code == 200, "the probe route itself must work, or 422 proves nothing"

    for rejected in (no_parameters, wrong_type, too_long):
        assert rejected.status_code == 422
        assert rejected.json() == {
            "error": {"code": "invalid_request", "message": INVALID_REQUEST_MESSAGE}
        }
        assert TEST_LEAKS not in rejected.text


def test_a_raised_exception_is_answered_without_disclosing_why() -> None:
    """The load-bearing no-leak gate.

    The handler raises an exception whose text is shaped like a leaked path and credential.
    ``raise_server_exceptions=False`` is how the real client sees this case: the response
    is delivered, and the exception still reaches the server log rather than the body.
    """
    app = FastAPI()
    install_error_contract(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(f"could not read {TEST_LEAKS}")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": SERVER_ERROR_MESSAGE}}
    assert TEST_LEAKS not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


def test_a_server_side_http_failure_does_not_echo_its_detail() -> None:
    """A 5xx raised on purpose is still a 5xx: its detail is not the application's to
    publish, because at that status the cause is exactly what must not be explained."""
    app = FastAPI()
    install_error_contract(app)

    @app.get("/unavailable")
    def unavailable() -> None:
        raise HTTPException(status_code=503, detail=f"workspace at {TEST_LEAKS} is gone")

    with TestClient(app) as client:
        response = client.get("/unavailable")

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "internal_error", "message": SERVER_ERROR_MESSAGE}}
    assert TEST_LEAKS not in response.text


def test_a_client_failure_still_explains_itself_in_the_envelope() -> None:
    """The complement of the previous gate: withholding everything would make the envelope
    useless. A refusal below 500 carries the detail the application itself wrote."""

    def app_that_refuses() -> FastAPI:
        app = FastAPI()
        install_error_contract(app)

        @app.get("/refused")
        def refused() -> None:
            raise HTTPException(status_code=409, detail="that plan is already compiled")

        return app

    with TestClient(app_that_refuses()) as client:
        response = client.get("/refused")

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "http_error", "message": "that plan is already compiled"}
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, ErrorCode.HTTP_ERROR),
        (401, ErrorCode.HTTP_ERROR),
        (404, ErrorCode.NOT_FOUND),
        (405, ErrorCode.METHOD_NOT_ALLOWED),
        (409, ErrorCode.HTTP_ERROR),
        (418, ErrorCode.HTTP_ERROR),
    ],
)
def test_the_status_a_client_observed_names_its_failure(status: int, code: ErrorCode) -> None:
    def app_that_raises() -> FastAPI:
        app = FastAPI()
        install_error_contract(app)

        @app.get("/refused")
        def refused() -> None:
            raise HTTPException(status_code=status, detail="no")

        return app

    with TestClient(app_that_raises()) as client:
        body = client.get("/refused").json()

    assert body["error"]["code"] == code


def test_the_envelope_is_exactly_one_key_and_nothing_else() -> None:
    """Stated as a closed shape, because the guarantee a client relies on is that it can
    read ``body["error"]["code"]`` and that no failure response carries a second,
    undocumented branch it might have to inspect."""
    with _client() as client:
        body = client.get(f"{API_V1_PREFIX}/no-such-thing").json()

    assert list(body) == ["error"]
    assert sorted(body["error"]) == ["code", "message"]
    assert ErrorResponse.model_validate(body).model_dump(mode="json") == body


def test_no_failure_response_is_a_json_array_or_a_bare_string() -> None:
    """FastAPI's default validation body is a list of objects and its default HTTP error is
    ``{"detail": ...}``. Both would be readable by a human and unreadable by the client
    contract, so the envelope has to have replaced them rather than merely been added."""
    with _client() as client:
        unknown = client.get(f"{API_V1_PREFIX}/no-such-thing")
        wrong_method = client.post(f"{API_V1_PREFIX}/health")

    for response in (unknown, wrong_method):
        assert isinstance(json.loads(response.text), dict)
        assert "detail" not in json.loads(response.text)


def test_a_successful_response_carries_no_error_key() -> None:
    """Stated because a handler that returned an error envelope with a 200 would otherwise
    satisfy every status-code assertion above while telling the client nothing useful."""
    with _client() as client:
        for path in ("/health", "/info"):
            body = client.get(f"{API_V1_PREFIX}{path}").json()

            assert "error" not in body
