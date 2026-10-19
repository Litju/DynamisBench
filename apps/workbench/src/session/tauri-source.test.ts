/**
 * The Tauri session adapter's lifecycle ordering.
 *
 * The mock is the IPC surface itself: `invoke` and `listen` are the only two calls this
 * adapter is allowed to make, and every test below drives the adapter through them rather
 * than through a stub of the adapter. What is asserted is what crosses the process boundary
 * and in which order — registration before bootstrap, a credential only ever from the
 * command, an immediate drop on a non-ready event, and no publication of an answer that a
 * later event has already invalidated.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { snapshot, readySessionWire } from "../test/session-fixtures";
import type { DesktopSessionSnapshot, WorkbenchSession } from "./types";

const bridge = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
  isTauri: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: bridge.invoke,
  isTauri: bridge.isTauri,
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: bridge.listen,
}));

/** One registered lifecycle handler, as `listen` received it. */
type LifecycleHandler = (event: { payload: DesktopSessionSnapshot }) => void;

let handlers: LifecycleHandler[];
let unlisten: Mock<() => void>;

/** Let every pending microtask and the mocked IPC's own promises settle. */
async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
}

beforeEach(() => {
  handlers = [];
  unlisten = vi.fn(() => {
    handlers = [];
  });
  bridge.invoke.mockReset();
  bridge.listen.mockReset();
  bridge.isTauri.mockReset();

  bridge.listen.mockImplementation(async (_event: string, handler: LifecycleHandler) => {
    handlers.push(handler);
    return unlisten;
  });
});

afterEach(() => {
  vi.clearAllTimers();
});

async function startSource(): Promise<{
  published: WorkbenchSession[];
  stop: () => void;
}> {
  const { tauriSessionSource } = await import("./tauri-source");
  const published: WorkbenchSession[] = [];
  const stop = tauriSessionSource().start((session) => {
    published.push(session);
  });
  return { published, stop };
}

