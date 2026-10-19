/**
 * The runtime-state model: every session state, and the two API-read states it implies.
 *
 * A pure function's whole matrix, which is the reason it is a pure function: the states a
 * user can see are enumerable here, and a phase added to the session vocabulary fails this
 * test rather than falling through to whatever the component's default branch happened to be.
 */

import { describe, expect, it } from "vitest";

import { ApiClientError } from "../api/errors";
import type { WorkbenchSession } from "../session/types";
import { runtimeState, type InfoState } from "./runtime-state";

const PENDING: InfoState = { status: "pending" };
const SUCCESS: InfoState = {
  status: "success",
  application: "DynamisBench",
  version: "0.0.0",
  apiVersion: "v1",
};

describe("runtimeState", () => {
  it("names an ordinary browser as unavailable rather than failed", () => {
    const state = runtimeState({ phase: "unavailable" }, PENDING);

    expect(state.id).toBe("browser_unavailable");
    expect(state.tone).toBe("neutral");
  });

  it("names the desktop lifecycle states", () => {
    expect(runtimeState({ phase: "starting" }, PENDING).id).toBe("starting");
    expect(runtimeState({ phase: "stopped" }, PENDING).id).toBe("stopped");
  });

  it("reports a failure with its bounded code and whether a restart is needed", () => {
    const restart = runtimeState(
      { phase: "failed", failure: "shutdown_timeout", restartRequired: true },
      PENDING,
    );
    const start = runtimeState(
      { phase: "failed", failure: "spawn_failed", restartRequired: false },
      PENDING,
    );

    expect(restart.id).toBe("failed");
    expect(restart.tone).toBe("danger");
    expect(restart.detail).toMatch(/did not stop within the shutdown deadline/);
    expect(restart.detail).toMatch(/restart the desktop shell/i);
    expect(start.detail).toMatch(/could not be started/);
    expect(start.detail).not.toMatch(/restart the desktop shell/i);
  });

  it("reports a failure with no code without inventing one", () => {
    const state = runtimeState(
      { phase: "failed", failure: null, restartRequired: false },
      PENDING,
    );

    expect(state.detail).toMatch(/did not name/);
  });

  it("reports an incompatible session with the versions involved", () => {
    const state = runtimeState({ phase: "incompatible", apiVersion: "v2", protocolVersion: 0 }, PENDING);

    expect(state.id).toBe("incompatible");
    expect(state.detail).toMatch(/v2 \/ protocol 0/);
    expect(state.detail).toMatch(/requires v1 \/ protocol 1/);
  });

  it("distinguishes connecting from ready", () => {
    const ready: WorkbenchSession = {
      phase: "ready",
      api: {
        origin: "http://127.0.0.1:49152",
        apiVersion: "v1",
        protocolVersion: 1,
        credential: "fixture-credential-not-a-secret",
      },
    };

    expect(runtimeState(ready, PENDING).id).toBe("connecting");
    expect(runtimeState(ready, SUCCESS).id).toBe("ready");
    expect(runtimeState(ready, SUCCESS).detail).toBe("DynamisBench 0.0.0, API v1.");
  });

  it("prefers the application's own message for a refused read", () => {
    const withMessage = new ApiClientError("http", {
      status: 400,
      code: "http_error",
      apiMessage: "The declared workspace roots could not be opened.",
    });
    const withoutMessage = new ApiClientError("network");

    expect(runtimeState({ phase: "ready", api: ready() }, { status: "error", error: withMessage }).detail).toBe(
      "The declared workspace roots could not be opened.",
    );
    expect(
      runtimeState({ phase: "ready", api: ready() }, { status: "error", error: withoutMessage }).detail,
    ).toBe("The DynamisBench application API could not be reached.");
  });

  it("never mentions a credential in any state", () => {
    const states = [
      runtimeState({ phase: "unavailable" }, PENDING),
      runtimeState({ phase: "starting" }, PENDING),
      runtimeState({ phase: "stopped" }, PENDING),
      runtimeState({ phase: "failed", failure: "protocol_violation", restartRequired: true }, PENDING),
      runtimeState({ phase: "incompatible", apiVersion: null, protocolVersion: null }, PENDING),
      runtimeState({ phase: "ready", api: ready() }, PENDING),
      runtimeState({ phase: "ready", api: ready() }, SUCCESS),
      runtimeState({ phase: "ready", api: ready() }, { status: "error", error: "not an error" }),
    ];

    for (const state of states) {
      expect(`${state.label} ${state.detail}`).not.toContain("fixture-credential-not-a-secret");
      expect(`${state.label} ${state.detail}`).not.toContain("Bearer");
    }
  });
});

function ready() {
  return {
    origin: "http://127.0.0.1:49152",
    apiVersion: "v1" as const,
    protocolVersion: 1 as const,
    credential: "fixture-credential-not-a-secret",
  };
}
