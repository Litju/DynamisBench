/**
 * The UI store: one shell concern, and no persistence.
 *
 * The store is asserted to *be* UI-local: a fixed set of fields, a boolean an interface
 * controls, and no middleware that would serialise it anywhere.
 */

import { describe, expect, it } from "vitest";

import { useUiStore } from "./ui";

describe("the UI store", () => {
  it("holds exactly one interface concern", () => {
    const state = useUiStore.getState();

    expect(Object.keys(state).sort()).toEqual([
      "setSidebarCollapsed",
      "sidebarCollapsed",
      "toggleSidebar",
    ]);
    expect(typeof state.sidebarCollapsed).toBe("boolean");
    expect(typeof state.toggleSidebar).toBe("function");
    expect(typeof state.setSidebarCollapsed).toBe("function");
  });

  it("collapses and expands the navigation rail", () => {
    const initial = useUiStore.getState().sidebarCollapsed;

    useUiStore.getState().toggleSidebar();
    expect(useUiStore.getState().sidebarCollapsed).toBe(!initial);

    useUiStore.getState().setSidebarCollapsed(initial);
    expect(useUiStore.getState().sidebarCollapsed).toBe(initial);
  });

  it("carries no persistence middleware", () => {
    const store = useUiStore as unknown as Record<string, unknown>;

    // `persist` is what `zustand/middleware`'s persistence attaches to a store; `persist` with
    // any storage would make a shell preference outlive the window, and this store must not
    // have the machinery to do it.
    expect(store.persist).toBeUndefined();
    expect(store.setOptions).toBeUndefined();
  });
});
