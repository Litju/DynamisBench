/**
 * The Activity panel follows the session, not the route.
 *
 * Opening a workspace publishes `workspace.opened` while the landing page's POST is in
 * flight. This gate drives that exact sequence through the production routes, form, typed
 * client and root-level panel: subscribe and become live on `/`, open through the real
 * form, receive the event the handler publishes during the POST, navigate to the returned
 * opaque workspace identifier, and find the line still present. The controlled response's
 * observable `cancel()` callback and the number of `/events` requests prove that navigation
 * neither replaced nor duplicated the session's one subscription.
 */

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { APPLICATION_INFO, DISCOVERY, OPEN_WORKSPACE } from "../test/api-fixtures";
import { controlledSource } from "../test/controlled-source";
import { stubFetch, unavailableEvents } from "../test/fetch-stub";
import { jsonResponse, observableStreamResponse } from "../test/http-fixtures";
import { renderApplication } from "../test/render-app";
import { readyApiSession } from "../test/session-fixtures";

const READY_EVENT = {
  schema_version: 1,
  event: "stream.ready",
  data: { heartbeat_seconds: 15, queue_capacity: 32 },
} as const;

const OPENED_EVENT = {
  schema_version: 1,
  event: "workspace.opened",
  data: {
    workspace_id: "workspace-1",
    categories_present: 3,
    evidence_inside_source: false,
  },
} as const;

function eventLine(event: unknown): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

function readySource() {
  const controlled = controlledSource();
  return {
    ...controlled,
    async publishReady(credential?: string) {
      await waitFor(() => expect(controlled.listening).toBe(true));
      act(() =>
        controlled.publish(
          credential === undefined
            ? { phase: "ready", api: readyApiSession() }
            : { phase: "ready", api: readyApiSession({ credential }) },
        ),
      );
    },
  };
}

describe("the Activity panel across navigation", () => {
  it("shows the first workspace-open event after the landing form navigates", async () => {
    const user = userEvent.setup();
    const source = readySource();
    const stream = observableStreamResponse();
    const eventRequests: string[] = [];

    stubFetch(({ url }) => {
      if (url.endsWith("/events")) {
        eventRequests.push(url);
        return stream.response;
      }
      if (url.endsWith("/workspaces/open")) {
        // The server publishes during the POST, before the form can navigate.
        stream.push(eventLine(OPENED_EVENT));
        return jsonResponse(OPEN_WORKSPACE);
      }
      if (url.endsWith("/artifacts")) {
        return jsonResponse(DISCOVERY);
      }
      if (url.endsWith("/info")) {
        return jsonResponse(APPLICATION_INFO);
      }
      return unavailableEvents();
    });

    const { router } = renderApplication("/", { source: source.source });
    await source.publishReady();

    stream.push(eventLine(READY_EVENT));
    expect(await screen.findByText("Events: live")).toBeInTheDocument();

    await user.type(await screen.findByLabelText("Source root"), "C:\\research\\source");
    await user.type(screen.getByLabelText("Evidence root"), "C:\\research\\evidence");
    await user.click(screen.getByRole("button", { name: "Open workspace" }));

    expect(await screen.findByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe("/workspace/workspace-1"));

    const activity = screen.getByRole("region", { name: "Activity" });
    expect(await within(activity).findByText("Workspace opened")).toBeInTheDocument();

    // Still one subscription, and it is the same open connection: navigation neither
    // cancelled it nor asked for a second stream.
    expect(eventRequests).toHaveLength(1);
    expect(stream.cancelCount()).toBe(0);
  });

  it("clears activity and replaces the one subscription when the session changes", async () => {
    const source = readySource();
    const streams: ReturnType<typeof observableStreamResponse>[] = [];

    stubFetch(({ url }) => {
      if (url.endsWith("/events")) {
        const stream = observableStreamResponse();
        streams.push(stream);
        stream.push(eventLine(READY_EVENT));
        return stream.response;
      }
      if (url.endsWith("/info")) {
        return jsonResponse(APPLICATION_INFO);
      }
      return unavailableEvents();
    });

    renderApplication("/", { source: source.source });
    await source.publishReady();
    expect(await screen.findByText("Events: live")).toBeInTheDocument();
    expect(streams).toHaveLength(1);

    streams[0]?.push(eventLine(OPENED_EVENT));
    expect(await screen.findByText("Workspace opened")).toBeInTheDocument();

    await source.publishReady("a-second-session-credential");

    await waitFor(() => expect(streams).toHaveLength(2));
    await waitFor(() => expect(streams[0]?.cancelCount()).toBe(1));
    await waitFor(() =>
      expect(screen.queryByText("Workspace opened")).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("Events: live")).toBeInTheDocument();
  });
});
