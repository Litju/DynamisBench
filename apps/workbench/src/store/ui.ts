/** Presentation preferences only; session and scientific authority stay outside this store. */
import { create } from "zustand";

export type WorkbenchMode = "study" | "lab" | "analysis" | "evidence";

export type UiStore = {
  mode: WorkbenchMode;
  setMode(mode: WorkbenchMode): void;
  theme: "light" | "dark";
  toggleTheme(): void;
  /** Whether the workspace Navigator is collapsed to a rail. */
  readonly sidebarCollapsed: boolean;
  /** Invert the rail's collapsed state. */
  toggleSidebar(): void;
};

export const useUiStore = create<UiStore>((set) => ({
  mode: "lab",
  setMode: (mode) => set({ mode }),
  // Studiolo, the dark ground, is the default for long sessions (DESIGN.md §2.2).
  theme: "dark",
  toggleTheme: () =>
    set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
  sidebarCollapsed: false,
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
