"""Transient one-way application events over Server-Sent Events.

The application already describes what it did in each response. This module adds a *second
view* of the same operations for a workbench that wants to show activity while it works:
workspace opens, discoveries and inspections, plus connection status. It is deliberately not
a record of the workspace. There is no database, no file, no module-level registry, no replay
log and no source-file watcher — only an in-memory broadcaster owned by one application
instance, whose subscribers are connections that are open right now.

**The envelope is closed and versioned.** Every frame's ``data:`` is one JSON object with
``schema_version``, a closed ``event`` name, and a small ``data`` object. Values are strings,
integers, booleans or null, bounded in count and length. There is no field for a root path, a
credential, authoring content, a raw exception, a timestamp or an evidence claim, so none can
reach a client by being passed through.

**Publishing is thread-safe.** FastAPI runs synchronous route handlers in a worker thread, so
:meth:`EventBroadcaster.publish` may be called from a thread that owns no event loop. Each
subscriber carries the loop its stream runs on; publishing hands the event to that loop with
``call_soon_threadsafe`` and never touches an ``asyncio.Queue`` from the wrong thread.

**Slow subscribers are disconnected, not buffered.** A subscriber's queue has a fixed
capacity. If it falls behind far enough that the queue is full, the broadcaster drains the
queue and closes that subscription with an end-of-stream sentinel: the connection finishes,
the client's own bounded reconnect policy decides whether to ask again, and the publisher is
never blocked. That is the whole backpressure policy, and it is tested rather than assumed.

**Heartbeats are comments.** Every ``heartbeat_seconds`` without an event the stream emits
``": heartbeat\\n\\n"``. A comment keeps a quiet connection alive through intermediaries and
is ignored by the SSE parser, so it cannot be mistaken for an application event.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator

from dynamisbench.api.errors import refusal_responses
from dynamisbench.api.models import ApiModel

EVENT_BROADCASTER_ATTRIBUTE: Final = "event_broadcaster"
"""Where the application's own broadcaster lives on ``app.state``.

An attribute rather than a module global for the same reason the workspace registry is one:
two applications built in one process must not share a stream. It also lets a qualification
gate replace one application's broadcaster without reaching into another's.
"""

EVENT_SCHEMA_VERSION: Final = 1
"""The event envelope version. A client that does not speak it must not guess."""

EVENT_PATH: Final = "/events"
"""The one versioned route this module publishes, under the application's own prefix."""

EVENT_CONTENT_TYPE: Final = "text/event-stream"
"""The media type of the response body."""

HEARTBEAT_SECONDS: Final = 15.0
"""How long a stream may be silent before a comment heartbeat is written."""

SUBSCRIBER_QUEUE_CAPACITY: Final = 32
"""How many pending events one subscriber may fall behind by.

Small on purpose. These are status events about operations happening now; a consumer that is
thirty-two events behind is not watching live activity, and growing its buffer would only
postpone the decision to disconnect it.
"""

MAX_EVENT_DATA_FIELDS: Final = 8
MAX_EVENT_KEY_LENGTH: Final = 32
MAX_EVENT_VALUE_LENGTH: Final = 128
"""The bounds on one event's data object.

Every payload this module builds has at most six scalar fields, each far shorter than this.
The bounds exist so a future publisher cannot turn the envelope into an unbounded copy of
something it was describing.
"""

MAX_EVENT_INTEGER: Final = 2**53
"""The largest integer a JavaScript client can represent exactly."""

EventValue = str | bool | int | None


class EventName(StrEnum):
    """The closed vocabulary of events a client may receive.

    A closed set because the Activity surface branches on it: a value added here is a
    reviewed change to the transport contract, not a string a caller may invent.
    """

    STREAM_READY = "stream.ready"
    WORKSPACE_OPENED = "workspace.opened"
    WORKSPACE_DISCOVERED = "workspace.discovered"
    ARTIFACT_INSPECTED = "artifact.inspected"


