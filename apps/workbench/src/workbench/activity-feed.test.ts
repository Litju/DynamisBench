/**
 * The Activity feed's reducer: bounded, and generation-scoped.
 *
 * A late frame from a superseded session must have no path into the current feed, which is a
 * property of the reducer rather than of a component effect ordering.
 */

import { describe, expect, it } from "vitest";

import type { ApplicationEvent } from "../api/types";
import {
  INITIAL_ACTIVITY_STATE,
  MAX_ACTIVITY_ENTRIES,
  activityReducer,
  describeEvent,
  type ActivityState,
} from "./activity-feed";

const OPENED: ApplicationEvent = {
  schema_version: 1,
  event: "workspace.opened",
  data: { workspace_id: "w", categories_present: 3 },
};

const DISCOVERED: ApplicationEvent = {
  schema_version: 1,
  event: "workspace.discovered",
  data: {
    workspace_id: "w",
    artifact_count: 3,
    valid_count: 2,
    invalid_count: 1,
    issue_count: 1,
    issues_truncated: true,
  },
};

const INSPECTED: ApplicationEvent = {
  schema_version: 1,
  event: "artifact.inspected",
  data: {
    workspace_id: "w",
    artifact_id: "a",
    category: "benchmarks",
    kind: "benchmark",
    validation_status: "valid",
    diagnostic_count: 0,
  },
};

function begun(generation = 1): ActivityState {
  return activityReducer(INITIAL_ACTIVITY_STATE, { type: "begin", generation });
}

describe("activityReducer", () => {
  it("describes each event from its bounded scalar facts", () => {
    expect(describeEvent(OPENED)).toBe("Workspace opened");
    expect(describeEvent(DISCOVERED)).toBe(
      "Discovery completed · 3 artifacts · 2 valid · 1 invalid · 1 issue (truncated)",
    );
    expect(describeEvent(INSPECTED)).toBe("Inspected benchmark · valid");
  });

  it("does not add a line for the connection frame", () => {
    const state = begun();
    const next = activityReducer(state, {
      type: "append",
      generation: 1,
      event: {
        schema_version: 1,
        event: "stream.ready",
        data: { heartbeat_seconds: 15, queue_capacity: 32 },
      },
    });

    expect(next.entries).toEqual([]);
  });

  it("refuses an event from a superseded generation", () => {
    const first = activityReducer(begun(1), {
      type: "append",
      generation: 1,
      event: OPENED,
    });
    const second = activityReducer(first, { type: "begin", generation: 2 });

    const late = activityReducer(second, {
      type: "append",
      generation: 1,
      event: DISCOVERED,
    });
    const lateState = activityReducer(second, {
      type: "state",
      generation: 1,
      state: "live",
    });

    expect(late).toBe(second);
    expect(lateState).toBe(second);
    expect(second.entries).toEqual([]);
    expect(second.streamState).toBe("connecting");
  });

  it("bounds the feed and keeps the newest entries", () => {
    let state = begun();
    for (let index = 0; index < MAX_ACTIVITY_ENTRIES + 10; index += 1) {
      state = activityReducer(state, {
        type: "append",
        generation: 1,
        event: index === 0 ? OPENED : INSPECTED,
      });
    }

    expect(state.entries).toHaveLength(MAX_ACTIVITY_ENTRIES);
    expect(state.entries.at(-1)?.id).toBe(MAX_ACTIVITY_ENTRIES + 10);
  });

  it("clears the feed when a new session generation begins", () => {
    const filled = activityReducer(begun(), {
      type: "append",
      generation: 1,
      event: OPENED,
    });
    const reset = activityReducer(filled, { type: "begin", generation: 2 });

    expect(reset.entries).toEqual([]);
    expect(reset.streamState).toBe("connecting");
    expect(reset.generation).toBe(2);
  });

  it("tracks the stream state within the generation", () => {
    const live = activityReducer(begun(), {
      type: "state",
      generation: 1,
      state: "live",
    });

    expect(live.streamState).toBe("live");
  });
});
