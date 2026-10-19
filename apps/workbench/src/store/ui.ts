/**
 * The workbench's UI-local state: one shell concern, and non-persistent.
 *
 * Zustand is used for exactly one thing — whether the navigation rail is collapsed — because
 * it is state that belongs to this browser window's presentation and to nothing else. It
 * holds no session, no credential, no API response, no workspace or artifact authority, no
 * digest, and no filesystem root: everything scientific is either the desktop session's (in
 * memory, above) or the application's (in TanStack Query, above). There is no `persist`
 * middleware and no storage adapter; a reload starts with the rail open, which is the correct
 * amount of memory for a preference that is not yet a product decision.
 */

import { create } from "zustand";

export type UiStore = {
  /** Whether the navigation rail is collapsed to its icons. */
  readonly sidebarCollapsed: boolean;

  /** Invert the rail's collapsed state. */
  toggleSidebar(): void;
};

export const useUiStore = create<UiStore>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
