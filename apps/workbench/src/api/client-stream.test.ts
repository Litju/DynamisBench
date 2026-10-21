/**
 * The event stream over the one HTTP client boundary.
 *
 * These gates prove the request the client builds (authenticated fetch, no cookie, no cache),
 * the frames it yields, and the bounded failures it reports instead of guessing. The parser's
 * own boundary cases live beside the parser.
 */

import { describe, expect, it } from "vitest";

import type { ApplicationEvent } from "./types";
import { createApiClient, type ApiClientConnection } from "./client";
import { ApiClientError } from "./errors";
import {
  bytesResponse,
  controlledStreamResponse,
  recordingFetch,
  streamResponse,
} from "../test/http-fixtures";
import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";

const CONNECTION: ApiClientConnection = readyApiSession();

function line(event: ApplicationEvent): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

const READY: ApplicationEvent = {
  schema_version: 1,
  event: "stream.ready",
  data: { heartbeat_seconds: 15, queue_capacity: 32 },
};

const OPENED: ApplicationEvent = {
  schema_version: 1,
  event: "workspace.opened",
  data: { workspace_id: "workspace-1", categories_present: 3 },
};

async function collect(
  client: ReturnType<typeof createApiClient>,
  signal = new AbortController().signal,
): Promise<ApplicationEvent[]> {
  const events: ApplicationEvent[] = [];
  for await (const event of client.streamEvents({ signal })) {
    events.push(event);
  }
  return events;
}

function streamClient(chunks: readonly string[], signal?: AbortSignal) {
  const recorder = recordingFetch(() => streamResponse(chunks));
  return {
    client: createApiClient(CONNECTION, { fetch: recorder.fetch }),
    calls: recorder.calls,
    signal,
  };
}

describe("ApiClient.streamEvents", () => {
  it("asks /api/v1/events with the bearer credential and no cookie or cache", async () => {
    const { client, calls } = streamClient([line(READY)]);

    await collect(client);

    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/events`);
    expect(calls[0]?.init.method).toBe("GET");
    expect(calls[0]?.init.credentials).toBe("omit");
    expect(calls[0]?.init.cache).toBe("no-store");
    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${FIXTURE_CREDENTIAL}`);
    expect(headers.Accept).toBe("text/event-stream");
  });

  it("decodes frames split across arbitrary chunk boundaries", async () => {
    const source = `${line(READY)}${line(OPENED)}`;
    const middle = Math.floor(source.length / 2);
    const { client } = streamClient([source.slice(0, middle), source.slice(middle)]);

    await expect(collect(client)).resolves.toEqual([READY, OPENED]);
  });

  it("decodes a UTF-8 character split across byte chunks", async () => {
    const payload = line({
      schema_version: 1,
      event: "artifact.inspected",
      data: {
        workspace_id: "w",
        artifact_id: "a",
        category: "benchmarks",
        kind: "café",
        validation_status: "valid",
        diagnostic_count: 0,
      },
    });
    const bytes = new TextEncoder().encode(payload);
    const split = bytes.indexOf(0xc3) + 1; // between the two bytes of "é"
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    });
    const recorder = recordingFetch(
      () => new Response(body, { status: 200 }),
    );
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    const events = await collect(client);

    expect(events[0]?.data.kind).toBe("café");
  });

  it("ignores comment heartbeats", async () => {
    const { client } = streamClient([line(READY), ": heartbeat\n\n", line(OPENED)]);

    await expect(collect(client)).resolves.toEqual([READY, OPENED]);
  });

  it("ends cleanly when the consumer aborts", async () => {
    const controlled = controlledStreamResponse();
    const recorder = recordingFetch(() => controlled.response);
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });
    const controller = new AbortController();
    const iterator = client.streamEvents({ signal: controller.signal })[Symbol.asyncIterator]();

    controlled.push(line(READY));
    await expect(iterator.next()).resolves.toEqual({ done: false, value: READY });

    controller.abort();
    await expect(iterator.next()).resolves.toEqual({ done: true, value: undefined });
  });

  it("reports a 401 as the application's bounded HTTP refusal", async () => {
    const recorder = recordingFetch(
      () =>
        new Response(
          JSON.stringify({
            error: { code: "unauthorized", message: "Authentication required." },
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
    );
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    await expect(collect(client)).rejects.toMatchObject({
      name: "ApiClientError",
      kind: "http",
      status: 401,
      code: "unauthorized",
    });
  });

  it("refuses a frame whose JSON is malformed", async () => {
    const { client } = streamClient(["data: {not json}\n\n"]);

    const error = await collect(client).catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiClientError);
    expect((error as ApiClientError).kind).toBe("invalid_response");
  });

  it("refuses a frame from a schema version this client does not speak", async () => {
    const { client } = streamClient([
      `data: ${JSON.stringify({ ...READY, schema_version: 2 })}\n\n`,
    ]);

    const error = await collect(client).catch((failure: unknown) => failure);
    expect((error as ApiClientError).kind).toBe("invalid_response");
  });

  it("refuses unknown event names and unbounded data", async () => {
    for (const body of [
      { schema_version: 1, event: "workspace.deleted", data: {} },
      { schema_version: 1, event: "workspace.opened", data: { workspace_id: "x".repeat(129) } },
      { schema_version: 1, event: "workspace.opened", data: { count: 2 ** 54 } },
    ]) {
      const { client } = streamClient([`data: ${JSON.stringify(body)}\n\n`]);
      const error = await collect(client).catch((failure: unknown) => failure);
      expect(error).toBeInstanceOf(ApiClientError);
      expect((error as ApiClientError).kind).toBe("invalid_response");
    }
  });

  it("refuses invalid UTF-8 rather than replacing it silently", async () => {
    const recorder = recordingFetch(() => bytesResponse(new Uint8Array([0xff, 0xfe])));
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    const error = await collect(client).catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiClientError);
    expect((error as ApiClientError).kind).toBe("invalid_response");
  });

  it("refuses an oversized frame instead of buffering it", async () => {
    const { client } = streamClient([`data: ${"x".repeat(70 * 1024)}`]);

    const error = await collect(client).catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ApiClientError);
    expect((error as ApiClientError).kind).toBe("invalid_response");
  });
});
