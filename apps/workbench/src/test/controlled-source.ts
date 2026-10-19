/**
 * A `SessionSource` whose published state a test controls.
 *
 * Test-only. It is the *abstraction* under test rather than a stub of it: the provider and
 * everything above it see exactly the interface production code sees, and the test decides
 * when the session changes.
 */

import { act } from "@testing-library/react";
import { vi } from "vitest";

import type { SessionSource } from "../session/source";
import type { WorkbenchSession } from "../session/types";

export type ControlledSource = {
  readonly source: SessionSource;
  readonly stop: ReturnType<typeof vi.fn<() => void>>;
  publish(session: WorkbenchSession): void;
  readonly listening: boolean;
};

export function controlledSource(kind: SessionSource["kind"] = "tauri"): ControlledSource {
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
    publish(session) {
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
