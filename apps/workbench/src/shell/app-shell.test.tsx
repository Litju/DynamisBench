/**
 * The workbench shell: product identity, the runtime status it carries, and the one piece of
 * UI-local state a user can actually change.
 *
 * The collapse control is the only interaction in this milestone, so it is driven the way a
 * person drives it — a real click — rather than by calling the store.
 */

import { userEvent } from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useUiStore } from "../store/ui";
import { renderApplication } from "../test/render-app";

beforeEach(() => {
  useUiStore.setState({ sidebarCollapsed: false });
});

afterEach(() => {
  useUiStore.setState({ sidebarCollapsed: false });
});

describe("the workbench shell", () => {
  it("identifies the product", async () => {
    renderApplication("/");

    expect(await screen.findByText("DynamisBench")).toBeInTheDocument();
    expect(screen.getByText("Human-movement VVUQ workbench")).toBeInTheDocument();
  });

  it("carries the runtime status in the header", async () => {
    renderApplication("/");

    // The label appears in the header and again in the route's explanation; the header's is
    // the first in the document.
    const [status] = await screen.findAllByText("Desktop session unavailable");

    expect(status).toBeDefined();
    expect(status?.closest("[data-runtime-state]")).toHaveAttribute(
      "data-runtime-state",
      "browser_unavailable",
    );
  });

  it("collapses and expands the navigation rail", async () => {
    const user = userEvent.setup();
    renderApplication("/");

    const rail = await screen.findByRole("navigation", { name: "Workbench" });
    expect(rail).toHaveAttribute("data-collapsed", "false");

    await user.click(screen.getByRole("button", { name: "Collapse navigation" }));

    expect(rail).toHaveAttribute("data-collapsed", "true");
    expect(screen.getByRole("button", { name: "Expand navigation" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "Expand navigation" }));

    expect(rail).toHaveAttribute("data-collapsed", "false");
  });

  it("does not offer a workspace link before there is a workspace", async () => {
    renderApplication("/");

    const workspaces = await screen.findByText("Workspaces");

    expect(workspaces.closest("[aria-disabled='true']")).not.toBeNull();
    expect(screen.queryByRole("link", { name: "Workspaces" })).toBeNull();
  });
});
