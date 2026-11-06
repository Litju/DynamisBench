import { Link, useRouterState } from "@tanstack/react-router";

import type { ReactNode } from "react";

import "../fonts";
import { useUiStore, type WorkbenchMode } from "../store/ui";

import { RuntimeStatus } from "./runtime-status";

const modes: [WorkbenchMode, string][] = [
  ["study", "Study & Model"],
  ["lab", "Simulation Laboratory"],
  ["analysis", "Analysis & VVUQ"],
  ["evidence", "Evidence & Provenance"],
];

/** The workbench mark: circle, square and plumb — the measured figure (DESIGN.md §1). */
function Emblem() {
  return (
    <svg className="wb-emblem" width="26" height="26" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="17" />
      <rect x="9" y="9" width="22" height="22" />
      <line x1="20" y1="3" x2="20" y2="32" />
      <circle cx="20" cy="34" r="2.6" className="wb-emblem-bob" />
    </svg>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { mode, setMode, theme, toggleTheme } = useUiStore();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const onLaboratory = pathname === "/laboratory";

  return (
    <div className="wb-shell" data-theme={theme} data-route={onLaboratory ? "laboratory" : "workbench"}>
      <header className="wb-header">
        <Emblem />

        <div className="wb-brand">
          <strong>DynamisBench</strong>
          <span>Human-movement VVUQ workbench</span>
        </div>

        <nav aria-label="Workbench">
          <Link to="/" activeOptions={{ exact: true, includeHash: false }} activeProps={{ "data-active": "true" }}>
            Overview
          </Link>

          <Link to="/" hash="open-workspace">
            Open workspace
          </Link>

          <Link to="/laboratory" activeProps={{ "data-active": "true" }}>
            Laboratory
          </Link>
        </nav>

        <RuntimeStatus className="ml-auto" />

        <button
          className="wb-theme"
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle color theme"
          title={theme === "dark" ? "Switch to the light ground (Vellum)" : "Switch to the dark ground (Studiolo)"}
        >
          <span data-active={theme === "dark"}>Studiolo</span>
          <span data-active={theme === "light"}>Vellum</span>
        </button>
      </header>

      {!onLaboratory && (
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
        </nav>
      )}

      <main>{children}</main>

      {!onLaboratory && (
        <footer className="wb-footer">
          <span>Source authority is read-only · runs are sealed as evidence</span>
          <span>Verification and assessment only · no validation against measured data</span>
        </footer>
      )}
    </div>
  );
}
