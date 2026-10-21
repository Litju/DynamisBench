/**
 * The Activity feed's state: bounded, transient, and generation-scoped.
 *
 * This reducer is the only place an event becomes a line of UI text. It is deliberately not
 * a store in the server-state sense: it holds no read model, no document, no digest and no
 * path, only the closed event name and the bounded counts the envelope carried. The feed is
 * capped, never persisted, and cleared whenever the session's client changes.
 *
 * **Generations are the isolation mechanism.** An effect begins a generation when it
 * subscribes and the reducer refuses every action from any other generation. A frame that
 * arrives late from a stream that has been superseded is therefore not "probably harmless";
 * it has no path into the current feed.
 */

import { useEffect, useReducer, useRef } from "react";

import type { ApiClient } from "../api/client";
import {
  startEventStream,
  type EventStreamState,
} from "../api/event-stream";
import type { ApplicationEvent } from "../api/types";

export const MAX_ACTIVITY_ENTRIES = 50;

export type ActivityStreamState = "idle" | EventStreamState;

export interface ActivityEntry {
  readonly id: number;
  readonly event: ApplicationEvent["event"];
  readonly text: string;
}

export interface ActivityState {
  readonly generation: number;
  readonly nextId: number;
  readonly entries: readonly ActivityEntry[];
  readonly streamState: ActivityStreamState;
}

export type ActivityAction =
  | { readonly type: "begin"; readonly generation: number }
  | {
      readonly type: "state";
      readonly generation: number;
      readonly state: ActivityStreamState;
    }
  | {
      readonly type: "append";
      readonly generation: number;
      readonly event: ApplicationEvent;
    };

export const INITIAL_ACTIVITY_STATE: ActivityState = {
  generation: 0,
  nextId: 1,
  entries: [],
  streamState: "idle",
};

export function activityReducer(
  state: ActivityState,
  action: ActivityAction,
): ActivityState {
  if (action.type !== "begin" && action.generation !== state.generation) {
    // A superseded stream generation has no path into the current feed.
    return state;
  }

  switch (action.type) {
    case "begin":
      return {
        generation: action.generation,
        nextId: 1,
        entries: [],
        streamState: "connecting",
      };

    case "state":
      return { ...state, streamState: action.state };

    case "append": {
      const text = describeEvent(action.event);
      if (text === null) {
        // Connection frames are represented by the stream state, not as duplicate lines.
        return state;
      }
      const entry: ActivityEntry = {
        id: state.nextId,
        event: action.event.event,
        text,
      };
      const entries = [...state.entries, entry].slice(-MAX_ACTIVITY_ENTRIES);
      return { ...state, nextId: state.nextId + 1, entries };
    }
  }
}

/**
 * One event as a bounded status line, or `null` when the stream state already says it.
 *
 * Only the envelope's documented scalar facts are read. The strings interpolated here are
 * `kind` and `validation_status`, both closed vocabularies the client's own event decoder
 * has already accepted; no authoring text, reference or identifier is displayed.
 */
export function describeEvent(event: ApplicationEvent): string | null {
  switch (event.event) {
    case "stream.ready":
      return null;
    case "workspace.opened":
      return "Workspace opened";
    case "workspace.discovered": {
      const artifactCount = integer(event.data.artifact_count);
      const validCount = integer(event.data.valid_count);
      const invalidCount = integer(event.data.invalid_count);
      const issueCount = integer(event.data.issue_count);
      const truncated = event.data.issues_truncated === true;

      const parts = ["Discovery completed"];
      if (artifactCount !== null) {
        parts.push(
          `${artifactCount} artifact${artifactCount === 1 ? "" : "s"}`,
        );
      }
      if (validCount !== null && invalidCount !== null) {
        parts.push(`${validCount} valid · ${invalidCount} invalid`);
      }
      if (issueCount !== null && issueCount > 0) {
        parts.push(
          `${issueCount} issue${issueCount === 1 ? "" : "s"}${truncated ? " (truncated)" : ""}`,
        );
      }
      return parts.join(" · ");
    }
    case "artifact.inspected": {
      const kind = event.data.kind;
      const status = event.data.validation_status;
      if (typeof kind !== "string" || typeof status !== "string") {
        return "Artifact inspected";
      }
      return `Inspected ${kind} · ${status}`;
    }
  }
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/**
 * Subscribe the current session's client to the event stream for as long as it is mounted.
 *
 * `client` changes when the session becomes ready again with a different credential, and the
 * effect's cleanup aborts the old fetch before the next generation begins. The reducer does
 * the rest.
 */
export function useActivityFeed(client: ApiClient | null): ActivityState {
  const [state, dispatch] = useReducer(activityReducer, INITIAL_ACTIVITY_STATE);
  const generation = useRef(0);

  useEffect(() => {
    const next = generation.current + 1;
    generation.current = next;
    dispatch({ type: "begin", generation: next });

    if (client === null) {
      dispatch({ type: "state", generation: next, state: "idle" });
      return;
    }

    const controller = new AbortController();
    const handle = startEventStream({
      client,
      signal: controller.signal,
      onEvent: (event) => dispatch({ type: "append", generation: next, event }),
      onState: (streamState) =>
        dispatch({ type: "state", generation: next, state: streamState }),
    });

    return () => {
      controller.abort();
      handle.stop();
      void handle.done;
    };
  }, [client]);

  return state;
}
