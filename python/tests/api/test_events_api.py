"""The event transport: one bounded stream, real operations, and no durable record.

The route is qualified through the application's real ASGI stack, and the broadcaster is
qualified directly where a test needs to control two subscribers, a worker thread, a slow
consumer or a closing loop. Nothing here waits on a wall-clock sleep: heartbeat timing uses a
small interval and a stream that is *expected* to be silent, and disconnect cleanup polls a
public count with a deadline rather than assuming a scheduler.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dynamisbench.api import API_V1_PREFIX, create_app
from dynamisbench.api.events import (
    EVENT_BROADCASTER_ATTRIBUTE,
    ApplicationEvent,
    EventBroadcaster,
    EventName,
    artifact_inspected_event,
    encode_event,
    stream_ready_event,
    workspace_discovered_event,
    workspace_opened_event,
)
from dynamisbench.api.session import secured_application
from dynamisbench.workspace import SourceCategory, initialize_workspace

from .factories import CREDENTIAL, OTHER_ALLOWED_ORIGINS, session_configuration

EVENTS = f"{API_V1_PREFIX}/events"
AUTHORIZATION = {"Authorization": f"Bearer {CREDENTIAL}"}


def _decode_frame(line: str) -> ApplicationEvent:
    assert line.startswith("data: "), line
    return ApplicationEvent.model_validate(json.loads(line[len("data: ") :]))


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before the deadline")


async def _drive_stream(
    application,
    *,
    headers: dict[str, str],
    frames: int = 1,
    on_first_frame=None,
) -> tuple[int, dict[str, str], str]:
    """Drive one real ASGI request and stop after ``frames`` SSE frames.

    ``TestClient`` buffers a response until its body completes, and a live event stream is
    deliberately open-ended, so the stream is exercised through the same ASGI application
    the server runs rather than through that in-process client. The driver cancels the
    application task once the frames it needs have arrived; the route's own ``finally`` then
    runs exactly as it would on a disconnect.
    """
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": EVENTS,
        "raw_path": EVENTS.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in headers.items()
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 50001),
        "extensions": {},
    }

    body = bytearray()
    status = {"code": 0}
    response_headers: dict[str, str] = {}
    first_frame = asyncio.Event()
    enough = asyncio.Event()
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if request_delivered:
            # The request body has been delivered; an open stream is never "disconnected"
            # until the driver cancels it.
            await asyncio.sleep(3600)
        request_delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = int(message["status"])
            response_headers.update(
                (key.decode("latin-1"), value.decode("latin-1"))
                for key, value in message.get("headers", [])
            )
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))
            if body.count(b"\n\n") >= 1:
                first_frame.set()
            if body.count(b"\n\n") >= frames:
                enough.set()

    task = asyncio.create_task(application(scope, receive, send))
    try:
        await asyncio.wait_for(first_frame.wait(), timeout=2)
        if on_first_frame is not None:
            on_first_frame()
        if frames > 1:
            await asyncio.wait_for(enough.wait(), timeout=2)
        return status["code"], response_headers, body.decode("utf-8")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# --------------------------------------------------------------------------- #
# The wire: ready frame, content type, heartbeat, disconnect
# --------------------------------------------------------------------------- #
def test_the_stream_starts_with_the_versioned_ready_event() -> None:
    app = create_app()

    status, headers, body = asyncio.run(_drive_stream(app, headers={}))

    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-store"
    event = _decode_frame(body.split("\n\n")[0])
    assert event.schema_version == 1
    assert event.event is EventName.STREAM_READY
    assert event.data["queue_capacity"] == 32


def test_a_quiet_stream_receives_comment_heartbeats() -> None:
    app = create_app()
    broadcaster = EventBroadcaster(heartbeat_seconds=0.01)
    setattr(app.state, EVENT_BROADCASTER_ATTRIBUTE, broadcaster)

    _status, _headers, body = asyncio.run(_drive_stream(app, headers={}, frames=2))

    frames = body.split("\n\n")
    assert _decode_frame(frames[0]).event is EventName.STREAM_READY
    assert frames[1] == ": heartbeat"


def test_a_live_stream_receives_a_published_operation_event() -> None:
    app = create_app()
    broadcaster = getattr(app.state, EVENT_BROADCASTER_ATTRIBUTE)

    def publish() -> None:
        broadcaster.publish(
            EventName.WORKSPACE_OPENED,
            {"workspace_id": "opaque-id", "categories_present": 3},
        )

    _status, _headers, body = asyncio.run(
        _drive_stream(app, headers={}, frames=2, on_first_frame=publish)
    )

    event = _decode_frame(body.split("\n\n")[1])
    assert event.event is EventName.WORKSPACE_OPENED
    assert event.data == {"workspace_id": "opaque-id", "categories_present": 3}


def test_closing_the_connection_unsubscribes_it() -> None:
    app = create_app()
    broadcaster = getattr(app.state, EVENT_BROADCASTER_ATTRIBUTE)

    asyncio.run(_drive_stream(app, headers={}))

    _wait_for(lambda: broadcaster.subscriber_count() == 0)


def test_the_application_lifespan_closes_live_subscriptions() -> None:
    app = create_app()
    broadcaster = getattr(app.state, EVENT_BROADCASTER_ATTRIBUTE)

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            subscription = broadcaster.subscribe()
            assert broadcaster.subscriber_count() == 1
        ended = await asyncio.wait_for(subscription.queue.get(), timeout=1)
        assert ended is None
        with pytest.raises(RuntimeError):
            broadcaster.subscribe()

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Authentication and CORS: the same middleware, no stream without a credential
# --------------------------------------------------------------------------- #
def test_the_secured_application_refuses_the_stream_without_a_credential() -> None:
    application = secured_application(session_configuration().credential, OTHER_ALLOWED_ORIGINS)
    with TestClient(application) as client:
        missing = client.get(EVENTS)
        wrong = client.get(EVENTS, headers={"Authorization": "Bearer not-the-credential"})

    for response in (missing, wrong):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "unauthorized"


def test_the_secured_application_streams_with_the_credential() -> None:
    application = secured_application(session_configuration().credential, OTHER_ALLOWED_ORIGINS)

    status, headers, body = asyncio.run(_drive_stream(application, headers=AUTHORIZATION))

    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert _decode_frame(body.split("\n\n")[0]).event is EventName.STREAM_READY


def test_the_stream_participates_in_the_exact_origin_cors_policy() -> None:
    application = secured_application(session_configuration().credential, OTHER_ALLOWED_ORIGINS)
    with TestClient(application) as client:
        preflight = client.options(
            EVENTS,
            headers={
                "Origin": OTHER_ALLOWED_ORIGINS[0],
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        refused_origin = client.options(
            EVENTS,
            headers={
                "Origin": "http://untrusted.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == OTHER_ALLOWED_ORIGINS[0]
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in refused_origin.headers


# --------------------------------------------------------------------------- #
# The broadcaster: subscribers, threads, backpressure, no replay
# --------------------------------------------------------------------------- #
def test_two_subscribers_each_receive_the_same_event() -> None:
    async def scenario() -> tuple[ApplicationEvent, ApplicationEvent]:
        broadcaster = EventBroadcaster()
        first = broadcaster.subscribe()
        second = broadcaster.subscribe()
        broadcaster.publish(EventName.WORKSPACE_DISCOVERED, {"artifact_count": 4})
        await asyncio.sleep(0)
        first_event = await asyncio.wait_for(first.queue.get(), timeout=1)
        second_event = await asyncio.wait_for(second.queue.get(), timeout=1)
        assert first_event is not None
        assert second_event is not None
        return first_event, second_event

    first, second = asyncio.run(scenario())
    assert (
        first
        == second
        == ApplicationEvent(event=EventName.WORKSPACE_DISCOVERED, data={"artifact_count": 4})
    )


def test_publishing_from_a_worker_thread_is_safe() -> None:
    async def scenario() -> ApplicationEvent:
        broadcaster = EventBroadcaster()
        subscription = broadcaster.subscribe()
        thread = threading.Thread(
            target=broadcaster.publish,
            args=(EventName.WORKSPACE_OPENED, {"workspace_id": "threaded"}),
        )
        thread.start()
        event = await asyncio.wait_for(subscription.queue.get(), timeout=2)
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert event is not None
        return event

    event = asyncio.run(scenario())
    assert event.data == {"workspace_id": "threaded"}


def test_a_slow_subscriber_is_disconnected_instead_of_buffering_without_bound() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster(queue_capacity=1)
        subscription = broadcaster.subscribe()

        broadcaster.publish(EventName.WORKSPACE_OPENED, {"workspace_id": "first"})
        await asyncio.sleep(0)
        assert broadcaster.subscriber_count() == 1

        # The first event is still queued (this subscriber has not read it), so the next
        # publish finds a full queue and exercises the slow-consumer decision.
        broadcaster.publish(EventName.WORKSPACE_OPENED, {"workspace_id": "second"})
        await asyncio.sleep(0)

        assert await asyncio.wait_for(subscription.queue.get(), timeout=1) is None
        broadcaster.unsubscribe(subscription.identifier)

    asyncio.run(scenario())


def test_a_new_subscription_receives_no_replayed_event() -> None:
    async def scenario() -> None:
        broadcaster = EventBroadcaster()
        first = broadcaster.subscribe()
        broadcaster.publish(EventName.ARTIFACT_INSPECTED, {"artifact_id": "one"})
        await asyncio.sleep(0)
        await asyncio.wait_for(first.queue.get(), timeout=1)
        broadcaster.unsubscribe(first.identifier)

        second = broadcaster.subscribe()
        await asyncio.sleep(0)
        assert second.queue.empty()

    asyncio.run(scenario())


def test_closing_the_broadcaster_ends_every_queue_and_refuses_new_ones() -> None:
    async def scenario() -> tuple[object, object]:
        broadcaster = EventBroadcaster()
        first = broadcaster.subscribe()
        second = broadcaster.subscribe()
        broadcaster.close()
        await asyncio.sleep(0)
        return (
            await asyncio.wait_for(first.queue.get(), timeout=1),
            await asyncio.wait_for(second.queue.get(), timeout=1),
        )

    assert asyncio.run(scenario()) == (None, None)


# --------------------------------------------------------------------------- #
# The envelope: closed, bounded, and free of operational state
# --------------------------------------------------------------------------- #
def test_the_envelope_rejects_unbounded_data() -> None:
    with pytest.raises(ValueError):
        ApplicationEvent(
            event=EventName.WORKSPACE_OPENED,
            data={f"key-{index}": index for index in range(9)},
        )
    with pytest.raises(ValueError):
        ApplicationEvent(event=EventName.WORKSPACE_OPENED, data={"workspace_id": "x" * 129})
    with pytest.raises(ValueError):
        ApplicationEvent(event=EventName.WORKSPACE_OPENED, data={"count": 2**53 + 1})


def test_the_published_events_carry_no_root_content_or_credential() -> None:
    opened = workspace_opened_event("opaque", 2, False)
    discovered = workspace_discovered_event("opaque", 3, 2, 1, 1, False)
    inspected = artifact_inspected_event(
        "opaque", "artifact", "benchmarks", "benchmark", "valid", 0
    )
    events = [
        stream_ready_event(15, 32),
        ApplicationEvent(event=opened[0], data=opened[1]),
        ApplicationEvent(event=discovered[0], data=discovered[1]),
        ApplicationEvent(event=inspected[0], data=inspected[1]),
    ]

    for event in events:
        encoded = encode_event(event)
        assert "this-root-must-never-appear" not in encoded
        assert CREDENTIAL not in encoded
        assert "Bearer" not in encoded
        assert "authoring content" not in encoded
        assert "\n\n" in encoded
        assert encoded.count("data:") == 1


def test_every_builder_uses_only_published_scalar_facts() -> None:
    assert workspace_opened_event("w", 3, True) == (
        EventName.WORKSPACE_OPENED,
        {"workspace_id": "w", "categories_present": 3, "evidence_inside_source": True},
    )
    assert workspace_discovered_event("w", 4, 3, 1, 2, True) == (
        EventName.WORKSPACE_DISCOVERED,
        {
            "workspace_id": "w",
            "artifact_count": 4,
            "valid_count": 3,
            "invalid_count": 1,
            "issue_count": 2,
            "issues_truncated": True,
        },
    )
    assert artifact_inspected_event("w", "a", "benchmarks", "benchmark", "valid", 0) == (
        EventName.ARTIFACT_INSPECTED,
        {
            "workspace_id": "w",
            "artifact_id": "a",
            "category": "benchmarks",
            "kind": "benchmark",
            "validation_status": "valid",
            "diagnostic_count": 0,
        },
    )


def test_application_events_are_not_domain_models_or_persisted() -> None:
    from dynamisbench.domain.spec.base import DomainModel

    assert not issubclass(ApplicationEvent, DomainModel)
    assert ApplicationEvent.model_config.get("frozen") is True


# --------------------------------------------------------------------------- #
# Real operations publish real events
# --------------------------------------------------------------------------- #
def test_workspace_operations_publish_events_from_worker_threads(tmp_path: Path) -> None:
    source = tmp_path / "source"
    evidence = tmp_path / "evidence"
    initialize_workspace(source, evidence, sources=[SourceCategory.BENCHMARKS])
    document = source / "benchmarks" / "scenario" / "case.json"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("{}", encoding="utf-8")

    app = create_app()
    recorded: list[tuple[EventName, dict[str, object]]] = []

    class Recorder(EventBroadcaster):
        def publish(self, event, data=None):  # type: ignore[no-untyped-def]
            recorded.append((event, dict(data or {})))
            super().publish(event, data)

    setattr(app.state, EVENT_BROADCASTER_ATTRIBUTE, Recorder())

    with TestClient(app) as client:
        opened = client.post(
            f"{API_V1_PREFIX}/workspaces/open",
            json={"source_root": str(source), "evidence_root": str(evidence)},
            headers=AUTHORIZATION,
        )
        workspace_id = opened.json()["workspace_id"]
        discovered = client.get(
            f"{API_V1_PREFIX}/workspaces/{workspace_id}/artifacts", headers=AUTHORIZATION
        )
        artifact_id = discovered.json()["artifacts"]["artifacts"][0]["artifact_id"]
        inspected = client.get(
            f"{API_V1_PREFIX}/workspaces/{workspace_id}/artifacts/{artifact_id}",
            headers=AUTHORIZATION,
        )

    assert opened.status_code == 200
    assert discovered.status_code == 200
    assert inspected.status_code == 200
    assert [name for name, _ in recorded] == [
        EventName.WORKSPACE_OPENED,
        EventName.WORKSPACE_DISCOVERED,
        EventName.ARTIFACT_INSPECTED,
    ]
    assert recorded[0][1]["workspace_id"] == workspace_id
    assert recorded[1][1]["artifact_count"] == 1
    assert recorded[1][1]["invalid_count"] == 1
    assert recorded[2][1]["artifact_id"] == artifact_id
    assert recorded[2][1]["validation_status"] == "invalid"


def test_a_refused_operation_publishes_nothing(tmp_path: Path) -> None:
    app = create_app()
    recorded: list[EventName] = []

    class Recorder(EventBroadcaster):
        def publish(self, event, data=None):  # type: ignore[no-untyped-def]
            recorded.append(event)

    setattr(app.state, EVENT_BROADCASTER_ATTRIBUTE, Recorder())

    with TestClient(app) as client:
        response = client.post(
            f"{API_V1_PREFIX}/workspaces/open",
            json={
                "source_root": str(tmp_path / "missing"),
                "evidence_root": str(tmp_path / "also-missing"),
            },
            headers=AUTHORIZATION,
        )

    assert response.status_code == 400
    assert recorded == []


def test_the_event_route_has_no_parameters_and_no_replay_surface() -> None:
    document = create_app().openapi()
    operation = document["paths"][EVENTS]["get"]

    assert operation.get("parameters", []) == []
    assert set(operation["responses"]) >= {"200", "405", "500"}
    assert "text/event-stream" in operation["responses"]["200"]["content"]
