/**
 * The session provider: what a React tree sees, and what it stops seeing.
 *
 * Every case here drives a `SessionSource` directly, so the browser-only test environment is
 * exactly the ordinary-browser environment the shell must work in.
 */

import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { readyApiSession, FIXTURE_CREDENTIAL } from "../test/session-fixtures";
import { SessionProvider, useSession } from "./provider";
import type { SessionSource } from "./source";
import type { WorkbenchSession } from "./types";

/** A source whose published state this test controls. */
function controlledSource(kind: SessionSource["kind"] = "tauri") {
  let listener: ((session: WorkbenchSession) => void) | null = null;
  const stop = vi.fn(() => {
    listener = null;
  });
  const source: SessionSource = {
    kind,
    start(next) {
      listener = next;
      return stop;
    },
  };

  return {
    source,
    stop,
    publish(session: WorkbenchSession) {
      // A source publishes from outside React, so the update is applied the way an external
      // event would apply it.
      act(() => {
        listener?.(session);
      });
    },
    get listening() {
      return listener !== null;
    },
  };
}

function CurrentSession() {
  const { session, ready, source } = useSession();

  return (
    <div>
      <span data-testid="phase">{session.phase}</span>
      <span data-testid="source">{source}</span>
      <span data-testid="credential">{ready === null ? "none" : ready.credential}</span>
    </div>
  );
}

describe("SessionProvider", () => {
  it("renders children with the browser source's unavailable state", async () => {
    const { browserSessionSource } = await import("./source");

    render(
      <SessionProvider source={browserSessionSource()}>
        <CurrentSession />
      </SessionProvider>,
    );

    expect(screen.getByTestId("phase")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("source")).toHaveTextContent("browser");
    expect(screen.getByTestId("credential")).toHaveTextContent("none");
  });

  it("starts a desktop session as starting until the source says otherwise", () => {
    const controlled = controlledSource("tauri");

    render(
      <SessionProvider source={controlled.source}>
        <CurrentSession />
      </SessionProvider>,
    );

    expect(screen.getByTestId("phase")).toHaveTextContent("starting");
    expect(screen.getByTestId("credential")).toHaveTextContent("none");
  });

  it("publishes a ready session to its children", () => {
    const controlled = controlledSource();

    render(
      <SessionProvider source={controlled.source}>
        <CurrentSession />
      </SessionProvider>,
    );

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(screen.getByTestId("phase")).toHaveTextContent("ready");
    expect(screen.getByTestId("credential")).toHaveTextContent(FIXTURE_CREDENTIAL);
  });

  it("returns to non-ready states as the source publishes them", () => {
    const controlled = controlledSource();

    render(
      <SessionProvider source={controlled.source}>
        <CurrentSession />
      </SessionProvider>,
    );

    controlled.publish({ phase: "ready", api: readyApiSession() });
    controlled.publish({ phase: "failed", failure: "unexpected_exit", restartRequired: true });

    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
    expect(screen.getByTestId("credential")).toHaveTextContent("none");
  });

  it("stops listening when it unmounts", () => {
    const controlled = controlledSource();

    const { unmount } = render(
      <SessionProvider source={controlled.source}>
        <CurrentSession />
      </SessionProvider>,
    );

    expect(controlled.listening).toBe(true);
    unmount();

    expect(controlled.stop).toHaveBeenCalledTimes(1);
    expect(controlled.listening).toBe(false);
  });

  it("refuses to answer outside a provider", () => {
    expect(() => render(<CurrentSession />)).toThrow(/SessionProvider/);
  });
});