class ApplicationEvent(ApiModel):
    """One frame's payload: the version, the event name, and bounded scalar data.

    ``data`` is a mapping rather than a union of per-event models so that the envelope stays
    one small shape a client can decode before it knows which event arrived. The mapping is
    bounded by validators; each builder below fixes the keys it publishes.
    """

    schema_version: Literal[1] = EVENT_SCHEMA_VERSION
    event: EventName
    data: dict[str, EventValue] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _bounded_data(cls, value: dict[str, EventValue]) -> dict[str, EventValue]:
        if len(value) > MAX_EVENT_DATA_FIELDS:
            raise ValueError("an event carries too many data fields")
        for key, entry in value.items():
            if not key or len(key) > MAX_EVENT_KEY_LENGTH:
                raise ValueError("an event data key is not bounded")
            if isinstance(entry, str) and len(entry) > MAX_EVENT_VALUE_LENGTH:
                raise ValueError("an event data value is not bounded")
            if isinstance(entry, int) and not isinstance(entry, bool):
                if abs(entry) > MAX_EVENT_INTEGER:
                    raise ValueError("an event integer is outside the exact range")
        return value


@dataclass(frozen=True, slots=True)
class EventSubscription:
    """One live subscription: its opaque handle and the queue its stream reads.

    The queue is the only place a pending event waits. It is bounded at construction, and
    ``None`` is the end-of-stream sentinel (a disconnected or lagging subscriber), not an
    event a client could receive.
    """

    identifier: int
    queue: asyncio.Queue[ApplicationEvent | None]


@dataclass(slots=True)
class _Subscriber:
    identifier: int
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[ApplicationEvent | None]
    closed: bool = False


@dataclass(slots=True)
class _State:
    closed: bool = False
    next_identifier: int = 1
    subscribers: dict[int, _Subscriber] = field(default_factory=dict)


