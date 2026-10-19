/**
 * The session provider: what a React tree sees, what it can call, and what it stops seeing.
 *
 * Every case here drives a `SessionSource` directly, so the browser-only test environment is
 * exactly the ordinary-browser environment the shell must work in.
 */

import { act, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createWorkbenchQueryClient } from "../query/client";
import { controlledSource } from "../test/controlled-source";
import { FIXTURE_CREDENTIAL, readyApiSession } from "../test/session-fixtures";
import { SessionProvider, useApiClient, useSession } from "./provider";
import type { SessionSource } from "./source";

function withSession(source: SessionSource, children: React.ReactNode) {
  return (
    <SessionProvider queryClient={createWorkbenchQueryClient()} source={source}>
      {children}
    </SessionProvider>
  );
}

function CurrentSession() {
  const { session, client } = useSession();

  return (
    <div>
      <span data-testid="phase">{session.phase}</span>
      <span data-testid="credential">
        {session.phase === "ready" ? session.api.credential : "none"}
      </span>
      <span data-testid="client">{client === null ? "none" : "api-client"}</span>
    </div>
  );
}

describe("SessionProvider", () => {
  it("renders children with the browser source's unavailable state", async () => {
    const { browserSessionSource } = await import("./source");

    render(withSession(browserSessionSource(), <CurrentSession />));

    expect(screen.getByTestId("phase")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("credential")).toHaveTextContent("none");
    expect(screen.getByTestId("client")).toHaveTextContent("none");
  });

  it("starts a desktop session as starting until the source says otherwise", () => {
    const controlled = controlledSource("tauri");

    render(withSession(controlled.source, <CurrentSession />));

    expect(screen.getByTestId("phase")).toHaveTextContent("starting");
    expect(screen.getByTestId("credential")).toHaveTextContent("none");
    expect(screen.getByTestId("client")).toHaveTextContent("none");
  });

  it("publishes a ready session and its client to its children", () => {
    const controlled = controlledSource();

    render(withSession(controlled.source, <CurrentSession />));

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(screen.getByTestId("phase")).toHaveTextContent("ready");
    expect(screen.getByTestId("credential")).toHaveTextContent(FIXTURE_CREDENTIAL);
    expect(screen.getByTestId("client")).toHaveTextContent("api-client");
  });

  it("returns to non-ready states as the source publishes them", () => {
    const controlled = controlledSource();

    render(withSession(controlled.source, <CurrentSession />));

    controlled.publish({ phase: "ready", api: readyApiSession() });
    controlled.publish({ phase: "failed", failure: "unexpected_exit", restartRequired: true });

    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
    expect(screen.getByTestId("credential")).toHaveTextContent("none");
    expect(screen.getByTestId("client")).toHaveTextContent("none");
  });

  it("stops listening when it unmounts", () => {
    const controlled = controlledSource();

    const { unmount } = render(withSession(controlled.source, <CurrentSession />));

    expect(controlled.listening).toBe(true);
    unmount();

    expect(controlled.stop).toHaveBeenCalledTimes(1);
    expect(controlled.listening).toBe(false);
  });

  it("refuses to answer outside a provider", () => {
    expect(() => render(<CurrentSession />)).toThrow(/SessionProvider/);
  });
});

describe("useApiClient", () => {
  function clientWrapper(source: SessionSource) {
    return function Wrapper({ children }: { children: React.ReactNode }) {
      return withSession(source, children);
    };
  }

  it("is null without a ready session", () => {
    const controlled = controlledSource();

    const { result } = renderHook(() => useApiClient(), {
      wrapper: clientWrapper(controlled.source),
    });

    expect(result.current).toBeNull();
  });

  it("is the client of the ready session", () => {
    const controlled = controlledSource();

    const { result } = renderHook(() => useApiClient(), {
      wrapper: clientWrapper(controlled.source),
    });

    act(() => {
      controlled.publish({ phase: "ready", api: readyApiSession() });
    });

    expect(result.current).not.toBeNull();
    expect(result.current?.info).toBeTypeOf("function");
  });
});
