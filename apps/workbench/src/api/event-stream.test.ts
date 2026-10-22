/**
 * Reconnect policy: bounded, abortable, and terminal for failures that cannot change.
 *
 * The controlled `wait` is the clock. No test sleeps, and the number of attempts is asserted
 * exactly rather than observed after an interval.
 */

import { describe, expect, it } from "vitest";

import type { ApiClient } from "./client";
import { createApiClient } from "./client";
import {
  startEventStream,
  reconnectDelay,
  type EventStreamState,
} from "./event-stream";
import { ApiClientError } from "./errors";
import type { ApplicationEvent } from "./types";
import { observableStreamResponse, recordingFetch } from "../test/http-fixtures";
import { readyApiSession } from "../test/session-fixtures";

const READY: ApplicationEvent = {
  schema_version: 1,
  event: "stream.ready",
  data: { heartbeat_seconds: 15, queue_capacity: 32 },
};

type Stream = (options: { signal: AbortSignal }) => AsyncIterable<ApplicationEvent>;

function clientFrom(stream: Stream): Pick<ApiClient, "streamEvents"> {
  return { streamEvents: stream };
}

describe("reconnectDelay", () => {
  it("is deterministic exponential backoff with a ceiling", () => {
    expect(reconnectDelay(0)).toBe(0);
    expect([1, 2, 3, 4, 5, 6, 7].map((attempt) => reconnectDelay(attempt))).toEqual([
      250, 500, 1000, 2000, 4000, 4000, 4000,
    ]);
  });
});

describe("startEventStream", () => {
  it("reports live and forwards events from a healthy stream", async () => {
    const states: EventStreamState[] = [];
    const events: ApplicationEvent[] = [];
    const client = clientFrom(async function* () {
      yield READY;
      yield READY;
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: (event) => {
        events.push(event);
        controller.abort();
      },
      onState: (state) => states.push(state),
      policy: { wait: async () => {} },
    });
    await handle.done;

    expect(events).toEqual([READY]);
    expect(states[0]).toBe("connecting");
    expect(states).toContain("live");
  });

  it("stops immediately on an authentication refusal", async () => {
    const states: EventStreamState[] = [];
    let calls = 0;
    const client = clientFrom(async function* () {
      calls += 1;
      throw new ApiClientError("http", { status: 401, code: "unauthorized" });
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: (state) => states.push(state),
      policy: { wait: async () => {} },
    });
    await handle.done;

    expect(calls).toBe(1);
    expect(states).toEqual(["connecting", "refused"]);
  });

  it("stops immediately on an incompatible envelope", async () => {
    const states: EventStreamState[] = [];
    const client = clientFrom(async function* () {
      throw new ApiClientError("invalid_response", { status: 200 });
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: (state) => states.push(state),
      policy: { wait: async () => {} },
    });
    await handle.done;

    expect(states).toEqual(["connecting", "refused"]);
  });

  it("retries a transient failure a bounded number of times", async () => {
    let calls = 0;
    const states: EventStreamState[] = [];
    const client = clientFrom(async function* () {
      calls += 1;
      throw new ApiClientError("network");
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: (state) => states.push(state),
      policy: { maxConsecutiveFailures: 2, wait: async () => {} },
    });
    await handle.done;

    expect(calls).toBe(3);
    expect(states.filter((state) => state === "reconnecting")).toHaveLength(2);
    expect(states.at(-1)).toBe("unavailable");
  });

  it("bounds total reconnect cycles even when every stream had been live", async () => {
    let calls = 0;
    const states: EventStreamState[] = [];
    const client = clientFrom(async function* () {
      calls += 1;
      yield READY;
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: (state) => states.push(state),
      policy: { maxReconnects: 2, wait: async () => {} },
    });
    await handle.done;

    expect(calls).toBe(3);
    expect(states.at(-1)).toBe("unavailable");
  });

  it("uses the backoff sequence from the injected clock", async () => {
    const delays: number[] = [];
    let calls = 0;
    const client = clientFrom(async function* () {
      calls += 1;
      throw new ApiClientError("network");
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: () => {},
      policy: {
        maxConsecutiveFailures: 3,
        wait: async (milliseconds) => {
          delays.push(milliseconds);
        },
      },
    });
    await handle.done;

    expect(calls).toBe(4);
    expect(delays).toEqual([250, 500, 1000]);
  });

  it("aborts the stream promptly and does not schedule a reconnect", async () => {
    const states: EventStreamState[] = [];
    let aborted = false;
    const client = clientFrom(async function* ({ signal }) {
      yield READY;
      if (signal.aborted) {
        aborted = true;
        return;
      }
      await new Promise<void>((resolve) => {
        signal.addEventListener(
          "abort",
          () => {
            aborted = true;
            resolve();
          },
          { once: true },
        );
      });
    });
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: (state) => states.push(state),
      policy: { wait: async () => {} },
    });

    for (let turn = 0; turn < 10 && !states.includes("live"); turn += 1) {
      await Promise.resolve();
    }
    handle.stop();
    await handle.done;

    expect(aborted).toBe(true);
    expect(states).not.toContain("reconnecting");
  });
});

describe("startEventStream terminal cancellation", () => {
  it("closes the connection once on a malformed frame and never reconnects", async () => {
    const controlled = observableStreamResponse();
    const recorder = recordingFetch(() => controlled.response);
    const client = createApiClient(readyApiSession(), { fetch: recorder.fetch });
    const states: EventStreamState[] = [];
    const controller = new AbortController();

    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: () => {},
      onState: (state) => states.push(state),
      policy: { wait: async () => {} },
    });

    controlled.push("data: {not json}\n\n");
    await handle.done;

    expect(states).toEqual(["connecting", "refused"]);
    expect(recorder.calls).toHaveLength(1);
    expect(controlled.cancelCount()).toBe(1);

    controller.abort();
  });
});
