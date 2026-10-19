/**
 * The browser half of the session boundary.
 *
 * A normal browser has no Tauri runtime, and the workbench must render there — with no IPC
 * attempted, nothing to await, and no state that implies a desktop session exists. These
 * tests mock the Tauri IPC modules and then assert they are never used, which is the only
 * form in which "never invokes Tauri" can be checked rather than intended.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkbenchSession } from "./types";

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

beforeEach(() => {
  bridge.invoke.mockReset();
  bridge.listen.mockReset();
  bridge.isTauri.mockReset();
});

describe("browserSessionSource", () => {
  it("publishes the unavailable state immediately and acquires nothing", async () => {
    const { browserSessionSource } = await import("./source");
    const published: WorkbenchSession[] = [];

    const stop = browserSessionSource().start((session) => {
      published.push(session);
    });

    expect(browserSessionSource().kind).toBe("browser");
    expect(published).toEqual([{ phase: "unavailable" }]);
    expect(() => stop()).not.toThrow();
    expect(bridge.invoke).not.toHaveBeenCalled();
    expect(bridge.listen).not.toHaveBeenCalled();
  });
});

describe("defaultSessionSource", () => {
  it("selects the browser source outside a Tauri runtime", async () => {
    bridge.isTauri.mockReturnValue(false);
    const { defaultSessionSource } = await import("./source");

    const source = defaultSessionSource();
    const published: WorkbenchSession[] = [];
    const stop = source.start((session) => {
      published.push(session);
    });
    stop();

    expect(source.kind).toBe("browser");
    expect(bridge.isTauri).toHaveBeenCalledTimes(1);
    expect(bridge.invoke).not.toHaveBeenCalled();
    expect(bridge.listen).not.toHaveBeenCalled();
    expect(published).toEqual([{ phase: "unavailable" }]);
  });

  it("selects the desktop source inside a Tauri runtime", async () => {
    bridge.isTauri.mockReturnValue(true);
    bridge.listen.mockResolvedValue(() => {});
    bridge.invoke.mockResolvedValue({ status: "starting" });
    const { defaultSessionSource } = await import("./source");

    const source = defaultSessionSource();

    expect(source.kind).toBe("tauri");
    expect(bridge.listen).not.toHaveBeenCalled();
    expect(bridge.invoke).not.toHaveBeenCalled();
  });
});
