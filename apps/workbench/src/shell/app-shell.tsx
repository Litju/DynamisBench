import { Link } from "@tanstack/react-router";

import { Activity, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import type { ReactNode } from "react";

import { useUiStore, type WorkbenchMode } from "../store/ui";

import { RuntimeStatus } from "./runtime-status";

const modes: [WorkbenchMode, string][] = [
  ["study", "Study & Model"],
  ["lab", "Simulation Laboratory"],
  ["analysis", "Analysis & VVUQ"],
  ["evidence", "Evidence & Provenance"],
];

export function AppShell({ children }: { children: ReactNode }) {
  const { sidebarCollapsed, toggleSidebar, mode, setMode, theme, toggleTheme } =
    useUiStore();

  return (
    <div className="wb-shell" data-theme={theme}>
      <header className="wb-header">
        <Activity aria-hidden size={22} className="text-accent" />

        <div>
          <strong className="block text-[13px]">DynamisBench</strong>
          <span className="block text-[10px] text-ink-3">
            Human-movement VVUQ workbench
          </span>
        </div>

        <nav aria-label="Workbench" data-collapsed={sidebarCollapsed}>
          <button
            type="button"
            onClick={toggleSidebar}
            aria-expanded={!sidebarCollapsed}
            aria-label={
              sidebarCollapsed ? "Expand navigation" : "Collapse navigation"
            }
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen size={16} />
            ) : (
              <PanelLeftClose size={16} />
            )}
          </button>

          <Link to="/" activeProps={{ "data-active": "true" }}>
            Overview
          </Link>

          <Link to="/" hash="open-workspace">
            Open workspace
          </Link>
        </nav>

        <RuntimeStatus className="ml-auto" />
      </header>

      <nav className="wb-modebar" aria-label="Scientific contexts">
        {modes.map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={mode === id}
            onClick={() => setMode(id)}
          >
            {label}
          </button>
        ))}

        <button
          className="wb-theme"
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle color theme"
        >
          {theme === "light" ? "Dark" : "Light"}
        </button>
      </nav>

      <main>{children}</main>

      <footer className="wb-footer">
        <span>Read-only source authority</span>
        <span>Simulation and scientific assessment unavailable</span>
      </footer>
    </div>
  );
}