class EventBroadcaster:
    """One application instance's transient set of live event subscribers.

    Constructed empty by :func:`dynamisbench.api.app.create_app`. It starts no thread, opens
    no file and owns no clock: a heartbeat is a timeout in the stream generator, not a
    background task.
    """

    def __init__(
        self,
        *,
        queue_capacity: int = SUBSCRIBER_QUEUE_CAPACITY,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("a subscriber queue must hold at least one event")
        if heartbeat_seconds <= 0:
            raise ValueError("a heartbeat interval must be positive")
        self._state = _State()
        self._lock = threading.Lock()
        self.queue_capacity = queue_capacity
        self.heartbeat_seconds = heartbeat_seconds

    def subscribe(self) -> EventSubscription:
        """Register the caller's running loop as one live subscriber.

        Called from the stream's own coroutine, so the running loop is the loop that will
        consume the queue. A subscriber is never created from a publishing thread.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[ApplicationEvent | None] = asyncio.Queue(maxsize=self.queue_capacity)
        with self._lock:
            if self._state.closed:
                raise RuntimeError("the event broadcaster is closed")
            identifier = self._state.next_identifier
            self._state.next_identifier += 1
            self._state.subscribers[identifier] = _Subscriber(
                identifier=identifier,
                loop=loop,
                queue=queue,
            )
        return EventSubscription(identifier=identifier, queue=queue)

    def unsubscribe(self, identifier: int) -> None:
        """Forget one subscription. Safe to call twice and from any thread."""
        with self._lock:
            subscriber = self._state.subscribers.pop(identifier, None)
        if subscriber is not None:
            subscriber.closed = True

    def subscriber_count(self) -> int:
        """How many streams are registered right now, for qualification rather than clients."""
        with self._lock:
            return len(self._state.subscribers)

    def publish(self, event: EventName, data: dict[str, EventValue] | None = None) -> None:
        """Publish one event to every connection open at this instant.

        Never raises into an operation route: a stream is a view of the operation, and a
        view that failed must not turn a successful workspace read into an HTTP failure.
        A loop that has already closed is dropped from the registry.
        """
        try:
            application_event = ApplicationEvent(event=event, data=dict(data or {}))
        except ValueError:
            # A caller built an unbounded event. Refusing it is better than publishing it;
            # the operation it describes has already happened and is still in its response.
            return

        with self._lock:
            if self._state.closed:
                return
            subscribers = tuple(self._state.subscribers.values())

        dead: list[int] = []
        for subscriber in subscribers:
            if subscriber.closed:
                dead.append(subscriber.identifier)
                continue
            try:
                subscriber.loop.call_soon_threadsafe(self._offer, subscriber, application_event)
            except RuntimeError:
                # The subscriber's loop is closed. Its connection is gone; nothing to send.
                dead.append(subscriber.identifier)

        for identifier in dead:
            self.unsubscribe(identifier)

    def close(self) -> None:
        """End every stream and refuse future subscriptions.

        Called by the application's lifespan shutdown. The sentinel is scheduled on each
        stream's own loop, so no queue is touched from the closing thread.
        """
        with self._lock:
            if self._state.closed:
                return
            self._state.closed = True
            subscribers = tuple(self._state.subscribers.values())
            self._state.subscribers.clear()

        for subscriber in subscribers:
            subscriber.closed = True
            try:
                subscriber.loop.call_soon_threadsafe(self._finish, subscriber)
            except RuntimeError:
                continue

    def _offer(self, subscriber: _Subscriber, event: ApplicationEvent) -> None:
        """Queue one event on the subscriber's loop, or disconnect it if it is behind.

        Runs only on the subscriber's own event loop, which is what makes touching its
        ``asyncio.Queue`` safe. A full queue is the slow-consumer decision: clear what is
        pending and place the end-of-stream sentinel, so the generator finishes and the
        client reconnects under its own bounded policy.
        """
        if subscriber.closed:
            return
        if subscriber.queue.full():
            self._drain(subscriber.queue)
            subscriber.queue.put_nowait(None)
            subscriber.closed = True
            return
        subscriber.queue.put_nowait(event)

    def _finish(self, subscriber: _Subscriber) -> None:
        """Place the sentinel on a closing subscriber's queue, on its own loop."""
        self._drain(subscriber.queue)
        subscriber.queue.put_nowait(None)

    @staticmethod
    def _drain(queue: asyncio.Queue[ApplicationEvent | None]) -> None:
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return


def encode_event(event: ApplicationEvent) -> str:
    """One SSE frame. The JSON object is the whole event; the field name carries no extra state."""
    return f"data: {event.model_dump_json()}\n\n"


def encode_heartbeat() -> str:
    """A comment frame. An SSE parser ignores it, so it cannot arrive as an event."""
    return ": heartbeat\n\n"


def stream_ready_event(heartbeat_seconds: float, queue_capacity: int) -> ApplicationEvent:
    """The first frame on a newly accepted stream: what this transport will do."""
    return ApplicationEvent(
        event=EventName.STREAM_READY,
        data={
            "heartbeat_seconds": int(heartbeat_seconds),
            "queue_capacity": queue_capacity,
        },
    )


def workspace_opened_event(
    workspace_id: str, categories_present: int, evidence_inside_source: bool
) -> tuple[EventName, dict[str, EventValue]]:
    """An open succeeded. The opaque identifier is safe; neither root is passed in."""
    return (
        EventName.WORKSPACE_OPENED,
        {
            "workspace_id": workspace_id,
            "categories_present": max(0, categories_present),
            "evidence_inside_source": evidence_inside_source,
        },
    )


def workspace_discovered_event(
    workspace_id: str,
    artifact_count: int,
    valid_count: int,
    invalid_count: int,
    issue_count: int,
    issues_truncated: bool,
) -> tuple[EventName, dict[str, EventValue]]:
    """A discovery pass completed: counts and one truncation fact, never documents."""
    return (
        EventName.WORKSPACE_DISCOVERED,
        {
            "workspace_id": workspace_id,
            "artifact_count": max(0, artifact_count),
            "valid_count": max(0, valid_count),
            "invalid_count": max(0, invalid_count),
            "issue_count": max(0, issue_count),
            "issues_truncated": issues_truncated,
        },
    )


def artifact_inspected_event(
    workspace_id: str,
    artifact_id: str,
    category: str,
    kind: str,
    validation_status: str,
    diagnostic_count: int,
) -> tuple[EventName, dict[str, EventValue]]:
    """One inspection completed. Identity and validation facts only; no content, no reference."""
    return (
        EventName.ARTIFACT_INSPECTED,
        {
            "workspace_id": workspace_id,
            "artifact_id": artifact_id,
            "category": category,
            "kind": kind,
            "validation_status": validation_status,
            "diagnostic_count": max(0, diagnostic_count),
        },
    )


def publish_from_request(request: Request, event: tuple[EventName, dict[str, EventValue]]) -> None:
    """Publish an operation event through the application's own broadcaster, if it has one.

    A missing broadcaster is a programming error in the factory rather than a client-visible
    failure, so it is not repaired and not reported: the operation's response is unaffected.
    """
    broadcaster = getattr(request.app.state, EVENT_BROADCASTER_ATTRIBUTE, None)
    if isinstance(broadcaster, EventBroadcaster):
        broadcaster.publish(event[0], event[1])


events_router = APIRouter()
"""The one event route, included under :data:`dynamisbench.api.routing.API_V1_PREFIX`."""


def _broadcaster(request: Request) -> EventBroadcaster:
    broadcaster = getattr(request.app.state, EVENT_BROADCASTER_ATTRIBUTE, None)
    if not isinstance(broadcaster, EventBroadcaster):
        raise RuntimeError("this application has no event broadcaster")
    return broadcaster


@events_router.get(
    EVENT_PATH,
    response_class=StreamingResponse,
    responses=refusal_responses(
        {
            200: {
                "description": "A live text/event-stream of bounded application events.",
                "content": {
                    EVENT_CONTENT_TYPE: {
                        "schema": {
                            "type": "string",
                            "description": (
                                "SSE frames whose data field is one ApplicationEvent JSON object."
                            ),
                        }
                    }
                },
            }
        }
    ),
)
async def read_events(request: Request) -> StreamingResponse:
    """Stream application events until the client disconnects or the application closes.

    The route is read-only and has no parameters. It does not take a workspace filter: an
    opaque identifier in a query is a second registry lookup and a second chance to accept
    something this application never minted, while the event set is already public to any
    client holding the session credential.
    """
    broadcaster = _broadcaster(request)

    async def frames():
        subscription = broadcaster.subscribe()
        try:
            yield encode_event(
                stream_ready_event(broadcaster.heartbeat_seconds, broadcaster.queue_capacity)
            )
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        subscription.queue.get(), timeout=broadcaster.heartbeat_seconds
                    )
                except TimeoutError:
                    yield encode_heartbeat()
                    continue
                if event is None:
                    break
                yield encode_event(event)
        finally:
            broadcaster.unsubscribe(subscription.identifier)

    return StreamingResponse(
        frames(),
        media_type=EVENT_CONTENT_TYPE,
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "EVENT_BROADCASTER_ATTRIBUTE",
    "EVENT_CONTENT_TYPE",
    "EVENT_PATH",
    "EVENT_SCHEMA_VERSION",
    "HEARTBEAT_SECONDS",
    "MAX_EVENT_DATA_FIELDS",
    "SUBSCRIBER_QUEUE_CAPACITY",
    "ApplicationEvent",
    "EventBroadcaster",
    "EventName",
    "EventSubscription",
    "artifact_inspected_event",
    "encode_event",
    "encode_heartbeat",
    "events_router",
    "publish_from_request",
    "read_events",
    "stream_ready_event",
    "workspace_discovered_event",
    "workspace_opened_event",
]
