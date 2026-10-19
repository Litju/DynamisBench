/**
 * Every state the runtime status surface can display.
 *
 * These are the states a user needs to distinguish: there is no desktop shell, one is
 * starting, the API is being read, the API is ready, the read failed, the shell's session
 * failed, and the session speaks a version this workbench cannot use. Each is asserted by
 * the text a person reads, not by an internal flag.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWorkbenchQueryClient } from "../query/client";
import { SessionProvider } from "../session/provider";
import { browserSessionSource } from "../session/source";
import { controlledSource, type ControlledSource } from "../test/controlled-source";
import { FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";
import { RuntimeStatus } from "./runtime-status";

function renderStatus(controlled: ControlledSource) {
  const queryClient = createWorkbenchQueryClient();

  render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider queryClient={queryClient} source={controlled.source}>
        <RuntimeStatus />
      </SessionProvider>
    </QueryClientProvider>,
  );

  return queryClient;
}

/** A read that never answers, so the connecting state stays observable. */
function stubPendingFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => {})),
  );
}

function stubInfoFetch(init: { status?: number; body?: unknown } = {}) {
  const status = init.status ?? 200;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        ({
          ok: status >= 200 && status < 300,
          status,
          json: async () =>
            init.body ?? { application: "DynamisBench", version: "0.0.0", api_version: "v1" },
        }) as unknown as Response,
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RuntimeStatus", () => {
  it("says a browser has no desktop session, and asks nothing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = createWorkbenchQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider queryClient={queryClient} source={browserSessionSource()}>
          <RuntimeStatus />
        </SessionProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Desktop session unavailable")).toBeInTheDocument();
    expect(screen.getByText(/no local API session/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports a starting session", () => {
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "starting" });

    expect(screen.getByText("Starting")).toBeInTheDocument();
    expect(screen.getByText(/waiting for the local application API/i)).toBeInTheDocument();
  });

  it("reports a stopped session", () => {
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "stopped" });

    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("reports connecting while the API is being read", async () => {
    stubPendingFetch();
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(await screen.findByText("Connecting")).toBeInTheDocument();
    expect(screen.getByText(/reading the application's build identity/i)).toBeInTheDocument();
  });

  it("reports the application's identity once it is ready", async () => {
    stubInfoFetch();
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("DynamisBench 0.0.0, API v1.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(`${FIXTURE_ORIGIN}/api/v1/info`, expect.anything());
  });

  it("reports an API refusal with the application's own message", async () => {
    stubInfoFetch({
      status: 500,
      body: { error: { code: "internal_error", message: "The application could not complete the request." } },
    });
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(await screen.findByText("API error")).toBeInTheDocument();
    expect(screen.getByText("The application could not complete the request.")).toBeInTheDocument();
  });

  it("reports an unreachable API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(await screen.findByText("API error")).toBeInTheDocument();
    expect(screen.getByText(/could not be reached/i)).toBeInTheDocument();
  });

  it("reports a desktop failure with its bounded reason", () => {
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "failed", failure: "unexpected_exit", restartRequired: true });

    expect(screen.getByText("Desktop session failed")).toBeInTheDocument();
    expect(screen.getByText(/exited after readiness/i)).toBeInTheDocument();
    expect(screen.getByText(/restart the desktop shell/i)).toBeInTheDocument();
  });

  it("reports an incompatible session and asks nothing of it", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const controlled = controlledSource();
    renderStatus(controlled);

    controlled.publish({ phase: "incompatible", apiVersion: "v2", protocolVersion: 3 });

    expect(await screen.findByText("Incompatible API")).toBeInTheDocument();
    expect(screen.getByText(/speaks v2 \/ protocol 3/)).toBeInTheDocument();
    expect(screen.getByText(/no request was made/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
