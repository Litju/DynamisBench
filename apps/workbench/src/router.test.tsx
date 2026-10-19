/**
 * The routes, rendered the way the application renders them.
 *
 * Browser-only on purpose: no Tauri runtime is present, `isTauri()` is false, and the shell
 * must still render both locations. That is the ordinary-browser architecture stated as a
 * test rather than as a claim.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createWorkbenchQueryClient } from "./query/client";
import { renderApplication } from "./test/render-app";
import { browserSessionSource } from "./session/source";

describe("the application's routes", () => {
  it("renders the overview at /", async () => {
    renderApplication("/");

    expect(
      await screen.findByRole("heading", { name: "Workbench overview" }),
    ).toBeInTheDocument();
    // The header carries the status at a glance and the route explains it, so the sentence
    // is deliberately present twice.
    expect(
      screen.getAllByText(/not running inside the DynamisBench desktop shell/i),
    ).toHaveLength(2);
  });

  it("renders a workspace at /workspace/$workspaceId", async () => {
    renderApplication("/workspace/w-1");

    expect(await screen.findByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByText("w-1")).toBeInTheDocument();
  });

  it("carries the runtime's one QueryClient in its context", () => {
    const queryClient = createWorkbenchQueryClient();

    const { router } = renderApplication("/", { queryClient });

    expect(router.options.context?.queryClient).toBe(queryClient);
  });

  it("keeps the shell — and its runtime status — mounted across routes", async () => {
    const { router } = renderApplication("/");
    await screen.findByRole("heading", { name: "Workbench overview" });

    await router.navigate({ to: "/workspace/$workspaceId", params: { workspaceId: "w-2" } });

    expect(await screen.findByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Workbench" })).toBeInTheDocument();
    expect(
      screen.getAllByText(/not running inside the DynamisBench desktop shell/i),
    ).not.toHaveLength(0);
  });

  it("renders the same tree with an explicitly browser-only session source", async () => {
    renderApplication("/", { source: browserSessionSource() });

    expect(
      await screen.findByRole("heading", { name: "Workbench overview" }),
    ).toBeInTheDocument();
  });
});

describe("the navigation rail", () => {
  it("is a real link to the overview", async () => {
    renderApplication("/");

    const link = await screen.findByRole("link", { name: "Overview" });

    expect(link).toHaveAttribute("href", "/");
  });

  it("marks the location it is showing", async () => {
    const atOverview = renderApplication("/");
    expect(await screen.findByRole("link", { name: "Overview" })).toHaveAttribute(
      "data-active",
      "true",
    );
    atOverview.unmount();

    renderApplication("/workspace/w-1");
    expect(await screen.findByRole("link", { name: "Overview" })).not.toHaveAttribute("data-active");
  });
});
