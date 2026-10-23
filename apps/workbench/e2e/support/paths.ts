/**
 * Repository locations for the browser-qualification harness.
 *
 * Resolved by walking up from the process's working directory to the pnpm workspace root.
 * `pnpm --filter ... run test:e2e` sets that directory to `apps/workbench`, and walking up
 * keeps the harness correct when a developer runs Playwright from the repository root.
 */

import { existsSync } from "node:fs";
import path from "node:path";

export function repositoryRoot(): string {
  let current = process.cwd();
  for (;;) {
    if (
      existsSync(path.join(current, "pnpm-workspace.yaml")) &&
      existsSync(path.join(current, "python", "pyproject.toml"))
    ) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error("the DynamisBench repository root could not be located");
    }
    current = parent;
  }
}

/** The interpreter of the repository's locked Python environment. */
export function pythonExecutable(): string {
  const root = repositoryRoot();
  return process.platform === "win32"
    ? path.join(root, "python", ".venv", "Scripts", "python.exe")
    : path.join(root, "python", ".venv", "bin", "python");
}

export function e2eWorkspaceTool(): string {
  return path.join(repositoryRoot(), "python", "tools", "e2e_workspace.py");
}

export const DEVELOPMENT_ORIGIN = "http://localhost:5173";

/**
 * The origin this run's harness page is served from.
 *
 * CI uses 5173, the Tauri `devUrl`. A developer machine may already be running the production
 * dev server there, so the runner can select another port with
 * `DYNAMISBENCH_E2E_PORT`; the sidecar is then configured with that exact origin, which is what
 * keeps the CORS claim exact rather than widening it.
 */
export function e2eOrigin(): string {
  return `http://localhost:${process.env.DYNAMISBENCH_E2E_PORT ?? "5173"}`;
}