describe("tauriSessionSource", () => {
  it("registers the lifecycle listener before the first bootstrap read", async () => {
    const order: string[] = [];
    bridge.listen.mockImplementation(async (_event: string, handler: LifecycleHandler) => {
      handlers.push(handler);
      order.push("listen");
      return unlisten;
    });
    bridge.invoke.mockImplementation(async () => {
      order.push("invoke");
      return snapshot();
    });

    await startSource();
    await settle();

    expect(order).toEqual(["listen", "invoke"]);
    expect(bridge.listen).toHaveBeenCalledWith("dynamisbench-api-status", expect.any(Function));
    expect(bridge.invoke).toHaveBeenCalledWith("get_api_session");
  });

  it("turns a ready bootstrap into a ready session", async () => {
    bridge.invoke.mockResolvedValue(readySessionWire());

    const { published } = await startSource();
    await settle();

    expect(published.at(-1)).toEqual({
      phase: "ready",
      api: {
        origin: "http://127.0.0.1:49152",
        apiVersion: "v1",
        protocolVersion: 1,
        credential: "fixture-credential-not-a-secret",
      },
    });
  });

  it("acquires the credential by re-invoking after a ready lifecycle event", async () => {
    bridge.invoke.mockResolvedValueOnce(snapshot({ status: "starting" }));
    bridge.invoke.mockResolvedValueOnce(readySessionWire());

    const { published } = await startSource();
    await settle();
    expect(published.at(-1)).toEqual({ phase: "starting" });

    handlers[0]?.({
      payload: snapshot({
        status: "ready",
        origin: "http://127.0.0.1:49152",
        api_version: "v1",
        protocol_version: 1,
      }),
    });
    await settle();

    expect(bridge.invoke).toHaveBeenCalledTimes(2);
    expect(published.at(-1)?.phase).toBe("ready");
    expect(published.at(-1)).toHaveProperty("api.credential", "fixture-credential-not-a-secret");
  });

  it("drops the previous credential as soon as a non-ready event arrives", async () => {
    bridge.invoke.mockResolvedValueOnce(readySessionWire());

    const { published } = await startSource();
    await settle();
    expect(published.at(-1)?.phase).toBe("ready");

    // The reconcile read is held open, so anything observed before it resolves had to come
    // from the event itself.
    const held = deferred<unknown>();
    bridge.invoke.mockReturnValueOnce(held.promise);

    handlers[0]?.({
      payload: snapshot({ status: "failed", failure: "unexpected_exit", restart_required: true }),
    });

    expect(published.at(-1)).toEqual({
      phase: "failed",
      failure: "unexpected_exit",
      restartRequired: true,
    });
    expect(JSON.stringify(published.at(-1))).not.toContain("fixture-credential-not-a-secret");

    held.resolve(snapshot({ status: "failed", failure: "unexpected_exit", restart_required: true }));
    await settle();

    expect(published.at(-1)).toEqual({
      phase: "failed",
      failure: "unexpected_exit",
      restartRequired: true,
    });
  });

  it("discards a bootstrap answer that a later event invalidated", async () => {
    const first = deferred<unknown>();
    bridge.invoke.mockReturnValueOnce(first.promise);

    const { published } = await startSource();
    await settle();
    expect(published).toEqual([]);

    handlers[0]?.({
      payload: snapshot({ status: "failed", failure: "sidecar_startup_exit", restart_required: false }),
    });
    expect(published.at(-1)?.phase).toBe("failed");

    // The held read resolves with the session that existed before the failure — the exact
    // answer that must not be published now.
    bridge.invoke.mockResolvedValueOnce(snapshot({ status: "stopped" }));
    first.resolve(readySessionWire());
    await settle();

    expect(published.map((session) => session.phase)).toEqual(["failed", "stopped"]);
    expect(JSON.stringify(published)).not.toContain("fixture-credential-not-a-secret");
  });
  it("reconciles overlapping lifecycle events into one settled read", async () => {
    bridge.invoke.mockResolvedValueOnce(readySessionWire());
    const { published } = await startSource();
    await settle();

    const held = deferred<unknown>();
    bridge.invoke.mockReturnValueOnce(held.promise);
    bridge.invoke.mockResolvedValue(snapshot({ status: "stopped" }));

    handlers[0]?.({ payload: snapshot({ status: "starting" }) });
    handlers[0]?.({ payload: snapshot({ status: "stopped" }) });

    held.resolve(snapshot({ status: "starting" }));
    await settle();

    const phases = published.map((session) => session.phase);
    expect(phases.at(-1)).toBe("stopped");
    expect(phases.indexOf("stopped")).toBeGreaterThan(phases.lastIndexOf("starting"));
  });

  it("detaches the lifecycle listener on disposal", async () => {
    bridge.invoke.mockResolvedValue(readySessionWire());

    const { published, stop } = await startSource();
    await settle();

    const count = published.length;
    stop();

    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(handlers).toHaveLength(0);
    expect(published).toHaveLength(count);
  });

  it("detaches a listener that was still registering when disposal arrived", async () => {
    const registration = deferred<() => void>();
    bridge.listen.mockReturnValueOnce(registration.promise);
    bridge.invoke.mockResolvedValue(readySessionWire());

    const { published, stop } = await startSource();
    stop();
    registration.resolve(unlisten);
    await settle();

    expect(unlisten).toHaveBeenCalledTimes(1);
    expect(bridge.invoke).not.toHaveBeenCalled();
    expect(published).toEqual([]);
  });

  it("reports a sidecar session the bridge cannot answer for as a desktop failure", async () => {
    bridge.invoke.mockRejectedValue(new Error("the bridge is gone"));

    const { published } = await startSource();
    await settle();

    expect(published).toEqual([{ phase: "failed", failure: null, restartRequired: false }]);
  });

  it("reports a listener that could not be registered as a desktop failure", async () => {
    bridge.listen.mockRejectedValue(new Error("no such event"));

    const { published } = await startSource();
    await settle();

    expect(published).toEqual([{ phase: "failed", failure: null, restartRequired: false }]);
    expect(bridge.invoke).not.toHaveBeenCalled();
  });
});
