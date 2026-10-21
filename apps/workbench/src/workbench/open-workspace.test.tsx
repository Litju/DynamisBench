/**
 * Opening a workspace is explicit, typed, and does not retain the roots.
 *
 * The gates drive the production landing route with a ready session and a recording `fetch`,
 * then assert the one POST it builds, the navigation to the returned opaque identifier, and
 * that the form does not remember either root.
 */

import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DISCOVERY, OPEN_WORKSPACE, APPLICATION_INFO } from "../test/api-fixtures";
import { errorResponse, stubFetch, unavailableEvents } from "../test/fetch-stub";
import { jsonResponse } from "../test/http-fixtures";
import { renderApplication } from "../test/render-app";
import { readyApiSession } from "../test/session-fixtures";
import { controlledSource } from "../test/controlled-source";

function readySource() {
  const controlled = controlledSource();
  return {
    ...controlled,
    async publishReady() {
      await waitFor(() => expect(controlled.listening).toBe(true));
      act(() => controlled.publish({ phase: "ready", api: readyApiSession() }));
    },
  };
}

describe("the open-workspace flow", () => {
  it("opens a workspace and navigates to the opaque identifier it returned", async () => {
    const user = userEvent.setup();
    const source = readySource();
    const { calls } = stubFetch(({ url, init }) => {
      if (url.endsWith("/workspaces/open")) {
        expect(init.method).toBe("POST");
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

    await user.type(await screen.findByLabelText("Source root"), "C:\\research\\source");
    await user.type(screen.getByLabelText("Evidence root"), "C:\\research\\evidence");
    await user.click(screen.getByRole("button", { name: "Open workspace" }));

    expect(await screen.findByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    expect(
      screen.getByText("workspace-1", { selector: "code" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe("/workspace/workspace-1"));

    const openCall = calls.find((call) => call.url.endsWith("/workspaces/open"));
    expect(openCall).toBeDefined();
    expect(JSON.parse(String(openCall?.init.body))).toEqual({
      source_root: "C:\\research\\source",
      evidence_root: "C:\\research\\evidence",
    });
    expect(openCall?.init.credentials).toBe("omit");
    expect(openCall?.init.cache).toBe("no-store");
  });

  it("clears both roots after a successful open", async () => {
    const user = userEvent.setup();
    const source = readySource();
    stubFetch(({ url }) => {
      if (url.endsWith("/workspaces/open")) {
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

    await user.type(await screen.findByLabelText("Source root"), "C:\\research\\source");
    await user.type(screen.getByLabelText("Evidence root"), "C:\\research\\evidence");
    await user.click(screen.getByRole("button", { name: "Open workspace" }));
    await screen.findByRole("heading", { name: "Workspace" });

    await router.navigate({ to: "/" });

    expect(await screen.findByLabelText("Source root")).toHaveValue("");
    expect(screen.getByLabelText("Evidence root")).toHaveValue("");
  });

  it("reports a bounded refusal without echoing the roots", async () => {
    const user = userEvent.setup();
    const source = readySource();
    const sourceRoot = "C:\\private\\this-root-must-not-be-echoed";
    stubFetch(({ url }) => {
      if (url.endsWith("/workspaces/open")) {
        return errorResponse(400, "http_error", "The declared workspace roots could not be opened.");
      }
      return unavailableEvents();
    });

    renderApplication("/", { source: source.source });
    await source.publishReady();

    await user.type(await screen.findByLabelText("Source root"), sourceRoot);
    await user.type(screen.getByLabelText("Evidence root"), "C:\\private\\evidence");
    await user.click(screen.getByRole("button", { name: "Open workspace" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The declared workspace roots could not be opened.");
    expect(alert).not.toHaveTextContent(sourceRoot);
    expect(screen.getByLabelText("Source root")).toHaveValue(sourceRoot);
  });

  it("does not present the form in a browser without a session", async () => {
    renderApplication("/");

    expect(
      await screen.findByText(/a ready local api session is required to open a workspace/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Source root")).not.toBeInTheDocument();
  });
});
